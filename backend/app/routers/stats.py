"""Stats router.

Routes:
  GET /api/v1/profiles/{profile_id}/stats/weekly   — weekly km totals
  GET /api/v1/profiles/{profile_id}/stats/monthly  — monthly summary
  GET /api/v1/profiles/{profile_id}/stats/prs      — personal records
  GET /api/v1/profiles/{profile_id}/stats/streak   — current and all-time streak
"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.orm import Profile, Run

router = APIRouter(tags=["stats"])

VALID_PROFILE_IDS = {1, 2}

# PR target distances in metres
PR_DISTANCES = {
    "1km": 1000,
    "5km": 5000,
    "10km": 10000,
    "half_marathon": 21097,
    "marathon": 42195,
}

PR_TOLERANCE = 0.05  # 5% tolerance


def _require_profile(profile_id: int, db: Session) -> Profile:
    if profile_id not in VALID_PROFILE_IDS:
        raise HTTPException(status_code=404, detail="Profile not found")
    profile = db.query(Profile).filter(Profile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class WeeklyStats(BaseModel):
    week_start: date
    total_km: float
    run_count: int


class MonthlyStats(BaseModel):
    year: int
    month: int
    total_km: float
    total_duration_seconds: int
    run_count: int


class PersonalRecord(BaseModel):
    distance_label: str
    target_distance_metres: int
    run_id: int | None
    run_date: date | None
    distance_metres: float | None
    duration_seconds: int | None
    avg_pace_sec_per_km: float | None


class PRsResponse(BaseModel):
    records: list[PersonalRecord]


class StreakResponse(BaseModel):
    current_streak: int
    all_time_streak: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/profiles/{profile_id}/stats/weekly", response_model=list[WeeklyStats])
def weekly_stats(profile_id: int, db: Session = Depends(get_db)):
    """
    Return list of {week_start, total_km, run_count} for all weeks with runs.
    Week starts on Monday (ISO week).
    """
    _require_profile(profile_id, db)

    runs = (
        db.query(Run)
        .filter(Run.profile_id == profile_id)
        .order_by(Run.date.asc())
        .all()
    )

    if not runs:
        return []

    # Group by ISO week start (Monday)
    week_map: dict[date, dict] = {}
    for run in runs:
        # Calculate Monday of the run's week
        run_date = run.date
        week_start = run_date - timedelta(days=run_date.weekday())
        if week_start not in week_map:
            week_map[week_start] = {"total_metres": 0.0, "run_count": 0}
        week_map[week_start]["total_metres"] += run.distance_metres
        week_map[week_start]["run_count"] += 1

    return [
        WeeklyStats(
            week_start=ws,
            total_km=round(data["total_metres"] / 1000, 2),
            run_count=data["run_count"],
        )
        for ws, data in sorted(week_map.items())
    ]


@router.get("/profiles/{profile_id}/stats/monthly", response_model=list[MonthlyStats])
def monthly_stats(profile_id: int, db: Session = Depends(get_db)):
    """Return list of monthly summaries for all months with runs."""
    _require_profile(profile_id, db)

    runs = (
        db.query(Run)
        .filter(Run.profile_id == profile_id)
        .order_by(Run.date.asc())
        .all()
    )

    if not runs:
        return []

    # Group by year + month
    month_map: dict[tuple[int, int], dict] = {}
    for run in runs:
        key = (run.date.year, run.date.month)
        if key not in month_map:
            month_map[key] = {"total_metres": 0.0, "total_duration": 0, "run_count": 0}
        month_map[key]["total_metres"] += run.distance_metres
        month_map[key]["total_duration"] += run.duration_seconds
        month_map[key]["run_count"] += 1

    return [
        MonthlyStats(
            year=year,
            month=month,
            total_km=round(data["total_metres"] / 1000, 2),
            total_duration_seconds=data["total_duration"],
            run_count=data["run_count"],
        )
        for (year, month), data in sorted(month_map.items())
    ]


@router.get("/profiles/{profile_id}/stats/prs", response_model=PRsResponse)
def personal_records(profile_id: int, db: Session = Depends(get_db)):
    """
    Return personal records for standard distances.
    PR = run with minimum avg_pace_sec_per_km where distance_metres is within 5% of target.
    """
    _require_profile(profile_id, db)

    records = []
    for label, target_m in PR_DISTANCES.items():
        lower = target_m * (1 - PR_TOLERANCE)
        upper = target_m * (1 + PR_TOLERANCE)

        # Find the run with the best (lowest) avg_pace_sec_per_km within distance tolerance
        best_run = (
            db.query(Run)
            .filter(
                Run.profile_id == profile_id,
                Run.distance_metres >= lower,
                Run.distance_metres <= upper,
                Run.avg_pace_sec_per_km.isnot(None),
            )
            .order_by(Run.avg_pace_sec_per_km.asc())
            .first()
        )

        if best_run:
            records.append(
                PersonalRecord(
                    distance_label=label,
                    target_distance_metres=target_m,
                    run_id=best_run.id,
                    run_date=best_run.date,
                    distance_metres=best_run.distance_metres,
                    duration_seconds=best_run.duration_seconds,
                    avg_pace_sec_per_km=best_run.avg_pace_sec_per_km,
                )
            )
        else:
            records.append(
                PersonalRecord(
                    distance_label=label,
                    target_distance_metres=target_m,
                    run_id=None,
                    run_date=None,
                    distance_metres=None,
                    duration_seconds=None,
                    avg_pace_sec_per_km=None,
                )
            )

    return PRsResponse(records=records)


def _calculate_streaks(run_dates: list[date]) -> tuple[int, int]:
    """
    Calculate current and all-time streaks from a list of run dates.

    A streak is the number of consecutive calendar weeks (Monday–Sunday) in
    which at least one run was completed.  The current streak counts backwards
    from the most recent week that contains a run; the all-time streak is the
    longest such consecutive sequence in the entire history.

    Args:
        run_dates: List of run dates (may be unsorted, may contain duplicates).

    Returns:
        (current_streak, all_time_streak) as a tuple of ints.
    """
    if not run_dates:
        return 0, 0

    # Collect the unique set of ISO week-start Mondays that have at least one run
    def _week_start(d: date) -> date:
        return d - timedelta(days=d.weekday())

    active_weeks = sorted({_week_start(d) for d in run_dates})

    # Calculate all-time streak: longest consecutive sequence of weeks
    all_time = 1
    current_run = 1
    for i in range(1, len(active_weeks)):
        if active_weeks[i] - active_weeks[i - 1] == timedelta(weeks=1):
            current_run += 1
            all_time = max(all_time, current_run)
        else:
            current_run = 1

    # Calculate current streak: consecutive weeks ending at the most recent active week
    current = 1
    for i in range(len(active_weeks) - 1, 0, -1):
        if active_weeks[i] - active_weeks[i - 1] == timedelta(weeks=1):
            current += 1
        else:
            break

    return current, all_time


@router.get("/profiles/{profile_id}/stats/streak", response_model=StreakResponse)
def streak_stats(profile_id: int, db: Session = Depends(get_db)):
    """
    Return the current and all-time run streaks for a profile.

    A streak counts consecutive calendar weeks (Mon–Sun) in which at least one
    run was completed.  The current streak counts backwards from the most recent
    week with a run; the all-time streak is the longest such sequence ever.
    """
    _require_profile(profile_id, db)

    runs = (
        db.query(Run.date)
        .filter(Run.profile_id == profile_id)
        .all()
    )

    run_dates = [r.date for r in runs]
    current_streak, all_time_streak = _calculate_streaks(run_dates)

    return StreakResponse(
        current_streak=current_streak,
        all_time_streak=all_time_streak,
    )
