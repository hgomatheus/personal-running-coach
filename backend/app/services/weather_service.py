"""Weather service — Open-Meteo API client with 3-hour cache."""
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone, timedelta

import httpx
from sqlalchemy.orm import Session

from app.models.orm import ProfileWeatherSettings, WeatherCache

logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
CACHE_TTL_HOURS = 3


@dataclass
class WeatherForecast:
    """Weather forecast data for a specific location and date."""
    temperature_c: float
    humidity_pct: float
    wind_kmh: float
    conditions: str
    cached: bool


def _location_key(lat: float, lon: float) -> str:
    """Normalise lat/lon to a cache key string."""
    return f"{lat:.4f},{lon:.4f}"


def _wmo_to_conditions(wmo_code: int) -> str:
    """Map WMO weather code to a human-readable condition string."""
    if wmo_code == 0:
        return "clear"
    elif wmo_code in (1, 2, 3):
        return "cloudy"
    elif wmo_code in range(51, 68):
        return "rain"
    elif wmo_code in range(71, 78):
        return "snow"
    elif wmo_code in range(80, 83):
        return "rain"
    elif wmo_code in range(95, 100):
        return "thunderstorm"
    return "cloudy"


async def get_forecast(
    profile_id: int,
    forecast_date: date,
    db: Session,
) -> WeatherForecast | None:
    """
    Get weather forecast for a profile's location on a given date.

    1. Loads ProfileWeatherSettings for the profile — returns None if no location set.
    2. Checks WeatherCache for a cached entry (same location_key + forecast_date) with TTL ≤ 3 hours.
    3. If cache miss, calls Open-Meteo API.
    4. Parses response and stores in WeatherCache.
    5. Returns a WeatherForecast dataclass.
    """
    settings = (
        db.query(ProfileWeatherSettings)
        .filter(ProfileWeatherSettings.profile_id == profile_id)
        .first()
    )

    if settings is None or settings.latitude is None or settings.longitude is None:
        return None

    lat = settings.latitude
    lon = settings.longitude
    loc_key = _location_key(lat, lon)

    # Check cache (3-hour TTL)
    now = datetime.now(timezone.utc)
    cache_cutoff = now - timedelta(hours=CACHE_TTL_HOURS)

    cached = (
        db.query(WeatherCache)
        .filter(
            WeatherCache.location_key == loc_key,
            WeatherCache.forecast_date == forecast_date,
            WeatherCache.fetched_at >= cache_cutoff,
        )
        .order_by(WeatherCache.fetched_at.desc())
        .first()
    )

    if cached:
        return WeatherForecast(
            temperature_c=cached.temperature_c,
            humidity_pct=cached.humidity_pct,
            wind_kmh=cached.wind_kmh,
            conditions=cached.conditions,
            cached=True,
        )

    # Fetch from Open-Meteo API
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                OPEN_METEO_URL,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "daily": "temperature_2m_max,precipitation_sum,windspeed_10m_max,relativehumidity_2m_max,weathercode",
                    "timezone": "auto",
                    "start_date": forecast_date.isoformat(),
                    "end_date": forecast_date.isoformat(),
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.error(f"Open-Meteo API call failed: {e}")
        return None

    daily = data.get("daily", {})
    if not daily.get("time"):
        return None

    temperature_c = (daily.get("temperature_2m_max") or [15.0])[0] or 15.0
    humidity_pct = (daily.get("relativehumidity_2m_max") or [50.0])[0] or 50.0
    wind_kmh = (daily.get("windspeed_10m_max") or [0.0])[0] or 0.0
    precipitation = (daily.get("precipitation_sum") or [0.0])[0] or 0.0
    wmo_code = int((daily.get("weathercode") or [0])[0] or 0)
    conditions = _wmo_to_conditions(wmo_code)

    # If precipitation > 0 but WMO code didn't map to rain, override conditions
    if precipitation > 0 and conditions not in ("rain", "thunderstorm"):
        conditions = "rain"

    # Store in cache
    cache_entry = WeatherCache(
        location_key=loc_key,
        forecast_date=forecast_date,
        fetched_at=now,
        temperature_c=temperature_c,
        humidity_pct=humidity_pct,
        wind_kmh=wind_kmh,
        conditions=conditions,
        raw_response=data,
    )
    db.add(cache_entry)
    db.commit()

    return WeatherForecast(
        temperature_c=temperature_c,
        humidity_pct=humidity_pct,
        wind_kmh=wind_kmh,
        conditions=conditions,
        cached=False,
    )


def build_advisories(forecast: WeatherForecast) -> list[str]:
    """
    Build a list of advisory keys from a WeatherForecast.

    Thresholds:
    - "heat" if temperature_c > 25°C OR humidity_pct > 80%
    - "rain" if conditions contains "rain" or precipitation > 0
    - "wind" if wind_kmh > 30
    """
    advisories: list[str] = []

    if forecast.temperature_c > 25 or forecast.humidity_pct > 80:
        advisories.append("heat")

    if "rain" in forecast.conditions:
        advisories.append("rain")

    if forecast.wind_kmh > 30:
        advisories.append("wind")

    return advisories


def format_advisory_text(key: str) -> str:
    """Return human-readable advisory text for an advisory key."""
    texts = {
        "heat": "High heat or humidity — hydrate well, consider running early morning or evening.",
        "rain": "Rain expected — wear moisture-wicking layers and watch for slippery surfaces.",
        "wind": "Strong winds forecast — adjust your effort on exposed sections and expect slower paces.",
    }
    return texts.get(key, key)
