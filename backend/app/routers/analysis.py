"""Post-run analysis endpoint."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.orm import Run, Workout, PaceZones
from app.models.schemas import PostRunAnalysisResponse
from app.services.post_run_analyzer import analyze

logger = logging.getLogger(__name__)

router = APIRouter(tags=["analysis"])


@router.get(
    "/profiles/{profile_id}/runs/{run_id}/analysis",
    response_model=PostRunAnalysisResponse,
)
async def get_run_analysis(
    profile_id: int,
    run_id: int,
    db: Session = Depends(get_db),
):
    """
    Return post-run analysis for a completed run.
    HTTP 404 if run not found or not matched to a workout.
    """
    run = (
        db.query(Run)
        .filter(Run.id == run_id, Run.profile_id == profile_id)
        .first()
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    # Find the workout matched to this run
    workout = (
        db.query(Workout)
        .filter(
            Workout.matched_run_id == run_id,
            Workout.profile_id == profile_id,
        )
        .first()
    )
    if workout is None:
        raise HTTPException(
            status_code=404,
            detail="Run is not matched to a workout — analysis unavailable",
        )

    pace_zones = (
        db.query(PaceZones).filter(PaceZones.profile_id == profile_id).first()
    )

    result = await analyze(run, workout, pace_zones)

    # Convert KmSplit dataclasses to dicts for Pydantic schema
    km_splits_data = [
        {"km": s.km, "pace_sec_per_km": s.pace_sec_per_km, "avg_hr": s.avg_hr}
        for s in result.km_splits
    ]

    return PostRunAnalysisResponse(
        run_id=result.run_id,
        workout_id=result.workout_id,
        target_distance_km=result.target_distance_km,
        actual_distance_km=result.actual_distance_km,
        target_pace_zone=result.target_pace_zone,
        actual_avg_pace_sec_per_km=result.actual_avg_pace_sec_per_km,
        pace_on_target=result.pace_on_target,
        pace_comparison=result.pace_comparison,
        target_hr_zone=result.target_hr_zone,
        actual_avg_hr=result.actual_avg_hr,
        actual_elevation_gain_metres=result.actual_elevation_gain_metres,
        km_splits=km_splits_data,
        coaching_summary=result.coaching_summary,
    )
