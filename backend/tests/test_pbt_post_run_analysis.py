"""
Property-based tests for post-run pace comparison classification.

# Feature: personal-running-coach

**Validates: Requirements 18.4**

Property 29: The post-run pace comparison classification SHALL be:
  - "on_target" when actual_avg_pace_sec_per_km is within the target pace zone
    boundaries (min_sec_per_km ≤ actual ≤ max_sec_per_km)
  - "faster"    when actual_avg_pace_sec_per_km < min_sec_per_km (faster than
    the zone's fastest boundary — lower sec/km = faster pace)
  - "slower"    when actual_avg_pace_sec_per_km > max_sec_per_km (slower than
    the zone's slowest boundary)

Note: In running, lower sec/km = faster pace.
  - fast_bound (min_sec_per_km) = lower number = faster end of zone
  - slow_bound (max_sec_per_km) = higher number = slower end of zone
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.services.post_run_analyzer import _classify_pace, analyze

# ---------------------------------------------------------------------------
# Naming note
# ---------------------------------------------------------------------------
# In the PaceZones ORM model the field naming is:
#   easy_max_sec_per_km  → the FASTER bound (lower sec/km value)
#   easy_min_sec_per_km  → the SLOWER bound (higher sec/km value)
#
# get_pace_zone_bounds() maps these correctly:
#   fast_attr = "easy_max_sec_per_km"  → fast_bound (lower number)
#   slow_attr = "easy_min_sec_per_km"  → slow_bound (higher number)
#
# Classification logic in _classify_pace:
#   fast_bound <= actual <= slow_bound  → "on_target"
#   actual < fast_bound                 → "faster"
#   actual > slow_bound                 → "slower"
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Minimal mock objects
# ---------------------------------------------------------------------------


@dataclass
class _MockPaceZones:
    """
    Minimal PaceZones-like object.

    Attribute naming mirrors the ORM:
      *_max_sec_per_km = faster bound (lower number)
      *_min_sec_per_km = slower bound (higher number)
    """
    # easy zone (used as the default in tests)
    easy_max_sec_per_km: int = 300    # 5:00/km — faster end
    easy_min_sec_per_km: int = 420    # 7:00/km — slower end
    # other zones (not exercised in Property 29 tests but required by the interface)
    moderate_max_sec_per_km: int = 270
    moderate_min_sec_per_km: int = 360
    threshold_max_sec_per_km: int = 240
    threshold_min_sec_per_km: int = 300
    vo2max_max_sec_per_km: int = 210
    vo2max_min_sec_per_km: int = 270
    anaerobic_max_sec_per_km: int = 180
    anaerobic_min_sec_per_km: int = 240


@dataclass
class _MockRun:
    """Minimal Run-like object for analyze()."""
    id: int = 1
    profile_id: int = 1
    distance_metres: float = 10_000.0
    duration_seconds: int = 3600
    avg_pace_sec_per_km: float | None = None
    avg_heart_rate: int | None = None
    elevation_gain_metres: float | None = None
    raw_strava_data: dict | None = None


@dataclass
class _MockWorkout:
    """Minimal Workout-like object for analyze()."""
    id: int = 1
    profile_id: int = 1
    workout_type: str = "easy"
    target_distance_metres: float | None = 10_000.0
    target_pace_zone: str = "easy"
    target_hr_zone: int | None = None
    steps: list = None

    def __post_init__(self):
        if self.steps is None:
            self.steps = []


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

# Valid pace zone names
_pace_zone_st = st.sampled_from(["easy", "moderate", "threshold", "vo2max", "anaerobic"])

# Pace zone boundaries: fast_bound < slow_bound (both in realistic sec/km range)
# fast_bound = faster end (lower sec/km), slow_bound = slower end (higher sec/km)
# Realistic running paces: 120 sec/km (2:00/km) to 600 sec/km (10:00/km)
_fast_bound_st = st.integers(min_value=120, max_value=500)


@st.composite
def _pace_zone_bounds_st(draw):
    """Generate (fast_bound, slow_bound) where fast_bound < slow_bound."""
    fast = draw(_fast_bound_st)
    # slow_bound must be strictly greater than fast_bound
    slow = draw(st.integers(min_value=fast + 1, max_value=fast + 200))
    return fast, slow


@st.composite
def _mock_pace_zones_for_zone_st(draw, zone_name: str):
    """
    Generate a _MockPaceZones with valid bounds for the given zone_name.
    Returns (pace_zones, fast_bound, slow_bound).
    """
    fast, slow = draw(_pace_zone_bounds_st())
    pz = _MockPaceZones()
    # Set the bounds for the requested zone
    # ORM naming: *_max_sec_per_km = faster bound, *_min_sec_per_km = slower bound
    if zone_name == "easy":
        pz.easy_max_sec_per_km = fast
        pz.easy_min_sec_per_km = slow
    elif zone_name == "moderate":
        pz.moderate_max_sec_per_km = fast
        pz.moderate_min_sec_per_km = slow
    elif zone_name == "threshold":
        pz.threshold_max_sec_per_km = fast
        pz.threshold_min_sec_per_km = slow
    elif zone_name == "vo2max":
        pz.vo2max_max_sec_per_km = fast
        pz.vo2max_min_sec_per_km = slow
    elif zone_name == "anaerobic":
        pz.anaerobic_max_sec_per_km = fast
        pz.anaerobic_min_sec_per_km = slow
    return pz, fast, slow


# ---------------------------------------------------------------------------
# Property 29a: "on_target" when actual pace is within zone boundaries
# ---------------------------------------------------------------------------


@given(zone_name=_pace_zone_st)
@settings(max_examples=100)
def test_pace_comparison_on_target(zone_name: str):
    """
    Property 29a: _classify_pace SHALL return ("on_target", True) when
    actual_avg_pace_sec_per_km is within the target pace zone boundaries
    (fast_bound ≤ actual ≤ slow_bound).

    **Validates: Requirements 18.4**
    """
    # Use fixed bounds to generate an in-zone pace
    fast_bound = 300   # 5:00/km
    slow_bound = 420   # 7:00/km

    pz = _MockPaceZones()
    if zone_name == "easy":
        pz.easy_max_sec_per_km = fast_bound
        pz.easy_min_sec_per_km = slow_bound
    elif zone_name == "moderate":
        pz.moderate_max_sec_per_km = fast_bound
        pz.moderate_min_sec_per_km = slow_bound
    elif zone_name == "threshold":
        pz.threshold_max_sec_per_km = fast_bound
        pz.threshold_min_sec_per_km = slow_bound
    elif zone_name == "vo2max":
        pz.vo2max_max_sec_per_km = fast_bound
        pz.vo2max_min_sec_per_km = slow_bound
    elif zone_name == "anaerobic":
        pz.anaerobic_max_sec_per_km = fast_bound
        pz.anaerobic_min_sec_per_km = slow_bound

    # Test boundary values and midpoint
    for actual_pace in [fast_bound, slow_bound, (fast_bound + slow_bound) // 2]:
        on_target, comparison = _classify_pace(actual_pace, zone_name, pz)
        assert comparison == "on_target", (
            f"Expected 'on_target' for actual_pace={actual_pace}, "
            f"zone={zone_name!r}, fast_bound={fast_bound}, slow_bound={slow_bound}. "
            f"Got: comparison={comparison!r}"
        )
        assert on_target is True, (
            f"Expected on_target=True for actual_pace={actual_pace}, "
            f"zone={zone_name!r}. Got: on_target={on_target}"
        )


@given(
    zone_name=_pace_zone_st,
    bounds_and_pace=_pace_zone_bounds_st().flatmap(
        lambda bounds: st.tuples(
            st.just(bounds),
            st.integers(min_value=bounds[0], max_value=bounds[1]),
        )
    ),
)
@settings(max_examples=100)
def test_pace_comparison_on_target_property(
    zone_name: str,
    bounds_and_pace: tuple,
):
    """
    Property 29a (full property): For any valid pace zone boundaries
    (fast_bound, slow_bound) and any actual pace in [fast_bound, slow_bound],
    _classify_pace SHALL return "on_target".

    **Validates: Requirements 18.4**
    """
    (fast_bound, slow_bound), actual_pace = bounds_and_pace

    pz = _MockPaceZones()
    _set_zone_bounds(pz, zone_name, fast_bound, slow_bound)

    on_target, comparison = _classify_pace(actual_pace, zone_name, pz)

    assert comparison == "on_target", (
        f"Expected 'on_target' for actual_pace={actual_pace}, "
        f"zone={zone_name!r}, fast_bound={fast_bound}, slow_bound={slow_bound}. "
        f"Got: comparison={comparison!r}"
    )
    assert on_target is True, (
        f"Expected on_target=True for actual_pace={actual_pace}, "
        f"zone={zone_name!r}. Got: on_target={on_target}"
    )


# ---------------------------------------------------------------------------
# Property 29b: "faster" when actual pace < fast_bound (lower sec/km)
# ---------------------------------------------------------------------------


@given(
    zone_name=_pace_zone_st,
    bounds_and_pace=_pace_zone_bounds_st().flatmap(
        lambda bounds: st.tuples(
            st.just(bounds),
            # actual pace strictly less than fast_bound (faster than zone)
            st.integers(min_value=1, max_value=bounds[0] - 1),
        )
    ),
)
@settings(max_examples=100)
def test_pace_comparison_faster_property(
    zone_name: str,
    bounds_and_pace: tuple,
):
    """
    Property 29b: For any valid pace zone boundaries (fast_bound, slow_bound)
    and any actual pace strictly less than fast_bound, _classify_pace SHALL
    return "faster".

    In running, lower sec/km = faster pace. So actual < fast_bound means the
    runner went faster than the zone's fastest boundary.

    **Validates: Requirements 18.4**
    """
    (fast_bound, slow_bound), actual_pace = bounds_and_pace

    pz = _MockPaceZones()
    _set_zone_bounds(pz, zone_name, fast_bound, slow_bound)

    on_target, comparison = _classify_pace(actual_pace, zone_name, pz)

    assert comparison == "faster", (
        f"Expected 'faster' for actual_pace={actual_pace}, "
        f"zone={zone_name!r}, fast_bound={fast_bound}, slow_bound={slow_bound}. "
        f"Got: comparison={comparison!r}"
    )
    assert on_target is False, (
        f"Expected on_target=False for actual_pace={actual_pace} < fast_bound={fast_bound}. "
        f"Got: on_target={on_target}"
    )


# ---------------------------------------------------------------------------
# Property 29c: "slower" when actual pace > slow_bound (higher sec/km)
# ---------------------------------------------------------------------------


@given(
    zone_name=_pace_zone_st,
    bounds_and_pace=_pace_zone_bounds_st().flatmap(
        lambda bounds: st.tuples(
            st.just(bounds),
            # actual pace strictly greater than slow_bound (slower than zone)
            st.integers(min_value=bounds[1] + 1, max_value=bounds[1] + 300),
        )
    ),
)
@settings(max_examples=100)
def test_pace_comparison_slower_property(
    zone_name: str,
    bounds_and_pace: tuple,
):
    """
    Property 29c: For any valid pace zone boundaries (fast_bound, slow_bound)
    and any actual pace strictly greater than slow_bound, _classify_pace SHALL
    return "slower".

    In running, higher sec/km = slower pace. So actual > slow_bound means the
    runner went slower than the zone's slowest boundary.

    **Validates: Requirements 18.4**
    """
    (fast_bound, slow_bound), actual_pace = bounds_and_pace

    pz = _MockPaceZones()
    _set_zone_bounds(pz, zone_name, fast_bound, slow_bound)

    on_target, comparison = _classify_pace(actual_pace, zone_name, pz)

    assert comparison == "slower", (
        f"Expected 'slower' for actual_pace={actual_pace}, "
        f"zone={zone_name!r}, fast_bound={fast_bound}, slow_bound={slow_bound}. "
        f"Got: comparison={comparison!r}"
    )
    assert on_target is False, (
        f"Expected on_target=False for actual_pace={actual_pace} > slow_bound={slow_bound}. "
        f"Got: on_target={on_target}"
    )


# ---------------------------------------------------------------------------
# Property 29d: None when pace data is unavailable
# ---------------------------------------------------------------------------


@given(zone_name=_pace_zone_st)
@settings(max_examples=100)
def test_pace_comparison_none_when_no_pace(zone_name: str):
    """
    Property 29d: _classify_pace SHALL return (None, None) when
    actual_avg_pace_sec_per_km is None (pace data unavailable).

    **Validates: Requirements 18.4**
    """
    pz = _MockPaceZones()
    on_target, comparison = _classify_pace(None, zone_name, pz)

    assert on_target is None, (
        f"Expected on_target=None when actual_pace=None. Got: {on_target}"
    )
    assert comparison is None, (
        f"Expected comparison=None when actual_pace=None. Got: {comparison!r}"
    )


@given(zone_name=_pace_zone_st)
@settings(max_examples=100)
def test_pace_comparison_none_when_no_pace_zones(zone_name: str):
    """
    Property 29d (variant): _classify_pace SHALL return (None, None) when
    pace_zones is None (zones not yet calculated for the profile).

    **Validates: Requirements 18.4**
    """
    on_target, comparison = _classify_pace(300.0, zone_name, None)

    assert on_target is None, (
        f"Expected on_target=None when pace_zones=None. Got: {on_target}"
    )
    assert comparison is None, (
        f"Expected comparison=None when pace_zones=None. Got: {comparison!r}"
    )


# ---------------------------------------------------------------------------
# Property 29e: analyze() propagates pace_comparison correctly
# ---------------------------------------------------------------------------


@given(
    zone_name=_pace_zone_st,
    bounds_and_pace=_pace_zone_bounds_st().flatmap(
        lambda bounds: st.tuples(
            st.just(bounds),
            st.integers(min_value=bounds[0], max_value=bounds[1]),
        )
    ),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_analyze_pace_comparison_on_target(
    zone_name: str,
    bounds_and_pace: tuple,
):
    """
    Property 29e: analyze(run, workout, pace_zones) SHALL set
    result.pace_comparison = "on_target" when actual pace is within the
    target pace zone boundaries.

    Gemini is mocked to avoid external API calls.

    **Validates: Requirements 18.4**
    """
    (fast_bound, slow_bound), actual_pace = bounds_and_pace

    pz = _MockPaceZones()
    _set_zone_bounds(pz, zone_name, fast_bound, slow_bound)

    run = _MockRun(avg_pace_sec_per_km=float(actual_pace))
    workout = _MockWorkout(target_pace_zone=zone_name)

    with patch(
        "app.services.post_run_analyzer._get_coaching_summary",
        new=AsyncMock(return_value="Great run!"),
    ):
        result = asyncio.run(analyze(run, workout, pz))

    assert result.pace_comparison == "on_target", (
        f"Expected pace_comparison='on_target' for actual_pace={actual_pace}, "
        f"zone={zone_name!r}, fast_bound={fast_bound}, slow_bound={slow_bound}. "
        f"Got: {result.pace_comparison!r}"
    )
    assert result.pace_on_target is True, (
        f"Expected pace_on_target=True. Got: {result.pace_on_target}"
    )


@given(
    zone_name=_pace_zone_st,
    bounds_and_pace=_pace_zone_bounds_st().flatmap(
        lambda bounds: st.tuples(
            st.just(bounds),
            st.integers(min_value=1, max_value=bounds[0] - 1),
        )
    ),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_analyze_pace_comparison_faster(
    zone_name: str,
    bounds_and_pace: tuple,
):
    """
    Property 29f: analyze(run, workout, pace_zones) SHALL set
    result.pace_comparison = "faster" when actual pace < fast_bound.

    **Validates: Requirements 18.4**
    """
    (fast_bound, slow_bound), actual_pace = bounds_and_pace

    pz = _MockPaceZones()
    _set_zone_bounds(pz, zone_name, fast_bound, slow_bound)

    run = _MockRun(avg_pace_sec_per_km=float(actual_pace))
    workout = _MockWorkout(target_pace_zone=zone_name)

    with patch(
        "app.services.post_run_analyzer._get_coaching_summary",
        new=AsyncMock(return_value="You ran fast!"),
    ):
        result = asyncio.run(analyze(run, workout, pz))

    assert result.pace_comparison == "faster", (
        f"Expected pace_comparison='faster' for actual_pace={actual_pace}, "
        f"zone={zone_name!r}, fast_bound={fast_bound}. "
        f"Got: {result.pace_comparison!r}"
    )
    assert result.pace_on_target is False, (
        f"Expected pace_on_target=False. Got: {result.pace_on_target}"
    )


@given(
    zone_name=_pace_zone_st,
    bounds_and_pace=_pace_zone_bounds_st().flatmap(
        lambda bounds: st.tuples(
            st.just(bounds),
            st.integers(min_value=bounds[1] + 1, max_value=bounds[1] + 300),
        )
    ),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_analyze_pace_comparison_slower(
    zone_name: str,
    bounds_and_pace: tuple,
):
    """
    Property 29g: analyze(run, workout, pace_zones) SHALL set
    result.pace_comparison = "slower" when actual pace > slow_bound.

    **Validates: Requirements 18.4**
    """
    (fast_bound, slow_bound), actual_pace = bounds_and_pace

    pz = _MockPaceZones()
    _set_zone_bounds(pz, zone_name, fast_bound, slow_bound)

    run = _MockRun(avg_pace_sec_per_km=float(actual_pace))
    workout = _MockWorkout(target_pace_zone=zone_name)

    with patch(
        "app.services.post_run_analyzer._get_coaching_summary",
        new=AsyncMock(return_value="Take it easy next time."),
    ):
        result = asyncio.run(analyze(run, workout, pz))

    assert result.pace_comparison == "slower", (
        f"Expected pace_comparison='slower' for actual_pace={actual_pace}, "
        f"zone={zone_name!r}, slow_bound={slow_bound}. "
        f"Got: {result.pace_comparison!r}"
    )
    assert result.pace_on_target is False, (
        f"Expected pace_on_target=False. Got: {result.pace_on_target}"
    )


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _set_zone_bounds(
    pz: _MockPaceZones,
    zone_name: str,
    fast_bound: int,
    slow_bound: int,
) -> None:
    """
    Set the fast/slow bounds on a _MockPaceZones for the given zone_name.

    ORM naming convention:
      *_max_sec_per_km = faster bound (lower sec/km value)
      *_min_sec_per_km = slower bound (higher sec/km value)
    """
    if zone_name == "easy":
        pz.easy_max_sec_per_km = fast_bound
        pz.easy_min_sec_per_km = slow_bound
    elif zone_name == "moderate":
        pz.moderate_max_sec_per_km = fast_bound
        pz.moderate_min_sec_per_km = slow_bound
    elif zone_name == "threshold":
        pz.threshold_max_sec_per_km = fast_bound
        pz.threshold_min_sec_per_km = slow_bound
    elif zone_name == "vo2max":
        pz.vo2max_max_sec_per_km = fast_bound
        pz.vo2max_min_sec_per_km = slow_bound
    elif zone_name == "anaerobic":
        pz.anaerobic_max_sec_per_km = fast_bound
        pz.anaerobic_min_sec_per_km = slow_bound
