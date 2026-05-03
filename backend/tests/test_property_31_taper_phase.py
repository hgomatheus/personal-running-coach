"""
Property-based tests for taper phase activation threshold and volume block.

# Feature: personal-running-coach

**Validates: Requirements 22.1, 22.6**

Property 31: Taper phase activates at the correct day threshold and never
increases volume.

For any active Training_Plan with a Race_Goal, the taper phase SHALL be
active if and only if `(race_goal.target_date - today).days <= 21`.

Sub-properties tested:
  31a: When days_until_race <= 21, taper_active is True
  31b: When days_until_race > 21, taper_active is False
  31c: When taper is active, should_block_volume_increase() returns True
  31d: When taper is NOT active (days_until_race > 21), should_block_volume_increase() returns False
  31e: Volume reduction percentage is always between 20% and 40% when taper is active
  31f: Boundary — exactly 21 days remaining activates taper
  31g: Boundary — exactly 22 days remaining does NOT activate taper
  31h: Taper week assignment is correct (week 1: days 15-21, week 2: days 8-14, week 3: days 1-7)
  31i: No active plan → taper_active is False
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.models.orm import RaceGoal, TrainingPlan
from app.services.taper_calculator import get_taper_status, should_block_volume_increase

# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

_profile_id_st = st.sampled_from([1, 2])

# days_until_race in the taper window: 0 to 21 (inclusive)
_taper_days_st = st.integers(min_value=0, max_value=21)

# days_until_race outside the taper window: 22 to 365
_non_taper_days_st = st.integers(min_value=22, max_value=365)

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


def _create_plan_with_race_goal(
    db_session,
    profile_id: int,
    days_until_race: int,
) -> tuple[TrainingPlan, RaceGoal]:
    """
    Insert an active TrainingPlan with a linked active RaceGoal whose
    target_date is `days_until_race` days from today.

    Returns (plan, race_goal).
    """
    _archive_existing_active_plans(db_session, profile_id)

    today = date.today()
    race_date = today + timedelta(days=days_until_race)
    now = datetime.now(timezone.utc)

    race_goal = RaceGoal(
        profile_id=profile_id,
        distance_metres=42195.0,  # marathon
        target_date=race_date,
        label="Test Race",
        is_active=True,
        created_at=now,
    )
    db_session.add(race_goal)
    db_session.flush()

    plan = TrainingPlan(
        profile_id=profile_id,
        race_goal_id=race_goal.id,
        start_date=today - timedelta(days=30),
        end_date=race_date,
        status="active",
        gemini_prompt_hash=None,
        created_at=now,
        updated_at=now,
    )
    db_session.add(plan)
    db_session.flush()

    return plan, race_goal


# ---------------------------------------------------------------------------
# Property 31a: When days_until_race <= 21, taper_active is True
# ---------------------------------------------------------------------------


@given(
    profile_id=_profile_id_st,
    days_until_race=_taper_days_st,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_taper_active_when_days_until_race_lte_21(
    db_session,
    profile_id: int,
    days_until_race: int,
) -> None:
    """
    Property 31a: get_taper_status() SHALL return taper_active=True for any
    days_until_race in [0, 21].

    **Validates: Requirements 22.1, 22.6**
    """
    _create_plan_with_race_goal(db_session, profile_id, days_until_race)

    status = get_taper_status(profile_id, db_session)

    assert status.taper_active is True, (
        f"Expected taper_active=True for days_until_race={days_until_race} "
        f"(profile_id={profile_id}), but got taper_active={status.taper_active}"
    )


# ---------------------------------------------------------------------------
# Property 31b: When days_until_race > 21, taper_active is False
# ---------------------------------------------------------------------------


@given(
    profile_id=_profile_id_st,
    days_until_race=_non_taper_days_st,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_taper_not_active_when_days_until_race_gt_21(
    db_session,
    profile_id: int,
    days_until_race: int,
) -> None:
    """
    Property 31b: get_taper_status() SHALL return taper_active=False for any
    days_until_race > 21.

    **Validates: Requirements 22.1, 22.6**
    """
    _create_plan_with_race_goal(db_session, profile_id, days_until_race)

    status = get_taper_status(profile_id, db_session)

    assert status.taper_active is False, (
        f"Expected taper_active=False for days_until_race={days_until_race} "
        f"(profile_id={profile_id}), but got taper_active={status.taper_active}"
    )


# ---------------------------------------------------------------------------
# Property 31c: When taper is active, should_block_volume_increase() returns True
# ---------------------------------------------------------------------------


@given(
    profile_id=_profile_id_st,
    days_until_race=_taper_days_st,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_block_volume_increase_when_taper_active(
    db_session,
    profile_id: int,
    days_until_race: int,
) -> None:
    """
    Property 31c: should_block_volume_increase() SHALL return True whenever
    the taper phase is active (days_until_race <= 21).

    **Validates: Requirements 22.1, 22.6**
    """
    _create_plan_with_race_goal(db_session, profile_id, days_until_race)

    blocked = should_block_volume_increase(profile_id, db_session)

    assert blocked is True, (
        f"Expected should_block_volume_increase()=True for "
        f"days_until_race={days_until_race} (profile_id={profile_id}), "
        f"but got {blocked}"
    )


# ---------------------------------------------------------------------------
# Property 31d: When taper is NOT active, should_block_volume_increase() returns False
# ---------------------------------------------------------------------------


@given(
    profile_id=_profile_id_st,
    days_until_race=_non_taper_days_st,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_no_block_volume_increase_when_taper_not_active(
    db_session,
    profile_id: int,
    days_until_race: int,
) -> None:
    """
    Property 31d: should_block_volume_increase() SHALL return False whenever
    the taper phase is NOT active (days_until_race > 21).

    **Validates: Requirements 22.1, 22.6**
    """
    _create_plan_with_race_goal(db_session, profile_id, days_until_race)

    blocked = should_block_volume_increase(profile_id, db_session)

    assert blocked is False, (
        f"Expected should_block_volume_increase()=False for "
        f"days_until_race={days_until_race} (profile_id={profile_id}), "
        f"but got {blocked}"
    )


# ---------------------------------------------------------------------------
# Property 31e: Volume reduction percentage is always between 20% and 40%
#               when taper is active
# ---------------------------------------------------------------------------


@given(
    profile_id=_profile_id_st,
    days_until_race=_taper_days_st,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_volume_reduction_pct_in_range_when_taper_active(
    db_session,
    profile_id: int,
    days_until_race: int,
) -> None:
    """
    Property 31e: When taper is active, volume_reduction_pct SHALL always be
    in the range [20, 40] (inclusive).

    **Validates: Requirements 22.1, 22.6**
    """
    _create_plan_with_race_goal(db_session, profile_id, days_until_race)

    status = get_taper_status(profile_id, db_session)

    assert status.taper_active is True, (
        f"Precondition failed: expected taper_active=True for "
        f"days_until_race={days_until_race}"
    )
    assert status.volume_reduction_pct is not None, (
        f"Expected volume_reduction_pct to be set when taper is active, "
        f"but got None (days_until_race={days_until_race})"
    )
    assert 20 <= status.volume_reduction_pct <= 40, (
        f"Expected volume_reduction_pct in [20, 40], but got "
        f"{status.volume_reduction_pct} for days_until_race={days_until_race} "
        f"(profile_id={profile_id})"
    )


# ---------------------------------------------------------------------------
# Boundary tests (deterministic)
# ---------------------------------------------------------------------------


def test_taper_active_at_exactly_21_days(db_session) -> None:
    """
    Boundary 31f: days_until_race == 21 SHALL activate taper (boundary is
    inclusive: <= 21).

    **Validates: Requirements 22.1, 22.6**
    """
    profile_id = 1
    _create_plan_with_race_goal(db_session, profile_id, days_until_race=21)

    status = get_taper_status(profile_id, db_session)

    assert status.taper_active is True, (
        f"Expected taper_active=True at exactly 21 days, got {status.taper_active}"
    )
    assert status.days_until_race == 21
    assert should_block_volume_increase(profile_id, db_session) is True


def test_taper_not_active_at_22_days(db_session) -> None:
    """
    Boundary 31g: days_until_race == 22 SHALL NOT activate taper.

    **Validates: Requirements 22.1, 22.6**
    """
    profile_id = 1
    _create_plan_with_race_goal(db_session, profile_id, days_until_race=22)

    status = get_taper_status(profile_id, db_session)

    assert status.taper_active is False, (
        f"Expected taper_active=False at 22 days, got {status.taper_active}"
    )
    assert status.days_until_race == 22
    assert should_block_volume_increase(profile_id, db_session) is False


def test_taper_active_at_20_days(db_session) -> None:
    """
    Boundary: days_until_race == 20 SHALL activate taper.

    **Validates: Requirements 22.1, 22.6**
    """
    profile_id = 2
    _create_plan_with_race_goal(db_session, profile_id, days_until_race=20)

    status = get_taper_status(profile_id, db_session)

    assert status.taper_active is True, (
        f"Expected taper_active=True at 20 days, got {status.taper_active}"
    )
    assert should_block_volume_increase(profile_id, db_session) is True


# ---------------------------------------------------------------------------
# Property 31h: Taper week assignment correctness
# ---------------------------------------------------------------------------


def test_taper_week_1_for_days_15_to_21(db_session) -> None:
    """
    Property 31h (week 1): days_until_race in [15, 21] → taper_week == 1,
    volume_reduction_pct == 20.

    **Validates: Requirements 22.1, 22.6**
    """
    profile_id = 1
    for days in [15, 16, 17, 18, 19, 20, 21]:
        _create_plan_with_race_goal(db_session, profile_id, days_until_race=days)
        status = get_taper_status(profile_id, db_session)

        assert status.taper_week == 1, (
            f"Expected taper_week=1 for days_until_race={days}, "
            f"got taper_week={status.taper_week}"
        )
        assert status.volume_reduction_pct == 20, (
            f"Expected volume_reduction_pct=20 for taper week 1 "
            f"(days_until_race={days}), got {status.volume_reduction_pct}"
        )


def test_taper_week_2_for_days_8_to_14(db_session) -> None:
    """
    Property 31h (week 2): days_until_race in [8, 14] → taper_week == 2,
    volume_reduction_pct == 30.

    **Validates: Requirements 22.1, 22.6**
    """
    profile_id = 1
    for days in [8, 9, 10, 11, 12, 13, 14]:
        _create_plan_with_race_goal(db_session, profile_id, days_until_race=days)
        status = get_taper_status(profile_id, db_session)

        assert status.taper_week == 2, (
            f"Expected taper_week=2 for days_until_race={days}, "
            f"got taper_week={status.taper_week}"
        )
        assert status.volume_reduction_pct == 30, (
            f"Expected volume_reduction_pct=30 for taper week 2 "
            f"(days_until_race={days}), got {status.volume_reduction_pct}"
        )


def test_taper_week_3_for_days_1_to_7(db_session) -> None:
    """
    Property 31h (week 3): days_until_race in [1, 7] → taper_week == 3,
    volume_reduction_pct == 40.

    **Validates: Requirements 22.1, 22.6**
    """
    profile_id = 1
    for days in [1, 2, 3, 4, 5, 6, 7]:
        _create_plan_with_race_goal(db_session, profile_id, days_until_race=days)
        status = get_taper_status(profile_id, db_session)

        assert status.taper_week == 3, (
            f"Expected taper_week=3 for days_until_race={days}, "
            f"got taper_week={status.taper_week}"
        )
        assert status.volume_reduction_pct == 40, (
            f"Expected volume_reduction_pct=40 for taper week 3 "
            f"(days_until_race={days}), got {status.volume_reduction_pct}"
        )


def test_taper_week_3_for_race_day(db_session) -> None:
    """
    Property 31h (race day): days_until_race == 0 → taper_week == 3,
    volume_reduction_pct == 40.

    **Validates: Requirements 22.1, 22.6**
    """
    profile_id = 2
    _create_plan_with_race_goal(db_session, profile_id, days_until_race=0)
    status = get_taper_status(profile_id, db_session)

    assert status.taper_active is True
    assert status.taper_week == 3
    assert status.volume_reduction_pct == 40


# ---------------------------------------------------------------------------
# Property 31i: No active plan → taper_active is False
# ---------------------------------------------------------------------------


def test_no_active_plan_returns_taper_inactive(db_session) -> None:
    """
    Property 31i: When there is no active Training_Plan for a profile,
    get_taper_status() SHALL return taper_active=False and
    should_block_volume_increase() SHALL return False.

    **Validates: Requirements 22.1, 22.6**
    """
    profile_id = 1
    # Archive all existing active plans
    _archive_existing_active_plans(db_session, profile_id)

    status = get_taper_status(profile_id, db_session)

    assert status.taper_active is False, (
        f"Expected taper_active=False when no active plan exists, "
        f"got {status.taper_active}"
    )
    assert status.days_until_race is None
    assert status.taper_week is None
    assert status.volume_reduction_pct is None
    assert status.guidance is None

    blocked = should_block_volume_increase(profile_id, db_session)
    assert blocked is False, (
        f"Expected should_block_volume_increase()=False when no active plan, "
        f"got {blocked}"
    )


# ---------------------------------------------------------------------------
# Property 31j: Taper week assignment via PBT — week is always 1, 2, or 3
# ---------------------------------------------------------------------------


@given(
    profile_id=_profile_id_st,
    days_until_race=_taper_days_st,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_taper_week_always_1_2_or_3_when_active(
    db_session,
    profile_id: int,
    days_until_race: int,
) -> None:
    """
    Property 31j: When taper is active, taper_week SHALL always be 1, 2, or 3.

    **Validates: Requirements 22.1, 22.6**
    """
    _create_plan_with_race_goal(db_session, profile_id, days_until_race)

    status = get_taper_status(profile_id, db_session)

    assert status.taper_active is True
    assert status.taper_week in (1, 2, 3), (
        f"Expected taper_week in {{1, 2, 3}}, got {status.taper_week} "
        f"for days_until_race={days_until_race} (profile_id={profile_id})"
    )


# ---------------------------------------------------------------------------
# Property 31k: Volume reduction is None when taper is NOT active
# ---------------------------------------------------------------------------


@given(
    profile_id=_profile_id_st,
    days_until_race=_non_taper_days_st,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_volume_reduction_none_when_taper_not_active(
    db_session,
    profile_id: int,
    days_until_race: int,
) -> None:
    """
    Property 31k: When taper is NOT active, volume_reduction_pct SHALL be None.

    **Validates: Requirements 22.1, 22.6**
    """
    _create_plan_with_race_goal(db_session, profile_id, days_until_race)

    status = get_taper_status(profile_id, db_session)

    assert status.taper_active is False
    assert status.volume_reduction_pct is None, (
        f"Expected volume_reduction_pct=None when taper is not active "
        f"(days_until_race={days_until_race}), got {status.volume_reduction_pct}"
    )
