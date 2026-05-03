import logging
from datetime import date, timedelta
from sqlalchemy.orm import Session
from app.models.orm import ProfileSettings, Workout, Run, Profile

logger = logging.getLogger(__name__)


def send_push(subscription: dict, title: str, body: str) -> bool:
    """
    Send a Web Push notification to the given subscription endpoint.
    Returns True on success, False on failure.
    """
    try:
        from pywebpush import webpush, WebPushException
        from app.config import get_settings
        settings = get_settings()

        webpush(
            subscription_info=subscription,
            data=f'{{"title": "{title}", "body": "{body}"}}',
            vapid_private_key=settings.secret_key[:32],  # use first 32 chars as VAPID key placeholder
            vapid_claims={"sub": "mailto:admin@localhost"},
        )
        return True
    except Exception as e:
        logger.warning(f"Push notification failed: {e}")
        return False


def dispatch_workout_reminder(profile_id: int, db: Session) -> bool:
    """
    Send a workout reminder for tomorrow's scheduled workout.
    Returns True if a notification was sent.
    """
    profile_settings = (
        db.query(ProfileSettings)
        .filter(ProfileSettings.profile_id == profile_id)
        .first()
    )

    if not profile_settings or not profile_settings.notification_enabled:
        return False
    if not profile_settings.push_subscription:
        return False

    tomorrow = date.today() + timedelta(days=1)
    workout = (
        db.query(Workout)
        .filter(
            Workout.profile_id == profile_id,
            Workout.scheduled_date == tomorrow,
            Workout.status == "scheduled",
            Workout.workout_type != "rest",
        )
        .first()
    )

    if not workout:
        return False

    profile = db.query(Profile).filter(Profile.id == profile_id).first()
    name = profile.display_name if profile else f"Profile {profile_id}"
    distance_km = (
        round(workout.target_distance_metres / 1000, 1)
        if workout.target_distance_metres
        else 0
    )

    title = f"Tomorrow's workout — {workout.workout_type.title()} Run"
    body = f"{distance_km} km at {workout.target_pace_zone} pace. You've got this, {name}!"

    return send_push(profile_settings.push_subscription, title, body)


def dispatch_inactivity_check(profile_id: int, db: Session) -> bool:
    """
    Send a motivational check-in if no run has been logged in the past 3 days.
    Returns True if a notification was sent.
    """
    profile_settings = (
        db.query(ProfileSettings)
        .filter(ProfileSettings.profile_id == profile_id)
        .first()
    )

    if not profile_settings or not profile_settings.notification_enabled:
        return False
    if not profile_settings.push_subscription:
        return False

    three_days_ago = date.today() - timedelta(days=3)
    recent_run = (
        db.query(Run)
        .filter(
            Run.profile_id == profile_id,
            Run.date >= three_days_ago,
        )
        .first()
    )

    if recent_run:
        return False  # Activity found — no check-in needed

    # Check if there's an active training plan
    from app.models.orm import TrainingPlan
    active_plan = (
        db.query(TrainingPlan)
        .filter(
            TrainingPlan.profile_id == profile_id,
            TrainingPlan.status == "active",
        )
        .first()
    )

    if not active_plan:
        return False

    title = "Missing you on the roads! 👟"
    body = (
        "You haven't logged a run in 3 days. "
        "Your training plan is waiting — even an easy 20 min counts!"
    )

    return send_push(profile_settings.push_subscription, title, body)
