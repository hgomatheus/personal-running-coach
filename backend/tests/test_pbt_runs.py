"""
Property-based tests for the manual run entry endpoint.

# Feature: personal-running-coach, Property 17: manual run validation (non-positive distance/duration)

**Validates: Requirements 7.1, 7.2**
"""

from datetime import date

import math

from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

_profile_id_st = st.sampled_from([1, 2])

# Non-positive distances: floats ≤ 0 (including 0.0, negatives, -inf)
_non_positive_distance_st = st.one_of(
    st.floats(max_value=0.0, allow_nan=False, allow_infinity=False),
    st.just(0.0),
    st.floats(max_value=-0.001, allow_nan=False, allow_infinity=False),
)

# Non-positive durations: integers ≤ 0
_non_positive_duration_st = st.integers(max_value=0)

# Valid distances: positive floats in a realistic range (0.001m to 200,000m)
_valid_distance_st = st.floats(
    min_value=0.001,
    max_value=200_000.0,
    allow_nan=False,
    allow_infinity=False,
).filter(lambda x: x > 0.0 and math.isfinite(x))

# Valid durations: positive integers (1 second to 24 hours)
_valid_duration_st = st.integers(min_value=1, max_value=86_400)

# A fixed valid date for all tests
_valid_date_st = st.dates(
    min_value=date(2020, 1, 1),
    max_value=date(2030, 12, 31),
).map(lambda d: d.isoformat())


# ---------------------------------------------------------------------------
# Property 17a: Non-positive distance is rejected with HTTP 422
# ---------------------------------------------------------------------------


@given(
    profile_id=_profile_id_st,
    distance=_non_positive_distance_st,
    duration=_valid_duration_st,
    run_date=_valid_date_st,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_non_positive_distance_rejected_with_422(
    client,
    profile_id: int,
    distance: float,
    duration: int,
    run_date: str,
):
    """
    Property 17a: For any manual run submission where distance_metres ≤ 0,
    POST /api/v1/profiles/{profile_id}/runs SHALL return HTTP 422.

    # Feature: personal-running-coach, Property 17: manual run validation
    **Validates: Requirements 7.2, 7.3**
    """
    assume(math.isfinite(distance))

    payload = {
        "date": run_date,
        "distance_metres": distance,
        "duration_seconds": duration,
    }

    response = client.post(f"/api/v1/profiles/{profile_id}/runs", json=payload)

    assert response.status_code == 422, (
        f"Expected HTTP 422 for non-positive distance_metres={distance} "
        f"(profile_id={profile_id}, duration_seconds={duration}), "
        f"got {response.status_code}: {response.text}"
    )


# ---------------------------------------------------------------------------
# Property 17b: Non-positive duration is rejected with HTTP 422
# ---------------------------------------------------------------------------


@given(
    profile_id=_profile_id_st,
    distance=_valid_distance_st,
    duration=_non_positive_duration_st,
    run_date=_valid_date_st,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_non_positive_duration_rejected_with_422(
    client,
    profile_id: int,
    distance: float,
    duration: int,
    run_date: str,
):
    """
    Property 17b: For any manual run submission where duration_seconds ≤ 0,
    POST /api/v1/profiles/{profile_id}/runs SHALL return HTTP 422.

    # Feature: personal-running-coach, Property 17: manual run validation
    **Validates: Requirements 7.2, 7.3**
    """
    payload = {
        "date": run_date,
        "distance_metres": distance,
        "duration_seconds": duration,
    }

    response = client.post(f"/api/v1/profiles/{profile_id}/runs", json=payload)

    assert response.status_code == 422, (
        f"Expected HTTP 422 for non-positive duration_seconds={duration} "
        f"(profile_id={profile_id}, distance_metres={distance}), "
        f"got {response.status_code}: {response.text}"
    )


# ---------------------------------------------------------------------------
# Property 17c: Valid distance and duration are accepted with HTTP 201
# ---------------------------------------------------------------------------


@given(
    profile_id=_profile_id_st,
    distance=_valid_distance_st,
    duration=_valid_duration_st,
    run_date=_valid_date_st,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_valid_distance_and_duration_accepted_with_201(
    client,
    db_session,
    profile_id: int,
    distance: float,
    duration: int,
    run_date: str,
):
    """
    Property 17c: For any manual run submission where distance_metres > 0 AND
    duration_seconds > 0, POST /api/v1/profiles/{profile_id}/runs SHALL return
    HTTP 201 (created successfully).

    # Feature: personal-running-coach, Property 17: manual run validation
    **Validates: Requirements 7.1, 7.2**
    """
    payload = {
        "date": run_date,
        "distance_metres": distance,
        "duration_seconds": duration,
    }

    response = client.post(f"/api/v1/profiles/{profile_id}/runs", json=payload)

    assert response.status_code == 201, (
        f"Expected HTTP 201 for valid distance_metres={distance} and "
        f"duration_seconds={duration} (profile_id={profile_id}), "
        f"got {response.status_code}: {response.text}"
    )

    body = response.json()
    assert body["distance_metres"] == distance, (
        f"Returned distance_metres {body['distance_metres']} != submitted {distance}"
    )
    assert body["duration_seconds"] == duration, (
        f"Returned duration_seconds {body['duration_seconds']} != submitted {duration}"
    )
