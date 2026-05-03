"""Plans router.

Routes:
  GET    /api/v1/profiles/{profile_id}/plans
  POST   /api/v1/profiles/{profile_id}/plans
  GET    /api/v1/profiles/{profile_id}/plans/{plan_id}
  POST   /api/v1/profiles/{profile_id}/plans/{plan_id}/regenerate
  DELETE /api/v1/profiles/{profile_id}/plans/{plan_id}
"""
import asyncio
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.orm import Profile, TrainingBlock, TrainingPlan, Workout
from app.models.schemas import TrainingBlockResponse, TrainingPlanResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["plans"])

VALID_PROFILE_IDS = {1, 2}


def _require_profile(profile_id: int, db: Session) -> Profile:
    if profile_id not in VALID_PROFILE_IDS:
        raise HTTPException(status_code=404, detail="Profile not found")
    profile = db.query(Profile).filter(Profile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


def _require_plan(profile_id: int, plan_id: int, db: Session) -> TrainingPlan:
    plan = db.query(TrainingPlan).filter(
        TrainingPlan.id == plan_id,
        TrainingPlan.profile_id == profile_id,
    ).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Training plan not found")
    return plan


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class PlanCreateRequest(BaseModel):
    race_goal_id: int


class WorkoutSummary(BaseModel):
    id: int
    scheduled_date: Any
    workout_type: str
    target_distance_metres: float | None
    target_pace_zone: str | None
    status: str
    coaching_note: str | None

    model_config = {"from_attributes": True}


class TrainingBlockWithWorkouts(BaseModel):
    id: int
    profile_id: int
    plan_id: int
    name: str
    start_date: Any
    end_date: Any
    sequence: int
    workouts: list[WorkoutSummary]

    model_config = {"from_attributes": True}


class TrainingPlanDetail(BaseModel):
    id: int
    profile_id: int
    race_goal_id: int | None
    start_date: Any
    end_date: Any
    status: str
    gemini_prompt_hash: str | None
    created_at: Any
    updated_at: Any
    blocks: list[TrainingBlockWithWorkouts]

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/profiles/{profile_id}/plans", response_model=list[TrainingPlanResponse])
def list_plans(profile_id: int, db: Session = Depends(get_db)):
    """List all training plans for a profile."""
    _require_profile(profile_id, db)
    return (
        db.query(TrainingPlan)
        .filter(TrainingPlan.profile_id == profile_id)
        .order_by(TrainingPlan.created_at.desc())
        .all()
    )


@router.post("/profiles/{profile_id}/plans", response_model=TrainingPlanResponse, status_code=202)
def create_plan(
    profile_id: int,
    body: PlanCreateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Create a new training plan by triggering AI plan generation.
    Returns 202 Accepted immediately; generation runs in the background.
    A placeholder plan record is returned with status="draft".
    """
    from app.models.orm import RaceGoal

    _require_profile(profile_id, db)

    race_goal = db.query(RaceGoal).filter(
        RaceGoal.id == body.race_goal_id,
        RaceGoal.profile_id == profile_id,
    ).first()
    if not race_goal:
        raise HTTPException(status_code=404, detail="Race goal not found")

    # Create a draft placeholder immediately so the client has an ID to poll
    from datetime import date
    plan = TrainingPlan(
        profile_id=profile_id,
        race_goal_id=body.race_goal_id,
        start_date=date.today(),
        end_date=race_goal.target_date,
        status="draft",
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)

    plan_id = plan.id

    async def _generate():
        from app.database import SessionLocal
        from app.services.ai_coach import generate_plan
        gen_db = SessionLocal()
        try:
            await generate_plan(profile_id, body.race_goal_id, gen_db)
            # Mark the draft as archived (generate_plan creates its own active plan)
            draft = gen_db.query(TrainingPlan).filter(TrainingPlan.id == plan_id).first()
            if draft and draft.status == "draft":
                draft.status = "archived"
                gen_db.commit()
        except Exception as e:
            logger.error(f"Background plan generation failed: {e}", exc_info=True)
            gen_db_plan = gen_db.query(TrainingPlan).filter(TrainingPlan.id == plan_id).first()
            if gen_db_plan:
                gen_db_plan.status = "archived"
                gen_db.commit()
        finally:
            gen_db.close()

    background_tasks.add_task(_generate)
    return plan


@router.get("/profiles/{profile_id}/plans/{plan_id}", response_model=TrainingPlanDetail)
def get_plan(profile_id: int, plan_id: int, db: Session = Depends(get_db)):
    """Return plan detail with blocks and workouts."""
    _require_profile(profile_id, db)
    plan = _require_plan(profile_id, plan_id, db)

    blocks = (
        db.query(TrainingBlock)
        .filter(TrainingBlock.plan_id == plan_id, TrainingBlock.profile_id == profile_id)
        .order_by(TrainingBlock.sequence)
        .all()
    )

    block_list = []
    for block in blocks:
        workouts = (
            db.query(Workout)
            .filter(Workout.block_id == block.id, Workout.profile_id == profile_id)
            .order_by(Workout.scheduled_date)
            .all()
        )
        block_list.append(
            TrainingBlockWithWorkouts(
                id=block.id,
                profile_id=block.profile_id,
                plan_id=block.plan_id,
                name=block.name,
                start_date=block.start_date,
                end_date=block.end_date,
                sequence=block.sequence,
                workouts=[WorkoutSummary.model_validate(w) for w in workouts],
            )
        )

    return TrainingPlanDetail(
        id=plan.id,
        profile_id=plan.profile_id,
        race_goal_id=plan.race_goal_id,
        start_date=plan.start_date,
        end_date=plan.end_date,
        status=plan.status,
        gemini_prompt_hash=plan.gemini_prompt_hash,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
        blocks=block_list,
    )


@router.post(
    "/profiles/{profile_id}/plans/{plan_id}/regenerate",
    response_model=TrainingPlanResponse,
    status_code=202,
)
def regenerate_plan(
    profile_id: int,
    plan_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Regenerate a training plan using AI."""
    _require_profile(profile_id, db)
    plan = _require_plan(profile_id, plan_id, db)

    if not plan.race_goal_id:
        raise HTTPException(status_code=400, detail="Plan has no associated race goal")

    race_goal_id = plan.race_goal_id

    async def _regenerate():
        from app.database import SessionLocal
        from app.services.ai_coach import generate_plan
        gen_db = SessionLocal()
        try:
            await generate_plan(profile_id, race_goal_id, gen_db)
        except Exception as e:
            logger.error(f"Background plan regeneration failed: {e}", exc_info=True)
        finally:
            gen_db.close()

    background_tasks.add_task(_regenerate)
    return plan


@router.delete("/profiles/{profile_id}/plans/{plan_id}", status_code=204)
def delete_plan(
    profile_id: int,
    plan_id: int,
    confirm: bool = Query(False),
    db: Session = Depends(get_db),
):
    """
    Reset plan: delete plan + all blocks + workouts (preserves Run records).
    Requires ?confirm=true query param; returns 400 if not confirmed.
    """
    _require_profile(profile_id, db)
    plan = _require_plan(profile_id, plan_id, db)

    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Deletion requires confirmation. Add ?confirm=true to the request.",
        )

    # Delete workouts first (FK constraint), then blocks, then plan
    db.query(Workout).filter(
        Workout.plan_id == plan_id, Workout.profile_id == profile_id
    ).delete(synchronize_session=False)
    db.query(TrainingBlock).filter(
        TrainingBlock.plan_id == plan_id, TrainingBlock.profile_id == profile_id
    ).delete(synchronize_session=False)
    db.delete(plan)
    db.commit()
