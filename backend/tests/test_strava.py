"""
Property-based tests for Strava integration.

# Feature: personal-running-coach, Properties 15–16: run import/matching invocation,
# Strava error handling

**Validates: Requirements 6.4, 6.6, 7.4**
"""

import asyncio
from datetime import date, datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st

from app.models.orm import Run, StravaToken
from app.services.strava_client import StravaActivity, fetch_activities
from app.services.strava_sync import sync_profile

# ---------------------------------------------------------------------------
# Shared strategies
# ---------------------------------------------------------------------------

_profile_id_st = st.sampled_from([1, 2])

# Generate a list of 1–20 unique Strava activity IDs
_activity_ids_st = st.lists(
    st.integers(min_value=100_000, max_value=999_999_999),
    min_size=1,
    max_size=20,
    unique=True,
)

# HTTP error status codes that Strava may return
_http_error_status_st = st.sampled_from([400, 401, 403, 404, 429, 500, 502, 503])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_strava_activity(activity_id: int, run_date: date) -> StravaActivity:
    """Build a minimal StravaActivity for testing."""
    return StravaActivity(
        id=activity_id,
        name=f"Run {activity_id}",
        type="Run",
        start_date=datetime.combine(run_date, datetime.min.time()).replace(
            tzinfo=timezone.utc
        ),
        distance=5000.0,
        moving_time=1800,
        average_heartrate=None,
        total_elevation_gain=None,
        summary_polyline=None,
        raw={
            "id": activity_id,
            "name": f"Run {activity_id}",
            "sport_type": "Run",
            "start_date": run_date.isoformat() + "T06:00:00Z",
            "distance": 5000.0,
            "moving_time": 1800,
        },
    )


def _make_strava_token(db_session, profile_id: int) -> StravaToken:
    """Upsert a StravaToken row for the given profile and return it.

    Idempotent: if a token already exists for this profile_id, update it in
    place so that repeated Hypothesis examples don't hit the UNIQUE constraint.
    """
    from app.services.strava_client import _encrypt

    now = datetime.now(timezone.utc)

    # Roll back any pending failed transaction before querying
    try:
        token = (
            db_session.query(StravaToken)
            .filter(StravaToken.profile_id == profile_id)
            .first()
        )
    except Exception:
        db_session.rollback()
        token = (
            db_session.query(StravaToken)
            .filter(StravaToken.profile_id == profile_id)
            .first()
        )

    if token is None:
        token = StravaToken(
            profile_id=profile_id,
            athlete_id=12345,
            access_token=_encrypt("fake_access_token"),
            refresh_token=_encrypt("fake_refresh_token"),
            expires_at=now + timedelta(hours=6),
            last_sync_at=None,
            sync_error=None,
        )
        db_session.add(token)
    else:
        # Reset the token to a clean state for this example
        token.athlete_id = 12345
        token.access_token = _encrypt("fake_access_token")
        token.refresh_token = _encrypt("fake_refresh_token")
        token.expires_at = now + timedelta(hours=6)
        token.last_sync_at = None
        token.sync_error = None

    db_session.flush()
    return token


# ---------------------------------------------------------------------------
# Property 15: match_run_to_workout is called exactly once per imported run
#
# For every activity imported via Strava sync, match_run_to_workout() SHALL
# be called exactly once per imported run.
# ---------------------------------------------------------------------------


@given(
    profile_id=_profile_id_st,
    activity_ids=_activity_ids_st,
)
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_match_run_to_workout_called_once_per_imported_run(
    db_session,
    profile_id: int,
    activity_ids: list[int],
):
    """
    Property 15 (new activities): For every new Strava activity imported via
    sync_profile(), match_run_to_workout() SHALL be called exactly once per
    imported run.

    # Feature: personal-running-coach, Property 15: Run import/matching invocation
    **Validates: Requirements 6.4, 7.4**
    """
    # Ensure no pre-existing runs for these activity IDs
    for aid in activity_ids:
        existing = (
            db_session.query(Run)
            .filter(Run.profile_id == profile_id, Run.strava_activity_id == aid)
            .first()
        )
        assume(existing is None)

    # Create a StravaToken so sync_profile proceeds
    _make_strava_token(db_session, profile_id)

    run_date = date(2025, 3, 15)
    activities = [_make_strava_activity(aid, run_date) for aid in activity_ids]

    match_calls: list[int] = []  # records run.strava_activity_id for each call

    def mock_match(run, pid, db):
        match_calls.append(run.strava_activity_id)
        return None  # no workout matched

    with (
        patch(
            "app.services.strava_sync.strava_client.fetch_activities",
            new=AsyncMock(return_value=activities),
        ),
        patch(
            "app.services.strava_sync.match_run_to_workout",
            side_effect=mock_match,
        ),
    ):
        imported = asyncio.get_event_loop().run_until_complete(
            sync_profile(profile_id, db_session)
        )

    assert imported == len(activity_ids), (
        f"Expected {len(activity_ids)} runs imported, got {imported}"
    )
    assert len(match_calls) == len(activity_ids), (
        f"Expected match_run_to_workout to be called exactly {len(activity_ids)} "
        f"time(s) (once per imported run), but was called {len(match_calls)} time(s). "
        f"activity_ids={activity_ids}"
    )
    # Each activity ID should appear exactly once in match_calls
    assert sorted(match_calls) == sorted(activity_ids), (
        f"match_run_to_workout was not called with the correct activity IDs. "
        f"Expected {sorted(activity_ids)}, got {sorted(match_calls)}"
    )


@given(
    profile_id=_profile_id_st,
    activity_ids=_activity_ids_st,
)
@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_match_run_to_workout_not_called_for_duplicate_activities(
    db_session,
    profile_id: int,
    activity_ids: list[int],
):
    """
    Property 15 (duplicate activities): For Strava activities that already exist
    as Run records (duplicates), match_run_to_workout() SHALL NOT be called —
    only new runs trigger matching.

    # Feature: personal-running-coach, Property 15: Run import/matching invocation
    **Validates: Requirements 6.4, 7.4**
    """
    run_date = date(2025, 4, 10)

    # Pre-insert all activities as existing Run records (simulate prior import)
    for aid in activity_ids:
        existing = (
            db_session.query(Run)
            .filter(Run.profile_id == profile_id, Run.strava_activity_id == aid)
            .first()
        )
        if existing is None:
            run = Run(
                profile_id=profile_id,
                source="strava",
                strava_activity_id=aid,
                date=run_date,
                distance_metres=5000.0,
                duration_seconds=1800,
            )
            db_session.add(run)
    db_session.flush()

    # Create a StravaToken so sync_profile proceeds
    _make_strava_token(db_session, profile_id)

    activities = [_make_strava_activity(aid, run_date) for aid in activity_ids]

    match_calls: list[int] = []

    def mock_match(run, pid, db):
        match_calls.append(run.strava_activity_id)
        return None

    with (
        patch(
            "app.services.strava_sync.strava_client.fetch_activities",
            new=AsyncMock(return_value=activities),
        ),
        patch(
            "app.services.strava_sync.match_run_to_workout",
            side_effect=mock_match,
        ),
    ):
        imported = asyncio.get_event_loop().run_until_complete(
            sync_profile(profile_id, db_session)
        )

    assert imported == 0, (
        f"Expected 0 runs imported (all duplicates), got {imported}"
    )
    assert len(match_calls) == 0, (
        f"match_run_to_workout should NOT be called for duplicate activities, "
        f"but was called {len(match_calls)} time(s). activity_ids={activity_ids}"
    )


@given(
    profile_id=_profile_id_st,
    new_ids=st.lists(
        st.integers(min_value=100_000, max_value=499_999),
        min_size=1,
        max_size=10,
        unique=True,
    ),
    dup_ids=st.lists(
        st.integers(min_value=500_000, max_value=999_999),
        min_size=1,
        max_size=10,
        unique=True,
    ),
)
@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_match_run_to_workout_called_only_for_new_activities_in_mixed_batch(
    db_session,
    profile_id: int,
    new_ids: list[int],
    dup_ids: list[int],
):
    """
    Property 15 (mixed batch): When a batch contains both new and duplicate
    activities, match_run_to_workout() SHALL be called exactly once for each
    new activity and zero times for each duplicate.

    # Feature: personal-running-coach, Property 15: Run import/matching invocation
    **Validates: Requirements 6.4, 7.4**
    """
    # Ensure no overlap between new and dup IDs
    assume(set(new_ids).isdisjoint(set(dup_ids)))

    run_date = date(2025, 5, 20)

    # Pre-insert duplicate activities
    for aid in dup_ids:
        existing = (
            db_session.query(Run)
            .filter(Run.profile_id == profile_id, Run.strava_activity_id == aid)
            .first()
        )
        if existing is None:
            run = Run(
                profile_id=profile_id,
                source="strava",
                strava_activity_id=aid,
                date=run_date,
                distance_metres=5000.0,
                duration_seconds=1800,
            )
            db_session.add(run)

    # Ensure new IDs don't already exist
    for aid in new_ids:
        existing = (
            db_session.query(Run)
            .filter(Run.profile_id == profile_id, Run.strava_activity_id == aid)
            .first()
        )
        assume(existing is None)

    db_session.flush()

    # Create a StravaToken so sync_profile proceeds
    _make_strava_token(db_session, profile_id)

    all_activities = [
        _make_strava_activity(aid, run_date) for aid in new_ids + dup_ids
    ]

    match_calls: list[int] = []

    def mock_match(run, pid, db):
        match_calls.append(run.strava_activity_id)
        return None

    with (
        patch(
            "app.services.strava_sync.strava_client.fetch_activities",
            new=AsyncMock(return_value=all_activities),
        ),
        patch(
            "app.services.strava_sync.match_run_to_workout",
            side_effect=mock_match,
        ),
    ):
        imported = asyncio.get_event_loop().run_until_complete(
            sync_profile(profile_id, db_session)
        )

    assert imported == len(new_ids), (
        f"Expected {len(new_ids)} new runs imported, got {imported}. "
        f"new_ids={new_ids}, dup_ids={dup_ids}"
    )
    assert len(match_calls) == len(new_ids), (
        f"Expected match_run_to_workout to be called {len(new_ids)} time(s) "
        f"(once per new run), but was called {len(match_calls)} time(s). "
        f"new_ids={new_ids}, dup_ids={dup_ids}"
    )
    # Only new IDs should appear in match_calls
    assert set(match_calls) == set(new_ids), (
        f"match_run_to_workout was called with unexpected IDs. "
        f"Expected {sorted(new_ids)}, got {sorted(match_calls)}"
    )


# ---------------------------------------------------------------------------
# Property 16: Strava API errors are handled gracefully without crashing
#
# For any HTTP 4xx/5xx error from the Strava API, fetch_activities() SHALL
# not raise an unhandled exception and SHALL return a list (possibly empty).
# ---------------------------------------------------------------------------


@given(
    profile_id=_profile_id_st,
    status_code=_http_error_status_st,
)
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_fetch_activities_handles_http_errors_gracefully(
    db_session,
    profile_id: int,
    status_code: int,
):
    """
    Property 16 (fetch_activities): When the Strava API returns an HTTP error
    (4xx or 5xx), fetch_activities() SHALL not raise an unhandled exception
    and SHALL return a list (empty or partial).

    # Feature: personal-running-coach, Property 16: Strava error handling
    **Validates: Requirements 6.6**
    """
    # Create a StravaToken so fetch_activities can proceed past the token check
    _make_strava_token(db_session, profile_id)

    after_ts = int((datetime.now(timezone.utc) - timedelta(days=7)).timestamp())

    # Build a mock httpx response with the given error status code
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = status_code
    mock_response.headers = {}
    mock_response.text = f"Error {status_code}"
    mock_response.json.return_value = []

    # raise_for_status should raise HTTPStatusError for 4xx/5xx (except 429 handled separately)
    if status_code != 429:
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"HTTP {status_code}",
            request=MagicMock(),
            response=mock_response,
        )
    else:
        mock_response.raise_for_status.return_value = None

    mock_async_client = AsyncMock()
    mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
    mock_async_client.__aexit__ = AsyncMock(return_value=False)
    mock_async_client.get = AsyncMock(return_value=mock_response)

    with (
        patch(
            "app.services.strava_client.refresh_token_if_needed",
            new=AsyncMock(return_value=db_session.query(StravaToken)
                          .filter(StravaToken.profile_id == profile_id)
                          .first()),
        ),
        patch("app.services.strava_client.httpx.AsyncClient", return_value=mock_async_client),
    ):
        # This must NOT raise any unhandled exception
        try:
            result = asyncio.get_event_loop().run_until_complete(
                fetch_activities(profile_id, after_ts, db_session)
            )
        except Exception as exc:
            pytest.fail(
                f"fetch_activities raised an unhandled exception for HTTP {status_code}: "
                f"{type(exc).__name__}: {exc}"
            )

    # Result must be a list (possibly empty)
    assert isinstance(result, list), (
        f"fetch_activities should return a list for HTTP {status_code}, "
        f"got {type(result).__name__}"
    )


@given(
    profile_id=_profile_id_st,
    status_code=_http_error_status_st,
)
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_sync_profile_handles_fetch_errors_gracefully(
    db_session,
    profile_id: int,
    status_code: int,
):
    """
    Property 16 (sync_profile): When fetch_activities() raises due to a Strava
    API error, sync_profile() SHALL not propagate the exception and SHALL
    record the error in strava_token.sync_error.

    # Feature: personal-running-coach, Property 16: Strava error handling
    **Validates: Requirements 6.6**
    """
    token = _make_strava_token(db_session, profile_id)

    # Simulate fetch_activities raising an exception (as it would for auth errors
    # that propagate, e.g. token refresh failure)
    error_message = f"Strava API error: HTTP {status_code}"

    with patch(
        "app.services.strava_sync.strava_client.fetch_activities",
        new=AsyncMock(side_effect=Exception(error_message)),
    ):
        # sync_profile must NOT raise an unhandled exception
        try:
            result = asyncio.get_event_loop().run_until_complete(
                sync_profile(profile_id, db_session)
            )
        except Exception as exc:
            pytest.fail(
                f"sync_profile raised an unhandled exception for HTTP {status_code}: "
                f"{type(exc).__name__}: {exc}"
            )

    # sync_profile should return 0 (no runs imported)
    assert result == 0, (
        f"sync_profile should return 0 when fetch fails, got {result}"
    )

    # The error should be recorded in strava_token.sync_error
    db_session.refresh(token)
    assert token.sync_error is not None, (
        f"sync_profile should record the error in strava_token.sync_error "
        f"for HTTP {status_code}, but sync_error is None"
    )
    assert error_message in token.sync_error, (
        f"sync_error should contain the error message. "
        f"Expected '{error_message}' in sync_error, got '{token.sync_error}'"
    )


@given(
    profile_id=_profile_id_st,
)
@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_fetch_activities_handles_network_error_gracefully(
    db_session,
    profile_id: int,
):
    """
    Property 16 (network error): When a network-level error occurs (e.g.
    connection refused), fetch_activities() SHALL not raise an unhandled
    exception and SHALL return a list.

    # Feature: personal-running-coach, Property 16: Strava error handling
    **Validates: Requirements 6.6**
    """
    _make_strava_token(db_session, profile_id)

    after_ts = int((datetime.now(timezone.utc) - timedelta(days=7)).timestamp())

    mock_async_client = AsyncMock()
    mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
    mock_async_client.__aexit__ = AsyncMock(return_value=False)
    mock_async_client.get = AsyncMock(
        side_effect=httpx.RequestError("Connection refused", request=MagicMock())
    )

    with (
        patch(
            "app.services.strava_client.refresh_token_if_needed",
            new=AsyncMock(return_value=db_session.query(StravaToken)
                          .filter(StravaToken.profile_id == profile_id)
                          .first()),
        ),
        patch("app.services.strava_client.httpx.AsyncClient", return_value=mock_async_client),
    ):
        try:
            result = asyncio.get_event_loop().run_until_complete(
                fetch_activities(profile_id, after_ts, db_session)
            )
        except Exception as exc:
            pytest.fail(
                f"fetch_activities raised an unhandled exception for network error: "
                f"{type(exc).__name__}: {exc}"
            )

    assert isinstance(result, list), (
        f"fetch_activities should return a list on network error, "
        f"got {type(result).__name__}"
    )
