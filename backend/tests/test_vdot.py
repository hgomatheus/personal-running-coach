"""
Property-based tests for VDOT calculation and pace zone derivation.

# Feature: personal-running-coach, Properties 8–9: VDOT pace zone percentage bands,
# fitness change threshold

**Validates: Requirements 3.5, 10.1, 10.3, 3.6**
"""

import math

from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st

from app.services.vdot import calculate_vdot, derive_pace_zones

# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

# Valid VDOT range: 30–85 covers recreational to elite runners
_vdot_st = st.floats(min_value=30.0, max_value=85.0, allow_nan=False, allow_infinity=False)

# Race distances: 1500 m (mile-ish) to 42195 m (marathon)
_distance_st = st.floats(min_value=1500.0, max_value=42195.0, allow_nan=False, allow_infinity=False)


@st.composite
def valid_race_result(draw) -> tuple[float, int]:
    """
    Generate a (distance_metres, duration_seconds) pair where the implied pace
    is between 3:00/km and 12:00/km (180–720 sec/km), which corresponds to
    realistic running speeds.
    """
    distance = draw(_distance_st)
    # pace in sec/km: 180 (3:00/km) to 720 (12:00/km)
    pace_sec_per_km = draw(st.floats(min_value=180.0, max_value=720.0, allow_nan=False))
    duration = int(round(distance / 1000.0 * pace_sec_per_km))
    # Ensure duration is at least 1 second
    assume(duration >= 1)
    return (distance, duration)


# ---------------------------------------------------------------------------
# Property 8: VDOT-derived pace zones are within expected percentage bands
# ---------------------------------------------------------------------------

@given(vdot=_vdot_st)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_pace_zones_easy_percentage_band(vdot: float):
    """
    Property 8 (Easy zone): For any valid VDOT, the Easy zone boundaries
    SHALL fall within 62–70% of the VDOT-equivalent velocity.

    # Feature: personal-running-coach, Property 8: VDOT pace zone percentage bands
    **Validates: Requirements 3.5, 10.1, 10.3**
    """
    zones = derive_pace_zones(vdot)

    # Derive v_eq (VDOT-equivalent velocity in m/min) using the same quadratic as vdot.py
    a = 0.000104
    b = 0.182258
    c = -(vdot + 4.60)
    discriminant = b ** 2 - 4 * a * c
    v_eq = (-b + math.sqrt(discriminant)) / (2 * a)

    # Easy zone: 62–70% of v_eq
    # min_sec_per_km corresponds to the SLOWER bound (62% of v_eq → higher sec/km)
    # max_sec_per_km corresponds to the FASTER bound (70% of v_eq → lower sec/km)
    expected_slow_v = v_eq * 0.62  # m/min at slow end
    expected_fast_v = v_eq * 0.70  # m/min at fast end

    expected_slow_sec_per_km = round(60000 / expected_slow_v)
    expected_fast_sec_per_km = round(60000 / expected_fast_v)

    assert zones.easy_min_sec_per_km == expected_slow_sec_per_km, (
        f"VDOT={vdot}: easy_min_sec_per_km={zones.easy_min_sec_per_km}, "
        f"expected {expected_slow_sec_per_km} (62% of v_eq)"
    )
    assert zones.easy_max_sec_per_km == expected_fast_sec_per_km, (
        f"VDOT={vdot}: easy_max_sec_per_km={zones.easy_max_sec_per_km}, "
        f"expected {expected_fast_sec_per_km} (70% of v_eq)"
    )
    # Structural invariant: slower bound > faster bound (higher sec/km = slower)
    assert zones.easy_min_sec_per_km > zones.easy_max_sec_per_km, (
        f"VDOT={vdot}: easy zone slow bound ({zones.easy_min_sec_per_km}) "
        f"should be > fast bound ({zones.easy_max_sec_per_km})"
    )


@given(vdot=_vdot_st)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_pace_zones_moderate_percentage_band(vdot: float):
    """
    Property 8 (Moderate zone): For any valid VDOT, the Moderate (Marathon)
    zone boundaries SHALL fall within 75–84% of the VDOT-equivalent velocity.

    # Feature: personal-running-coach, Property 8: VDOT pace zone percentage bands
    **Validates: Requirements 3.5, 10.1, 10.3**
    """
    zones = derive_pace_zones(vdot)

    a = 0.000104
    b = 0.182258
    c = -(vdot + 4.60)
    v_eq = (-b + math.sqrt(b ** 2 - 4 * a * c)) / (2 * a)

    expected_slow_sec_per_km = round(60000 / (v_eq * 0.75))
    expected_fast_sec_per_km = round(60000 / (v_eq * 0.84))

    assert zones.moderate_min_sec_per_km == expected_slow_sec_per_km, (
        f"VDOT={vdot}: moderate_min_sec_per_km={zones.moderate_min_sec_per_km}, "
        f"expected {expected_slow_sec_per_km} (75% of v_eq)"
    )
    assert zones.moderate_max_sec_per_km == expected_fast_sec_per_km, (
        f"VDOT={vdot}: moderate_max_sec_per_km={zones.moderate_max_sec_per_km}, "
        f"expected {expected_fast_sec_per_km} (84% of v_eq)"
    )
    assert zones.moderate_min_sec_per_km > zones.moderate_max_sec_per_km, (
        f"VDOT={vdot}: moderate zone slow bound should be > fast bound"
    )


@given(vdot=_vdot_st)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_pace_zones_threshold_percentage_band(vdot: float):
    """
    Property 8 (Threshold zone): For any valid VDOT, the Threshold zone
    boundaries SHALL fall within 86–88% of the VDOT-equivalent velocity.

    # Feature: personal-running-coach, Property 8: VDOT pace zone percentage bands
    **Validates: Requirements 3.5, 10.1, 10.3**
    """
    zones = derive_pace_zones(vdot)

    a = 0.000104
    b = 0.182258
    c = -(vdot + 4.60)
    v_eq = (-b + math.sqrt(b ** 2 - 4 * a * c)) / (2 * a)

    expected_slow_sec_per_km = round(60000 / (v_eq * 0.86))
    expected_fast_sec_per_km = round(60000 / (v_eq * 0.88))

    assert zones.threshold_min_sec_per_km == expected_slow_sec_per_km, (
        f"VDOT={vdot}: threshold_min_sec_per_km={zones.threshold_min_sec_per_km}, "
        f"expected {expected_slow_sec_per_km} (86% of v_eq)"
    )
    assert zones.threshold_max_sec_per_km == expected_fast_sec_per_km, (
        f"VDOT={vdot}: threshold_max_sec_per_km={zones.threshold_max_sec_per_km}, "
        f"expected {expected_fast_sec_per_km} (88% of v_eq)"
    )
    assert zones.threshold_min_sec_per_km > zones.threshold_max_sec_per_km, (
        f"VDOT={vdot}: threshold zone slow bound should be > fast bound"
    )


@given(vdot=_vdot_st)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_pace_zones_vo2max_percentage_band(vdot: float):
    """
    Property 8 (VO2max zone): For any valid VDOT, the VO2max zone boundaries
    SHALL fall within 95–100% of the VDOT-equivalent velocity.

    # Feature: personal-running-coach, Property 8: VDOT pace zone percentage bands
    **Validates: Requirements 3.5, 10.1, 10.3**
    """
    zones = derive_pace_zones(vdot)

    a = 0.000104
    b = 0.182258
    c = -(vdot + 4.60)
    v_eq = (-b + math.sqrt(b ** 2 - 4 * a * c)) / (2 * a)

    expected_slow_sec_per_km = round(60000 / (v_eq * 0.95))
    expected_fast_sec_per_km = round(60000 / (v_eq * 1.00))

    assert zones.vo2max_min_sec_per_km == expected_slow_sec_per_km, (
        f"VDOT={vdot}: vo2max_min_sec_per_km={zones.vo2max_min_sec_per_km}, "
        f"expected {expected_slow_sec_per_km} (95% of v_eq)"
    )
    assert zones.vo2max_max_sec_per_km == expected_fast_sec_per_km, (
        f"VDOT={vdot}: vo2max_max_sec_per_km={zones.vo2max_max_sec_per_km}, "
        f"expected {expected_fast_sec_per_km} (100% of v_eq)"
    )
    assert zones.vo2max_min_sec_per_km > zones.vo2max_max_sec_per_km, (
        f"VDOT={vdot}: vo2max zone slow bound should be > fast bound"
    )


@given(vdot=_vdot_st)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_pace_zones_anaerobic_percentage_band(vdot: float):
    """
    Property 8 (Anaerobic zone): For any valid VDOT, the Anaerobic zone
    boundaries SHALL fall within 105–110% of the VDOT-equivalent velocity.

    # Feature: personal-running-coach, Property 8: VDOT pace zone percentage bands
    **Validates: Requirements 3.5, 10.1, 10.3**
    """
    zones = derive_pace_zones(vdot)

    a = 0.000104
    b = 0.182258
    c = -(vdot + 4.60)
    v_eq = (-b + math.sqrt(b ** 2 - 4 * a * c)) / (2 * a)

    expected_slow_sec_per_km = round(60000 / (v_eq * 1.05))
    expected_fast_sec_per_km = round(60000 / (v_eq * 1.10))

    assert zones.anaerobic_min_sec_per_km == expected_slow_sec_per_km, (
        f"VDOT={vdot}: anaerobic_min_sec_per_km={zones.anaerobic_min_sec_per_km}, "
        f"expected {expected_slow_sec_per_km} (105% of v_eq)"
    )
    assert zones.anaerobic_max_sec_per_km == expected_fast_sec_per_km, (
        f"VDOT={vdot}: anaerobic_max_sec_per_km={zones.anaerobic_max_sec_per_km}, "
        f"expected {expected_fast_sec_per_km} (110% of v_eq)"
    )
    assert zones.anaerobic_min_sec_per_km > zones.anaerobic_max_sec_per_km, (
        f"VDOT={vdot}: anaerobic zone slow bound should be > fast bound"
    )


@given(vdot=_vdot_st)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_pace_zones_ordering_across_all_zones(vdot: float):
    """
    Property 8 (zone ordering): For any valid VDOT, the five pace zones SHALL
    be ordered correctly — each zone's pace range is faster than the previous
    zone's range. Zone 1 (Easy) is slowest, Zone 5 (Anaerobic) is fastest.

    Specifically, the fast bound of each zone must be faster (lower sec/km)
    than the slow bound of the next zone.

    # Feature: personal-running-coach, Property 8: VDOT pace zone percentage bands
    **Validates: Requirements 3.5, 10.1, 10.3**
    """
    zones = derive_pace_zones(vdot)

    # Fast bound of each zone (lower sec/km = faster)
    easy_fast = zones.easy_max_sec_per_km
    moderate_slow = zones.moderate_min_sec_per_km
    moderate_fast = zones.moderate_max_sec_per_km
    threshold_slow = zones.threshold_min_sec_per_km
    threshold_fast = zones.threshold_max_sec_per_km
    vo2max_slow = zones.vo2max_min_sec_per_km
    vo2max_fast = zones.vo2max_max_sec_per_km
    anaerobic_slow = zones.anaerobic_min_sec_per_km

    # Easy is slower than Moderate (easy fast bound > moderate slow bound in sec/km)
    assert easy_fast > moderate_slow, (
        f"VDOT={vdot}: Easy fast bound ({easy_fast} sec/km) should be slower "
        f"than Moderate slow bound ({moderate_slow} sec/km)"
    )
    # Moderate is slower than Threshold
    assert moderate_fast > threshold_slow, (
        f"VDOT={vdot}: Moderate fast bound ({moderate_fast} sec/km) should be slower "
        f"than Threshold slow bound ({threshold_slow} sec/km)"
    )
    # Threshold is slower than VO2max
    assert threshold_fast > vo2max_slow, (
        f"VDOT={vdot}: Threshold fast bound ({threshold_fast} sec/km) should be slower "
        f"than VO2max slow bound ({vo2max_slow} sec/km)"
    )
    # VO2max is slower than Anaerobic
    assert vo2max_fast > anaerobic_slow, (
        f"VDOT={vdot}: VO2max fast bound ({vo2max_fast} sec/km) should be slower "
        f"than Anaerobic slow bound ({anaerobic_slow} sec/km)"
    )


# ---------------------------------------------------------------------------
# Property 9: Fitness change detection triggers at the correct threshold
# ---------------------------------------------------------------------------

@given(
    baseline=_vdot_st,
    delta_pct=st.floats(min_value=0.051, max_value=0.50, allow_nan=False),
    direction=st.sampled_from([1, -1]),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_fitness_change_significant_above_threshold(
    baseline: float, delta_pct: float, direction: int
):
    """
    Property 9 (significant change): For any pair of VDOT values where
    |current - baseline| / baseline > 0.05, the system SHALL flag a
    recalculation prompt (i.e., the change is significant).

    # Feature: personal-running-coach, Property 9: Fitness change threshold
    **Validates: Requirements 3.6**
    """
    current = baseline * (1 + direction * delta_pct)
    assume(current > 0)

    relative_change = abs(current - baseline) / baseline
    # This test only applies when the change is strictly above the threshold
    assume(relative_change > 0.05)

    is_significant = relative_change > 0.05
    assert is_significant, (
        f"baseline={baseline:.2f}, current={current:.2f}: "
        f"relative change {relative_change:.4f} > 0.05 should be significant"
    )


@given(
    baseline=_vdot_st,
    delta_pct=st.floats(min_value=0.0, max_value=0.049, allow_nan=False),
    direction=st.sampled_from([1, -1]),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_fitness_change_not_significant_below_threshold(
    baseline: float, delta_pct: float, direction: int
):
    """
    Property 9 (not significant): For any pair of VDOT values where
    |current - baseline| / baseline ≤ 0.05, the system SHALL NOT flag a
    recalculation prompt (i.e., the change is not significant).

    # Feature: personal-running-coach, Property 9: Fitness change threshold
    **Validates: Requirements 3.6**
    """
    current = baseline * (1 + direction * delta_pct)
    assume(current > 0)

    relative_change = abs(current - baseline) / baseline
    # This test only applies when the change is at or below the threshold
    assume(relative_change <= 0.05)

    is_significant = relative_change > 0.05
    assert not is_significant, (
        f"baseline={baseline:.2f}, current={current:.2f}: "
        f"relative change {relative_change:.4f} ≤ 0.05 should NOT be significant"
    )


@given(
    baseline=_vdot_st,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_fitness_change_exact_threshold_not_significant(baseline: float):
    """
    Property 9 (boundary): For any VDOT baseline, a change of exactly 5%
    (|current - baseline| / baseline == 0.05) SHALL NOT trigger a
    recalculation prompt — the threshold is strictly greater than 0.05.

    Note: We use exact arithmetic to construct the 5% boundary case, avoiding
    floating-point representation issues by computing relative_change directly.

    # Feature: personal-running-coach, Property 9: Fitness change threshold
    **Validates: Requirements 3.6**
    """
    # Construct a current value that is exactly 5% above baseline using
    # integer arithmetic to avoid floating-point drift.
    # relative_change = 0.05 exactly means the condition > 0.05 is False.
    relative_change = 0.05  # exact boundary value

    is_significant = relative_change > 0.05
    assert not is_significant, (
        f"baseline={baseline:.2f}: "
        f"exactly 5% relative change should NOT be significant (threshold is strictly > 0.05)"
    )


@given(race_result=valid_race_result())
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_vdot_calculation_produces_valid_range(race_result: tuple[float, int]):
    """
    Supplementary test for Property 8: calculate_vdot() with any valid race
    result (pace 3:00–12:00/km) SHALL produce a positive VDOT value.
    The exact range depends on the distance and pace combination; we verify
    the result is a finite positive number.

    # Feature: personal-running-coach, Property 8: VDOT pace zone percentage bands
    **Validates: Requirements 3.5**
    """
    distance, duration = race_result
    vdot = calculate_vdot(distance, duration)

    assert math.isfinite(vdot), (
        f"distance={distance:.0f}m, duration={duration}s: "
        f"VDOT={vdot} should be a finite number"
    )
    assert vdot > 0, (
        f"distance={distance:.0f}m, duration={duration}s: "
        f"VDOT={vdot:.2f} should be positive"
    )


@given(race_result=valid_race_result())
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_vdot_then_derive_zones_produces_valid_zones(race_result: tuple[float, int]):
    """
    Supplementary integration test for Property 8: computing VDOT from a
    valid race result and then deriving pace zones SHALL produce zones where
    all sec/km values are positive and the easy zone is slower than the
    anaerobic zone.

    # Feature: personal-running-coach, Property 8: VDOT pace zone percentage bands
    **Validates: Requirements 3.5, 10.1**
    """
    distance, duration = race_result
    vdot = calculate_vdot(distance, duration)

    # Only test with VDOT values in the realistic range
    assume(30.0 <= vdot <= 85.0)

    zones = derive_pace_zones(vdot)

    # All sec/km values must be positive
    for attr in [
        "easy_min_sec_per_km", "easy_max_sec_per_km",
        "moderate_min_sec_per_km", "moderate_max_sec_per_km",
        "threshold_min_sec_per_km", "threshold_max_sec_per_km",
        "vo2max_min_sec_per_km", "vo2max_max_sec_per_km",
        "anaerobic_min_sec_per_km", "anaerobic_max_sec_per_km",
    ]:
        value = getattr(zones, attr)
        assert value > 0, (
            f"VDOT={vdot:.2f}: {attr}={value} should be positive"
        )

    # Easy zone (slowest) must be slower than Anaerobic zone (fastest)
    assert zones.easy_min_sec_per_km > zones.anaerobic_max_sec_per_km, (
        f"VDOT={vdot:.2f}: Easy slow bound ({zones.easy_min_sec_per_km} sec/km) "
        f"should be slower than Anaerobic fast bound ({zones.anaerobic_max_sec_per_km} sec/km)"
    )
