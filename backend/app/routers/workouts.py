"""Workouts router.

Routes:
  GET   /api/v1/workouts/{workout_id}  — workout detail with computed estimated_duration_seconds
  PATCH /api/v1/workouts/{workout_id}  — update status / rpe_score; trigger adapt_plan on RPE >8
"""
import asyncio
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.orm import PaceZones, Workout
from app.models.schemas import WorkoutPatch, WorkoutResponse, WorkoutStepResponse
from app.services.vdot import pace_zone_velocity_m_per_s

logger = logging.getLogger(__name__)

router = APIRouter(tags=["workouts"])


def _build_workout_response(workout: Workout, pace_zones: PaceZones | None) -> WorkoutResponse:
    """Build a WorkoutResponse with computed estimated_duration_seconds fields."""

    def _estimate_duration(distance_m: float | None, zone: str | None) -> int | None:
        if not distance_m or not zone:
            return None
        velocity = pace_zone_velocity_m_per_s(zone or "easy", pace_zones) if pace_zones else None
        if not velocity:
            return None
        return int(round(distance_m / velocity))

    # Build step responses with estimated durations
    steps = []
    raw_steps = workout.steps or []
    for step in raw_steps:
        step_distance = step.get("distance_metres")
        step_zone = step.get("pace_zone")
        est_dur = _estimate_duration(step_distance, step_zone)
        steps.append(
            WorkoutStepResponse(
                sequence=step.get("sequence", 0),
                label=step.get("label", ""),
                distance_metres=step_distance or 0,
                estimated_duration_seconds=est_dur or 0,
                pace_zone=step_zone,
                hr_zone=step.get("hr_zone"),
                description=step.get("description"),
            )
        )

    # Compute overall estimated duration
    overall_est = _estimate_duration(workout.target_distance_metres, workout.target_pace_zone)

    return WorkoutResponse(
        id=workout.id,
        profile_id=workout.profile_id,
        block_id=workout.block_id,
        plan_id=workout.plan_id,
        scheduled_date=workout.scheduled_date,
        workout_type=workout.workout_type,
        target_distance_metres=workout.target_distance_metres,
        estimated_duration_seconds=overall_est,
        target_pace_zone=workout.target_pace_zone,
        target_hr_zone=workout.target_hr_zone,
        steps=steps,
        coaching_note=workout.coaching_note,
        status=workout.status,
        rpe_score=workout.rpe_score,
        matched_run_id=workout.matched_run_id,
        created_at=workout.created_at,
        updated_at=workout.updated_at,
    )


@router.get("/workouts/{workout_id}", response_model=WorkoutResponse)
async def get_workout(
    workout_id: int,
    profile_id: int = Query(..., description="Profile ID to verify ownership"),
    db: Session = Depends(get_db),
):
    """Return workout detail with computed estimated_duration_seconds on each step.
    Appends weather advisory text to coaching_note when advisories are present
    and weather_advisories_enabled is true for the profile.
    """
    workout = db.query(Workout).filter(Workout.id == workout_id).first()
    if not workout:
        raise HTTPException(status_code=404, detail="Workout not found")
    if workout.profile_id != profile_id:
        raise HTTPException(status_code=403, detail="Workout does not belong to this profile")

    pace_zones = db.query(PaceZones).filter(PaceZones.profile_id == profile_id).first()
    response = _build_workout_response(workout, pace_zones)

    # Append weather advisories to coaching_note if enabled
    try:
        from app.models.orm import ProfileWeatherSettings
        from app.services.weather_service import get_forecast, build_advisories, format_advisory_text

        weather_settings = (
            db.query(ProfileWeatherSettings)
            .filter(ProfileWeatherSettings.profile_id == profile_id)
            .first()
        )
        if weather_settings and weather_settings.weather_advisories_enabled:
            forecast = await get_forecast(profile_id, workout.scheduled_date, db)
            if forecast:
                advisories = build_advisories(forecast)
                if advisories:
                    advisory_texts = " ".join(format_advisory_text(a) for a in advisories)
                    existing_note = response.coaching_note or ""
                    separator = " " if existing_note else ""
                    response.coaching_note = f"{existing_note}{separator}⚠️ Weather: {advisory_texts}"
    except Exception as e:
        logger.warning(f"Weather advisory injection failed for workout {workout_id}: {e}")

    return response


@router.patch("/workouts/{workout_id}", response_model=WorkoutResponse)
def patch_workout(
    workout_id: int,
    body: WorkoutPatch,
    profile_id: int = Query(..., description="Profile ID to verify ownership"),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db),
):
    """
    Update workout status (completed/skipped) and/or rpe_score.
    After RPE update, check if 2 consecutive same-type workouts have rpe > 8
    and trigger adapt_plan("rpe_high", ...) if so.
    """
    workout = db.query(Workout).filter(Workout.id == workout_id).first()
    if not workout:
        raise HTTPException(status_code=404, detail="Workout not found")
    if workout.profile_id != profile_id:
        raise HTTPException(status_code=403, detail="Workout does not belong to this profile")

    if body.status is not None:
        workout.status = body.status

    rpe_updated = False
    if body.rpe_score is not None:
        workout.rpe_score = body.rpe_score
        rpe_updated = True

    db.commit()
    db.refresh(workout)

    # Check RPE adaptation trigger
    if rpe_updated and body.rpe_score is not None and body.rpe_score > 8:
        _check_rpe_adaptation(workout, profile_id, background_tasks, db)

    pace_zones = db.query(PaceZones).filter(PaceZones.profile_id == profile_id).first()
    return _build_workout_response(workout, pace_zones)


def _check_rpe_adaptation(
    current_workout: Workout,
    profile_id: int,
    background_tasks: BackgroundTasks | None,
    db: Session,
) -> None:
    """
    Check if 2 consecutive same-type workouts have rpe > 8.
    If so, trigger adapt_plan("rpe_high", ...).
    """
    # Find the most recent previous workout of the same type with rpe > 8
    previous = (
        db.query(Workout)
        .filter(
            Workout.profile_id == profile_id,
            Workout.workout_type == current_workout.workout_type,
            Workout.id != current_workout.id,
            Workout.rpe_score > 8,
            Workout.scheduled_date < current_workout.scheduled_date,
        )
        .order_by(Workout.scheduled_date.desc())
        .first()
    )

    if not previous:
        return

    # Two consecutive same-type workouts with RPE > 8 — trigger adaptation
    context = {
        "workout_type": current_workout.workout_type,
        "current_workout_id": current_workout.id,
        "previous_workout_id": previous.id,
        "current_rpe": current_workout.rpe_score,
        "previous_rpe": previous.rpe_score,
    }

    logger.info(
        f"RPE >8 for 2 consecutive {current_workout.workout_type} workouts "
        f"for profile {profile_id} — triggering plan adaptation"
    )

    async def _adapt():
        from app.database import SessionLocal
        from app.services.ai_coach import adapt_plan
        adapt_db = SessionLocal()
        try:
            await adapt_plan("rpe_high", context, profile_id, adapt_db)
        except Exception as e:
            logger.error(f"RPE adaptation failed: {e}")
        finally:
            adapt_db.close()

    if background_tasks is not None:
        background_tasks.add_task(asyncio.run, _adapt())
    else:
        # Fire-and-forget if no background_tasks available
        asyncio.create_task(_adapt())
