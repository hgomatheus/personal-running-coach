"""Taper status endpoint."""
import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.schemas import TaperGuidance, TaperStatusResponse
from app.services.taper_calculator import get_taper_status

logger = logging.getLogger(__name__)

router = APIRouter(tags=["taper"])


@router.get("/profiles/{profile_id}/taper", response_model=TaperStatusResponse)
def get_taper(profile_id: int, db: Session = Depends(get_db)):
    """Return taper phase status and guidance for the active training plan."""
    status = get_taper_status(profile_id, db)

    guidance = None
    if status.guidance is not None:
        guidance = TaperGuidance(
            target_mileage_reduction_pct=status.guidance.target_mileage_reduction_pct,
            sleep_nutrition_reminder=status.guidance.sleep_nutrition_reminder,
            sluggishness_note=status.guidance.sluggishness_note,
        )

    return TaperStatusResponse(
        taper_active=status.taper_active,
        days_until_race=status.days_until_race,
        taper_week=status.taper_week,
        volume_reduction_pct=status.volume_reduction_pct,
        guidance=guidance,
    )
