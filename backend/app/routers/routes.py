"""GPX route suggestions endpoint."""
import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.orm import Workout
from app.models.schemas import RouteRecordResponse
from app.services.route_extractor import get_suggestions

logger = logging.getLogger(__name__)

router = APIRouter(tags=["routes"])

# Static map tile base URL (OpenStreetMap-compatible polyline thumbnail)
_STATIC_MAP_BASE = "https://maps.googleapis.com/maps/api/staticmap"


def _build_thumbnail_url(polyline: str) -> str | None:
    """Build a static map thumbnail URL from an encoded polyline."""
    if not polyline:
        return None
    # Use a simple OpenStreetMap-based static map service
    encoded = quote(polyline)
    return f"https://static-maps.yandex.ru/1.x/?l=map&pl=enc:{encoded}&size=300,200"


@router.get("/profiles/{profile_id}/routes", response_model=list[RouteRecordResponse])
def get_route_suggestions(
    profile_id: int,
    workout_id: int = Query(...),
    db: Session = Depends(get_db),
):
    """Return up to 3 route suggestions for a workout."""
    workout = (
        db.query(Workout)
        .filter(Workout.id == workout_id, Workout.profile_id == profile_id)
        .first()
    )
    if workout is None:
        raise HTTPException(status_code=404, detail="Workout not found")

    suggestions = get_suggestions(workout, profile_id, db)

    return [
        RouteRecordResponse(
            id=r.id,
            polyline=r.polyline,
            typical_distance_km=r.typical_distance_metres / 1000,
            run_count=r.run_count,
            last_used_at=r.last_used_at,
            workout_type_affinity=r.workout_type_affinity,
            thumbnail_url=_build_thumbnail_url(r.polyline),
        )
        for r in suggestions
    ]
