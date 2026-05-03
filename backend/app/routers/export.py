"""Garmin FIT export endpoint."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.orm import Workout, PaceZones
from app.services.fit_exporter import export as fit_export

logger = logging.getLogger(__name__)

router = APIRouter(tags=["export"])


@router.get("/workouts/{workout_id}/export/fit")
def export_workout_fit(
    workout_id: int,
    profile_id: int = Query(...),
    db: Session = Depends(get_db),
):
    """
    Download a workout as a Garmin FIT file.
    Returns HTTP 404 if workout not found, HTTP 422 if a step is missing distance.
    """
    workout = (
        db.query(Workout)
        .filter(Workout.id == workout_id, Workout.profile_id == profile_id)
        .first()
    )
    if workout is None:
        raise HTTPException(status_code=404, detail="Workout not found")

    pace_zones = (
        db.query(PaceZones).filter(PaceZones.profile_id == profile_id).first()
    )

    try:
        fit_bytes = fit_export(workout, pace_zones)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"FIT export failed for workout {workout_id}: {e}")
        raise HTTPException(status_code=500, detail="FIT export failed")

    filename = f"{workout.workout_type}_{workout.scheduled_date}.fit"
    return Response(
        content=fit_bytes,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
