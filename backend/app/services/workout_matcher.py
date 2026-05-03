from datetime import date, timedelta
from sqlalchemy.orm import Session
from app.models.orm import Workout, Run

# Workout types that are compatible with each run type for matching
COMPATIBLE_TYPES = {
    "easy":     {"easy", "recovery", None},
    "tempo":    {"tempo", None},
    "interval": {"interval", None},
    "hills":    {"hills", None},
    "long":     {"long", None},
    "race":     {"race", None},
    "rest":     set(),      # rest days never match a run
    "recovery": {"easy", "recovery", None},
}


def match_run_to_workout(run: Run, profile_id: int, db: Session) -> Workout | None:
    """
    Find a scheduled workout on the same date as the run for the given profile.
    Sets matched_run_id on the workout if a match is found.
    Returns the matched Workout or None.
    """
    # Find scheduled workouts on the same date for this profile
    candidates = (
        db.query(Workout)
        .filter(
            Workout.profile_id == profile_id,
            Workout.scheduled_date == run.date,
            Workout.status == "scheduled",
            Workout.workout_type != "rest",
        )
        .all()
    )

    if not candidates:
        return None

    # Find best match: prefer type-compatible workout
    run_type = run.run_type
    for workout in candidates:
        compatible = COMPATIBLE_TYPES.get(workout.workout_type, set())
        if run_type in compatible or run_type is None:
            workout.matched_run_id = run.id
            workout.status = "completed"
            db.commit()
            return workout

    # Fallback: match the first candidate regardless of type
    workout = candidates[0]
    workout.matched_run_id = run.id
    workout.status = "completed"
    db.commit()
    return workout


def calculate_deviation_pct(run: Run, workout: Workout) -> float | None:
    """
    Calculate the percentage deviation of actual run distance from target.
    Returns None if workout has no target distance.
    """
    if not workout.target_distance_metres or workout.target_distance_metres == 0:
        return None
    return abs(run.distance_metres - workout.target_distance_metres) / workout.target_distance_metres
