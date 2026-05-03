"""Strava OAuth client — token management and activity fetching."""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

import httpx
from cryptography.fernet import Fernet
import base64
import hashlib
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.orm import StravaToken

logger = logging.getLogger(__name__)

STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"
STRAVA_DEAUTH_URL = "https://www.strava.com/oauth/deauthorize"


@dataclass
class StravaActivity:
    """Typed representation of a Strava activity (Run type only)."""
    id: int
    name: str
    type: str
    start_date: datetime
    distance: float          # metres
    moving_time: int         # seconds
    average_heartrate: float | None = None
    total_elevation_gain: float | None = None
    summary_polyline: str | None = None
    raw: dict = field(default_factory=dict)


def _activity_from_dict(data: dict) -> StravaActivity:
    """Convert a raw Strava API activity dict to a StravaActivity dataclass."""
    start_date = datetime.now(timezone.utc)
    raw_date = data.get("start_date") or data.get("start_date_local")
    if raw_date:
        try:
            start_date = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
        except ValueError:
            pass

    summary_polyline: str | None = None
    map_data = data.get("map")
    if isinstance(map_data, dict):
        summary_polyline = map_data.get("summary_polyline") or None

    return StravaActivity(
        id=data["id"],
        name=data.get("name", ""),
        type=data.get("sport_type") or data.get("type", ""),
        start_date=start_date,
        distance=float(data.get("distance") or 0),
        moving_time=int(data.get("moving_time") or 0),
        average_heartrate=data.get("average_heartrate"),
        total_elevation_gain=data.get("total_elevation_gain"),
        summary_polyline=summary_polyline,
        raw=data,
    )


def _get_fernet() -> Fernet:
    """Derive a Fernet key from SECRET_KEY using SHA-256 + base64url encoding."""
    settings = get_settings()
    key_bytes = hashlib.sha256(settings.secret_key.encode()).digest()
    fernet_key = base64.urlsafe_b64encode(key_bytes)
    return Fernet(fernet_key)


def _encrypt(value: str) -> str:
    return _get_fernet().encrypt(value.encode()).decode()


def _decrypt(value: str) -> str:
    return _get_fernet().decrypt(value.encode()).decode()


async def exchange_code(code: str, profile_id: int, db: Session) -> StravaToken:
    """
    Exchange an OAuth authorisation code for access + refresh tokens.
    Stores encrypted tokens in the database.
    """
    settings = get_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            STRAVA_TOKEN_URL,
            data={
                "client_id": settings.strava_client_id,
                "client_secret": settings.strava_client_secret,
                "code": code,
                "grant_type": "authorization_code",
            },
        )
        resp.raise_for_status()
        data = resp.json()

    expires_at = datetime.fromtimestamp(data["expires_at"], tz=timezone.utc)

    token = db.query(StravaToken).filter(StravaToken.profile_id == profile_id).first()
    if token is None:
        token = StravaToken(profile_id=profile_id)
        db.add(token)

    token.athlete_id = data["athlete"]["id"]
    token.access_token = _encrypt(data["access_token"])
    token.refresh_token = _encrypt(data["refresh_token"])
    token.expires_at = expires_at
    token.sync_error = None
    db.commit()
    db.refresh(token)
    logger.info(
        "Strava token stored for profile %d, athlete %d",
        profile_id,
        token.athlete_id,
    )
    return token


async def refresh_token_if_needed(profile_id: int, db: Session) -> StravaToken | None:
    """
    Check token expiry and refresh if within 5 minutes of expiry.
    Returns the (possibly refreshed) StravaToken, or None if not connected.
    """
    token = db.query(StravaToken).filter(StravaToken.profile_id == profile_id).first()
    if token is None:
        return None

    now = datetime.now(timezone.utc)
    expires_at = token.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at - now > timedelta(minutes=5):
        return token  # still valid

    logger.info("Refreshing Strava token for profile %d", profile_id)
    settings = get_settings()
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                STRAVA_TOKEN_URL,
                data={
                    "client_id": settings.strava_client_id,
                    "client_secret": settings.strava_client_secret,
                    "refresh_token": _decrypt(token.refresh_token),
                    "grant_type": "refresh_token",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        token.access_token = _encrypt(data["access_token"])
        token.refresh_token = _encrypt(data["refresh_token"])
        token.expires_at = datetime.fromtimestamp(data["expires_at"], tz=timezone.utc)
        token.sync_error = None
        db.commit()
        db.refresh(token)
        logger.info("Strava token refreshed for profile %d", profile_id)
    except Exception as e:
        token.sync_error = str(e)
        db.commit()
        logger.error("Token refresh failed for profile %d: %s", profile_id, e)
        raise

    return token


async def fetch_activities(
    profile_id: int,
    after_timestamp: int,
    db: Session,
) -> list[StravaActivity]:
    """
    Fetch Strava running activities after the given Unix timestamp.

    Auto-refreshes the token if within 5 minutes of expiry.
    Filters to activities with type == "Run" only.
    Handles Strava API rate limits (HTTP 429) gracefully — logs the error
    and returns whatever activities have been collected so far.

    Returns a list of StravaActivity dataclass instances.
    """
    token = await refresh_token_if_needed(profile_id, db)
    if token is None:
        raise ValueError(f"No Strava token for profile {profile_id}")

    access_token = _decrypt(token.access_token)
    activities: list[StravaActivity] = []
    page = 1

    async with httpx.AsyncClient() as client:
        while True:
            try:
                resp = await client.get(
                    STRAVA_ACTIVITIES_URL,
                    headers={"Authorization": f"Bearer {access_token}"},
                    params={"after": after_timestamp, "per_page": 100, "page": page},
                )
            except httpx.RequestError as exc:
                logger.error(
                    "Network error fetching Strava activities for profile %d (page %d): %s",
                    profile_id,
                    page,
                    exc,
                )
                break

            if resp.status_code == 429:
                # Rate limit hit — log and return what we have so far
                retry_after = resp.headers.get("X-RateLimit-Limit", "unknown")
                logger.warning(
                    "Strava rate limit hit for profile %d on page %d "
                    "(X-RateLimit-Limit: %s). Returning %d activities collected so far.",
                    profile_id,
                    page,
                    retry_after,
                    len(activities),
                )
                break

            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "Strava API error for profile %d (page %d): HTTP %d — %s",
                    profile_id,
                    page,
                    exc.response.status_code,
                    exc.response.text[:200],
                )
                break

            batch: list[dict] = resp.json()
            if not batch:
                break

            for raw in batch:
                # Filter to Run type only (sport_type takes precedence over legacy type)
                activity_type = raw.get("sport_type") or raw.get("type", "")
                if activity_type != "Run":
                    continue
                try:
                    activities.append(_activity_from_dict(raw))
                except (KeyError, TypeError, ValueError) as exc:
                    logger.warning(
                        "Skipping malformed activity (id=%s): %s",
                        raw.get("id"),
                        exc,
                    )

            if len(batch) < 100:
                break
            page += 1

    logger.info(
        "Fetched %d running activities for profile %d",
        len(activities),
        profile_id,
    )
    return activities


async def revoke_token(profile_id: int, db: Session) -> bool:
    """
    Revoke the Strava token and delete the record from the database.
    Run data is retained.
    Returns True if a token was found and revoked.
    """
    token = db.query(StravaToken).filter(StravaToken.profile_id == profile_id).first()
    if token is None:
        return False

    try:
        access_token = _decrypt(token.access_token)
        async with httpx.AsyncClient() as client:
            await client.post(
                STRAVA_DEAUTH_URL,
                data={"access_token": access_token},
            )
    except Exception as e:
        logger.warning(
            "Strava deauth request failed (continuing with local deletion): %s", e
        )

    db.delete(token)
    db.commit()
    logger.info("Strava token revoked for profile %d", profile_id)
    return True
