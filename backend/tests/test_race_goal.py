"""
Property-based tests for race goal date preservation across plan adaptation triggers.

# Feature: personal-running-coach, Property 14: Race goal date preserved across all adaptation triggers

**Validates: Requirements 4.5**
"""

import asyncio
import json
import sys
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Mock google.generativeai before importing ai_coach (package may not be
# installed in the test environment).
# ---------------------------------------------------------------------------
_mock_genai = MagicMock()
_mock_genai.types = MagicMock()
_mock_genai.types.GenerationConfig = MagicMock(return_value=MagicMock())
sys.modules.setdefault("google", MagicMock())
sys.modules.setdefault("google.generativeai", _mock_genai)
sys.modules.setdefault("google.generativeai.types", _mock_genai.types)

from app.models.orm import RaceGoal, TrainingBlock, TrainingPlan, Workout
from app.services.ai_coach import adapt_plan

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Profile IDs pre-seeded in the test database
_profile_id_st = st.sampled_from([1, 2])

# Race target dates: at least 4 weeks in the future, up to 2 years out
_target_date_st = st.dates(
    min_value=date.today() + timedelta(days=28),
    max_value=date.today() + timedelta(days=730),
)

# All four adaptation trigger types specified in Property 14
_trigger_st = st.sampled_from(
    ["skipped_workout", "run_deviation", "rpe_high", "injury"]
)

# Valid workout types
_workout_type_st = st.sampled_from(
    ["easy", "tempo", "interval", "hills", "long", "recovery"]
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Minimal valid Gemini response for adapt_plan — just enough to satisfy json.loads
_MOCK_GEMINI_RESPONSE = json.dumps(
    {"adaptation_applied": True, "message": "Plan adapted for test"}
)


def _make_race_goal(db_session, profile_id: int, target_date: date) -> RaceGoal:
    """Insert a RaceGoal and return it."""
    race_goal = RaceGoal(
        profile_id=profile_id,
        distance_metres=42_195.0,
        target_date=target_date,
        label="Test Race",
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(race_goal)
    db_session.flush()
    return race_goal


def _make_active_plan(
    db_session, profile_id: int, race_goal_id: int, target_date: date
) -> TrainingPlan:
    """Insert an active TrainingPlan linked to the given RaceGoal and return it."""
    now = datetime.now(timezone.utc)
    plan = TrainingPlan(
        profile_id=profile_id,
        race_goal_id=race_goal_id,
        start_date=date.today(),
        end_date=target_date,
        status="active",
        gemini_prompt_hash=None,
        created_at=now,
        updated_at=now,
    )
    db_session.add(plan)
    db_session.flush()
    return plan


def _make_workout(
    db_session,
    profile_id: int,
    plan_id: int,
    workout_type: str,
    scheduled_date: date,
    status: str = "scheduled",
    rpe_score: int | None = None,
) -> Workout:
    """Insert a Workout row and return it."""
    now = datetime.now(timezone.utc)
    workout = Workout(
        profile_id=profile_id,
        block_id=None,
        plan_id=plan_id,
        scheduled_date=scheduled_date,
        workout_type=workout_type,
        target_distance_metres=8_000.0,
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


def _build_context(trigger: str, profile_id: int, workout_type: str) -> dict:
    """Build a minimal context dict for the given trigger type."""
    if trigger == "skipped_workout":
        return {
            "workout_id": 1,
            "workout_type": workout_type,
            "scheduled_date": date.today().isoformat(),
        }
    elif trigger == "run_deviation":
        return {
            "workout_id": 1,
            "run_id": 1,
            "target_distance_metres": 8_000.0,
            "actual_distance_metres": 10_500.0,
            "deviation_pct": 0.3125,
        }
    elif trigger == "rpe_high":
        return {
            "workout_type": workout_type,
            "current_workout_id": 1,
            "previous_workout_id": 2,
            "current_rpe": 9,
            "previous_rpe": 9,
        }
    elif trigger == "injury":
        return {
            "injury_notes": "Knee pain — reduce load",
            "profile_id": profile_id,
        }
    return {}


# ---------------------------------------------------------------------------
# Property 14: Race goal date preserved across all adaptation triggers
# ---------------------------------------------------------------------------


@given(
    profile_id=_profile_id_st,
    target_date=_target_date_st,
    trigger=_trigger_st,
    workout_type=_workout_type_st,
)
@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_race_goal_date_preserved_after_adapt_plan(
    db_session,
    profile_id: int,
    target_date: date,
    trigger: str,
    workout_type: str,
):
    """
    Property 14: For any plan adaptation trigger (skipped_workout, run_deviation,
    rpe_high, injury), the RaceGoal.target_date SHALL remain unchanged after
    adapt_plan() is called.

    # Feature: personal-running-coach, Property 14: Race goal date preserved
    **Validates: Requirements 4.5**
    """
    # Set up: create a RaceGoal with a specific target_date
    race_goal = _make_race_goal(db_session, profile_id, target_date)
    original_target_date = race_goal.target_date

    # Create an active TrainingPlan linked to that RaceGoal
    _make_active_plan(db_session, profile_id, race_goal.id, target_date)

    # Create a workout so the plan has content
    _make_workout(
        db_session,
        profile_id=profile_id,
        plan_id=db_session.query(TrainingPlan)
        .filter(
            TrainingPlan.profile_id == profile_id,
            TrainingPlan.status == "active",
        )
        .first()
        .id,
        workout_type=workout_type,
        scheduled_date=date.today() + timedelta(days=1),
    )

    context = _build_context(trigger, profile_id, workout_type)

    # Mock Gemini to avoid real API calls
    with patch(
        "app.services.ai_coach._rate_limited_generate",
        new=AsyncMock(return_value=_MOCK_GEMINI_RESPONSE),
    ):
        result = asyncio.run(adapt_plan(trigger, context, profile_id, db_session))

    # Reload the RaceGoal from the DB to check it wasn't modified
    db_session.expire(race_goal)
    refreshed_goal = (
        db_session.query(RaceGoal).filter(RaceGoal.id == race_goal.id).first()
    )

    assert refreshed_goal is not None, (
        f"RaceGoal (id={race_goal.id}) was deleted after adapt_plan() — "
        f"trigger={trigger}, profile_id={profile_id}"
    )
    assert refreshed_goal.target_date == original_target_date, (
        f"RaceGoal.target_date was modified by adapt_plan()! "
        f"trigger={trigger}, profile_id={profile_id}, "
        f"original={original_target_date.isoformat()}, "
        f"after={refreshed_goal.target_date.isoformat()}"
    )


@given(
    profile_id=_profile_id_st,
    target_date=_target_date_st,
    workout_type=_workout_type_st,
)
@settings(
    max_examples=30,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_race_goal_date_preserved_all_triggers_combined(
    db_session,
    profile_id: int,
    target_date: date,
    workout_type: str,
):
    """
    Property 14 (exhaustive): For a single RaceGoal, calling adapt_plan() with
    ALL four trigger types in sequence SHALL leave target_date unchanged after
    each call.

    # Feature: personal-running-coach, Property 14: Race goal date preserved
    **Validates: Requirements 4.5**
    """
    race_goal = _make_race_goal(db_session, profile_id, target_date)
    original_target_date = race_goal.target_date

    plan = _make_active_plan(db_session, profile_id, race_goal.id, target_date)

    _make_workout(
        db_session,
        profile_id=profile_id,
        plan_id=plan.id,
        workout_type=workout_type,
        scheduled_date=date.today() + timedelta(days=1),
    )

    all_triggers = ["skipped_workout", "run_deviation", "rpe_high", "injury"]

    with patch(
        "app.services.ai_coach._rate_limited_generate",
        new=AsyncMock(return_value=_MOCK_GEMINI_RESPONSE),
    ):
        for trigger in all_triggers:
            context = _build_context(trigger, profile_id, workout_type)
            asyncio.run(adapt_plan(trigger, context, profile_id, db_session))

            # Check after each trigger
            db_session.expire(race_goal)
            refreshed_goal = (
                db_session.query(RaceGoal).filter(RaceGoal.id == race_goal.id).first()
            )

            assert refreshed_goal is not None, (
                f"RaceGoal was deleted after trigger={trigger}"
            )
            assert refreshed_goal.target_date == original_target_date, (
                f"RaceGoal.target_date changed after trigger={trigger}! "
                f"original={original_target_date.isoformat()}, "
                f"after={refreshed_goal.target_date.isoformat()}"
            )


@given(
    profile_id=_profile_id_st,
    target_date=_target_date_st,
    trigger=_trigger_st,
)
@settings(
    max_examples=30,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_race_goal_date_preserved_when_no_active_plan(
    db_session,
    profile_id: int,
    target_date: date,
    trigger: str,
):
    """
    Property 14 (edge case): When there is no active TrainingPlan, adapt_plan()
    returns False without modifying any RaceGoal.target_date.

    # Feature: personal-running-coach, Property 14: Race goal date preserved
    **Validates: Requirements 4.5**
    """
    # Create a RaceGoal but NO active plan
    race_goal = _make_race_goal(db_session, profile_id, target_date)
    original_target_date = race_goal.target_date

    context = _build_context(trigger, profile_id, "easy")

    with patch(
        "app.services.ai_coach._rate_limited_generate",
        new=AsyncMock(return_value=_MOCK_GEMINI_RESPONSE),
    ):
        result = asyncio.run(adapt_plan(trigger, context, profile_id, db_session))

    # adapt_plan returns False when no active plan exists
    assert result is False, (
        f"Expected adapt_plan to return False when no active plan exists, "
        f"got {result!r}. trigger={trigger}, profile_id={profile_id}"
    )

    # RaceGoal must still be intact
    db_session.expire(race_goal)
    refreshed_goal = (
        db_session.query(RaceGoal).filter(RaceGoal.id == race_goal.id).first()
    )
    assert refreshed_goal is not None, "RaceGoal was unexpectedly deleted"
    assert refreshed_goal.target_date == original_target_date, (
        f"RaceGoal.target_date changed even with no active plan! "
        f"trigger={trigger}, original={original_target_date.isoformat()}, "
        f"after={refreshed_goal.target_date.isoformat()}"
    )
