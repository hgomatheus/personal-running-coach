"""Runs router.

Routes:
  GET    /api/v1/profiles/{profile_id}/runs
  POST   /api/v1/profiles/{profile_id}/runs
  GET    /api/v1/profiles/{profile_id}/runs/{run_id}
  PUT    /api/v1/profiles/{profile_id}/runs/{run_id}
  DELETE /api/v1/profiles/{profile_id}/runs/{run_id}
"""
import asyncio
import logging
from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.orm import Profile, Run
from app.models.schemas import RunCreate, RunResponse, RunUpdate
from app.services.workout_matcher import calculate_deviation_pct, match_run_to_workout

logger = logging.getLogger(__name__)

router = APIRouter(tags=["runs"])

VALID_PROFILE_IDS = {1, 2}


def _require_profile(profile_id: int, db: Session) -> Profile:
    if profile_id not in VALID_PROFILE_IDS:
        raise HTTPException(status_code=404, detail="Profile not found")
    profile = db.query(Profile).filter(Profile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


def _require_run(profile_id: int, run_id: int, db: Session) -> Run:
    run = db.query(Run).filter(Run.id == run_id, Run.profile_id == profile_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/profiles/{profile_id}/runs", response_model=list[RunResponse])
def list_runs(
    profile_id: int,
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    run_type: str | None = Query(None),
    min_distance_km: float | None = Query(None, ge=0),
    max_distance_km: float | None = Query(None, ge=0),
    db: Session = Depends(get_db),
):
    """List runs with optional filters, sorted by date ascending."""
    _require_profile(profile_id, db)

    query = db.query(Run).filter(Run.profile_id == profile_id)

    if date_from is not None:
        query = query.filter(Run.date >= date_from)
    if date_to is not None:
        query = query.filter(Run.date <= date_to)
    if run_type is not None:
        query = query.filter(Run.run_type == run_type)
    if min_distance_km is not None:
        query = query.filter(Run.distance_metres >= min_distance_km * 1000)
    if max_distance_km is not None:
        query = query.filter(Run.distance_metres <= max_distance_km * 1000)

    return query.order_by(Run.date.asc()).all()


@router.post("/profiles/{profile_id}/runs", response_model=RunResponse, status_code=201)
def create_run(
    profile_id: int,
    body: RunCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Create a manual run entry.
    Validates distance > 0 and duration > 0 (enforced by schema).
    Computes avg_pace_sec_per_km.
    Calls match_run_to_workout.
    Triggers adapt_plan if deviation > 20%.
    """
    _require_profile(profile_id, db)

    avg_pace = body.duration_seconds / (body.distance_metres / 1000)

    run = Run(
        profile_id=profile_id,
        source="manual",
        date=body.date,
        distance_metres=body.distance_metres,
        duration_seconds=body.duration_seconds,
        avg_pace_sec_per_km=avg_pace,
        avg_heart_rate=body.avg_heart_rate,
        elevation_gain_metres=body.elevation_gain_metres,
        run_type=body.run_type,
        notes=body.notes,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # Task 7.2: Match run to workout and check deviation
    matched_workout = match_run_to_workout(run, profile_id, db)

    if matched_workout:
        deviation = calculate_deviation_pct(run, matched_workout)
        if deviation is not None and deviation > 0.20:
            context = {
                "run_id": run.id,
                "workout_id": matched_workout.id,
                "deviation_pct": round(deviation * 100, 1),
                "actual_distance_metres": run.distance_metres,
                "target_distance_metres": matched_workout.target_distance_metres,
            }
            logger.info(
                f"Run deviation {deviation*100:.1f}% > 20% for profile {profile_id} "
                f"— triggering plan adaptation"
            )

            async def _adapt():
                from app.database import SessionLocal
                from app.services.ai_coach import adapt_plan
                adapt_db = SessionLocal()
                try:
                    await adapt_plan("run_deviation", context, profile_id, adapt_db)
                except Exception as e:
                    logger.error(f"Run deviation adaptation failed: {e}")
                finally:
                    adapt_db.close()

            background_tasks.add_task(asyncio.run, _adapt())

    db.refresh(run)
    return run


@router.get("/profiles/{profile_id}/runs/{run_id}", response_model=RunResponse)
def get_run(profile_id: int, run_id: int, db: Session = Depends(get_db)):
    """Return a single run record."""
    _require_profile(profile_id, db)
    return _require_run(profile_id, run_id, db)


@router.put("/profiles/{profile_id}/runs/{run_id}", response_model=RunResponse)
def update_run(
    profile_id: int,
    run_id: int,
    body: RunUpdate,
    db: Session = Depends(get_db),
):
    """Update a manual run (source must be 'manual')."""
    _require_profile(profile_id, db)
    run = _require_run(profile_id, run_id, db)

    if run.source != "manual":
        raise HTTPException(
            status_code=400,
            detail="Only manually logged runs can be updated",
        )

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(run, field, value)

    # Recompute avg_pace if distance or duration changed
    if body.distance_metres is not None or body.duration_seconds is not None:
        run.avg_pace_sec_per_km = run.duration_seconds / (run.distance_metres / 1000)

    db.commit()
    db.refresh(run)
    return run


@router.delete("/profiles/{profile_id}/runs/{run_id}", status_code=204)
def delete_run(profile_id: int, run_id: int, db: Session = Depends(get_db)):
    """Delete a manual run (source must be 'manual')."""
    _require_profile(profile_id, db)
    run = _require_run(profile_id, run_id, db)

    if run.source != "manual":
        raise HTTPException(
            status_code=400,
            detail="Only manually logged runs can be deleted",
        )

    db.delete(run)
    db.commit()
