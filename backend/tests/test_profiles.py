"""
Property-based tests for the Profiles API.

# Feature: personal-running-coach, Properties 2–3: profile round-trip and validation

**Validates: Requirements 2.2, 2.4, 2.5**
"""

from datetime import date

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

# Valid display_name: 1–50 characters (printable text, no leading/trailing whitespace
# to avoid edge cases with strip behaviour in the API)
_display_name_st = st.text(
    alphabet=st.characters(
        whitelist_categories=("Lu", "Ll", "Nd"),
        whitelist_characters=" ",
    ),
    min_size=1,
    max_size=50,
).filter(lambda s: len(s.strip()) >= 1)

# Valid biological_sex values
_biological_sex_st = st.sampled_from(["male", "female", "other"])

# Valid date_of_birth: ISO date string between 1920-01-01 and 2005-12-31
_date_of_birth_st = st.dates(
    min_value=date(1920, 1, 1),
    max_value=date(2005, 12, 31),
).map(lambda d: d.isoformat())

# Profile IDs that are pre-seeded in the test database
_profile_id_st = st.sampled_from([1, 2])


@st.composite
def valid_profile_update(draw) -> dict:
    """
    Generate a valid ProfileUpdate payload:
      - display_name: 1–50 chars
      - biological_sex: one of "male", "female", "other"
      - date_of_birth: ISO date string
    """
    return {
        "display_name": draw(_display_name_st),
        "biological_sex": draw(_biological_sex_st),
        "date_of_birth": draw(_date_of_birth_st),
    }


# ---------------------------------------------------------------------------
# Property 2: Profile round-trip preserves all fields
# ---------------------------------------------------------------------------

@given(profile_id=_profile_id_st, payload=valid_profile_update())
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_profile_round_trip(client, profile_id: int, payload: dict):
    """
    Property 2: For any valid ProfileUpdate, PUT /api/v1/profiles/{profile_id}
    followed by GET /api/v1/profiles/{profile_id} SHALL return the same values
    that were PUT.

    # Feature: personal-running-coach, Property 2: Profile round-trip preserves all fields
    **Validates: Requirements 2.2, 2.4**
    """
    put_response = client.put(f"/api/v1/profiles/{profile_id}", json=payload)
    assert put_response.status_code == 200, (
        f"PUT /api/v1/profiles/{profile_id} returned {put_response.status_code}: "
        f"{put_response.text}"
    )

    get_response = client.get(f"/api/v1/profiles/{profile_id}")
    assert get_response.status_code == 200, (
        f"GET /api/v1/profiles/{profile_id} returned {get_response.status_code}: "
        f"{get_response.text}"
    )

    body = get_response.json()
    assert body["display_name"] == payload["display_name"], (
        f"display_name mismatch: PUT {payload['display_name']!r}, "
        f"GET {body['display_name']!r}"
    )
    assert body["biological_sex"] == payload["biological_sex"], (
        f"biological_sex mismatch: PUT {payload['biological_sex']!r}, "
        f"GET {body['biological_sex']!r}"
    )
    assert body["date_of_birth"] == payload["date_of_birth"], (
        f"date_of_birth mismatch: PUT {payload['date_of_birth']!r}, "
        f"GET {body['date_of_birth']!r}"
    )


# ---------------------------------------------------------------------------
# Property 3: Profile validation rejects empty display_name with HTTP 422
# ---------------------------------------------------------------------------

@given(profile_id=_profile_id_st)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_profile_validation_rejects_empty_display_name(client, profile_id: int):
    """
    Property 3: PUT /api/v1/profiles/{profile_id} with an empty display_name
    (length 0) SHALL return HTTP 422 (validation error).

    # Feature: personal-running-coach, Property 3: Profile validation rejects incomplete submissions
    **Validates: Requirements 2.5**
    """
    payload = {
        "display_name": "",
        "biological_sex": "male",
        "date_of_birth": "1990-01-01",
    }
    response = client.put(f"/api/v1/profiles/{profile_id}", json=payload)
    assert response.status_code == 422, (
        f"Expected 422 for empty display_name on profile {profile_id}, "
        f"got {response.status_code}: {response.text}"
    )
