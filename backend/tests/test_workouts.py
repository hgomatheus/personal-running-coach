"""
Property-based tests for the Workouts API.

# Feature: personal-running-coach, Properties 10–11: workout API field completeness, step distance sum

**Validates: Requirements 3.8, 5.1, 5.2, 5.3, 5.4**
"""

from datetime import date, datetime, timezone

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.models.orm import TrainingBlock, TrainingPlan, Workout

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REQUIRED_WORKOUT_FIELDS = {
    "id",
    "workout_type",
    "scheduled_date",
    "target_distance_metres",
    "target_pace_zone",
    "steps",
    "estimated_duration_seconds",
}

REQUIRED_STEP_FIELDS = {
    "sequence",
    "label",
    "distance_metres",
    "estimated_duration_seconds",
}

VALID_WORKOUT_TYPES = ["easy", "tempo", "interval", "hills", "long", "race", "recovery"]
VALID_PACE_ZONES = ["easy", "moderate", "threshold", "vo2max", "anaerobic"]

# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

_workout_type_st = st.sampled_from(VALID_WORKOUT_TYPES)
_pace_zone_st = st.sampled_from(VALID_PACE_ZONES)
_profile_id_st = st.sampled_from([1, 2])

# Step distance: positive float, reasonable range (100m to 10km per step)
_step_distance_st = st.floats(min_value=100.0, max_value=10_000.0, allow_nan=False, allow_infinity=False)

# Number of steps: 1 to 6
_num_steps_st = st.integers(min_value=1, max_value=6)

# Scheduled date: within a reasonable range
_scheduled_date_st = st.dates(
    min_value=date(2025, 1, 1),
    max_value=date(2026, 12, 31),
)


@st.composite
def workout_steps_with_total(draw) -> tuple[list[dict], float]:
    """
    Generate a list of workout steps and the corresponding total distance.
    The total distance is exactly the sum of all step distances.
    Returns (steps, total_distance_metres).
    """
    num_steps = draw(_num_steps_st)
    step_distances = [draw(_step_distance_st) for _ in range(num_steps)]
    total_distance = sum(step_distances)

    steps = []
    for i, dist in enumerate(step_distances):
        steps.append({
            "sequence": i + 1,
            "label": f"Step {i + 1}",
            "distance_metres": dist,
            "pace_zone": draw(_pace_zone_st),
            "hr_zone": None,
            "description": None,
        })

    return steps, total_distance


# ---------------------------------------------------------------------------
# Helper: create minimal TrainingPlan + TrainingBlock + Workout in the test DB
# ---------------------------------------------------------------------------

def _create_workout(
    db_session,
    profile_id: int,
    workout_type: str,
    scheduled_date: date,
    target_distance_metres: float,
    target_pace_zone: str,
    steps: list[dict],
) -> Workout:
    """Insert a minimal TrainingPlan, TrainingBlock, and Workout into the test DB."""
    now = datetime.now(timezone.utc)

    plan = TrainingPlan(
        profile_id=profile_id,
        race_goal_id=None,
        start_date=scheduled_date,
        end_date=scheduled_date,
        status="active",
        gemini_prompt_hash=None,
        created_at=now,
        updated_at=now,
    )
    db_session.add(plan)
    db_session.flush()  # get plan.id

    block = TrainingBlock(
        profile_id=profile_id,
        plan_id=plan.id,
        name="Test Block",
        start_date=scheduled_date,
        end_date=scheduled_date,
        sequence=1,
    )
    db_session.add(block)
    db_session.flush()  # get block.id

    workout = Workout(
        profile_id=profile_id,
        block_id=block.id,
        plan_id=plan.id,
        scheduled_date=scheduled_date,
        workout_type=workout_type,
        target_distance_metres=target_distance_metres,
        target_pace_zone=target_pace_zone,
        target_hr_zone=None,
        steps=steps,
        coaching_note="Test coaching note",
        status="scheduled",
        rpe_score=None,
        matched_run_id=None,
        created_at=now,
        updated_at=now,
    )
    db_session.add(workout)
    db_session.flush()  # get workout.id

    return workout


# ---------------------------------------------------------------------------
# Property 10: Workout API response contains all required fields
# ---------------------------------------------------------------------------

@given(
    profile_id=_profile_id_st,
    workout_type=_workout_type_st,
    scheduled_date=_scheduled_date_st,
    steps_and_total=workout_steps_with_total(),
    target_pace_zone=_pace_zone_st,
)
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_workout_api_field_completeness(
    client,
    db_session,
    profile_id: int,
    workout_type: str,
    scheduled_date: date,
    steps_and_total: tuple[list[dict], float],
    target_pace_zone: str,
):
    """
    Property 10: For any Workout stored in the database, GET /api/v1/workouts/{id}
    SHALL include all required fields: id, workout_type, scheduled_date,
    target_distance_metres, target_pace_zone, steps, estimated_duration_seconds.
    Each step SHALL include: sequence, label, distance_metres, estimated_duration_seconds.

    # Feature: personal-running-coach, Property 10: Workout API field completeness
    **Validates: Requirements 3.8, 5.1, 5.2, 5.3**
    """
    steps, total_distance = steps_and_total

    workout = _create_workout(
        db_session,
        profile_id=profile_id,
        workout_type=workout_type,
        scheduled_date=scheduled_date,
        target_distance_metres=total_distance,
        target_pace_zone=target_pace_zone,
        steps=steps,
    )

    response = client.get(
        f"/api/v1/workouts/{workout.id}",
        params={"profile_id": profile_id},
    )
    assert response.status_code == 200, (
        f"GET /api/v1/workouts/{workout.id} returned {response.status_code}: "
        f"{response.text}"
    )

    body = response.json()

    # Verify all required top-level fields are present
    missing_fields = REQUIRED_WORKOUT_FIELDS - set(body.keys())
    assert not missing_fields, (
        f"Workout response missing required fields: {missing_fields}. "
        f"Got keys: {set(body.keys())}"
    )

    # Verify steps array is present and non-empty
    assert isinstance(body["steps"], list), (
        f"Expected 'steps' to be a list, got {type(body['steps'])}"
    )
    assert len(body["steps"]) == len(steps), (
        f"Expected {len(steps)} steps, got {len(body['steps'])}"
    )

    # Verify each step contains required fields
    for i, step in enumerate(body["steps"]):
        missing_step_fields = REQUIRED_STEP_FIELDS - set(step.keys())
        assert not missing_step_fields, (
            f"Step {i} missing required fields: {missing_step_fields}. "
            f"Got keys: {set(step.keys())}"
        )
        assert step["distance_metres"] is not None, (
            f"Step {i} has null distance_metres"
        )
        assert step["sequence"] is not None, (
            f"Step {i} has null sequence"
        )
        assert step["label"] is not None, (
            f"Step {i} has null label"
        )


# ---------------------------------------------------------------------------
# Property 11: Workout total distance equals sum of step distances
# ---------------------------------------------------------------------------

@given(
    profile_id=_profile_id_st,
    workout_type=_workout_type_st,
    scheduled_date=_scheduled_date_st,
    steps_and_total=workout_steps_with_total(),
    target_pace_zone=_pace_zone_st,
)
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_workout_step_distance_sum(
    client,
    db_session,
    profile_id: int,
    workout_type: str,
    scheduled_date: date,
    steps_and_total: tuple[list[dict], float],
    target_pace_zone: str,
):
    """
    Property 11: For any Workout with steps, the sum of distance_metres across
    all steps SHALL equal the workout's target_distance_metres (within ±1m tolerance).

    # Feature: personal-running-coach, Property 11: Step distance sum
    **Validates: Requirements 5.4**
    """
    steps, total_distance = steps_and_total

    workout = _create_workout(
        db_session,
        profile_id=profile_id,
        workout_type=workout_type,
        scheduled_date=scheduled_date,
        target_distance_metres=total_distance,
        target_pace_zone=target_pace_zone,
        steps=steps,
    )

    response = client.get(
        f"/api/v1/workouts/{workout.id}",
        params={"profile_id": profile_id},
    )
    assert response.status_code == 200, (
        f"GET /api/v1/workouts/{workout.id} returned {response.status_code}: "
        f"{response.text}"
    )

    body = response.json()

    target_distance = body["target_distance_metres"]
    assert target_distance is not None, "target_distance_metres should not be None"

    returned_steps = body["steps"]
    assert len(returned_steps) > 0, "Expected at least one step"

    step_distance_sum = sum(s["distance_metres"] for s in returned_steps)

    assert abs(step_distance_sum - target_distance) <= 1.0, (
        f"Sum of step distances ({step_distance_sum:.4f}m) does not equal "
        f"target_distance_metres ({target_distance:.4f}m) within ±1m tolerance. "
        f"Difference: {abs(step_distance_sum - target_distance):.4f}m"
    )
