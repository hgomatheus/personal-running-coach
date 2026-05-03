"""
Property-based tests for HR zone percentage bands.

# Feature: personal-running-coach

**Validates: Requirements 10.2**
"""

from datetime import date, timedelta

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.services.zones_calculator import calculate_hr_zones, estimate_max_hr

# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

# Realistic max HR range: 100–250 bpm
_max_hr_st = st.integers(min_value=100, max_value=250)

# Age range 18–80 years (maps to valid date_of_birth values)
_age_st = st.integers(min_value=18, max_value=80)

# Biological sex values accepted by the app
_biological_sex_st = st.sampled_from(["male", "female", "other"])

# Profile IDs
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


# ---------------------------------------------------------------------------
# Property 24a: calculate_hr_zones produces 5 zones with correct percentage bands
# ---------------------------------------------------------------------------


@given(max_hr=_max_hr_st)
@settings(max_examples=100)
def test_hr_zones_percentage_bands(max_hr: int):
    """
    Property 24a: calculate_hr_zones(max_hr) SHALL produce 5 HR zones where:
      - zone1_max = round(60% of max_hr)
      - zone2_max = round(70% of max_hr)
      - zone3_max = round(80% of max_hr)
      - zone4_max = round(90% of max_hr)
      - zone5_max = 100% of max_hr

    For any max_hr in [100, 250], all five zone boundaries must equal the
    expected rounded percentage of max_hr.

    # Feature: personal-running-coach, Property 24: HR zone percentage bands
    **Validates: Requirements 10.2**
    """
    zones = calculate_hr_zones(max_hr)

    assert zones.zone1_max == round(max_hr * 0.60), (
        f"zone1_max={zones.zone1_max} != round({max_hr} * 0.60) = {round(max_hr * 0.60)}"
    )
    assert zones.zone2_max == round(max_hr * 0.70), (
        f"zone2_max={zones.zone2_max} != round({max_hr} * 0.70) = {round(max_hr * 0.70)}"
    )
    assert zones.zone3_max == round(max_hr * 0.80), (
        f"zone3_max={zones.zone3_max} != round({max_hr} * 0.80) = {round(max_hr * 0.80)}"
    )
    assert zones.zone4_max == round(max_hr * 0.90), (
        f"zone4_max={zones.zone4_max} != round({max_hr} * 0.90) = {round(max_hr * 0.90)}"
    )
    assert zones.zone5_max == max_hr, (
        f"zone5_max={zones.zone5_max} != max_hr={max_hr}"
    )


# ---------------------------------------------------------------------------
# Property 24b: HR zones are strictly increasing
# ---------------------------------------------------------------------------


@given(max_hr=_max_hr_st)
@settings(max_examples=100)
def test_hr_zones_strictly_increasing(max_hr: int):
    """
    Property 24b: For any max_hr in [100, 250], the 5 HR zone boundaries
    produced by calculate_hr_zones SHALL be strictly increasing:
      zone1_max < zone2_max < zone3_max < zone4_max < zone5_max

    # Feature: personal-running-coach, Property 24: HR zone percentage bands
    **Validates: Requirements 10.2**
    """
    zones = calculate_hr_zones(max_hr)

    assert zones.zone1_max < zones.zone2_max, (
        f"zone1_max ({zones.zone1_max}) >= zone2_max ({zones.zone2_max}) "
        f"for max_hr={max_hr}"
    )
    assert zones.zone2_max < zones.zone3_max, (
        f"zone2_max ({zones.zone2_max}) >= zone3_max ({zones.zone3_max}) "
        f"for max_hr={max_hr}"
    )
    assert zones.zone3_max < zones.zone4_max, (
        f"zone3_max ({zones.zone3_max}) >= zone4_max ({zones.zone4_max}) "
        f"for max_hr={max_hr}"
    )
    assert zones.zone4_max < zones.zone5_max, (
        f"zone4_max ({zones.zone4_max}) >= zone5_max ({zones.zone5_max}) "
        f"for max_hr={max_hr}"
    )


# ---------------------------------------------------------------------------
# Property 24c: estimate_max_hr returns a value in [150, 220] for ages 18–80
# ---------------------------------------------------------------------------


@given(
    age=_age_st,
    biological_sex=_biological_sex_st,
)
@settings(max_examples=100)
def test_estimate_max_hr_in_valid_range(age: int, biological_sex: str):
    """
    Property 24c: estimate_max_hr(age, biological_sex) SHALL return a value
    in the range [150, 220] for any valid age (18–80) and any biological sex.

    The Tanaka formula (208 - 0.7 × age) gives:
      - age 18 → 208 - 12.6 = 195.4 → round = 195
      - age 80 → 208 - 56.0 = 152.0 → round = 152

    Both endpoints are well within [150, 220].

    # Feature: personal-running-coach, Property 24: HR zone percentage bands
    **Validates: Requirements 10.2**
    """
    max_hr = estimate_max_hr(age, biological_sex)

    assert 150 <= max_hr <= 220, (
        f"estimate_max_hr(age={age}, biological_sex={biological_sex!r}) = {max_hr} "
        f"is outside the expected range [150, 220]"
    )


# ---------------------------------------------------------------------------
# Property 24d: HR zones via API recalculate endpoint have correct percentage bands
# ---------------------------------------------------------------------------


@given(
    profile_id=_profile_id_st,
    max_hr=_max_hr_st,
    race_distance=_race_distance_st,
    race_duration=_race_duration_st,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_api_recalculate_hr_zones_percentage_bands(
    client,
    db_session,
    profile_id: int,
    max_hr: int,
    race_distance: float,
    race_duration: int,
):
    """
    Property 24d: POST /api/v1/profiles/{profile_id}/zones/recalculate with a
    race result and max_hr SHALL return HR zones where each zone boundary equals
    the expected percentage of max_hr (rounded to nearest integer), and the
    zones are strictly increasing.

    # Feature: personal-running-coach, Property 24: HR zone percentage bands
    **Validates: Requirements 10.2**
    """
    payload = {
        "distance_metres": race_distance,
        "duration_seconds": race_duration,
        "max_hr": max_hr,
    }

    response = client.post(
        f"/api/v1/profiles/{profile_id}/zones/recalculate",
        json=payload,
    )

    assert response.status_code == 200, (
        f"Expected HTTP 200, got {response.status_code}: {response.text}"
    )

    body = response.json()
    assert "hr_zones" in body, f"'hr_zones' missing from response: {body}"
    hr = body["hr_zones"]
    assert hr is not None, "hr_zones should not be null when max_hr is provided"

    # Verify percentage bands
    assert hr["zone1_max"] == round(max_hr * 0.60), (
        f"zone1_max={hr['zone1_max']} != round({max_hr} * 0.60) = {round(max_hr * 0.60)}"
    )
    assert hr["zone2_max"] == round(max_hr * 0.70), (
        f"zone2_max={hr['zone2_max']} != round({max_hr} * 0.70) = {round(max_hr * 0.70)}"
    )
    assert hr["zone3_max"] == round(max_hr * 0.80), (
        f"zone3_max={hr['zone3_max']} != round({max_hr} * 0.80) = {round(max_hr * 0.80)}"
    )
    assert hr["zone4_max"] == round(max_hr * 0.90), (
        f"zone4_max={hr['zone4_max']} != round({max_hr} * 0.90) = {round(max_hr * 0.90)}"
    )
    assert hr["zone5_max"] == max_hr, (
        f"zone5_max={hr['zone5_max']} != max_hr={max_hr}"
    )

    # Verify strictly increasing
    assert hr["zone1_max"] < hr["zone2_max"], (
        f"zone1_max ({hr['zone1_max']}) >= zone2_max ({hr['zone2_max']}) "
        f"for max_hr={max_hr}"
    )
    assert hr["zone2_max"] < hr["zone3_max"], (
        f"zone2_max ({hr['zone2_max']}) >= zone3_max ({hr['zone3_max']}) "
        f"for max_hr={max_hr}"
    )
    assert hr["zone3_max"] < hr["zone4_max"], (
        f"zone3_max ({hr['zone3_max']}) >= zone4_max ({hr['zone4_max']}) "
        f"for max_hr={max_hr}"
    )
    assert hr["zone4_max"] < hr["zone5_max"], (
        f"zone4_max ({hr['zone4_max']}) >= zone5_max ({hr['zone5_max']}) "
        f"for max_hr={max_hr}"
    )
