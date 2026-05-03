"""Strava sync service — fetch new activities and import as Run records."""
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from app.models.orm import StravaToken, Run, Profile
from app.services import strava_client
from app.services.workout_matcher import match_run_to_workout, calculate_deviation_pct

logger = logging.getLogger(__name__)


def _strava_type_to_run_type(activity_type: str) -> str | None:
    """Map Strava activity type string to internal run_type."""
    mapping = {
        "Run": None,  # let workout matcher determine
        "EasyRun": "easy",
        "TempoRun": "tempo",
        "Workout": "interval",
        "LongRun": "long",
        "Race": "race",
    }
    return mapping.get(activity_type)


async def sync_profile(profile_id: int, db: Session) -> int:
    """
    Fetch new Strava activities since last_sync_at (or 90 days ago for first sync).
    Creates Run records, matches to workouts, triggers plan adaptation if needed.
    Returns the number of new runs imported.
    """
    token = db.query(StravaToken).filter(StravaToken.profile_id == profile_id).first()
    if token is None:
        logger.debug(f"No Strava token for profile {profile_id}, skipping sync")
        return 0

    # Determine fetch window
    if token.last_sync_at:
        last_sync = token.last_sync_at
        if last_sync.tzinfo is None:
            last_sync = last_sync.replace(tzinfo=timezone.utc)
        after_ts = int(last_sync.timestamp())
    else:
        after_ts = int((datetime.now(timezone.utc) - timedelta(days=90)).timestamp())

    try:
        activities = await strava_client.fetch_activities(profile_id, after_ts, db)
    except Exception as e:
        token.sync_error = str(e)
        db.commit()
        logger.error(f"Strava fetch failed for profile {profile_id}: {e}")
        return 0

    imported = 0
    for activity in activities:
        # fetch_activities already filters to Run type only
        strava_id = activity.id
        # Idempotency check
        existing = (
            db.query(Run)
            .filter(Run.profile_id == profile_id, Run.strava_activity_id == strava_id)
            .first()
        )
        if existing:
            continue

        distance_m = activity.distance
        duration_s = activity.moving_time
        if distance_m <= 0 or duration_s <= 0:
            continue

        avg_pace = (duration_s / 60) / (distance_m / 1000) * 60 if distance_m > 0 else None

        started_at = activity.start_date
        run_date = started_at.date() if started_at else datetime.now(timezone.utc).date()

        run = Run(
            profile_id=profile_id,
            source="strava",
            strava_activity_id=strava_id,
            date=run_date,
            started_at=started_at,
            distance_metres=distance_m,
            duration_seconds=duration_s,
            avg_pace_sec_per_km=avg_pace,
            avg_heart_rate=activity.average_heartrate,
            elevation_gain_metres=activity.total_elevation_gain,
            run_type=_strava_type_to_run_type(activity.type),
            raw_strava_data=activity.raw,
        )
        db.add(run)
        db.flush()

        # Match to workout
        workout = match_run_to_workout(run, profile_id, db)
        if workout:
            deviation = calculate_deviation_pct(run, workout)
            if deviation is not None and deviation > 0.20:
                # Trigger plan adaptation asynchronously
                try:
                    import asyncio
                    from app.services.ai_coach import adapt_plan
                    asyncio.create_task(
                        adapt_plan(
                            "run_deviation",
                            {
                                "run_id": run.id,
                                "workout_id": workout.id,
                                "deviation_pct": round(deviation * 100, 1),
                            },
                            profile_id,
                            db,
                        )
                    )
                except Exception as e:
                    logger.warning(f"Plan adaptation task creation failed: {e}")

        imported += 1

    # Update last_sync_at
    token.last_sync_at = datetime.now(timezone.utc)
    token.sync_error = None
    db.commit()

    logger.info(f"Strava sync complete for profile {profile_id}: {imported} new runs")
    return imported


async def sync_all_profiles(db: Session) -> None:
    """Sync all profiles that have a connected Strava account."""
    tokens = db.query(StravaToken).all()
    for token in tokens:
        try:
            await sync_profile(token.profile_id, db)
        except Exception as e:
            logger.error(f"Sync failed for profile {token.profile_id}: {e}")
