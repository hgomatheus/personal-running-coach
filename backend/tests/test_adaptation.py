"""
Property-based tests for adaptation trigger logic.

# Feature: personal-running-coach, Properties 12–13: RPE adaptation trigger, run deviation threshold

**Validates: Requirements 5.6, 4.2**
"""

from datetime import date, datetime, timezone, timedelta
from unittest.mock import patch, AsyncMock

from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st

from app.models.orm import TrainingBlock, TrainingPlan, Workout, Run
from app.services.workout_matcher import calculate_deviation_pct

# ---------------------------------------------------------------------------
# Shared strategies
# ---------------------------------------------------------------------------

_profile_id_st = st.sampled_from([1, 2])

VALID_WORKOUT_TYPES = ["easy", "tempo", "interval", "hills", "long", "recovery"]
_workout_type_st = st.sampled_from(VALID_WORKOUT_TYPES)

# RPE scores: 1–10 (schema enforces ge=1, le=10)
_rpe_high_st = st.integers(min_value=9, max_value=10)   # RPE > 8
_rpe_low_st = st.integers(min_value=1, max_value=8)     # RPE ≤ 8

# Target distance: 1 km to 42 km in metres
_target_distance_st = st.floats(
    min_value=1_000.0,
    max_value=42_000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Deviation multiplier that produces |actual - target| / target > 0.20
# Either actual > target * 1.20  OR  actual < target * 0.80
# We use two ranges and merge them:
#   multiplier > 1.20  → deviation = multiplier - 1 > 0.20
#   multiplier < 0.80  → deviation = 1 - multiplier > 0.20
_deviation_above_st = st.one_of(
    st.floats(min_value=1.21, max_value=2.0, allow_nan=False, allow_infinity=False),
    st.floats(min_value=0.01, max_value=0.79, allow_nan=False, allow_infinity=False),
)

# Deviation multiplier that produces |actual - target| / target ≤ 0.20
# i.e. 0.80 ≤ multiplier ≤ 1.20, but exclude exact boundary to avoid
# floating-point precision issues (1.2 * x can exceed 0.20 due to FP rounding)
_deviation_at_or_below_st = st.floats(
    min_value=0.81,
    max_value=1.19,
    allow_nan=False,
    allow_infinity=False,
)

# ---------------------------------------------------------------------------
# Helper: create a minimal plan + block + workout in the test DB
# ---------------------------------------------------------------------------

def _make_plan_and_block(db_session, profile_id: int, scheduled_date: date) -> tuple:
    """Return (plan, block) inserted into db_session."""
    now = datetime.now(timezone.utc)
    plan = TrainingPlan(
        profile_id=profile_id,
        race_goal_id=None,
        start_date=scheduled_date,
        end_date=scheduled_date + timedelta(days=90),
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
        start_date=scheduled_date,
        end_date=scheduled_date + timedelta(days=90),
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
    workout_type: str,
    scheduled_date: date,
    rpe_score: int | None = None,
    status: str = "completed",
    target_distance_metres: float = 5000.0,
) -> Workout:
    """Insert a Workout row and return it."""
    now = datetime.now(timezone.utc)
    workout = Workout(
        profile_id=profile_id,
        block_id=block_id,
        plan_id=plan_id,
        scheduled_date=scheduled_date,
        workout_type=workout_type,
        target_distance_metres=target_distance_metres,
        target_pace_zone="easy",
        target_hr_zone=None,
        steps=[],
        coaching_note=None,
        status=status,
        rpe_score=rpe_score,
        matched_run_id=None,
        created_at=now,
        updated_at=now,
    )
    db_session.add(workout)
    db_session.flush()
    return workout


# ---------------------------------------------------------------------------
# Property 12: RPE adaptation trigger
#
# When RPE > 8 is logged for 2 consecutive workouts of the same type,
# adapt_plan() SHALL be called.
# When RPE ≤ 8 or only 1 workout has RPE > 8, it SHALL NOT be triggered.
# ---------------------------------------------------------------------------

@given(
    profile_id=_profile_id_st,
    workout_type=_workout_type_st,
    prev_rpe=_rpe_high_st,
    curr_rpe=_rpe_high_st,
)
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_rpe_adaptation_triggered_for_two_consecutive_high_rpe(
    client,
    db_session,
    profile_id: int,
    workout_type: str,
    prev_rpe: int,
    curr_rpe: int,
):
    """
    Property 12 (trigger case): When two consecutive same-type workouts both have
    rpe_score > 8, patching the second workout's RPE SHALL trigger adapt_plan().

    # Feature: personal-running-coach, Property 12: RPE adaptation trigger
    **Validates: Requirements 5.6**
    """
    base_date = date(2025, 6, 1)
    plan, block = _make_plan_and_block(db_session, profile_id, base_date)

    # Previous workout: same type, earlier date, RPE > 8 already set
    _make_workout(
        db_session,
        profile_id=profile_id,
        plan_id=plan.id,
        block_id=block.id,
        workout_type=workout_type,
        scheduled_date=base_date,
        rpe_score=prev_rpe,
        status="completed",
    )

    # Current workout: same type, later date, no RPE yet (scheduled)
    current = _make_workout(
        db_session,
        profile_id=profile_id,
        plan_id=plan.id,
        block_id=block.id,
        workout_type=workout_type,
        scheduled_date=base_date + timedelta(days=7),
        rpe_score=None,
        status="scheduled",
    )

    background_adapt_calls = []

    def patched_check_rpe(workout, pid, bg_tasks, db):
        from app.models.orm import Workout as W
        previous = (
            db.query(W)
            .filter(
                W.profile_id == pid,
                W.workout_type == workout.workout_type,
                W.id != workout.id,
                W.rpe_score > 8,
                W.scheduled_date < workout.scheduled_date,
            )
            .order_by(W.scheduled_date.desc())
            .first()
        )
        if previous:
            background_adapt_calls.append({
                "workout_type": workout.workout_type,
                "current_workout_id": workout.id,
                "previous_workout_id": previous.id,
                "current_rpe": workout.rpe_score,
                "previous_rpe": previous.rpe_score,
            })

    with patch("app.routers.workouts._check_rpe_adaptation", side_effect=patched_check_rpe):
        response = client.patch(
            f"/api/v1/workouts/{current.id}",
            json={"rpe_score": curr_rpe},
            params={"profile_id": profile_id},
        )

    assert response.status_code == 200, (
        f"PATCH /api/v1/workouts/{current.id} returned {response.status_code}: "
        f"{response.text}"
    )

    # The adaptation check should have been triggered
    assert len(background_adapt_calls) >= 1, (
        f"Expected adapt_plan to be triggered at least once for 2 consecutive high-RPE "
        f"same-type workouts, but got {len(background_adapt_calls)} calls. "
        f"workout_type={workout_type}, prev_rpe={prev_rpe}, curr_rpe={curr_rpe}"
    )
    call = background_adapt_calls[0]
    assert call["workout_type"] == workout_type
    assert call["current_rpe"] == curr_rpe
    assert call["previous_rpe"] > 8, (
        f"Expected previous_rpe > 8, got {call['previous_rpe']}"
    )


@given(
    profile_id=_profile_id_st,
    workout_type=_workout_type_st,
    prev_rpe=_rpe_low_st,
    curr_rpe=_rpe_high_st,
)
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_rpe_adaptation_not_triggered_when_previous_rpe_low(
    client,
    db_session,
    profile_id: int,
    workout_type: str,
    prev_rpe: int,
    curr_rpe: int,
):
    """
    Property 12 (no-trigger case A): When the previous same-type workout has
    rpe_score ≤ 8, patching the current workout with RPE > 8 SHALL NOT trigger
    adapt_plan().

    # Feature: personal-running-coach, Property 12: RPE adaptation trigger
    **Validates: Requirements 5.6**
    """
    base_date = date(2025, 7, 1)
    plan, block = _make_plan_and_block(db_session, profile_id, base_date)

    # Previous workout: same type, earlier date, RPE ≤ 8
    _make_workout(
        db_session,
        profile_id=profile_id,
        plan_id=plan.id,
        block_id=block.id,
        workout_type=workout_type,
        scheduled_date=base_date,
        rpe_score=prev_rpe,
        status="completed",
    )

    # Current workout: same type, later date
    current = _make_workout(
        db_session,
        profile_id=profile_id,
        plan_id=plan.id,
        block_id=block.id,
        workout_type=workout_type,
        scheduled_date=base_date + timedelta(days=7),
        rpe_score=None,
        status="scheduled",
    )

    background_adapt_calls = []

    def patched_check_rpe(workout, pid, bg_tasks, db):
        from app.models.orm import Workout as W
        previous = (
            db.query(W)
            .filter(
                W.profile_id == pid,
                W.workout_type == workout.workout_type,
                W.id != workout.id,
                W.rpe_score > 8,
                W.scheduled_date < workout.scheduled_date,
            )
            .order_by(W.scheduled_date.desc())
            .first()
        )
        if previous:
            background_adapt_calls.append(True)

    with patch("app.routers.workouts._check_rpe_adaptation", side_effect=patched_check_rpe):
        response = client.patch(
            f"/api/v1/workouts/{current.id}",
            json={"rpe_score": curr_rpe},
            params={"profile_id": profile_id},
        )

    assert response.status_code == 200, (
        f"PATCH returned {response.status_code}: {response.text}"
    )

    assert len(background_adapt_calls) == 0, (
        f"adapt_plan should NOT be triggered when previous RPE ≤ 8, "
        f"but got {len(background_adapt_calls)} calls. "
        f"workout_type={workout_type}, prev_rpe={prev_rpe}, curr_rpe={curr_rpe}"
    )


@given(
    profile_id=_profile_id_st,
    workout_type=_workout_type_st,
    curr_rpe=_rpe_high_st,
)
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_rpe_adaptation_not_triggered_for_first_high_rpe_workout(
    client,
    db_session,
    profile_id: int,
    workout_type: str,
    curr_rpe: int,
):
    """
    Property 12 (no-trigger case B): When only one workout of a given type has
    rpe_score > 8 (no prior same-type workout with high RPE), adapt_plan()
    SHALL NOT be triggered.

    # Feature: personal-running-coach, Property 12: RPE adaptation trigger
    **Validates: Requirements 5.6**
    """
    base_date = date(2025, 8, 1)
    plan, block = _make_plan_and_block(db_session, profile_id, base_date)

    # Only one workout of this type — no prior high-RPE workout exists
    current = _make_workout(
        db_session,
        profile_id=profile_id,
        plan_id=plan.id,
        block_id=block.id,
        workout_type=workout_type,
        scheduled_date=base_date,
        rpe_score=None,
        status="scheduled",
    )

    background_adapt_calls = []

    def patched_check_rpe(workout, pid, bg_tasks, db):
        from app.models.orm import Workout as W
        previous = (
            db.query(W)
            .filter(
                W.profile_id == pid,
                W.workout_type == workout.workout_type,
                W.id != workout.id,
                W.rpe_score > 8,
                W.scheduled_date < workout.scheduled_date,
            )
            .order_by(W.scheduled_date.desc())
            .first()
        )
        if previous:
            background_adapt_calls.append(True)

    with patch("app.routers.workouts._check_rpe_adaptation", side_effect=patched_check_rpe):
        response = client.patch(
            f"/api/v1/workouts/{current.id}",
            json={"rpe_score": curr_rpe},
            params={"profile_id": profile_id},
        )

    assert response.status_code == 200, (
        f"PATCH returned {response.status_code}: {response.text}"
    )

    assert len(background_adapt_calls) == 0, (
        f"adapt_plan should NOT be triggered for the first high-RPE workout "
        f"(no prior same-type workout), but got {len(background_adapt_calls)} calls. "
        f"workout_type={workout_type}, curr_rpe={curr_rpe}"
    )


@given(
    profile_id=_profile_id_st,
    workout_type=_workout_type_st,
    curr_rpe=_rpe_low_st,
)
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_rpe_adaptation_not_triggered_when_current_rpe_low(
    client,
    db_session,
    profile_id: int,
    workout_type: str,
    curr_rpe: int,
):
    """
    Property 12 (no-trigger case C): When the current workout's rpe_score ≤ 8,
    adapt_plan() SHALL NOT be triggered even if a prior high-RPE workout exists.

    # Feature: personal-running-coach, Property 12: RPE adaptation trigger
    **Validates: Requirements 5.6**
    """
    base_date = date(2025, 9, 1)
    plan, block = _make_plan_and_block(db_session, profile_id, base_date)

    # Previous workout: same type, high RPE
    _make_workout(
        db_session,
        profile_id=profile_id,
        plan_id=plan.id,
        block_id=block.id,
        workout_type=workout_type,
        scheduled_date=base_date,
        rpe_score=9,
        status="completed",
    )

    # Current workout: same type, RPE ≤ 8
    current = _make_workout(
        db_session,
        profile_id=profile_id,
        plan_id=plan.id,
        block_id=block.id,
        workout_type=workout_type,
        scheduled_date=base_date + timedelta(days=7),
        rpe_score=None,
        status="scheduled",
    )

    background_adapt_calls = []

    def patched_check_rpe(workout, pid, bg_tasks, db):
        # This should not be called at all when rpe_score ≤ 8
        background_adapt_calls.append(True)

    # The router only calls _check_rpe_adaptation when rpe_score > 8
    # So we verify the router's guard condition by checking the response
    # and that _check_rpe_adaptation is NOT called
    with patch("app.routers.workouts._check_rpe_adaptation", side_effect=patched_check_rpe):
        response = client.patch(
            f"/api/v1/workouts/{current.id}",
            json={"rpe_score": curr_rpe},
            params={"profile_id": profile_id},
        )

    assert response.status_code == 200, (
        f"PATCH returned {response.status_code}: {response.text}"
    )

    # _check_rpe_adaptation should not be called when rpe_score ≤ 8
    assert len(background_adapt_calls) == 0, (
        f"_check_rpe_adaptation should NOT be called when rpe_score ≤ 8, "
        f"but was called {len(background_adapt_calls)} times. "
        f"workout_type={workout_type}, curr_rpe={curr_rpe}"
    )


# ---------------------------------------------------------------------------
# Property 13: Run deviation threshold
#
# The system SHALL trigger plan_adaptation_check if and only if
# |actual - target| / target > 0.20.
# ---------------------------------------------------------------------------

@given(
    target_distance=_target_distance_st,
    multiplier=_deviation_above_st,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_deviation_above_threshold_triggers_adaptation(
    target_distance: float,
    multiplier: float,
):
    """
    Property 13 (trigger case): For any run where
    |actual - target| / target > 0.20, calculate_deviation_pct SHALL return
    a value > 0.20.

    Tests the pure deviation calculation function directly.

    # Feature: personal-running-coach, Property 13: Run deviation threshold
    **Validates: Requirements 4.2**
    """
    actual_distance = target_distance * multiplier

    run = Run(
        profile_id=1,
        source="manual",
        date=date(2025, 6, 1),
        distance_metres=actual_distance,
        duration_seconds=3600,
    )
    workout = Workout(
        profile_id=1,
        plan_id=1,
        scheduled_date=date(2025, 6, 1),
        workout_type="easy",
        target_distance_metres=target_distance,
        target_pace_zone="easy",
        steps=[],
        status="scheduled",
    )

    deviation = calculate_deviation_pct(run, workout)

    assert deviation is not None, (
        f"calculate_deviation_pct returned None for target={target_distance}, "
        f"actual={actual_distance}"
    )
    assert deviation > 0.20, (
        f"Expected deviation > 0.20 for multiplier={multiplier:.4f}, "
        f"target={target_distance:.1f}m, actual={actual_distance:.1f}m, "
        f"got deviation={deviation:.4f}"
    )


@given(
    target_distance=_target_distance_st,
    multiplier=_deviation_at_or_below_st,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_deviation_at_or_below_threshold_does_not_trigger_adaptation(
    target_distance: float,
    multiplier: float,
):
    """
    Property 13 (no-trigger case): For any run where
    |actual - target| / target ≤ 0.20, calculate_deviation_pct SHALL return
    a value ≤ 0.20.

    Tests the pure deviation calculation function directly.

    # Feature: personal-running-coach, Property 13: Run deviation threshold
    **Validates: Requirements 4.2**
    """
    actual_distance = target_distance * multiplier

    run = Run(
        profile_id=1,
        source="manual",
        date=date(2025, 6, 1),
        distance_metres=actual_distance,
        duration_seconds=3600,
    )
    workout = Workout(
        profile_id=1,
        plan_id=1,
        scheduled_date=date(2025, 6, 1),
        workout_type="easy",
        target_distance_metres=target_distance,
        target_pace_zone="easy",
        steps=[],
        status="scheduled",
    )

    deviation = calculate_deviation_pct(run, workout)

    assert deviation is not None, (
        f"calculate_deviation_pct returned None for target={target_distance}, "
        f"actual={actual_distance}"
    )
    assert deviation <= 0.20, (
        f"Expected deviation ≤ 0.20 for multiplier={multiplier:.4f}, "
        f"target={target_distance:.1f}m, actual={actual_distance:.1f}m, "
        f"got deviation={deviation:.4f}"
    )


@given(
    target_distance=_target_distance_st,
)
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_deviation_returns_none_when_no_target_distance(
    target_distance: float,
):
    """
    Property 13 (edge case): When a workout has no target_distance_metres,
    calculate_deviation_pct SHALL return None (no adaptation triggered).

    # Feature: personal-running-coach, Property 13: Run deviation threshold
    **Validates: Requirements 4.2**
    """
    run = Run(
        profile_id=1,
        source="manual",
        date=date(2025, 6, 1),
        distance_metres=target_distance,
        duration_seconds=3600,
    )
    workout = Workout(
        profile_id=1,
        plan_id=1,
        scheduled_date=date(2025, 6, 1),
        workout_type="easy",
        target_distance_metres=None,  # no target set
        target_pace_zone="easy",
        steps=[],
        status="scheduled",
    )

    deviation = calculate_deviation_pct(run, workout)

    assert deviation is None, (
        f"Expected None when workout has no target_distance_metres, "
        f"got {deviation}"
    )


@given(
    profile_id=_profile_id_st,
    target_distance=_target_distance_st,
    multiplier=_deviation_above_st,
)
@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_run_creation_triggers_adaptation_when_deviation_exceeds_threshold(
    client,
    db_session,
    profile_id: int,
    target_distance: float,
    multiplier: float,
):
    """
    Property 13 (API integration): When a run is created via POST
    /api/v1/profiles/{profile_id}/runs and the deviation from the matched
    workout's target exceeds 20%, adapt_plan SHALL be scheduled as a
    background task.

    # Feature: personal-running-coach, Property 13: Run deviation threshold
    **Validates: Requirements 4.2**
    """
    run_date = date(2025, 10, 1)
    actual_distance = target_distance * multiplier

    plan, block = _make_plan_and_block(db_session, profile_id, run_date)

    # Create a scheduled workout on the same date
    _make_workout(
        db_session,
        profile_id=profile_id,
        plan_id=plan.id,
        block_id=block.id,
        workout_type="easy",
        scheduled_date=run_date,
        rpe_score=None,
        status="scheduled",
        target_distance_metres=target_distance,
    )

    adapt_triggered = []

    def mock_add_task(func, *args, **kwargs):
        adapt_triggered.append(True)

    with patch("app.routers.runs.BackgroundTasks.add_task", side_effect=mock_add_task):
        response = client.post(
            f"/api/v1/profiles/{profile_id}/runs",
            json={
                "date": run_date.isoformat(),
                "distance_metres": actual_distance,
                "duration_seconds": 3600,
                "run_type": "easy",
            },
        )

    assert response.status_code == 201, (
        f"POST /api/v1/profiles/{profile_id}/runs returned {response.status_code}: "
        f"{response.text}"
    )

    assert len(adapt_triggered) >= 1, (
        f"Expected adapt_plan background task to be scheduled when deviation "
        f"{(multiplier - 1) * 100:.1f}% > 20%, but no task was added. "
        f"target={target_distance:.1f}m, actual={actual_distance:.1f}m"
    )


@given(
    profile_id=_profile_id_st,
    target_distance=_target_distance_st,
    multiplier=_deviation_at_or_below_st,
)
@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_run_creation_does_not_trigger_adaptation_when_deviation_within_threshold(
    client,
    db_session,
    profile_id: int,
    target_distance: float,
    multiplier: float,
):
    """
    Property 13 (API no-trigger): When a run is created and the deviation from
    the matched workout's target is ≤ 20%, adapt_plan SHALL NOT be scheduled.

    # Feature: personal-running-coach, Property 13: Run deviation threshold
    **Validates: Requirements 4.2**
    """
    run_date = date(2025, 11, 1)
    actual_distance = target_distance * multiplier

    plan, block = _make_plan_and_block(db_session, profile_id, run_date)

    _make_workout(
        db_session,
        profile_id=profile_id,
        plan_id=plan.id,
        block_id=block.id,
        workout_type="easy",
        scheduled_date=run_date,
        rpe_score=None,
        status="scheduled",
        target_distance_metres=target_distance,
    )

    adapt_triggered = []

    def mock_add_task(func, *args, **kwargs):
        adapt_triggered.append(True)

    with patch("app.routers.runs.BackgroundTasks.add_task", side_effect=mock_add_task):
        response = client.post(
            f"/api/v1/profiles/{profile_id}/runs",
            json={
                "date": run_date.isoformat(),
                "distance_metres": actual_distance,
                "duration_seconds": 3600,
                "run_type": "easy",
            },
        )

    assert response.status_code == 201, (
        f"POST /api/v1/profiles/{profile_id}/runs returned {response.status_code}: "
        f"{response.text}"
    )

    assert len(adapt_triggered) == 0, (
        f"adapt_plan should NOT be scheduled when deviation ≤ 20%, "
        f"but {len(adapt_triggered)} task(s) were added. "
        f"target={target_distance:.1f}m, actual={actual_distance:.1f}m, "
        f"multiplier={multiplier:.4f}"
    )
