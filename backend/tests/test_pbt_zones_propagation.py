"""
Property-based tests for pace zone propagation to future workouts.

# Feature: personal-running-coach

**Validates: Requirements 10.5**

Property 25: When pace zones are updated for a profile (via
POST /api/v1/profiles/{profile_id}/zones/recalculate), the new
target_pace_zone values SHALL be applied to all future (scheduled) Workouts
in the active Training_Plan for that profile. Past workouts (completed,
skipped, or with a scheduled_date before today) SHALL NOT have their
target_pace_zone changed.

Implementation note: The propagation logic in zones.py resets any workout
whose target_pace_zone is not a recognised zone name to "easy". Workouts
that already have a valid zone name are left unchanged (the zone name stays
the same; only the underlying pace values change). The filter is
scheduled_date > today — status is not considered.
"""

from datetime import date, datetime, timedelta, timezone
from typing import List

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.models.orm import TrainingBlock, TrainingPlan, Workout

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_PACE_ZONES = ["easy", "moderate", "threshold", "vo2max", "anaerobic"]
INVALID_PACE_ZONES = ["sprint", "race_pace", "jog", "unknown", "EASY", "Zone1", ""]

# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

_profile_id_st = st.sampled_from([1, 2])

# Valid race distance: 5 km to marathon (in metres)
_race_distance_st = st.floats(
    min_value=5_000.0,
    max_value=42_195.0,
    allow_nan=False,
    allow_infinity=False,
)

# Valid race duration: 15 minutes to 6 hours (in seconds)
_race_duration_st = st.integers(min_value=900, max_value=21_600)

# A valid pace zone name
_valid_zone_st = st.sampled_from(VALID_PACE_ZONES)

# An invalid pace zone name (not in VALID_PACE_ZONES)
_invalid_zone_st = st.sampled_from(INVALID_PACE_ZONES)

# Number of future workouts to create: 1–5
_future_count_st = st.integers(min_value=1, max_value=5)

# Number of past workouts to create: 1–5
_past_count_st = st.integers(min_value=1, max_value=5)

# Workout status for past workouts
_past_status_st = st.sampled_from(["completed", "skipped", "missed"])

# Days in the future: 1–90
_future_days_st = st.integers(min_value=1, max_value=90)

# Days in the past: 1–90
_past_days_st = st.integers(min_value=1, max_value=90)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _archive_existing_active_plans(db_session, profile_id: int) -> None:
    """Archive any existing active plans for this profile to avoid conflicts."""
    existing = (
        db_session.query(TrainingPlan)
        .filter(
            TrainingPlan.profile_id == profile_id,
            TrainingPlan.status == "active",
        )
        .all()
    )
    for plan in existing:
        plan.status = "archived"
    db_session.flush()


def _make_plan_and_block(
    db_session,
    profile_id: int,
    start_date: date,
    end_date: date,
) -> tuple:
    """Insert a TrainingPlan + TrainingBlock and return (plan, block).

    Archives any existing active plans for this profile first to ensure
    the new plan is the one the router finds.
    """
    _archive_existing_active_plans(db_session, profile_id)

    now = datetime.now(timezone.utc)
    plan = TrainingPlan(
        profile_id=profile_id,
        race_goal_id=None,
        start_date=start_date,
        end_date=end_date,
        status="active",
        gemini_prompt_hash=None,
        created_at=now,
        updated_at=now,
    )
    db_session.add(plan)
    db_session.flush()

    block = TrainingBlock(
        profile_id=profile_id,
        plan_id=plan.id,
        name="Test Block",
        start_date=start_date,
        end_date=end_date,
        sequence=1,
    )
    db_session.add(block)
    db_session.flush()
    return plan, block


def _make_workout(
    db_session,
    profile_id: int,
    plan_id: int,
    block_id: int,
    scheduled_date: date,
    target_pace_zone: str,
    status: str = "scheduled",
) -> Workout:
    """Insert a Workout row and return it."""
    now = datetime.now(timezone.utc)
    workout = Workout(
        profile_id=profile_id,
        block_id=block_id,
        plan_id=plan_id,
        scheduled_date=scheduled_date,
        workout_type="easy",
        target_distance_metres=5000.0,
        target_pace_zone=target_pace_zone,
        target_hr_zone=None,
        steps=[],
        coaching_note=None,
        status=status,
        rpe_score=None,
        matched_run_id=None,
        created_at=now,
        updated_at=now,
    )
    db_session.add(workout)
    db_session.flush()
    return workout


# ---------------------------------------------------------------------------
# Property 25a: Future workouts with invalid zone names are reset to "easy"
# ---------------------------------------------------------------------------


@given(
    profile_id=_profile_id_st,
    race_distance=_race_distance_st,
    race_duration=_race_duration_st,
    invalid_zone=_invalid_zone_st,
    future_days=_future_days_st,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_future_workouts_with_invalid_zone_reset_to_easy(
    client,
    db_session,
    profile_id: int,
    race_distance: float,
    race_duration: int,
    invalid_zone: str,
    future_days: int,
):
    """
    Property 25a: After POST .../zones/recalculate, any future scheduled
    workout whose target_pace_zone is not a recognised zone name SHALL have
    its target_pace_zone reset to "easy".

    # Feature: personal-running-coach, Property 25: pace zone propagation
    **Validates: Requirements 10.5**
    """
    today = date.today()
    future_date = today + timedelta(days=future_days)

    plan, block = _make_plan_and_block(
        db_session,
        profile_id=profile_id,
        start_date=today,
        end_date=future_date + timedelta(days=30),
    )

    workout = _make_workout(
        db_session,
        profile_id=profile_id,
        plan_id=plan.id,
        block_id=block.id,
        scheduled_date=future_date,
        target_pace_zone=invalid_zone,
        status="scheduled",
    )
    workout_id = workout.id

    response = client.post(
        f"/api/v1/profiles/{profile_id}/zones/recalculate",
        json={
            "distance_metres": race_distance,
            "duration_seconds": race_duration,
        },
    )

    assert response.status_code == 200, (
        f"Expected HTTP 200, got {response.status_code}: {response.text}"
    )

    # Reload the workout from the DB
    db_session.expire_all()
    updated = db_session.query(Workout).filter(Workout.id == workout_id).first()
    assert updated is not None, "Workout was unexpectedly deleted"

    assert updated.target_pace_zone == "easy", (
        f"Future workout with invalid zone '{invalid_zone}' should have been "
        f"reset to 'easy' after recalculate, but got '{updated.target_pace_zone}'. "
        f"profile_id={profile_id}, scheduled_date={future_date}"
    )


# ---------------------------------------------------------------------------
# Property 25b: Future workouts with valid zone names are NOT changed
# ---------------------------------------------------------------------------


@given(
    profile_id=_profile_id_st,
    race_distance=_race_distance_st,
    race_duration=_race_duration_st,
    valid_zone=_valid_zone_st,
    future_days=_future_days_st,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_future_workouts_with_valid_zone_unchanged(
    client,
    db_session,
    profile_id: int,
    race_distance: float,
    race_duration: int,
    valid_zone: str,
    future_days: int,
):
    """
    Property 25b: After POST .../zones/recalculate, any future scheduled
    workout whose target_pace_zone is already a recognised zone name SHALL
    retain its original target_pace_zone (the zone name does not change;
    only the underlying pace values change).

    # Feature: personal-running-coach, Property 25: pace zone propagation
    **Validates: Requirements 10.5**
    """
    today = date.today()
    future_date = today + timedelta(days=future_days)

    plan, block = _make_plan_and_block(
        db_session,
        profile_id=profile_id,
        start_date=today,
        end_date=future_date + timedelta(days=30),
    )

    workout = _make_workout(
        db_session,
        profile_id=profile_id,
        plan_id=plan.id,
        block_id=block.id,
        scheduled_date=future_date,
        target_pace_zone=valid_zone,
        status="scheduled",
    )
    workout_id = workout.id

    response = client.post(
        f"/api/v1/profiles/{profile_id}/zones/recalculate",
        json={
            "distance_metres": race_distance,
            "duration_seconds": race_duration,
        },
    )

    assert response.status_code == 200, (
        f"Expected HTTP 200, got {response.status_code}: {response.text}"
    )

    db_session.expire_all()
    updated = db_session.query(Workout).filter(Workout.id == workout_id).first()
    assert updated is not None, "Workout was unexpectedly deleted"

    assert updated.target_pace_zone == valid_zone, (
        f"Future workout with valid zone '{valid_zone}' should be unchanged "
        f"after recalculate, but got '{updated.target_pace_zone}'. "
        f"profile_id={profile_id}, scheduled_date={future_date}"
    )


# ---------------------------------------------------------------------------
# Property 25c: Past workouts (scheduled_date <= today) are NOT changed
# ---------------------------------------------------------------------------


@given(
    profile_id=_profile_id_st,
    race_distance=_race_distance_st,
    race_duration=_race_duration_st,
    original_zone=st.one_of(_valid_zone_st, _invalid_zone_st),
    past_days=_past_days_st,
    past_status=_past_status_st,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_past_workouts_not_changed_by_zone_recalculate(
    client,
    db_session,
    profile_id: int,
    race_distance: float,
    race_duration: int,
    original_zone: str,
    past_days: int,
    past_status: str,
):
    """
    Property 25c: After POST .../zones/recalculate, workouts with
    scheduled_date <= today SHALL NOT have their target_pace_zone changed,
    regardless of their status (completed, skipped, missed) or whether their
    zone name is valid or invalid.

    The propagation filter is scheduled_date > today, so past workouts are
    always excluded.

    # Feature: personal-running-coach, Property 25: pace zone propagation
    **Validates: Requirements 10.5**
    """
    today = date.today()
    past_date = today - timedelta(days=past_days)

    plan, block = _make_plan_and_block(
        db_session,
        profile_id=profile_id,
        start_date=past_date,
        end_date=today + timedelta(days=30),
    )

    workout = _make_workout(
        db_session,
        profile_id=profile_id,
        plan_id=plan.id,
        block_id=block.id,
        scheduled_date=past_date,
        target_pace_zone=original_zone,
        status=past_status,
    )
    workout_id = workout.id

    response = client.post(
        f"/api/v1/profiles/{profile_id}/zones/recalculate",
        json={
            "distance_metres": race_distance,
            "duration_seconds": race_duration,
        },
    )

    assert response.status_code == 200, (
        f"Expected HTTP 200, got {response.status_code}: {response.text}"
    )

    db_session.expire_all()
    updated = db_session.query(Workout).filter(Workout.id == workout_id).first()
    assert updated is not None, "Workout was unexpectedly deleted"

    assert updated.target_pace_zone == original_zone, (
        f"Past workout (scheduled_date={past_date}, status={past_status}) "
        f"should NOT have its target_pace_zone changed from '{original_zone}', "
        f"but got '{updated.target_pace_zone}'. "
        f"profile_id={profile_id}"
    )


# ---------------------------------------------------------------------------
# Property 25d: Today's workouts (scheduled_date == today) are NOT changed
# ---------------------------------------------------------------------------


@given(
    profile_id=_profile_id_st,
    race_distance=_race_distance_st,
    race_duration=_race_duration_st,
    original_zone=st.one_of(_valid_zone_st, _invalid_zone_st),
)
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_todays_workouts_not_changed_by_zone_recalculate(
    client,
    db_session,
    profile_id: int,
    race_distance: float,
    race_duration: int,
    original_zone: str,
):
    """
    Property 25d: After POST .../zones/recalculate, workouts with
    scheduled_date == today SHALL NOT have their target_pace_zone changed.

    The propagation filter is strictly scheduled_date > today (not >=),
    so today's workouts are excluded.

    # Feature: personal-running-coach, Property 25: pace zone propagation
    **Validates: Requirements 10.5**
    """
    today = date.today()

    plan, block = _make_plan_and_block(
        db_session,
        profile_id=profile_id,
        start_date=today,
        end_date=today + timedelta(days=30),
    )

    workout = _make_workout(
        db_session,
        profile_id=profile_id,
        plan_id=plan.id,
        block_id=block.id,
        scheduled_date=today,
        target_pace_zone=original_zone,
        status="scheduled",
    )
    workout_id = workout.id

    response = client.post(
        f"/api/v1/profiles/{profile_id}/zones/recalculate",
        json={
            "distance_metres": race_distance,
            "duration_seconds": race_duration,
        },
    )

    assert response.status_code == 200, (
        f"Expected HTTP 200, got {response.status_code}: {response.text}"
    )

    db_session.expire_all()
    updated = db_session.query(Workout).filter(Workout.id == workout_id).first()
    assert updated is not None, "Workout was unexpectedly deleted"

    assert updated.target_pace_zone == original_zone, (
        f"Today's workout (scheduled_date={today}) should NOT have its "
        f"target_pace_zone changed from '{original_zone}', "
        f"but got '{updated.target_pace_zone}'. "
        f"profile_id={profile_id}"
    )


# ---------------------------------------------------------------------------
# Property 25e: Workouts in archived/draft plans are NOT changed
# ---------------------------------------------------------------------------


@given(
    profile_id=_profile_id_st,
    race_distance=_race_distance_st,
    race_duration=_race_duration_st,
    invalid_zone=_invalid_zone_st,
    future_days=_future_days_st,
    plan_status=st.sampled_from(["archived", "draft"]),
)
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_workouts_in_non_active_plans_not_changed(
    client,
    db_session,
    profile_id: int,
    race_distance: float,
    race_duration: int,
    invalid_zone: str,
    future_days: int,
    plan_status: str,
):
    """
    Property 25e: After POST .../zones/recalculate, workouts belonging to
    archived or draft Training_Plans SHALL NOT have their target_pace_zone
    changed, even if they are scheduled in the future.

    The propagation only targets the active Training_Plan.

    # Feature: personal-running-coach, Property 25: pace zone propagation
    **Validates: Requirements 10.5**
    """
    today = date.today()
    future_date = today + timedelta(days=future_days)

    # Archive any existing active plans so the router finds no active plan
    # (or only the non-active plan we're about to create)
    _archive_existing_active_plans(db_session, profile_id)

    now = datetime.now(timezone.utc)
    non_active_plan = TrainingPlan(
        profile_id=profile_id,
        race_goal_id=None,
        start_date=today,
        end_date=future_date + timedelta(days=30),
        status=plan_status,
        gemini_prompt_hash=None,
        created_at=now,
        updated_at=now,
    )
    db_session.add(non_active_plan)
    db_session.flush()

    block = TrainingBlock(
        profile_id=profile_id,
        plan_id=non_active_plan.id,
        name="Non-Active Block",
        start_date=today,
        end_date=future_date + timedelta(days=30),
        sequence=1,
    )
    db_session.add(block)
    db_session.flush()

    workout = _make_workout(
        db_session,
        profile_id=profile_id,
        plan_id=non_active_plan.id,
        block_id=block.id,
        scheduled_date=future_date,
        target_pace_zone=invalid_zone,
        status="scheduled",
    )
    workout_id = workout.id

    response = client.post(
        f"/api/v1/profiles/{profile_id}/zones/recalculate",
        json={
            "distance_metres": race_distance,
            "duration_seconds": race_duration,
        },
    )

    assert response.status_code == 200, (
        f"Expected HTTP 200, got {response.status_code}: {response.text}"
    )

    db_session.expire_all()
    updated = db_session.query(Workout).filter(Workout.id == workout_id).first()
    assert updated is not None, "Workout was unexpectedly deleted"

    assert updated.target_pace_zone == invalid_zone, (
        f"Workout in {plan_status} plan should NOT have its target_pace_zone "
        f"changed from '{invalid_zone}', but got '{updated.target_pace_zone}'. "
        f"profile_id={profile_id}, plan_status={plan_status}"
    )


# ---------------------------------------------------------------------------
# Property 25f: Mixed past/future workouts — only future invalid ones change
# ---------------------------------------------------------------------------


@given(
    profile_id=_profile_id_st,
    race_distance=_race_distance_st,
    race_duration=_race_duration_st,
    future_count=_future_count_st,
    past_count=_past_count_st,
)
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_mixed_workouts_only_future_invalid_zones_updated(
    client,
    db_session,
    profile_id: int,
    race_distance: float,
    race_duration: int,
    future_count: int,
    past_count: int,
):
    """
    Property 25f: Given a training plan with a mix of past and future workouts
    all having invalid zone names, after POST .../zones/recalculate:
      - All future workouts (scheduled_date > today) SHALL have target_pace_zone
        reset to "easy"
      - All past workouts (scheduled_date <= today) SHALL retain their original
        invalid zone name

    This verifies the boundary condition: the date cutoff is strictly today.

    # Feature: personal-running-coach, Property 25: pace zone propagation
    **Validates: Requirements 10.5**
    """
    today = date.today()
    invalid_zone = "sprint"  # a fixed invalid zone for simplicity

    plan, block = _make_plan_and_block(
        db_session,
        profile_id=profile_id,
        start_date=today - timedelta(days=past_count),
        end_date=today + timedelta(days=future_count + 30),
    )

    # Create past workouts with invalid zone names
    past_workout_ids: List[int] = []
    for i in range(past_count):
        past_date = today - timedelta(days=i + 1)
        w = _make_workout(
            db_session,
            profile_id=profile_id,
            plan_id=plan.id,
            block_id=block.id,
            scheduled_date=past_date,
            target_pace_zone=invalid_zone,
            status="completed",
        )
        past_workout_ids.append(w.id)

    # Create future workouts with invalid zone names
    future_workout_ids: List[int] = []
    for i in range(future_count):
        future_date = today + timedelta(days=i + 1)
        w = _make_workout(
            db_session,
            profile_id=profile_id,
            plan_id=plan.id,
            block_id=block.id,
            scheduled_date=future_date,
            target_pace_zone=invalid_zone,
            status="scheduled",
        )
        future_workout_ids.append(w.id)

    response = client.post(
        f"/api/v1/profiles/{profile_id}/zones/recalculate",
        json={
            "distance_metres": race_distance,
            "duration_seconds": race_duration,
        },
    )

    assert response.status_code == 200, (
        f"Expected HTTP 200, got {response.status_code}: {response.text}"
    )

    db_session.expire_all()

    # Past workouts must be unchanged
    for wid in past_workout_ids:
        w = db_session.query(Workout).filter(Workout.id == wid).first()
        assert w is not None
        assert w.target_pace_zone == invalid_zone, (
            f"Past workout (id={wid}, scheduled_date={w.scheduled_date}) "
            f"should retain '{invalid_zone}', but got '{w.target_pace_zone}'. "
            f"profile_id={profile_id}"
        )

    # Future workouts must be reset to "easy"
    for wid in future_workout_ids:
        w = db_session.query(Workout).filter(Workout.id == wid).first()
        assert w is not None
        assert w.target_pace_zone == "easy", (
            f"Future workout (id={wid}, scheduled_date={w.scheduled_date}) "
            f"with invalid zone '{invalid_zone}' should be reset to 'easy', "
            f"but got '{w.target_pace_zone}'. "
            f"profile_id={profile_id}"
        )
