"""Zones router.

Routes:
  GET  /api/v1/profiles/{profile_id}/zones              — PaceZones + HeartRateZones
  POST /api/v1/profiles/{profile_id}/zones/recalculate  — recalculate from race result
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.orm import HeartRateZones, PaceZones, Profile, Workout, TrainingPlan
from app.models.schemas import HRZonesResponse, PaceZonesResponse, ZoneRecalculateRequest
from app.services.vdot import calculate_vdot, derive_pace_zones
from app.services.zones_calculator import calculate_hr_zones

router = APIRouter(tags=["zones"])

VALID_PROFILE_IDS = {1, 2}


def _require_profile(profile_id: int, db: Session) -> Profile:
    if profile_id not in VALID_PROFILE_IDS:
        raise HTTPException(status_code=404, detail="Profile not found")
    profile = db.query(Profile).filter(Profile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


class ZonesResponse(BaseModel):
    pace_zones: PaceZonesResponse | None
    hr_zones: HRZonesResponse | None


class ZoneRecalculateResponse(BaseModel):
    pace_zones: PaceZonesResponse
    hr_zones: HRZonesResponse | None
    vdot: float


@router.get("/profiles/{profile_id}/zones", response_model=ZonesResponse)
def get_zones(profile_id: int, db: Session = Depends(get_db)):
    """Return PaceZones and HeartRateZones for the profile."""
    _require_profile(profile_id, db)
    pace_zones = db.query(PaceZones).filter(PaceZones.profile_id == profile_id).first()
    hr_zones = db.query(HeartRateZones).filter(HeartRateZones.profile_id == profile_id).first()
    return ZonesResponse(
        pace_zones=PaceZonesResponse.model_validate(pace_zones) if pace_zones else None,
        hr_zones=HRZonesResponse.model_validate(hr_zones) if hr_zones else None,
    )


@router.post("/profiles/{profile_id}/zones/recalculate", response_model=ZoneRecalculateResponse)
def recalculate_zones(
    profile_id: int,
    body: ZoneRecalculateRequest,
    db: Session = Depends(get_db),
):
    """Recalculate VDOT and pace zones from a race result; optionally update HR zones."""
    _require_profile(profile_id, db)

    vdot = calculate_vdot(body.distance_metres, body.duration_seconds)
    zone_values = derive_pace_zones(vdot)

    # Upsert PaceZones
    pace_zones = db.query(PaceZones).filter(PaceZones.profile_id == profile_id).first()
    if not pace_zones:
        pace_zones = PaceZones(profile_id=profile_id)
        db.add(pace_zones)

    pace_zones.vdot = vdot
    pace_zones.easy_min_sec_per_km = zone_values.easy_min_sec_per_km
    pace_zones.easy_max_sec_per_km = zone_values.easy_max_sec_per_km
    pace_zones.moderate_min_sec_per_km = zone_values.moderate_min_sec_per_km
    pace_zones.moderate_max_sec_per_km = zone_values.moderate_max_sec_per_km
    pace_zones.threshold_min_sec_per_km = zone_values.threshold_min_sec_per_km
    pace_zones.threshold_max_sec_per_km = zone_values.threshold_max_sec_per_km
    pace_zones.vo2max_min_sec_per_km = zone_values.vo2max_min_sec_per_km
    pace_zones.vo2max_max_sec_per_km = zone_values.vo2max_max_sec_per_km
    pace_zones.anaerobic_min_sec_per_km = zone_values.anaerobic_min_sec_per_km
    pace_zones.anaerobic_max_sec_per_km = zone_values.anaerobic_max_sec_per_km
    db.flush()

    # Optionally update HR zones
    hr_zones_record = None
    if body.max_hr is not None:
        hr_values = calculate_hr_zones(body.max_hr)
        hr_zones_record = db.query(HeartRateZones).filter(
            HeartRateZones.profile_id == profile_id
        ).first()
        if not hr_zones_record:
            hr_zones_record = HeartRateZones(profile_id=profile_id)
            db.add(hr_zones_record)
        hr_zones_record.max_hr = hr_values.max_hr
        hr_zones_record.zone1_max = hr_values.zone1_max
        hr_zones_record.zone2_max = hr_values.zone2_max
        hr_zones_record.zone3_max = hr_values.zone3_max
        hr_zones_record.zone4_max = hr_values.zone4_max
        hr_zones_record.zone5_max = hr_values.zone5_max
        db.flush()

    # Task 5.2: Propagate new pace zone references to future workouts in the active plan
    _propagate_zones_to_future_workouts(profile_id, db)

    db.commit()
    db.refresh(pace_zones)
    if hr_zones_record:
        db.refresh(hr_zones_record)

    return ZoneRecalculateResponse(
        pace_zones=PaceZonesResponse.model_validate(pace_zones),
        hr_zones=HRZonesResponse.model_validate(hr_zones_record) if hr_zones_record else None,
        vdot=vdot,
    )


# Valid pace zone names
VALID_PACE_ZONES = {"easy", "moderate", "threshold", "vo2max", "anaerobic"}


def _propagate_zones_to_future_workouts(profile_id: int, db: Session) -> None:
    """
    Task 5.2: After updating PaceZones, update target_pace_zone on all future
    Workouts in the active Training_Plan for this profile where the current
    target_pace_zone is still a valid zone name.

    This ensures workouts reference valid zone names after a recalculation.
    The zone name itself doesn't change — the underlying pace values do —
    so we only need to ensure the zone name is still valid and leave it as-is.
    Any workout whose target_pace_zone is not a recognised zone name gets
    reset to "easy" as a safe fallback.
    """
    today = date.today()

    # Find the active plan for this profile
    active_plan = (
        db.query(TrainingPlan)
        .filter(
            TrainingPlan.profile_id == profile_id,
            TrainingPlan.status == "active",
        )
        .first()
    )
    if not active_plan:
        return

    # Find future workouts in the active plan with invalid zone names
    future_workouts = (
        db.query(Workout)
        .filter(
            Workout.profile_id == profile_id,
            Workout.plan_id == active_plan.id,
            Workout.scheduled_date > today,
        )
        .all()
    )

    for workout in future_workouts:
        if workout.target_pace_zone not in VALID_PACE_ZONES:
            workout.target_pace_zone = "easy"
