"""Race Goals router.

Routes:
  GET  /api/v1/profiles/{profile_id}/race-goals
  POST /api/v1/profiles/{profile_id}/race-goals
  GET  /api/v1/profiles/{profile_id}/race-goals/{goal_id}
  PUT  /api/v1/profiles/{profile_id}/race-goals/{goal_id}
  DELETE /api/v1/profiles/{profile_id}/race-goals/{goal_id}
"""
import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.orm import RaceGoal

logger = logging.getLogger(__name__)

router = APIRouter(tags=["race-goals"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class RaceGoalCreate(BaseModel):
    distance_metres: float
    target_date: date
    label: str | None = None
    is_active: bool = True


class RaceGoalUpdate(BaseModel):
    distance_metres: float | None = None
    target_date: date | None = None
    label: str | None = None
    is_active: bool | None = None


class RaceGoalResponse(BaseModel):
    id: int
    profile_id: int
    distance_metres: float
    target_date: date
    label: str | None
    is_active: bool
    created_at: object | None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_goal(profile_id: int, goal_id: int, db: Session) -> RaceGoal:
    goal = (
        db.query(RaceGoal)
        .filter(RaceGoal.id == goal_id, RaceGoal.profile_id == profile_id)
        .first()
    )
    if not goal:
        raise HTTPException(status_code=404, detail="Race goal not found")
    return goal


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/profiles/{profile_id}/race-goals", response_model=list[RaceGoalResponse])
def list_race_goals(profile_id: int, db: Session = Depends(get_db)):
    """List all race goals for a profile."""
    return (
        db.query(RaceGoal)
        .filter(RaceGoal.profile_id == profile_id)
        .order_by(RaceGoal.target_date)
        .all()
    )


@router.post(
    "/profiles/{profile_id}/race-goals",
    response_model=RaceGoalResponse,
    status_code=201,
)
def create_race_goal(
    profile_id: int,
    body: RaceGoalCreate,
    db: Session = Depends(get_db),
):
    """Create a new race goal for a profile."""
    if body.distance_metres <= 0:
        raise HTTPException(status_code=422, detail="distance_metres must be positive")
    if body.target_date <= date.today():
        raise HTTPException(status_code=422, detail="target_date must be in the future")

    goal = RaceGoal(
        profile_id=profile_id,
        distance_metres=body.distance_metres,
        target_date=body.target_date,
        label=body.label,
        is_active=body.is_active,
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return goal


@router.get(
    "/profiles/{profile_id}/race-goals/{goal_id}",
    response_model=RaceGoalResponse,
)
def get_race_goal(profile_id: int, goal_id: int, db: Session = Depends(get_db)):
    """Return a single race goal."""
    return _require_goal(profile_id, goal_id, db)


@router.put(
    "/profiles/{profile_id}/race-goals/{goal_id}",
    response_model=RaceGoalResponse,
)
def update_race_goal(
    profile_id: int,
    goal_id: int,
    body: RaceGoalUpdate,
    db: Session = Depends(get_db),
):
    """Update a race goal."""
    goal = _require_goal(profile_id, goal_id, db)
    if body.distance_metres is not None:
        if body.distance_metres <= 0:
            raise HTTPException(status_code=422, detail="distance_metres must be positive")
        goal.distance_metres = body.distance_metres
    if body.target_date is not None:
        goal.target_date = body.target_date
    if body.label is not None:
        goal.label = body.label
    if body.is_active is not None:
        goal.is_active = body.is_active
    db.commit()
    db.refresh(goal)
    return goal


@router.delete("/profiles/{profile_id}/race-goals/{goal_id}", status_code=204)
def delete_race_goal(profile_id: int, goal_id: int, db: Session = Depends(get_db)):
    """Delete a race goal."""
    goal = _require_goal(profile_id, goal_id, db)
    db.delete(goal)
    db.commit()
