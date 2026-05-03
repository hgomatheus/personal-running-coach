"""
Property-based tests for run history ordering, metric fields, and aggregation totals.

# Feature: personal-running-coach

**Validates: Requirements 8.1, 8.2, 8.3, 8.4**
"""

import math
from datetime import date, timedelta

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.models.orm import Run

# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

_profile_id_st = st.sampled_from([1, 2])

# Dates spread across a realistic range to exercise multi-week / multi-month grouping
_run_date_st = st.dates(
    min_value=date(2022, 1, 1),
    max_value=date(2025, 12, 31),
)

# Valid distances: 100 m to 100 km (in metres)
_distance_st = st.floats(
    min_value=100.0,
    max_value=100_000.0,
    allow_nan=False,
    allow_infinity=False,
).filter(lambda x: x > 0.0 and math.isfinite(x))

# Valid durations: 1 minute to 12 hours (in seconds)
_duration_st = st.integers(min_value=60, max_value=43_200)

# Optional heart rate: 30–250 bpm or None
_hr_st = st.one_of(st.none(), st.integers(min_value=30, max_value=250))

# Optional elevation: 0–5000 m or None
_elevation_st = st.one_of(st.none(), st.floats(min_value=0.0, max_value=5000.0, allow_nan=False, allow_infinity=False))

# A single run record as a dict
_run_record_st = st.fixed_dictionaries(
    {
        "date": _run_date_st,
        "distance_metres": _distance_st,
        "duration_seconds": _duration_st,
        "avg_heart_rate": _hr_st,
        "elevation_gain_metres": _elevation_st,
    }
)

# A non-empty list of run records (1–20 runs)
_run_list_st = st.lists(_run_record_st, min_size=1, max_size=20)


# ---------------------------------------------------------------------------
# Helper: insert runs directly into the DB via ORM
# ---------------------------------------------------------------------------

def _insert_runs(db_session, profile_id: int, run_records: list[dict]) -> list[Run]:
    """Insert run records directly into the DB and return the ORM objects."""
    inserted = []
    for rec in run_records:
        distance = rec["distance_metres"]
        duration = rec["duration_seconds"]
        avg_pace = duration / (distance / 1000)
        run = Run(
            profile_id=profile_id,
            source="manual",
            date=rec["date"],
            distance_metres=distance,
            duration_seconds=duration,
            avg_pace_sec_per_km=avg_pace,
            avg_heart_rate=rec.get("avg_heart_rate"),
            elevation_gain_metres=rec.get("elevation_gain_metres"),
        )
        db_session.add(run)
    db_session.flush()
    db_session.refresh
    # Collect inserted runs
    for run in db_session.new:
        inserted.append(run)
    db_session.commit()
    return inserted


# ---------------------------------------------------------------------------
# Property 18: Run history is returned in chronological order (ascending by date)
# ---------------------------------------------------------------------------


@given(
    profile_id=_profile_id_st,
    run_records=_run_list_st,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_run_history_sorted_ascending_by_date(
    client,
    db_session,
    profile_id: int,
    run_records: list[dict],
):
    """
    Property 18: GET /api/v1/profiles/{profile_id}/runs SHALL return runs sorted
    by date ascending (chronological order). For any set of runs inserted with
    arbitrary dates, the response list must be sorted ascending by date.

    # Feature: personal-running-coach, Property 18: run history ordering
    **Validates: Requirements 8.1**
    """
    # Insert runs directly via ORM
    for rec in run_records:
        distance = rec["distance_metres"]
        duration = rec["duration_seconds"]
        avg_pace = duration / (distance / 1000)
        run = Run(
            profile_id=profile_id,
            source="manual",
            date=rec["date"],
            distance_metres=distance,
            duration_seconds=duration,
            avg_pace_sec_per_km=avg_pace,
            avg_heart_rate=rec.get("avg_heart_rate"),
            elevation_gain_metres=rec.get("elevation_gain_metres"),
        )
        db_session.add(run)
    db_session.commit()

    response = client.get(f"/api/v1/profiles/{profile_id}/runs")

    assert response.status_code == 200, (
        f"Expected HTTP 200, got {response.status_code}: {response.text}"
    )

    body = response.json()
    assert isinstance(body, list), f"Expected list response, got {type(body)}"

    # The response must contain at least the runs we inserted
    assert len(body) >= len(run_records), (
        f"Expected at least {len(run_records)} runs in response, got {len(body)}"
    )

    # Verify ascending date order
    dates = [item["date"] for item in body]
    assert dates == sorted(dates), (
        f"Run history is not sorted ascending by date. Got dates: {dates}"
    )


# ---------------------------------------------------------------------------
# Property 19: Run API response contains all required metric fields
# ---------------------------------------------------------------------------

# Required fields that must always be present (non-null)
_REQUIRED_FIELDS = {"id", "date", "distance_metres", "duration_seconds"}

# Optional fields that must be present as keys (may be null)
_OPTIONAL_FIELDS = {"avg_pace_sec_per_km", "avg_heart_rate", "elevation_gain_metres"}


@given(
    profile_id=_profile_id_st,
    run_records=_run_list_st,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_run_response_contains_required_metric_fields(
    client,
    db_session,
    profile_id: int,
    run_records: list[dict],
):
    """
    Property 19: Every run returned by GET /api/v1/profiles/{profile_id}/runs
    SHALL include the required metric fields: id, date, distance_metres,
    duration_seconds. Optional fields (avg_pace_sec_per_km, avg_heart_rate,
    elevation_gain_metres) may be null but must be present as keys in the response.

    # Feature: personal-running-coach, Property 19: run metric fields
    **Validates: Requirements 8.2**
    """
    # Insert runs directly via ORM
    for rec in run_records:
        distance = rec["distance_metres"]
        duration = rec["duration_seconds"]
        avg_pace = duration / (distance / 1000)
        run = Run(
            profile_id=profile_id,
            source="manual",
            date=rec["date"],
            distance_metres=distance,
            duration_seconds=duration,
            avg_pace_sec_per_km=avg_pace,
            avg_heart_rate=rec.get("avg_heart_rate"),
            elevation_gain_metres=rec.get("elevation_gain_metres"),
        )
        db_session.add(run)
    db_session.commit()

    response = client.get(f"/api/v1/profiles/{profile_id}/runs")

    assert response.status_code == 200, (
        f"Expected HTTP 200, got {response.status_code}: {response.text}"
    )

    body = response.json()
    assert isinstance(body, list)

    for run_item in body:
        # Required fields must be present and non-null
        for field in _REQUIRED_FIELDS:
            assert field in run_item, (
                f"Required field '{field}' missing from run response: {run_item}"
            )
            assert run_item[field] is not None, (
                f"Required field '{field}' is null in run response: {run_item}"
            )

        # Optional fields must be present as keys (value may be null)
        for field in _OPTIONAL_FIELDS:
            assert field in run_item, (
                f"Optional field '{field}' missing from run response keys: {run_item}"
            )

        # Validate types of required fields
        assert isinstance(run_item["id"], int), (
            f"'id' should be int, got {type(run_item['id'])}: {run_item['id']}"
        )
        assert isinstance(run_item["date"], str), (
            f"'date' should be a string (ISO date), got {type(run_item['date'])}"
        )
        assert isinstance(run_item["distance_metres"], (int, float)), (
            f"'distance_metres' should be numeric, got {type(run_item['distance_metres'])}"
        )
        assert isinstance(run_item["duration_seconds"], int), (
            f"'duration_seconds' should be int, got {type(run_item['duration_seconds'])}"
        )

        # avg_pace_sec_per_km must be non-null (computed from distance/duration)
        assert run_item["avg_pace_sec_per_km"] is not None, (
            f"'avg_pace_sec_per_km' should be computed and non-null for run: {run_item}"
        )


# ---------------------------------------------------------------------------
# Property 20: Weekly aggregation totals equal the sum of constituent runs
# ---------------------------------------------------------------------------


def _week_start(d: date) -> date:
    """Return the Monday of the ISO week containing date d."""
    return d - timedelta(days=d.weekday())


@given(
    profile_id=_profile_id_st,
    run_records=_run_list_st,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_weekly_stats_totals_equal_sum_of_runs(
    client,
    db_session,
    profile_id: int,
    run_records: list[dict],
):
    """
    Property 20: GET /api/v1/profiles/{profile_id}/stats/weekly SHALL return
    weekly totals where the sum of all weekly total_km values (converted to metres)
    equals the total distance of all runs for that profile.

    Additionally, each week's total_km must equal the sum of distance_metres for
    all runs whose date falls within that calendar week (Monday–Sunday).

    # Feature: personal-running-coach, Property 20: aggregation totals
    **Validates: Requirements 8.3, 8.4**
    """
    # Insert runs directly via ORM
    for rec in run_records:
        distance = rec["distance_metres"]
        duration = rec["duration_seconds"]
        avg_pace = duration / (distance / 1000)
        run = Run(
            profile_id=profile_id,
            source="manual",
            date=rec["date"],
            distance_metres=distance,
            duration_seconds=duration,
            avg_pace_sec_per_km=avg_pace,
            avg_heart_rate=rec.get("avg_heart_rate"),
            elevation_gain_metres=rec.get("elevation_gain_metres"),
        )
        db_session.add(run)
    db_session.commit()

    # Compute expected weekly totals from the inserted data
    # (Note: db_session may have runs from other tests in the same transaction,
    #  so we query the API and compare against what we inserted)
    expected_week_totals: dict[date, float] = {}
    for rec in run_records:
        ws = _week_start(rec["date"])
        expected_week_totals[ws] = expected_week_totals.get(ws, 0.0) + rec["distance_metres"]

    # Call the weekly stats API
    response = client.get(f"/api/v1/profiles/{profile_id}/stats/weekly")

    assert response.status_code == 200, (
        f"Expected HTTP 200, got {response.status_code}: {response.text}"
    )

    body = response.json()
    assert isinstance(body, list), f"Expected list response, got {type(body)}"

    # Build a map of week_start -> total_km from the API response
    api_week_map: dict[date, float] = {}
    for week_item in body:
        assert "week_start" in week_item, f"'week_start' missing from weekly stats item: {week_item}"
        assert "total_km" in week_item, f"'total_km' missing from weekly stats item: {week_item}"
        ws = date.fromisoformat(week_item["week_start"])
        api_week_map[ws] = week_item["total_km"]

    # Verify: for each week we inserted runs into, the API total_km must be ≥
    # the sum of our inserted runs (there may be other runs from other tests).
    # We verify the sum of all weekly totals equals the total distance of all runs
    # returned by the runs endpoint.
    runs_response = client.get(f"/api/v1/profiles/{profile_id}/runs")
    assert runs_response.status_code == 200
    all_runs = runs_response.json()

    # Compute expected weekly totals from all runs returned by the API
    all_runs_week_totals: dict[date, float] = {}
    for run_item in all_runs:
        run_date = date.fromisoformat(run_item["date"])
        ws = _week_start(run_date)
        all_runs_week_totals[ws] = (
            all_runs_week_totals.get(ws, 0.0) + run_item["distance_metres"]
        )

    # The API weekly stats must cover all weeks present in the runs.
    # The endpoint rounds each week's total to 2 decimal places.
    # We compare the API value against the same rounded computation.
    for ws, expected_metres in all_runs_week_totals.items():
        assert ws in api_week_map, (
            f"Week starting {ws} has runs but is missing from weekly stats response"
        )
        # Apply the same rounding the API applies: round(total_metres / 1000, 2)
        expected_km_rounded = round(expected_metres / 1000, 2)
        actual_km = api_week_map[ws]
        # Allow tiny floating-point tolerance for the rounded comparison
        assert abs(actual_km - expected_km_rounded) < 1e-9, (
            f"Weekly total mismatch for week {ws}: "
            f"expected {expected_km_rounded} km (rounded from {expected_metres:.3f} m), "
            f"got {actual_km} km from API"
        )

    # The sum of all weekly totals must equal the total distance of all runs.
    # Since each week's total is rounded to 2 decimal places, we allow up to
    # 0.005 km rounding error per week in the aggregate.
    num_weeks = len(api_week_map)
    total_km_from_weekly = sum(api_week_map.values())
    total_km_from_runs = sum(r["distance_metres"] for r in all_runs) / 1000
    # Maximum rounding error: 0.005 km per week (half of the last decimal place)
    max_allowed_error = max(0.01, num_weeks * 0.005)
    assert abs(total_km_from_weekly - total_km_from_runs) <= max_allowed_error, (
        f"Sum of weekly totals ({total_km_from_weekly:.3f} km) does not equal "
        f"total distance from runs ({total_km_from_runs:.3f} km) "
        f"(allowed error: {max_allowed_error:.3f} km for {num_weeks} weeks)"
    )
