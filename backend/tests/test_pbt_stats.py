"""
Property-based tests for streak calculation, PR identification, and filter correctness.

# Feature: personal-running-coach

**Validates: Requirements 8.5, 8.6, 8.8**
"""

import math
from datetime import date, timedelta

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from app.models.orm import Run

# ---------------------------------------------------------------------------
# Shared Hypothesis strategies
# ---------------------------------------------------------------------------

_profile_id_st = st.sampled_from([1, 2])

# Dates spread across a realistic multi-year range
_run_date_st = st.dates(
    min_value=date(2020, 1, 1),
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

# Run type strings (valid values used in the app)
_run_type_st = st.one_of(
    st.none(),
    st.sampled_from(["easy", "tempo", "interval", "long", "race"]),
)

# A single run record as a dict
_run_record_st = st.fixed_dictionaries(
    {
        "date": _run_date_st,
        "distance_metres": _distance_st,
        "duration_seconds": _duration_st,
        "avg_heart_rate": _hr_st,
        "run_type": _run_type_st,
    }
)

# A non-empty list of run records (1–20 runs)
_run_list_st = st.lists(_run_record_st, min_size=1, max_size=20)


# ---------------------------------------------------------------------------
# Helper: insert runs directly into the DB via ORM
# ---------------------------------------------------------------------------

def _insert_runs(db_session, profile_id: int, run_records: list[dict]) -> None:
    """Insert run records directly into the DB."""
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
            run_type=rec.get("run_type"),
        )
        db_session.add(run)
    db_session.commit()


# ---------------------------------------------------------------------------
# Reference implementation for streak calculation (mirrors stats.py logic)
# ---------------------------------------------------------------------------

def _week_start(d: date) -> date:
    """Return the Monday of the ISO week containing date d."""
    return d - timedelta(days=d.weekday())


def _compute_streaks(run_dates: list[date]) -> tuple[int, int]:
    """
    Compute (current_streak, all_time_streak) from a list of run dates.

    A streak counts consecutive calendar weeks (Mon–Sun) in which at least one
    run was completed.
    """
    if not run_dates:
        return 0, 0

    active_weeks = sorted({_week_start(d) for d in run_dates})

    # All-time streak: longest consecutive sequence of weeks
    all_time = 1
    current_run = 1
    for i in range(1, len(active_weeks)):
        if active_weeks[i] - active_weeks[i - 1] == timedelta(weeks=1):
            current_run += 1
            all_time = max(all_time, current_run)
        else:
            current_run = 1

    # Current streak: consecutive weeks ending at the most recent active week
    current = 1
    for i in range(len(active_weeks) - 1, 0, -1):
        if active_weeks[i] - active_weeks[i - 1] == timedelta(weeks=1):
            current += 1
        else:
            break

    return current, all_time


# ---------------------------------------------------------------------------
# Property 21: Streak calculation is correct for any run sequence
# ---------------------------------------------------------------------------


@given(
    profile_id=_profile_id_st,
    run_records=_run_list_st,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_streak_calculation_correct_for_any_run_sequence(
    client,
    db_session,
    profile_id: int,
    run_records: list[dict],
):
    """
    Property 21: GET /api/v1/profiles/{profile_id}/stats/streak SHALL return
    the correct current and all-time streaks for any sequence of run records.

    The current streak is the number of consecutive calendar weeks ending with
    the most recent week that has at least one run.  The all-time streak is the
    maximum such consecutive sequence in the entire history.

    # Feature: personal-running-coach, Property 21: streak calculation
    **Validates: Requirements 8.5**
    """
    _insert_runs(db_session, profile_id, run_records)

    response = client.get(f"/api/v1/profiles/{profile_id}/stats/streak")

    assert response.status_code == 200, (
        f"Expected HTTP 200, got {response.status_code}: {response.text}"
    )

    body = response.json()
    assert "current_streak" in body, f"'current_streak' missing from response: {body}"
    assert "all_time_streak" in body, f"'all_time_streak' missing from response: {body}"

    # Compute expected streaks from all runs currently in the DB for this profile
    # (there may be runs from other hypothesis examples in the same transaction)
    all_runs_response = client.get(f"/api/v1/profiles/{profile_id}/runs")
    assert all_runs_response.status_code == 200
    all_run_dates = [date.fromisoformat(r["date"]) for r in all_runs_response.json()]

    expected_current, expected_all_time = _compute_streaks(all_run_dates)

    assert body["current_streak"] == expected_current, (
        f"current_streak mismatch: expected {expected_current}, "
        f"got {body['current_streak']}. "
        f"Run dates: {sorted(all_run_dates)}"
    )
    assert body["all_time_streak"] == expected_all_time, (
        f"all_time_streak mismatch: expected {expected_all_time}, "
        f"got {body['all_time_streak']}. "
        f"Run dates: {sorted(all_run_dates)}"
    )

    # Invariants that must always hold
    assert body["current_streak"] >= 1, (
        "current_streak must be at least 1 when runs exist"
    )
    assert body["all_time_streak"] >= body["current_streak"], (
        f"all_time_streak ({body['all_time_streak']}) must be >= "
        f"current_streak ({body['current_streak']})"
    )


# ---------------------------------------------------------------------------
# Property 22: Personal records are correctly identified
# ---------------------------------------------------------------------------

# PR target distances and their 5% tolerance bands (in metres)
_PR_TARGETS = {
    "1km": 1000,
    "5km": 5000,
    "10km": 10000,
    "half_marathon": 21097,
    "marathon": 42195,
}
_PR_TOLERANCE = 0.05


def _distance_near_target(target_m: float) -> st.SearchStrategy:
    """Generate distances within 5% of a PR target distance."""
    lower = target_m * (1 - _PR_TOLERANCE)
    upper = target_m * (1 + _PR_TOLERANCE)
    return st.floats(
        min_value=lower,
        max_value=upper,
        allow_nan=False,
        allow_infinity=False,
    ).filter(math.isfinite)


def _distance_far_from_all_targets() -> st.SearchStrategy:
    """Generate distances that are NOT within 5% of any PR target distance."""
    def _is_far_from_all(d: float) -> bool:
        for target_m in _PR_TARGETS.values():
            lower = target_m * (1 - _PR_TOLERANCE)
            upper = target_m * (1 + _PR_TOLERANCE)
            if lower <= d <= upper:
                return False
        return True

    return st.floats(
        min_value=100.0,
        max_value=50_000.0,
        allow_nan=False,
        allow_infinity=False,
    ).filter(lambda d: math.isfinite(d) and _is_far_from_all(d))


# Strategy: a list of runs near a specific PR target distance
_pr_run_record_st = st.fixed_dictionaries(
    {
        "date": _run_date_st,
        "duration_seconds": _duration_st,
        "avg_heart_rate": _hr_st,
    }
)


@given(
    profile_id=_profile_id_st,
    # Pick one PR target to test
    target_label=st.sampled_from(list(_PR_TARGETS.keys())),
    # 1–5 runs near the target distance with varying paces
    near_runs=st.lists(
        st.fixed_dictionaries(
            {
                "date": _run_date_st,
                "duration_seconds": _duration_st,
                "avg_heart_rate": _hr_st,
            }
        ),
        min_size=1,
        max_size=5,
    ),
    # Distances for each near run (within 5% of target)
    near_distances=st.lists(
        st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        min_size=1,
        max_size=5,
    ),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_pr_is_run_with_best_pace_within_tolerance(
    client,
    db_session,
    profile_id: int,
    target_label: str,
    near_runs: list[dict],
    near_distances: list[float],
):
    """
    Property 22: GET /api/v1/profiles/{profile_id}/stats/prs SHALL return the
    personal record for each tracked distance as the run with the minimum
    avg_pace_sec_per_km among all runs whose distance_metres is within 5% of
    the target distance.

    # Feature: personal-running-coach, Property 22: PR identification
    **Validates: Requirements 8.6**
    """
    target_m = _PR_TARGETS[target_label]
    lower = target_m * (1 - _PR_TOLERANCE)
    upper = target_m * (1 + _PR_TOLERANCE)

    # Align the near_distances list length with near_runs
    count = min(len(near_runs), len(near_distances))
    assume(count >= 1)

    near_runs = near_runs[:count]
    near_distances = near_distances[:count]

    # Map the [0,1] floats to actual distances within the tolerance band
    actual_distances = [lower + frac * (upper - lower) for frac in near_distances]
    assume(all(math.isfinite(d) and d > 0 for d in actual_distances))

    # Insert runs near the target distance
    inserted_paces = []
    for rec, dist in zip(near_runs, actual_distances):
        duration = rec["duration_seconds"]
        avg_pace = duration / (dist / 1000)
        run = Run(
            profile_id=profile_id,
            source="manual",
            date=rec["date"],
            distance_metres=dist,
            duration_seconds=duration,
            avg_pace_sec_per_km=avg_pace,
            avg_heart_rate=rec.get("avg_heart_rate"),
        )
        db_session.add(run)
        inserted_paces.append(avg_pace)
    db_session.commit()

    # The expected PR pace is the minimum pace among the inserted runs
    expected_best_pace = min(inserted_paces)

    # Call the PRs endpoint
    response = client.get(f"/api/v1/profiles/{profile_id}/stats/prs")

    assert response.status_code == 200, (
        f"Expected HTTP 200, got {response.status_code}: {response.text}"
    )

    body = response.json()
    assert "records" in body, f"'records' missing from PR response: {body}"

    # Find the record for our target label
    pr_record = next(
        (r for r in body["records"] if r["distance_label"] == target_label),
        None,
    )
    assert pr_record is not None, (
        f"PR record for '{target_label}' missing from response. "
        f"Available labels: {[r['distance_label'] for r in body['records']]}"
    )

    # The PR must be non-null (we inserted qualifying runs)
    assert pr_record["run_id"] is not None, (
        f"PR for '{target_label}' is null but we inserted runs within tolerance. "
        f"Inserted distances: {actual_distances}, target range: [{lower:.1f}, {upper:.1f}]"
    )
    assert pr_record["avg_pace_sec_per_km"] is not None, (
        f"PR avg_pace_sec_per_km is null for '{target_label}'"
    )

    # The PR pace must be ≤ the best pace we inserted (there may be other runs
    # from prior hypothesis examples that are even faster)
    assert pr_record["avg_pace_sec_per_km"] <= expected_best_pace + 1e-6, (
        f"PR pace {pr_record['avg_pace_sec_per_km']:.3f} s/km is worse than "
        f"the best pace we inserted ({expected_best_pace:.3f} s/km) for '{target_label}'"
    )

    # The PR run's distance must be within the 5% tolerance band
    assert pr_record["distance_metres"] is not None
    assert lower <= pr_record["distance_metres"] <= upper, (
        f"PR run distance {pr_record['distance_metres']:.1f} m is outside the "
        f"5% tolerance band [{lower:.1f}, {upper:.1f}] for '{target_label}'"
    )


@given(
    profile_id=_profile_id_st,
    # Runs whose distances are all far from every PR target
    far_distances=st.lists(
        st.floats(min_value=100.0, max_value=50_000.0, allow_nan=False, allow_infinity=False),
        min_size=1,
        max_size=10,
    ),
    durations=st.lists(
        _duration_st,
        min_size=1,
        max_size=10,
    ),
    dates=st.lists(
        _run_date_st,
        min_size=1,
        max_size=10,
    ),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_pr_is_null_when_no_run_within_tolerance(
    client,
    db_session,
    profile_id: int,
    far_distances: list[float],
    durations: list[int],
    dates: list[date],
):
    """
    Property 22b: For any PR target distance, if no run in the database has a
    distance_metres within 5% of that target, the PR record SHALL have
    run_id = null.

    # Feature: personal-running-coach, Property 22: PR identification
    **Validates: Requirements 8.6**
    """
    # Determine which PR targets have NO qualifying runs in the DB already
    # (from prior hypothesis examples in the same transaction)
    response_before = client.get(f"/api/v1/profiles/{profile_id}/stats/prs")
    assert response_before.status_code == 200
    null_labels_before = {
        r["distance_label"]
        for r in response_before.json()["records"]
        if r["run_id"] is None
    }

    if not null_labels_before:
        # All PR targets already have qualifying runs — nothing to test
        return

    # Filter far_distances to only those that are truly outside all tolerance bands
    def _is_far_from_all(d: float) -> bool:
        if not math.isfinite(d) or d <= 0:
            return False
        for target_m in _PR_TARGETS.values():
            lower = target_m * (1 - _PR_TOLERANCE)
            upper = target_m * (1 + _PR_TOLERANCE)
            if lower <= d <= upper:
                return False
        return True

    truly_far = [d for d in far_distances if _is_far_from_all(d)]
    assume(len(truly_far) >= 1)

    count = min(len(truly_far), len(durations), len(dates))
    assume(count >= 1)

    # Insert runs with distances far from all PR targets
    for i in range(count):
        dist = truly_far[i]
        duration = durations[i]
        avg_pace = duration / (dist / 1000)
        run = Run(
            profile_id=profile_id,
            source="manual",
            date=dates[i],
            distance_metres=dist,
            duration_seconds=duration,
            avg_pace_sec_per_km=avg_pace,
        )
        db_session.add(run)
    db_session.commit()

    # Call the PRs endpoint
    response = client.get(f"/api/v1/profiles/{profile_id}/stats/prs")
    assert response.status_code == 200, (
        f"Expected HTTP 200, got {response.status_code}: {response.text}"
    )

    body = response.json()
    assert "records" in body

    # For every label that had no qualifying run before, it must still be null
    # (we only inserted runs far from all targets)
    for record in body["records"]:
        if record["distance_label"] in null_labels_before:
            assert record["run_id"] is None, (
                f"PR for '{record['distance_label']}' became non-null after inserting "
                f"runs with distances far from all targets. "
                f"PR distance: {record['distance_metres']}"
            )


# ---------------------------------------------------------------------------
# Property 23: Run history filters return only matching records
# ---------------------------------------------------------------------------

# Date range strategy: two dates where from ≤ to
_date_range_st = st.tuples(
    st.dates(min_value=date(2020, 1, 1), max_value=date(2025, 12, 31)),
    st.dates(min_value=date(2020, 1, 1), max_value=date(2025, 12, 31)),
).map(lambda pair: (min(pair), max(pair)))

# Distance range in km: two values where min ≤ max
_distance_range_km_st = st.tuples(
    st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False),
    st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False),
).filter(
    lambda pair: math.isfinite(pair[0]) and math.isfinite(pair[1]) and pair[0] <= pair[1]
)


@given(
    profile_id=_profile_id_st,
    run_records=_run_list_st,
    date_range=_date_range_st,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_date_filter_returns_only_matching_runs(
    client,
    db_session,
    profile_id: int,
    run_records: list[dict],
    date_range: tuple[date, date],
):
    """
    Property 23a: GET /api/v1/profiles/{profile_id}/runs?date_from=X&date_to=Y
    SHALL return only runs whose date is within [date_from, date_to] (inclusive).
    No run outside the date range SHALL appear in the response.

    # Feature: personal-running-coach, Property 23: filter correctness
    **Validates: Requirements 8.8**
    """
    _insert_runs(db_session, profile_id, run_records)

    date_from, date_to = date_range

    response = client.get(
        f"/api/v1/profiles/{profile_id}/runs",
        params={
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
        },
    )

    assert response.status_code == 200, (
        f"Expected HTTP 200, got {response.status_code}: {response.text}"
    )

    body = response.json()
    assert isinstance(body, list)

    for run_item in body:
        run_date = date.fromisoformat(run_item["date"])
        assert date_from <= run_date <= date_to, (
            f"Run with date {run_date} is outside the filter range "
            f"[{date_from}, {date_to}]"
        )


@given(
    profile_id=_profile_id_st,
    run_records=_run_list_st,
    date_range=_date_range_st,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_date_filter_includes_all_matching_runs(
    client,
    db_session,
    profile_id: int,
    run_records: list[dict],
    date_range: tuple[date, date],
):
    """
    Property 23a (completeness): No run that satisfies the date filter criteria
    SHALL be omitted from the response.

    # Feature: personal-running-coach, Property 23: filter correctness
    **Validates: Requirements 8.8**
    """
    _insert_runs(db_session, profile_id, run_records)

    date_from, date_to = date_range

    # Get all runs without filter
    all_response = client.get(f"/api/v1/profiles/{profile_id}/runs")
    assert all_response.status_code == 200
    all_runs = all_response.json()

    # Get filtered runs
    filtered_response = client.get(
        f"/api/v1/profiles/{profile_id}/runs",
        params={
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
        },
    )
    assert filtered_response.status_code == 200
    filtered_runs = filtered_response.json()

    # Every run in all_runs that satisfies the filter must appear in filtered_runs
    filtered_ids = {r["id"] for r in filtered_runs}
    for run_item in all_runs:
        run_date = date.fromisoformat(run_item["date"])
        if date_from <= run_date <= date_to:
            assert run_item["id"] in filtered_ids, (
                f"Run id={run_item['id']} with date {run_date} satisfies the filter "
                f"[{date_from}, {date_to}] but is missing from the filtered response"
            )


@given(
    profile_id=_profile_id_st,
    run_records=_run_list_st,
    run_type=st.sampled_from(["easy", "tempo", "interval", "long", "race"]),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_run_type_filter_returns_only_matching_runs(
    client,
    db_session,
    profile_id: int,
    run_records: list[dict],
    run_type: str,
):
    """
    Property 23b: GET /api/v1/profiles/{profile_id}/runs?run_type=X SHALL return
    only runs whose run_type equals X.  No run with a different run_type SHALL
    appear in the response.

    # Feature: personal-running-coach, Property 23: filter correctness
    **Validates: Requirements 8.8**
    """
    _insert_runs(db_session, profile_id, run_records)

    response = client.get(
        f"/api/v1/profiles/{profile_id}/runs",
        params={"run_type": run_type},
    )

    assert response.status_code == 200, (
        f"Expected HTTP 200, got {response.status_code}: {response.text}"
    )

    body = response.json()
    assert isinstance(body, list)

    for run_item in body:
        assert run_item.get("run_type") == run_type, (
            f"Run id={run_item['id']} has run_type={run_item.get('run_type')!r} "
            f"but filter was run_type={run_type!r}"
        )


@given(
    profile_id=_profile_id_st,
    run_records=_run_list_st,
    distance_range_km=_distance_range_km_st,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_distance_filter_returns_only_matching_runs(
    client,
    db_session,
    profile_id: int,
    run_records: list[dict],
    distance_range_km: tuple[float, float],
):
    """
    Property 23c: GET /api/v1/profiles/{profile_id}/runs with
    min_distance_km and max_distance_km filters SHALL return only runs whose
    distance_metres is within [min_distance_km * 1000, max_distance_km * 1000].
    No run outside this range SHALL appear in the response.

    # Feature: personal-running-coach, Property 23: filter correctness
    **Validates: Requirements 8.8**
    """
    _insert_runs(db_session, profile_id, run_records)

    min_km, max_km = distance_range_km

    response = client.get(
        f"/api/v1/profiles/{profile_id}/runs",
        params={
            "min_distance_km": min_km,
            "max_distance_km": max_km,
        },
    )

    assert response.status_code == 200, (
        f"Expected HTTP 200, got {response.status_code}: {response.text}"
    )

    body = response.json()
    assert isinstance(body, list)

    min_metres = min_km * 1000
    max_metres = max_km * 1000

    for run_item in body:
        dist = run_item["distance_metres"]
        assert min_metres <= dist <= max_metres, (
            f"Run id={run_item['id']} has distance_metres={dist:.1f} which is "
            f"outside the filter range [{min_metres:.1f}, {max_metres:.1f}] "
            f"(min_distance_km={min_km}, max_distance_km={max_km})"
        )


@given(
    profile_id=_profile_id_st,
    run_records=_run_list_st,
    distance_range_km=_distance_range_km_st,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_distance_filter_includes_all_matching_runs(
    client,
    db_session,
    profile_id: int,
    run_records: list[dict],
    distance_range_km: tuple[float, float],
):
    """
    Property 23c (completeness): No run that satisfies the distance filter
    criteria SHALL be omitted from the response.

    # Feature: personal-running-coach, Property 23: filter correctness
    **Validates: Requirements 8.8**
    """
    _insert_runs(db_session, profile_id, run_records)

    min_km, max_km = distance_range_km
    min_metres = min_km * 1000
    max_metres = max_km * 1000

    # Get all runs without filter
    all_response = client.get(f"/api/v1/profiles/{profile_id}/runs")
    assert all_response.status_code == 200
    all_runs = all_response.json()

    # Get filtered runs
    filtered_response = client.get(
        f"/api/v1/profiles/{profile_id}/runs",
        params={
            "min_distance_km": min_km,
            "max_distance_km": max_km,
        },
    )
    assert filtered_response.status_code == 200
    filtered_runs = filtered_response.json()

    filtered_ids = {r["id"] for r in filtered_runs}

    for run_item in all_runs:
        dist = run_item["distance_metres"]
        if min_metres <= dist <= max_metres:
            assert run_item["id"] in filtered_ids, (
                f"Run id={run_item['id']} with distance_metres={dist:.1f} satisfies "
                f"the filter [{min_metres:.1f}, {max_metres:.1f}] but is missing "
                f"from the filtered response"
            )
