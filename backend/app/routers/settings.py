"""Settings router.

Routes:
  GET/PUT /api/v1/settings                              — shared AppSettings
  GET/PUT /api/v1/profiles/{profile_id}/settings        — ProfileSettings

Note: GET/PUT /api/v1/profiles/{profile_id}/settings/weather is handled by
      app.routers.weather (task 11.2).
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.orm import AppSettings, Profile, ProfileSettings
from app.models.schemas import (
    AppSettingsResponse,
    AppSettingsUpdate,
    ProfileSettingsResponse,
    ProfileSettingsUpdate,
)

router = APIRouter(tags=["settings"])

VALID_PROFILE_IDS = {1, 2}


def _require_profile(profile_id: int, db: Session) -> Profile:
    if profile_id not in VALID_PROFILE_IDS:
        raise HTTPException(status_code=404, detail="Profile not found")
    profile = db.query(Profile).filter(Profile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


# ---------------------------------------------------------------------------
# Shared AppSettings (singleton row id=1)
# ---------------------------------------------------------------------------

@router.get("/settings", response_model=AppSettingsResponse)
def get_app_settings(db: Session = Depends(get_db)):
    settings = db.query(AppSettings).filter(AppSettings.id == 1).first()
    if not settings:
        raise HTTPException(status_code=404, detail="App settings not found")
    return settings


@router.put("/settings", response_model=AppSettingsResponse)
def update_app_settings(body: AppSettingsUpdate, db: Session = Depends(get_db)):
    settings = db.query(AppSettings).filter(AppSettings.id == 1).first()
    if not settings:
        raise HTTPException(status_code=404, detail="App settings not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(settings, field, value)
    db.commit()
    db.refresh(settings)
    return settings


# ---------------------------------------------------------------------------
# Per-profile notification settings
# ---------------------------------------------------------------------------

def _get_or_create_profile_settings(profile_id: int, db: Session) -> ProfileSettings:
    ps = db.query(ProfileSettings).filter(ProfileSettings.profile_id == profile_id).first()
    if not ps:
        ps = ProfileSettings(profile_id=profile_id, notification_enabled=True)
        db.add(ps)
        db.commit()
        db.refresh(ps)
    return ps


@router.get("/profiles/{profile_id}/settings", response_model=ProfileSettingsResponse)
def get_profile_settings(profile_id: int, db: Session = Depends(get_db)):
    _require_profile(profile_id, db)
    return _get_or_create_profile_settings(profile_id, db)


@router.put("/profiles/{profile_id}/settings", response_model=ProfileSettingsResponse)
def update_profile_settings(
    profile_id: int,
    body: ProfileSettingsUpdate,
    db: Session = Depends(get_db),
):
    _require_profile(profile_id, db)
    ps = _get_or_create_profile_settings(profile_id, db)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(ps, field, value)
    db.commit()
    db.refresh(ps)
    return ps
