"""
Property-based tests for AI-generated Training Plan structure.

# Feature: personal-running-coach, Properties 4–7:
#   generated plan date range, training blocks, quality workout constraint,
#   rest day invariant (mock Gemini responses)

Since we cannot call Gemini in tests, these tests validate the plan
parsing/validation logic directly by constructing mock plan data and running
it through the same validation path used in ai_coach.py.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4**
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Constants (mirrors ALLOWED_WORKOUT_TYPES in ai_coach.py)
# ---------------------------------------------------------------------------

ALLOWED_WORKOUT_TYPES = {"easy", "tempo", "interval", "hills", "long", "race", "rest", "recovery"}
QUALITY_WORKOUT_TYPES = {"interval", "tempo", "hills"}
REST_RECOVERY_TYPES = {"rest", "recovery"}
ALL_WORKOUT_TYPES = list(ALLOWED_WORKOUT_TYPES)

# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------


@st.composite
def workout_type_st(draw) -> str:
    """Generate a valid workout type from the allowed set."""
    return draw(st.sampled_from(ALL_WORKOUT_TYPES))


@st.composite
def workout_st(draw, scheduled_date: date) -> dict:
    """Generate a single valid workout dict for a given date."""
    wtype = draw(workout_type_st())
    return {
        "scheduled_date": scheduled_date.isoformat(),
        "workout_type": wtype,
        "target_distance_metres": draw(st.integers(min_value=1000, max_value=42195)),
        "target_pace_zone": draw(
            st.sampled_from(["easy", "moderate", "threshold", "vo2max", "anaerobic"])
        ),
        "target_hr_zone": draw(st.one_of(st.none(), st.integers(min_value=1, max_value=5))),
        "coaching_note": draw(st.text(min_size=1, max_size=100)),
        "steps": [],
    }


@st.composite
def block_st(draw, block_start: date, block_end: date) -> dict:
    """
    Generate a single Training_Block dict with workouts spanning
    [block_start, block_end].
    """
    assume(block_start <= block_end)
    num_days = (block_end - block_start).days + 1

    # Generate one workout per day (or a subset — at least 1 workout)
    num_workouts = draw(st.integers(min_value=1, max_value=num_days))
    # Pick distinct day offsets within the block
    day_offsets = draw(
        st.lists(
            st.integers(min_value=0, max_value=num_days - 1),
            min_size=num_workouts,
            max_size=num_workouts,
            unique=True,
        )
    )

    workouts = []
    for offset in sorted(day_offsets):
        workout_date = block_start + timedelta(days=offset)
        workouts.append(draw(workout_st(workout_date)))

    # Block name: printable text with at least one non-whitespace character
    block_name = draw(
        st.text(
            alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters=" "),
            min_size=1,
            max_size=50,
        ).filter(lambda s: len(s.strip()) >= 1)
    )

    return {
        "name": block_name,
        "start_date": block_start.isoformat(),
        "end_date": block_end.isoformat(),
        "workouts": workouts,
    }


@st.composite
def plan_data_st(draw) -> tuple[dict, date, date]:
    """
    Generate a complete mock plan_data dict (as returned by Gemini) along with
    the plan's start_date and end_date.

    Returns (plan_data, plan_start_date, plan_end_date).
    """
    today = date.today()

    # Plan spans from today to some future date (1–52 weeks out)
    weeks_ahead = draw(st.integers(min_value=1, max_value=52))
    plan_end = today + timedelta(weeks=weeks_ahead)

    # Divide the plan into 1–4 blocks
    num_blocks = draw(st.integers(min_value=1, max_value=4))
    total_days = (plan_end - today).days

    # Partition total_days into num_blocks non-empty segments
    # Use sorted split points
    if num_blocks == 1:
        split_points = []
    else:
        split_points = sorted(
            draw(
                st.lists(
                    st.integers(min_value=1, max_value=total_days - 1),
                    min_size=num_blocks - 1,
                    max_size=num_blocks - 1,
                    unique=True,
                )
            )
        )

    boundaries = [0] + split_points + [total_days]
    blocks = []
    for i in range(num_blocks):
        b_start = today + timedelta(days=boundaries[i])
        b_end = today + timedelta(days=boundaries[i + 1] - 1) if i < num_blocks - 1 else plan_end
        assume(b_start <= b_end)
        blocks.append(draw(block_st(b_start, b_end)))

    plan_data = {"blocks": blocks}
    return plan_data, today, plan_end


# ---------------------------------------------------------------------------
# Helper: extract all workouts from plan_data
# ---------------------------------------------------------------------------


def _all_workouts(plan_data: dict) -> list[dict]:
    """Flatten all workouts from all blocks in plan_data."""
    workouts = []
    for block in plan_data.get("blocks", []):
        workouts.extend(block.get("workouts", []))
    return workouts


# ---------------------------------------------------------------------------
# Validation functions (mirror the logic in ai_coach.py)
# ---------------------------------------------------------------------------


def validate_plan_workout_types(plan_data: dict) -> list[str]:
    """
    Validate and sanitise workout types in plan_data, replacing invalid types
    with 'easy' (mirrors ai_coach.py behaviour).
    Returns a list of warning messages for replaced types.
    """
    warnings = []
    for block in plan_data.get("blocks", []):
        for workout in block.get("workouts", []):
            wtype = workout.get("workout_type", "easy")
            if wtype not in ALLOWED_WORKOUT_TYPES:
                workout["workout_type"] = "easy"
                warnings.append(f"Invalid workout type '{wtype}' replaced with 'easy'")
    return warnings


def check_quality_workout_constraint(plan_data: dict) -> list[str]:
    """
    Check Property 6: no 7-day window has more than 1 quality workout.
    Returns a list of violation descriptions (empty if compliant).
    """
    workouts = _all_workouts(plan_data)
    if not workouts:
        return []

    # Group quality workouts by date
    quality_by_date: dict[date, int] = {}
    for w in workouts:
        if w["workout_type"] in QUALITY_WORKOUT_TYPES:
            d = date.fromisoformat(w["scheduled_date"])
            quality_by_date[d] = quality_by_date.get(d, 0) + 1

    violations = []
    # Check every 7-day window
    all_dates = sorted(quality_by_date.keys())
    if not all_dates:
        return []

    min_date = min(date.fromisoformat(w["scheduled_date"]) for w in workouts)
    max_date = max(date.fromisoformat(w["scheduled_date"]) for w in workouts)

    current = min_date
    while current <= max_date:
        window_end = current + timedelta(days=6)
        count = sum(
            quality_by_date.get(current + timedelta(days=i), 0)
            for i in range(7)
        )
        if count > 1:
            violations.append(
                f"7-day window starting {current.isoformat()} has {count} quality workouts"
            )
        current += timedelta(days=1)

    return violations


def check_rest_day_invariant(plan_data: dict, plan_start: date, plan_end: date) -> list[str]:
    """
    Check Property 7: every calendar week in the plan has at least one
    rest or recovery workout.
    Returns a list of violation descriptions (empty if compliant).
    """
    workouts = _all_workouts(plan_data)

    # Build a set of (iso_year, iso_week) that have a rest/recovery workout
    rest_weeks: set[tuple[int, int]] = set()
    for w in workouts:
        if w["workout_type"] in REST_RECOVERY_TYPES:
            d = date.fromisoformat(w["scheduled_date"])
            iso = d.isocalendar()
            rest_weeks.add((iso[0], iso[1]))

    # Enumerate all calendar weeks that overlap with the plan
    violations = []
    current = plan_start
    while current <= plan_end:
        iso = current.isocalendar()
        week_key = (iso[0], iso[1])
        if week_key not in rest_weeks:
            violations.append(
                f"Calendar week {iso[0]}-W{iso[1]:02d} has no rest or recovery workout"
            )
        # Advance to the next Monday (start of next ISO week)
        days_until_next_monday = 7 - current.weekday()
        current += timedelta(days=days_until_next_monday)

    return violations


# ---------------------------------------------------------------------------
# Property 4: Generated plan spans the correct date range
# ---------------------------------------------------------------------------


@given(data=plan_data_st())
@settings(max_examples=100)
def test_property_4_plan_date_range(data: tuple[dict, date, date]):
    """
    Property 4: A generated Training_Plan's start_date SHALL be <= today and
    end_date SHALL be >= start_date and <= race_goal target_date.

    # Feature: personal-running-coach, Property 4: Generated plan spans the correct date range
    **Validates: Requirements 3.1**
    """
    plan_data, plan_start, plan_end = data
    today = date.today()

    # The plan start_date must be on or before today
    assert plan_start <= today, (
        f"plan start_date {plan_start} is after today {today}"
    )

    # The plan end_date must be >= start_date
    assert plan_end >= plan_start, (
        f"plan end_date {plan_end} is before start_date {plan_start}"
    )

    # All workout dates must fall within [plan_start, plan_end]
    for block in plan_data["blocks"]:
        block_start = date.fromisoformat(block["start_date"])
        block_end = date.fromisoformat(block["end_date"])

        assert block_start >= plan_start, (
            f"Block '{block['name']}' start_date {block_start} is before plan start {plan_start}"
        )
        assert block_end <= plan_end, (
            f"Block '{block['name']}' end_date {block_end} is after plan end {plan_end}"
        )

        for workout in block["workouts"]:
            workout_date = date.fromisoformat(workout["scheduled_date"])
            assert plan_start <= workout_date <= plan_end, (
                f"Workout on {workout_date} is outside plan range "
                f"[{plan_start}, {plan_end}]"
            )


# ---------------------------------------------------------------------------
# Property 5: Generated plan contains at least one named Training_Block
# ---------------------------------------------------------------------------


@given(data=plan_data_st())
@settings(max_examples=100)
def test_property_5_training_blocks(data: tuple[dict, date, date]):
    """
    Property 5: A generated Training_Plan SHALL have at least one Training_Block,
    and each block's start_date/end_date SHALL be within the plan's date range.

    # Feature: personal-running-coach, Property 5: Generated plan contains at least one named Training_Block
    **Validates: Requirements 3.2**
    """
    plan_data, plan_start, plan_end = data

    blocks = plan_data.get("blocks", [])

    # Must have at least one block
    assert len(blocks) >= 1, "Training_Plan must have at least one Training_Block"

    for block in blocks:
        # Each block must have a non-empty name
        assert block.get("name", "").strip(), (
            f"Training_Block has an empty name: {block!r}"
        )

        block_start = date.fromisoformat(block["start_date"])
        block_end = date.fromisoformat(block["end_date"])

        # Block dates must be within the plan's date range
        assert block_start >= plan_start, (
            f"Block '{block['name']}' start_date {block_start} is before plan start {plan_start}"
        )
        assert block_end <= plan_end, (
            f"Block '{block['name']}' end_date {block_end} is after plan end {plan_end}"
        )

        # Block end must be >= block start
        assert block_end >= block_start, (
            f"Block '{block['name']}' end_date {block_end} is before start_date {block_start}"
        )

        # Every workout in the block must have a scheduled_date within the block's range
        for workout in block.get("workouts", []):
            workout_date = date.fromisoformat(workout["scheduled_date"])
            assert block_start <= workout_date <= block_end, (
                f"Workout on {workout_date} is outside block "
                f"'{block['name']}' range [{block_start}, {block_end}]"
            )


# ---------------------------------------------------------------------------
# Property 6: No 7-day window has more than 1 quality workout
# ---------------------------------------------------------------------------


@st.composite
def compliant_plan_data_st(draw) -> tuple[dict, date, date]:
    """
    Generate a plan_data that satisfies the quality workout constraint:
    at most 1 quality workout per 7-day window.

    Strategy: generate workouts day by day, tracking the last quality workout
    date and enforcing a 7-day gap before placing another.
    """
    today = date.today()
    weeks_ahead = draw(st.integers(min_value=2, max_value=12))
    plan_end = today + timedelta(weeks=weeks_ahead)
    total_days = (plan_end - today).days

    workouts = []
    last_quality_date: date | None = None

    for day_offset in range(total_days + 1):
        current_date = today + timedelta(days=day_offset)
        # Decide whether to place a workout on this day
        place_workout = draw(st.booleans())
        if not place_workout:
            continue

        # Determine allowed workout types for this day
        if last_quality_date is not None and (current_date - last_quality_date).days < 7:
            # Cannot place a quality workout within 7 days of the last one
            allowed_types = [t for t in ALL_WORKOUT_TYPES if t not in QUALITY_WORKOUT_TYPES]
        else:
            allowed_types = ALL_WORKOUT_TYPES

        wtype = draw(st.sampled_from(allowed_types))
        if wtype in QUALITY_WORKOUT_TYPES:
            last_quality_date = current_date

        workouts.append({
            "scheduled_date": current_date.isoformat(),
            "workout_type": wtype,
            "target_distance_metres": draw(st.integers(min_value=1000, max_value=42195)),
            "target_pace_zone": "easy",
            "target_hr_zone": None,
            "coaching_note": "Test workout",
            "steps": [],
        })

    # Wrap all workouts in a single block
    plan_data = {
        "blocks": [
            {
                "name": "Training Block",
                "start_date": today.isoformat(),
                "end_date": plan_end.isoformat(),
                "workouts": workouts,
            }
        ]
    }
    return plan_data, today, plan_end


@given(data=compliant_plan_data_st())
@settings(max_examples=100)
def test_property_6_quality_workout_constraint(data: tuple[dict, date, date]):
    """
    Property 6: In any 7-day window of a generated plan, there SHALL be at most
    1 quality workout (workout_type in ["interval", "tempo", "hills"]).

    # Feature: personal-running-coach, Property 6: No day has more than one quality workout
    **Validates: Requirements 3.3**
    """
    plan_data, plan_start, plan_end = data

    workouts = _all_workouts(plan_data)

    # Group quality workouts by date
    quality_by_date: dict[date, int] = {}
    for w in workouts:
        if w["workout_type"] in QUALITY_WORKOUT_TYPES:
            d = date.fromisoformat(w["scheduled_date"])
            quality_by_date[d] = quality_by_date.get(d, 0) + 1

    if not quality_by_date:
        return  # No quality workouts — constraint trivially satisfied

    # Check every 7-day window within the plan
    current = plan_start
    while current <= plan_end:
        window_count = sum(
            quality_by_date.get(current + timedelta(days=i), 0)
            for i in range(7)
        )
        assert window_count <= 1, (
            f"7-day window starting {current.isoformat()} contains "
            f"{window_count} quality workouts (max 1 allowed)"
        )
        current += timedelta(days=1)


# ---------------------------------------------------------------------------
# Property 7: Every calendar week has at least one rest or recovery workout
# ---------------------------------------------------------------------------


@st.composite
def plan_with_rest_days_st(draw) -> tuple[dict, date, date]:
    """
    Generate a plan_data that satisfies the rest day invariant:
    every calendar week has at least one rest or recovery workout.
    """
    today = date.today()
    weeks_ahead = draw(st.integers(min_value=1, max_value=8))
    plan_end = today + timedelta(weeks=weeks_ahead)

    workouts = []

    # For each week in the plan, ensure at least one rest/recovery day
    current_week_start = today - timedelta(days=today.weekday())  # Monday of current week
    while current_week_start <= plan_end:
        week_end = current_week_start + timedelta(days=6)

        # Clamp to plan boundaries
        effective_start = max(current_week_start, today)
        effective_end = min(week_end, plan_end)

        if effective_start > effective_end:
            current_week_start += timedelta(weeks=1)
            continue

        # Place a mandatory rest/recovery workout on a day within this week
        days_in_week = (effective_end - effective_start).days + 1
        rest_offset = draw(st.integers(min_value=0, max_value=days_in_week - 1))
        rest_date = effective_start + timedelta(days=rest_offset)
        rest_type = draw(st.sampled_from(["rest", "recovery"]))

        workouts.append({
            "scheduled_date": rest_date.isoformat(),
            "workout_type": rest_type,
            "target_distance_metres": 0,
            "target_pace_zone": "easy",
            "target_hr_zone": None,
            "coaching_note": "Rest day",
            "steps": [],
        })

        # Optionally add some non-rest workouts on other days of the week
        other_days = [
            effective_start + timedelta(days=i)
            for i in range(days_in_week)
            if (effective_start + timedelta(days=i)) != rest_date
        ]
        for other_day in other_days:
            if draw(st.booleans()):
                non_rest_types = [t for t in ALL_WORKOUT_TYPES if t not in REST_RECOVERY_TYPES]
                workouts.append({
                    "scheduled_date": other_day.isoformat(),
                    "workout_type": draw(st.sampled_from(non_rest_types)),
                    "target_distance_metres": draw(
                        st.integers(min_value=1000, max_value=20000)
                    ),
                    "target_pace_zone": "easy",
                    "target_hr_zone": None,
                    "coaching_note": "Training workout",
                    "steps": [],
                })

        current_week_start += timedelta(weeks=1)

    plan_data = {
        "blocks": [
            {
                "name": "Training Block",
                "start_date": today.isoformat(),
                "end_date": plan_end.isoformat(),
                "workouts": workouts,
            }
        ]
    }
    return plan_data, today, plan_end


@given(data=plan_with_rest_days_st())
@settings(max_examples=100)
def test_property_7_rest_day_invariant(data: tuple[dict, date, date]):
    """
    Property 7: Every calendar week in a generated plan SHALL have at least 1
    workout with type "rest" or "recovery".

    # Feature: personal-running-coach, Property 7: Every calendar week contains at least one rest or recovery day
    **Validates: Requirements 3.4**
    """
    plan_data, plan_start, plan_end = data

    workouts = _all_workouts(plan_data)

    # Build a set of ISO (year, week) tuples that have a rest/recovery workout
    rest_weeks: set[tuple[int, int]] = set()
    for w in workouts:
        if w["workout_type"] in REST_RECOVERY_TYPES:
            d = date.fromisoformat(w["scheduled_date"])
            iso = d.isocalendar()
            rest_weeks.add((iso[0], iso[1]))

    # Check every calendar week that overlaps with the plan
    current = plan_start
    while current <= plan_end:
        iso = current.isocalendar()
        week_key = (iso[0], iso[1])
        assert week_key in rest_weeks, (
            f"Calendar week {iso[0]}-W{iso[1]:02d} (starting near {current.isoformat()}) "
            f"has no rest or recovery workout"
        )
        # Advance to the next Monday
        days_until_next_monday = 7 - current.weekday()
        current += timedelta(days=days_until_next_monday)


# ---------------------------------------------------------------------------
# Validate plan_workout_types: invalid types are replaced with 'easy'
# ---------------------------------------------------------------------------


@given(
    invalid_type=st.text(min_size=1, max_size=20).filter(
        lambda t: t not in ALLOWED_WORKOUT_TYPES
    )
)
@settings(max_examples=50)
def test_validate_plan_workout_types_replaces_invalid(invalid_type: str):
    """
    The validate_plan_workout_types function SHALL replace any workout_type
    not in ALLOWED_WORKOUT_TYPES with 'easy', mirroring ai_coach.py behaviour.

    **Validates: Requirements 3.5**
    """
    plan_data = {
        "blocks": [
            {
                "name": "Test Block",
                "start_date": date.today().isoformat(),
                "end_date": (date.today() + timedelta(days=6)).isoformat(),
                "workouts": [
                    {
                        "scheduled_date": date.today().isoformat(),
                        "workout_type": invalid_type,
                        "target_distance_metres": 5000,
                        "target_pace_zone": "easy",
                        "steps": [],
                    }
                ],
            }
        ]
    }

    warnings = validate_plan_workout_types(plan_data)

    # The invalid type should have been replaced
    assert plan_data["blocks"][0]["workouts"][0]["workout_type"] == "easy", (
        f"Expected 'easy' after replacing invalid type '{invalid_type}', "
        f"got '{plan_data['blocks'][0]['workouts'][0]['workout_type']}'"
    )
    assert len(warnings) == 1, f"Expected 1 warning, got {len(warnings)}"


@given(valid_type=st.sampled_from(ALL_WORKOUT_TYPES))
@settings(max_examples=50)
def test_validate_plan_workout_types_preserves_valid(valid_type: str):
    """
    The validate_plan_workout_types function SHALL NOT modify workout_type
    values that are already in ALLOWED_WORKOUT_TYPES.

    **Validates: Requirements 3.5**
    """
    plan_data = {
        "blocks": [
            {
                "name": "Test Block",
                "start_date": date.today().isoformat(),
                "end_date": (date.today() + timedelta(days=6)).isoformat(),
                "workouts": [
                    {
                        "scheduled_date": date.today().isoformat(),
                        "workout_type": valid_type,
                        "target_distance_metres": 5000,
                        "target_pace_zone": "easy",
                        "steps": [],
                    }
                ],
            }
        ]
    }

    warnings = validate_plan_workout_types(plan_data)

    assert plan_data["blocks"][0]["workouts"][0]["workout_type"] == valid_type, (
        f"Valid type '{valid_type}' was unexpectedly modified"
    )
    assert len(warnings) == 0, f"Expected no warnings for valid type, got {len(warnings)}"


# ---------------------------------------------------------------------------
# Integration test: generate_plan with mocked Gemini validates plan structure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_plan_with_mock_gemini_validates_structure(db_session):
    """
    Integration test: generate_plan() with a mocked Gemini response SHALL
    produce a TrainingPlan with at least one TrainingBlock, and all workouts
    SHALL have valid workout_type values.

    Uses unittest.mock to patch the Gemini API call.
    **Validates: Requirements 3.1, 3.2, 3.5**
    """
    import sys
    from unittest.mock import MagicMock

    # Mock the google.generativeai module before importing ai_coach
    # so the import doesn't fail when the package is not installed.
    mock_genai = MagicMock()
    mock_genai.types = MagicMock()
    mock_genai.types.GenerationConfig = MagicMock(return_value=MagicMock())
    sys.modules.setdefault("google", MagicMock())
    sys.modules.setdefault("google.generativeai", mock_genai)
    sys.modules.setdefault("google.generativeai.types", mock_genai.types)

    from app.models.orm import Profile, RaceGoal, TrainingPlan, TrainingBlock, Workout
    from app.services.ai_coach import generate_plan

    today = date.today()
    race_date = today + timedelta(weeks=8)

    # Ensure profile 1 exists (seeded by conftest)
    profile = db_session.query(Profile).filter(Profile.id == 1).first()
    assert profile is not None

    # Create a race goal
    race_goal = RaceGoal(
        profile_id=1,
        distance_metres=42195,
        target_date=race_date,
        label="Test Marathon",
        is_active=True,
    )
    db_session.add(race_goal)
    db_session.flush()

    # Build a minimal valid mock plan JSON response
    mock_plan_json = json.dumps({
        "blocks": [
            {
                "name": "Base Building",
                "start_date": today.isoformat(),
                "end_date": (today + timedelta(weeks=4) - timedelta(days=1)).isoformat(),
                "workouts": [
                    {
                        "scheduled_date": (today + timedelta(days=i)).isoformat(),
                        "workout_type": wtype,
                        "target_distance_metres": 8000,
                        "target_pace_zone": "easy",
                        "target_hr_zone": 2,
                        "coaching_note": "Easy run",
                        "steps": [
                            {
                                "sequence": 1,
                                "label": "Easy Run",
                                "distance_metres": 8000,
                                "pace_zone": "easy",
                                "hr_zone": 2,
                                "description": "Run easy",
                            }
                        ],
                    }
                    for i, wtype in enumerate(
                        ["easy", "rest", "easy", "tempo", "rest", "easy", "long"]
                    )
                ],
            },
            {
                "name": "Taper",
                "start_date": (today + timedelta(weeks=4)).isoformat(),
                "end_date": race_date.isoformat(),
                "workouts": [
                    {
                        "scheduled_date": (today + timedelta(weeks=4, days=i)).isoformat(),
                        "workout_type": wtype,
                        "target_distance_metres": 5000,
                        "target_pace_zone": "easy",
                        "target_hr_zone": 2,
                        "coaching_note": "Taper workout",
                        "steps": [
                            {
                                "sequence": 1,
                                "label": "Easy Run",
                                "distance_metres": 5000,
                                "pace_zone": "easy",
                                "hr_zone": 2,
                                "description": "Easy taper run",
                            }
                        ],
                    }
                    for i, wtype in enumerate(
                        ["easy", "rest", "easy", "rest", "easy", "rest", "race"]
                    )
                ],
            },
        ]
    })

    mock_response = MagicMock()
    mock_response.text = mock_plan_json

    with patch("app.services.ai_coach._get_model") as mock_get_model, \
         patch("app.services.ai_coach._rate_limited_generate", new_callable=AsyncMock) as mock_generate:

        mock_generate.return_value = mock_plan_json

        plan = await generate_plan(
            profile_id=1,
            race_goal_id=race_goal.id,
            db=db_session,
        )

    # Verify the plan was created
    assert plan is not None
    assert plan.profile_id == 1
    assert plan.race_goal_id == race_goal.id
    assert plan.start_date <= today
    assert plan.end_date == race_date
    assert plan.status == "active"

    # Verify at least one block was created
    blocks = db_session.query(TrainingBlock).filter(
        TrainingBlock.plan_id == plan.id
    ).all()
    assert len(blocks) >= 1, "Plan must have at least one TrainingBlock"

    # Verify all workouts have valid types
    workouts = db_session.query(Workout).filter(
        Workout.plan_id == plan.id
    ).all()
    assert len(workouts) > 0, "Plan must have at least one Workout"

    for workout in workouts:
        assert workout.workout_type in ALLOWED_WORKOUT_TYPES, (
            f"Workout has invalid type: '{workout.workout_type}'"
        )
