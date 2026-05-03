"""APScheduler setup and background job registration."""
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


# ---------------------------------------------------------------------------
# Job implementations
# ---------------------------------------------------------------------------

async def _strava_sync_job():
    """Sync Strava activities for all connected profiles."""
    from app.database import SessionLocal
    from app.services.strava_sync import sync_all_profiles

    db = SessionLocal()
    try:
        await sync_all_profiles(db)
        # Trigger route extraction after sync
        await _route_extraction_job()
    except Exception as e:
        logger.error(f"Strava sync job failed: {e}")
    finally:
        db.close()


async def _workout_reminder_job():
    """Send workout reminders for all profiles."""
    from app.database import SessionLocal
    from app.models.orm import Profile
    from app.services.notification import dispatch_workout_reminder

    db = SessionLocal()
    try:
        profiles = db.query(Profile).all()
        for profile in profiles:
            try:
                dispatch_workout_reminder(profile.id, db)
            except Exception as e:
                logger.warning(f"Workout reminder failed for profile {profile.id}: {e}")
    except Exception as e:
        logger.error(f"Workout reminder job failed: {e}")
    finally:
        db.close()


async def _inactivity_check_job():
    """Check for inactive profiles and send motivational notifications."""
    from app.database import SessionLocal
    from app.models.orm import Profile
    from app.services.notification import dispatch_inactivity_check

    db = SessionLocal()
    try:
        profiles = db.query(Profile).all()
        for profile in profiles:
            try:
                dispatch_inactivity_check(profile.id, db)
            except Exception as e:
                logger.warning(f"Inactivity check failed for profile {profile.id}: {e}")
    except Exception as e:
        logger.error(f"Inactivity check job failed: {e}")
    finally:
        db.close()


async def _daily_backup_job():
    """Run daily database backup and prune old backups."""
    from app.database import SessionLocal
    from app.models.orm import AppSettings
    from app.services.backup_service import run_backup, prune_backups

    db = SessionLocal()
    try:
        settings = db.query(AppSettings).filter(AppSettings.id == 1).first()
        if settings and not settings.backup_enabled:
            logger.info("Backup disabled in settings — skipping")
            return

        record = run_backup(db)
        if record.success:
            retain = settings.backup_retention_days if settings else 30
            prune_backups(db, retain=retain)
    except Exception as e:
        logger.error(f"Daily backup job failed: {e}")
    finally:
        db.close()


async def _weather_prefetch_job():
    """Pre-fetch weather forecasts for each profile's next 7 days of workouts."""
    from datetime import date, timedelta
    from app.database import SessionLocal
    from app.models.orm import Profile, Workout, ProfileWeatherSettings
    from app.services.weather_service import get_forecast

    db = SessionLocal()
    try:
        profiles = db.query(Profile).all()
        today = date.today()
        for profile in profiles:
            weather_settings = (
                db.query(ProfileWeatherSettings)
                .filter(ProfileWeatherSettings.profile_id == profile.id)
                .first()
            )
            if not weather_settings or not weather_settings.weather_advisories_enabled:
                continue
            if weather_settings.latitude is None or weather_settings.longitude is None:
                continue

            # Find next 7 days of scheduled workouts
            upcoming_dates = set()
            for i in range(7):
                upcoming_dates.add(today + timedelta(days=i))

            workouts = (
                db.query(Workout)
                .filter(
                    Workout.profile_id == profile.id,
                    Workout.scheduled_date.in_(list(upcoming_dates)),
                    Workout.status == "scheduled",
                )
                .all()
            )

            for workout in workouts:
                try:
                    await get_forecast(profile.id, workout.scheduled_date, db)
                except Exception as e:
                    logger.warning(
                        f"Weather prefetch failed for profile {profile.id} "
                        f"date {workout.scheduled_date}: {e}"
                    )
    except Exception as e:
        logger.error(f"Weather prefetch job failed: {e}")
    finally:
        db.close()


async def _route_extraction_job():
    """Extract GPS routes from Strava run data for all profiles."""
    from app.database import SessionLocal
    from app.models.orm import Profile
    from app.services.route_extractor import extract_routes

    db = SessionLocal()
    try:
        profiles = db.query(Profile).all()
        for profile in profiles:
            try:
                count = extract_routes(profile.id, db)
                if count > 0:
                    logger.info(f"Extracted {count} new routes for profile {profile.id}")
            except Exception as e:
                logger.warning(f"Route extraction failed for profile {profile.id}: {e}")
    except Exception as e:
        logger.error(f"Route extraction job failed: {e}")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Scheduler setup
# ---------------------------------------------------------------------------

def setup_scheduler(app_settings_getter):
    """Register all background jobs. Called during app lifespan startup."""
    settings = app_settings_getter()

    # Strava sync — configurable interval from DB AppSettings (default 15 min)
    sync_interval = 15
    try:
        from app.database import SessionLocal
        from app.models.orm import AppSettings as AppSettingsORM
        db = SessionLocal()
        try:
            db_settings = db.query(AppSettingsORM).filter(AppSettingsORM.id == 1).first()
            if db_settings and db_settings.strava_sync_interval_minutes:
                sync_interval = db_settings.strava_sync_interval_minutes
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Could not read strava_sync_interval_minutes from DB, using default {sync_interval}min: {e}")
    scheduler.add_job(
        _strava_sync_job,
        trigger=IntervalTrigger(minutes=sync_interval),
        id="strava_sync",
        replace_existing=True,
        misfire_grace_time=60,
    )

    # Workout reminder — daily at 20:00 UTC
    scheduler.add_job(
        _workout_reminder_job,
        trigger=CronTrigger(hour=20, minute=0),
        id="workout_reminder",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # Inactivity check — daily at 09:00 UTC
    scheduler.add_job(
        _inactivity_check_job,
        trigger=CronTrigger(hour=9, minute=0),
        id="inactivity_check",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # Daily backup — daily at 02:00 UTC
    scheduler.add_job(
        _daily_backup_job,
        trigger=CronTrigger(hour=2, minute=0),
        id="daily_backup",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # Weather prefetch — daily at 06:00 UTC
    scheduler.add_job(
        _weather_prefetch_job,
        trigger=CronTrigger(hour=6, minute=0),
        id="weather_prefetch",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # Route extraction — runs after strava_sync (also triggered directly from sync job)
    # Register as a standalone daily job as fallback
    scheduler.add_job(
        _route_extraction_job,
        trigger=CronTrigger(hour=3, minute=0),
        id="route_extraction",
        replace_existing=True,
        misfire_grace_time=300,
    )

    logger.info(
        f"Scheduler configured: strava_sync every {sync_interval}min, "
        "workout_reminder@20:00, inactivity_check@09:00, "
        "daily_backup@02:00, weather_prefetch@06:00, route_extraction@03:00"
    )


def start_scheduler():
    """Start the scheduler if it is not already running."""
    if not scheduler.running:
        scheduler.start()
        logger.info("APScheduler started")


def stop_scheduler():
    """Shut down the scheduler gracefully."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped")
