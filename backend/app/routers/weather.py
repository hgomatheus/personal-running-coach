"""Weather forecast and weather settings endpoints."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.orm import Profile, ProfileWeatherSettings, Workout
from app.models.schemas import (
    ProfileWeatherSettingsResponse,
    ProfileWeatherSettingsUpdate,
    WeatherForecastResponse,
)
from app.services.weather_service import build_advisories, get_forecast

logger = logging.getLogger(__name__)

router = APIRouter(tags=["weather"])

VALID_PROFILE_IDS = {1, 2}


def _require_profile(profile_id: int, db: Session) -> Profile:
    if profile_id not in VALID_PROFILE_IDS:
        raise HTTPException(status_code=404, detail="Profile not found")
    profile = db.query(Profile).filter(Profile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


def _get_or_create_weather_settings(
    profile_id: int, db: Session
) -> ProfileWeatherSettings:
    ws = (
        db.query(ProfileWeatherSettings)
        .filter(ProfileWeatherSettings.profile_id == profile_id)
        .first()
    )
    if not ws:
        ws = ProfileWeatherSettings(
            profile_id=profile_id, weather_advisories_enabled=True
        )
        db.add(ws)
        db.commit()
        db.refresh(ws)
    return ws


# ---------------------------------------------------------------------------
# Workout weather forecast
# ---------------------------------------------------------------------------


@router.get(
    "/profiles/{profile_id}/workouts/{workout_id}/weather",
    response_model=WeatherForecastResponse,
)
async def get_workout_weather(
    profile_id: int,
    workout_id: int,
    db: Session = Depends(get_db),
):
    """Return weather forecast for a workout's scheduled date."""
    workout = (
        db.query(Workout)
        .filter(Workout.id == workout_id, Workout.profile_id == profile_id)
        .first()
    )
    if workout is None:
        raise HTTPException(status_code=404, detail="Workout not found")

    forecast = await get_forecast(profile_id, workout.scheduled_date, db)
    if forecast is None:
        raise HTTPException(
            status_code=404,
            detail="No weather data available — configure location in weather settings",
        )

    advisories = build_advisories(forecast)

    return WeatherForecastResponse(
        workout_id=workout_id,
        forecast_date=workout.scheduled_date,
        temperature_c=forecast.temperature_c,
        humidity_pct=forecast.humidity_pct,
        wind_kmh=forecast.wind_kmh,
        conditions=forecast.conditions,
        advisories=advisories,
        cached=forecast.cached,
    )


# ---------------------------------------------------------------------------
# Profile weather settings
# ---------------------------------------------------------------------------


@router.get(
    "/profiles/{profile_id}/settings/weather",
    response_model=ProfileWeatherSettingsResponse,
)
def get_weather_settings(
    profile_id: int,
    db: Session = Depends(get_db),
):
    """Return weather settings for a profile."""
    _require_profile(profile_id, db)
    return _get_or_create_weather_settings(profile_id, db)


@router.put(
    "/profiles/{profile_id}/settings/weather",
    response_model=ProfileWeatherSettingsResponse,
)
def update_weather_settings(
    profile_id: int,
    body: ProfileWeatherSettingsUpdate,
    db: Session = Depends(get_db),
):
    """Update weather settings for a profile (location, advisories toggle)."""
    _require_profile(profile_id, db)
    ws = _get_or_create_weather_settings(profile_id, db)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(ws, field, value)
    db.commit()
    db.refresh(ws)
    return ws
