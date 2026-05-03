"""
Property-based tests for route suggestions distance tolerance.

# Feature: personal-running-coach

**Validates: Requirements 12.1**

Property 32: Route suggestions respect ±20% distance tolerance.

`get_suggestions(workout, profile_id, db) -> list[RouteRecord]` in
`backend/app/services/route_extractor.py`:

  - Filters routes by ±20% of the workout's target distance:
      0.8 * target_distance_metres <= typical_distance_metres <= 1.2 * target_distance_metres
  - Returns at most 3 routes
  - Ranks by: type affinity first, then run_count desc, then recency desc

Sub-properties tested:
  32a: All returned routes have typical_distance_metres within ±20% of target
  32b: Routes outside the ±20% tolerance are never returned
  32c: At most 3 routes are returned
  32d: Routes are ranked correctly (type affinity > run_count > recency)
  32e: Boundary — a route at exactly 80% of workout distance IS included
  32f: Boundary — a route at exactly 120% of workout distance IS included
  32g: Boundary — a route at 79.9% of workout distance is NOT included
  32h: Boundary — a route at 120.1% of workout distance is NOT included
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import NamedTuple

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.models.orm import RouteRecord, TrainingBlock, TrainingPlan, Workout
from app.services.route_extractor import get_suggestions

# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

_profile_id_st = st.sampled_from([1, 2])

# Realistic workout target distances: 1 km to 42.2 km in metres
_target_distance_st = st.floats(min_value=1000.0, max_value=42200.0, allow_nan=False, allow_infinity=False)

# Number of routes to insert (0 to 10)
_route_count_st = st.integers(min_value=0, max_value=10)

# Workout types
_workout_type_st = st.sampled_from(["easy", "tempo", "interval", "hills", "long", "race", "recovery"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _unique_fingerprint() -> str:
    """Generate a unique SHA-256-like fingerprint for a route."""
    return hashlib.sha256(uuid.uuid4().bytes).hexdigest()


def _make_workout(
    db_session,
    profile_id: int,
    target_distance_metres: float,
    workout_type: str = "easy",
) -> Workout:
    """
    Insert a minimal TrainingPlan + TrainingBlock + Workout and return the Workout.
    """
    today = date.today()
    now = datetime.now(timezone.utc)

    plan = TrainingPlan(
        profile_id=profile_id,
        start_date=today,
        end_date=today + timedelta(days=90),
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
        name="Base",
        start_date=today,
        end_date=today + timedelta(days=30),
        sequence=1,
    )
    db_session.add(block)
    db_session.flush()

    workout = Workout(
        profile_id=profile_id,
        block_id=block.id,
        plan_id=plan.id,
        scheduled_date=today,
        workout_type=workout_type,
        target_distance_metres=target_distance_metres,
        target_pace_zone="easy",
        steps=[],
        status="scheduled",
        created_at=now,
        updated_at=now,
    )
    db_session.add(workout)
    db_session.flush()
    return workout


def _make_route(
    db_session,
    profile_id: int,
    typical_distance_metres: float,
    run_count: int = 1,
    workout_type_affinity: str | None = None,
    last_used_at: datetime | None = None,
) -> RouteRecord:
    """Insert a RouteRecord with the given distance and return it."""
    if last_used_at is None:
        last_used_at = datetime.now(timezone.utc)

    route = RouteRecord(
        profile_id=profile_id,
        polyline="encodedpolyline",
        fingerprint=_unique_fingerprint(),
        typical_distance_metres=typical_distance_metres,
        run_count=run_count,
        last_used_at=last_used_at,
        workout_type_affinity=workout_type_affinity,
    )
    db_session.add(route)
    db_session.flush()
    return route


def _clear_routes(db_session, profile_id: int) -> None:
    """Delete all RouteRecord rows for a profile to ensure a clean slate."""
    db_session.query(RouteRecord).filter(RouteRecord.profile_id == profile_id).delete()
    db_session.flush()


# ---------------------------------------------------------------------------
# Property 32a: All returned routes are within ±20% of target distance
# ---------------------------------------------------------------------------


@given(
    profile_id=_profile_id_st,
    target_distance=_target_distance_st,
    route_count=_route_count_st,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_all_returned_routes_within_tolerance(
    db_session,
    profile_id: int,
    target_distance: float,
    route_count: int,
) -> None:
    """
    Property 32a: Every route returned by get_suggestions() SHALL have
    typical_distance_metres in [0.8 * target, 1.2 * target].

    **Validates: Requirements 12.1**
    """
    workout = _make_workout(db_session, profile_id, target_distance)

    low = target_distance * 0.80
    high = target_distance * 1.20

    # Insert routes with random distances spread around the target
    draw_distances = [
        target_distance * (0.5 + i * 0.1) for i in range(route_count)
    ]
    for d in draw_distances:
        _make_route(db_session, profile_id, d)

    suggestions = get_suggestions(workout, profile_id, db_session)

    for route in suggestions:
        assert low <= route.typical_distance_metres <= high, (
            f"Returned route distance {route.typical_distance_metres:.1f} m is outside "
            f"±20% tolerance [{low:.1f}, {high:.1f}] for target={target_distance:.1f} m"
        )


# ---------------------------------------------------------------------------
# Property 32b: Routes outside ±20% tolerance are never returned
# ---------------------------------------------------------------------------


@given(
    profile_id=_profile_id_st,
    target_distance=_target_distance_st,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_out_of_tolerance_routes_never_returned(
    db_session,
    profile_id: int,
    target_distance: float,
) -> None:
    """
    Property 32b: Routes with typical_distance_metres outside [0.8 * target,
    1.2 * target] SHALL never appear in get_suggestions() results.

    **Validates: Requirements 12.1**
    """
    workout = _make_workout(db_session, profile_id, target_distance)

    low = target_distance * 0.80
    high = target_distance * 1.20

    # Insert one route clearly below tolerance and one clearly above
    too_short = _make_route(db_session, profile_id, target_distance * 0.50)
    too_long = _make_route(db_session, profile_id, target_distance * 1.50)

    # Also insert one valid route so the function has something to return
    valid = _make_route(db_session, profile_id, target_distance)

    suggestions = get_suggestions(workout, profile_id, db_session)

    returned_ids = {r.id for r in suggestions}
    assert too_short.id not in returned_ids, (
        f"Route with distance {too_short.typical_distance_metres:.1f} m (below "
        f"tolerance floor {low:.1f} m) was incorrectly returned"
    )
    assert too_long.id not in returned_ids, (
        f"Route with distance {too_long.typical_distance_metres:.1f} m (above "
        f"tolerance ceiling {high:.1f} m) was incorrectly returned"
    )
    assert valid.id in returned_ids, (
        f"Valid route with distance {valid.typical_distance_metres:.1f} m was not returned"
    )


# ---------------------------------------------------------------------------
# Property 32c: At most 3 routes are returned
# ---------------------------------------------------------------------------


@given(
    profile_id=_profile_id_st,
    target_distance=_target_distance_st,
    extra_routes=st.integers(min_value=0, max_value=10),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_at_most_3_routes_returned(
    db_session,
    profile_id: int,
    target_distance: float,
    extra_routes: int,
) -> None:
    """
    Property 32c: get_suggestions() SHALL return at most 3 routes regardless
    of how many matching routes exist in the database.

    **Validates: Requirements 12.1**
    """
    workout = _make_workout(db_session, profile_id, target_distance)

    # Insert up to 10 routes all within tolerance
    for _ in range(extra_routes):
        _make_route(db_session, profile_id, target_distance)

    suggestions = get_suggestions(workout, profile_id, db_session)

    assert len(suggestions) <= 3, (
        f"Expected at most 3 suggestions, got {len(suggestions)} "
        f"(target={target_distance:.1f} m, {extra_routes} routes inserted)"
    )


# ---------------------------------------------------------------------------
# Property 32d: Ranking — type affinity > run_count > recency
# ---------------------------------------------------------------------------


@given(
    profile_id=_profile_id_st,
    target_distance=_target_distance_st,
    workout_type=_workout_type_st,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_ranking_type_affinity_first(
    db_session,
    profile_id: int,
    target_distance: float,
    workout_type: str,
) -> None:
    """
    Property 32d (affinity): A route with matching workout_type_affinity SHALL
    rank above a route with higher run_count but no affinity match.

    **Validates: Requirements 12.1**
    """
    _clear_routes(db_session, profile_id)
    workout = _make_workout(db_session, profile_id, target_distance, workout_type)

    now = datetime.now(timezone.utc)

    # High run_count but wrong affinity
    high_count_no_affinity = _make_route(
        db_session, profile_id, target_distance,
        run_count=100,
        workout_type_affinity="other_type",
        last_used_at=now,
    )
    # Low run_count but matching affinity
    low_count_with_affinity = _make_route(
        db_session, profile_id, target_distance,
        run_count=1,
        workout_type_affinity=workout_type,
        last_used_at=now - timedelta(days=30),
    )

    suggestions = get_suggestions(workout, profile_id, db_session)

    assert len(suggestions) >= 2, "Expected at least 2 suggestions"

    returned_ids = [r.id for r in suggestions]
    affinity_pos = returned_ids.index(low_count_with_affinity.id)
    no_affinity_pos = returned_ids.index(high_count_no_affinity.id)

    assert affinity_pos < no_affinity_pos, (
        f"Route with matching affinity (pos={affinity_pos}) should rank before "
        f"route with higher run_count but no affinity (pos={no_affinity_pos})"
    )


@given(
    profile_id=_profile_id_st,
    target_distance=_target_distance_st,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_ranking_run_count_second(
    db_session,
    profile_id: int,
    target_distance: float,
) -> None:
    """
    Property 32d (run_count): Among routes with the same affinity status,
    higher run_count SHALL rank first.

    **Validates: Requirements 12.1**
    """
    _clear_routes(db_session, profile_id)
    workout = _make_workout(db_session, profile_id, target_distance, "easy")

    now = datetime.now(timezone.utc)

    # Both have no affinity match; higher run_count should rank first
    low_count = _make_route(
        db_session, profile_id, target_distance,
        run_count=1,
        workout_type_affinity=None,
        last_used_at=now,
    )
    high_count = _make_route(
        db_session, profile_id, target_distance,
        run_count=50,
        workout_type_affinity=None,
        last_used_at=now - timedelta(days=10),
    )

    suggestions = get_suggestions(workout, profile_id, db_session)

    assert len(suggestions) >= 2, "Expected at least 2 suggestions"

    returned_ids = [r.id for r in suggestions]
    high_pos = returned_ids.index(high_count.id)
    low_pos = returned_ids.index(low_count.id)

    assert high_pos < low_pos, (
        f"Route with run_count=50 (pos={high_pos}) should rank before "
        f"route with run_count=1 (pos={low_pos})"
    )


@given(
    profile_id=_profile_id_st,
    target_distance=_target_distance_st,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_ranking_recency_third(
    db_session,
    profile_id: int,
    target_distance: float,
) -> None:
    """
    Property 32d (recency): Among routes with the same affinity and run_count,
    the more recently used route SHALL rank first.

    **Validates: Requirements 12.1**
    """
    _clear_routes(db_session, profile_id)
    workout = _make_workout(db_session, profile_id, target_distance, "easy")

    now = datetime.now(timezone.utc)

    older = _make_route(
        db_session, profile_id, target_distance,
        run_count=5,
        workout_type_affinity=None,
        last_used_at=now - timedelta(days=30),
    )
    newer = _make_route(
        db_session, profile_id, target_distance,
        run_count=5,
        workout_type_affinity=None,
        last_used_at=now,
    )

    suggestions = get_suggestions(workout, profile_id, db_session)

    assert len(suggestions) >= 2, "Expected at least 2 suggestions"

    returned_ids = [r.id for r in suggestions]
    newer_pos = returned_ids.index(newer.id)
    older_pos = returned_ids.index(older.id)

    assert newer_pos < older_pos, (
        f"More recent route (pos={newer_pos}) should rank before "
        f"older route (pos={older_pos})"
    )


# ---------------------------------------------------------------------------
# Boundary tests (deterministic)
# ---------------------------------------------------------------------------


def test_boundary_exactly_80_percent_is_included(db_session) -> None:
    """
    Boundary 32e: A route at exactly 80% of workout distance SHALL be included.

    **Validates: Requirements 12.1**
    """
    profile_id = 1
    target = 10000.0  # 10 km
    workout = _make_workout(db_session, profile_id, target)

    boundary_route = _make_route(db_session, profile_id, target * 0.80)  # exactly 8000 m

    suggestions = get_suggestions(workout, profile_id, db_session)

    returned_ids = {r.id for r in suggestions}
    assert boundary_route.id in returned_ids, (
        f"Route at exactly 80% ({target * 0.80:.1f} m) of target ({target:.1f} m) "
        f"should be included but was not"
    )


def test_boundary_exactly_120_percent_is_included(db_session) -> None:
    """
    Boundary 32f: A route at exactly 120% of workout distance SHALL be included.

    **Validates: Requirements 12.1**
    """
    profile_id = 1
    target = 10000.0  # 10 km
    workout = _make_workout(db_session, profile_id, target)

    boundary_route = _make_route(db_session, profile_id, target * 1.20)  # exactly 12000 m

    suggestions = get_suggestions(workout, profile_id, db_session)

    returned_ids = {r.id for r in suggestions}
    assert boundary_route.id in returned_ids, (
        f"Route at exactly 120% ({target * 1.20:.1f} m) of target ({target:.1f} m) "
        f"should be included but was not"
    )


def test_boundary_below_80_percent_is_excluded(db_session) -> None:
    """
    Boundary 32g: A route at 79.9% of workout distance SHALL NOT be included.

    **Validates: Requirements 12.1**
    """
    profile_id = 1
    target = 10000.0  # 10 km
    workout = _make_workout(db_session, profile_id, target)

    # 79.9% = 7990 m — just below the 8000 m floor
    excluded_route = _make_route(db_session, profile_id, target * 0.799)

    suggestions = get_suggestions(workout, profile_id, db_session)

    returned_ids = {r.id for r in suggestions}
    assert excluded_route.id not in returned_ids, (
        f"Route at 79.9% ({target * 0.799:.1f} m) of target ({target:.1f} m) "
        f"should be excluded but was returned"
    )


def test_boundary_above_120_percent_is_excluded(db_session) -> None:
    """
    Boundary 32h: A route at 120.1% of workout distance SHALL NOT be included.

    **Validates: Requirements 12.1**
    """
    profile_id = 1
    target = 10000.0  # 10 km
    workout = _make_workout(db_session, profile_id, target)

    # 120.1% = 12010 m — just above the 12000 m ceiling
    excluded_route = _make_route(db_session, profile_id, target * 1.201)

    suggestions = get_suggestions(workout, profile_id, db_session)

    returned_ids = {r.id for r in suggestions}
    assert excluded_route.id not in returned_ids, (
        f"Route at 120.1% ({target * 1.201:.1f} m) of target ({target:.1f} m) "
        f"should be excluded but was returned"
    )


# ---------------------------------------------------------------------------
# Additional: zero target distance returns empty list
# ---------------------------------------------------------------------------


def test_zero_target_distance_returns_empty(db_session) -> None:
    """
    Edge case: When workout has no target distance (None or 0), get_suggestions()
    SHALL return an empty list.

    **Validates: Requirements 12.1**
    """
    profile_id = 1
    workout = _make_workout(db_session, profile_id, 5000.0)
    workout.target_distance_metres = None
    db_session.flush()

    # Insert some routes that would otherwise match
    _make_route(db_session, profile_id, 5000.0)

    suggestions = get_suggestions(workout, profile_id, db_session)

    assert suggestions == [], (
        f"Expected empty list when target_distance_metres is None, got {suggestions}"
    )


# ---------------------------------------------------------------------------
# Additional: profile isolation — routes from other profiles are not returned
# ---------------------------------------------------------------------------


@given(
    target_distance=_target_distance_st,
)
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_profile_isolation(
    db_session,
    target_distance: float,
) -> None:
    """
    Profile isolation: Routes belonging to a different profile SHALL never
    appear in get_suggestions() results.

    **Validates: Requirements 12.1**
    """
    profile_id = 1
    other_profile_id = 2

    workout = _make_workout(db_session, profile_id, target_distance)

    # Insert a route for the OTHER profile at the exact target distance
    other_route = _make_route(db_session, other_profile_id, target_distance)

    suggestions = get_suggestions(workout, profile_id, db_session)

    returned_ids = {r.id for r in suggestions}
    assert other_route.id not in returned_ids, (
        f"Route from profile {other_profile_id} was returned for profile {profile_id}"
    )
