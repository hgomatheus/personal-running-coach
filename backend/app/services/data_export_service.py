"""Data export/import service — serialise and restore all profile data."""
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.orm import (
    Profile, PaceZones, HeartRateZones, RaceGoal,
    TrainingPlan, TrainingBlock, Workout, Run, ImportRecord,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0"


def _to_dict(obj) -> dict:
    """Convert a SQLAlchemy ORM object to a plain dict."""
    result = {}
    for col in obj.__table__.columns:
        val = getattr(obj, col.name)
        if isinstance(val, datetime):
            val = val.isoformat()
        elif hasattr(val, "isoformat"):  # date
            val = val.isoformat()
        result[col.name] = val
    return result


def export_profile(profile_id: int, db: Session) -> dict:
    """
    Serialise all profile data to a ProfileDataExport dict.
    Includes: profile, pace_zones, hr_zones, race_goals,
    training_plans (with blocks and workouts), runs, import_history.
    """
    profile = db.query(Profile).filter(Profile.id == profile_id).first()
    if profile is None:
        raise ValueError(f"Profile {profile_id} not found")

    pace_zones = db.query(PaceZones).filter(PaceZones.profile_id == profile_id).first()
    hr_zones = db.query(HeartRateZones).filter(HeartRateZones.profile_id == profile_id).first()
    race_goals = db.query(RaceGoal).filter(RaceGoal.profile_id == profile_id).all()
    plans = db.query(TrainingPlan).filter(TrainingPlan.profile_id == profile_id).all()
    runs = db.query(Run).filter(Run.profile_id == profile_id).order_by(Run.date).all()
    import_history = (
        db.query(ImportRecord)
        .filter(ImportRecord.profile_id == profile_id)
        .order_by(ImportRecord.imported_at)
        .all()
    )

    # Build plans with nested blocks and workouts
    plans_data = []
    for plan in plans:
        plan_dict = _to_dict(plan)
        blocks = (
            db.query(TrainingBlock)
            .filter(
                TrainingBlock.plan_id == plan.id,
                TrainingBlock.profile_id == profile_id,
            )
            .order_by(TrainingBlock.sequence)
            .all()
        )
        blocks_data = []
        for block in blocks:
            block_dict = _to_dict(block)
            workouts = (
                db.query(Workout)
                .filter(
                    Workout.block_id == block.id,
                    Workout.profile_id == profile_id,
                )
                .order_by(Workout.scheduled_date)
                .all()
            )
            block_dict["workouts"] = [_to_dict(w) for w in workouts]
            blocks_data.append(block_dict)
        plan_dict["blocks"] = blocks_data
        plans_data.append(plan_dict)

    return {
        "schema_version": SCHEMA_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "profile": _to_dict(profile),
        "pace_zones": _to_dict(pace_zones) if pace_zones else None,
        "hr_zones": _to_dict(hr_zones) if hr_zones else None,
        "race_goals": [_to_dict(g) for g in race_goals],
        "training_plans": plans_data,
        "runs": [_to_dict(r) for r in runs],
        "import_history": [_to_dict(i) for i in import_history],
    }


def import_profile(data: dict, profile_id: int, mode: str, db: Session) -> dict:
    """
    Restore profile data from a ProfileDataExport dict.
    mode="merge": skip existing records (idempotent).
    mode="replace": delete all existing data first, then restore.
    Returns a summary dict.
    """
    schema_version = data.get("schema_version")
    if schema_version != SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported schema version: {schema_version}. Expected {SCHEMA_VERSION}"
        )

    if mode == "replace":
        _delete_profile_data(profile_id, db)

    stats = {
        "race_goals_imported": 0,
        "plans_imported": 0,
        "runs_imported": 0,
        "import_history_imported": 0,
    }

    # Restore race goals
    for goal_data in data.get("race_goals", []):
        if mode == "merge":
            existing = db.query(RaceGoal).filter(RaceGoal.id == goal_data["id"]).first()
            if existing:
                continue
        goal = RaceGoal(
            profile_id=profile_id,
            distance_metres=goal_data["distance_metres"],
            target_date=_parse_date(goal_data["target_date"]),
            label=goal_data.get("label"),
            is_active=goal_data.get("is_active", True),
        )
        db.add(goal)
        stats["race_goals_imported"] += 1

    db.flush()

    # Restore training plans with blocks and workouts
    for plan_data in data.get("training_plans", []):
        if mode == "merge":
            existing = db.query(TrainingPlan).filter(TrainingPlan.id == plan_data["id"]).first()
            if existing:
                continue
        plan = TrainingPlan(
            profile_id=profile_id,
            start_date=_parse_date(plan_data["start_date"]),
            end_date=_parse_date(plan_data["end_date"]),
            status=plan_data.get("status", "archived"),
            gemini_prompt_hash=plan_data.get("gemini_prompt_hash"),
        )
        db.add(plan)
        db.flush()

        for block_data in plan_data.get("blocks", []):
            block = TrainingBlock(
                profile_id=profile_id,
                plan_id=plan.id,
                name=block_data["name"],
                start_date=_parse_date(block_data["start_date"]),
                end_date=_parse_date(block_data["end_date"]),
                sequence=block_data.get("sequence", 0),
            )
            db.add(block)
            db.flush()

            for workout_data in block_data.get("workouts", []):
                workout = Workout(
                    profile_id=profile_id,
                    block_id=block.id,
                    plan_id=plan.id,
                    scheduled_date=_parse_date(workout_data["scheduled_date"]),
                    workout_type=workout_data.get("workout_type", "easy"),
                    target_distance_metres=workout_data.get("target_distance_metres"),
                    target_pace_zone=workout_data.get("target_pace_zone"),
                    target_hr_zone=workout_data.get("target_hr_zone"),
                    steps=workout_data.get("steps", []),
                    coaching_note=workout_data.get("coaching_note"),
                    status=workout_data.get("status", "scheduled"),
                    rpe_score=workout_data.get("rpe_score"),
                )
                db.add(workout)

        stats["plans_imported"] += 1

    # Restore runs
    for run_data in data.get("runs", []):
        if mode == "merge":
            strava_id = run_data.get("strava_activity_id")
            if strava_id is not None:
                # For Strava runs, deduplicate by strava_activity_id
                existing = (
                    db.query(Run)
                    .filter(Run.profile_id == profile_id, Run.strava_activity_id == strava_id)
                    .first()
                )
            else:
                # For manual runs, deduplicate by id
                existing = db.query(Run).filter(Run.id == run_data["id"]).first()
            if existing:
                continue
        run = Run(
            profile_id=profile_id,
            source=run_data.get("source", "manual"),
            strava_activity_id=run_data.get("strava_activity_id"),
            date=_parse_date(run_data["date"]),
            distance_metres=run_data["distance_metres"],
            duration_seconds=run_data["duration_seconds"],
            avg_pace_sec_per_km=run_data.get("avg_pace_sec_per_km"),
            avg_heart_rate=run_data.get("avg_heart_rate"),
            elevation_gain_metres=run_data.get("elevation_gain_metres"),
            run_type=run_data.get("run_type"),
            notes=run_data.get("notes"),
        )
        db.add(run)
        stats["runs_imported"] += 1

    # Restore import history
    for record_data in data.get("import_history", []):
        if mode == "merge":
            existing = db.query(ImportRecord).filter(ImportRecord.id == record_data["id"]).first()
            if existing:
                continue
        record = ImportRecord(
            profile_id=profile_id,
            activities_imported=record_data.get("activities_imported", 0),
            duplicates_skipped=record_data.get("duplicates_skipped", 0),
            parse_errors=record_data.get("parse_errors", 0),
            vdot_calculated=record_data.get("vdot_calculated"),
            source_filename=record_data.get("source_filename"),
        )
        db.add(record)
        stats["import_history_imported"] += 1

    db.commit()
    logger.info(f"Profile {profile_id} import complete (mode={mode}): {stats}")
    return stats


def _delete_profile_data(profile_id: int, db: Session) -> None:
    """Delete all data for a profile (except the Profile record itself)."""
    # Delete in dependency order
    db.query(Workout).filter(Workout.profile_id == profile_id).delete()
    db.query(TrainingBlock).filter(TrainingBlock.profile_id == profile_id).delete()
    db.query(TrainingPlan).filter(TrainingPlan.profile_id == profile_id).delete()
    db.query(Run).filter(Run.profile_id == profile_id).delete()
    db.query(RaceGoal).filter(RaceGoal.profile_id == profile_id).delete()
    db.query(ImportRecord).filter(ImportRecord.profile_id == profile_id).delete()
    db.query(PaceZones).filter(PaceZones.profile_id == profile_id).delete()
    db.query(HeartRateZones).filter(HeartRateZones.profile_id == profile_id).delete()
    db.flush()
    logger.info(f"Deleted all data for profile {profile_id} (replace mode)")


def _parse_date(value: str | None):
    """Parse an ISO date string to a date object."""
    if value is None:
        return None
    from datetime import date
    try:
        return date.fromisoformat(value[:10])
    except (ValueError, TypeError):
        return None
