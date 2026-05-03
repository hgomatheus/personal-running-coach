"""
Property-based tests for backup pruning and bulk import idempotency.

# Feature: personal-running-coach

**Validates: Requirements 14.2, 15.5**

Property 26: prune_backups(db, retain=30) SHALL retain exactly min(N, 30)
backup records after pruning. For any number of backup records N:
  - If N ≤ 30: all records are retained
  - If N > 30: exactly 30 records are retained (the 30 most recent)
  - The oldest records (by completed_at) are deleted first

Property 27: import_activities(records, profile_id, db) SHALL be idempotent:
importing the same set of ActivityRecord objects twice SHALL result in the
same number of Run records as importing once. Duplicate activities (same
strava_activity_id + profile_id) SHALL be skipped, not duplicated.
"""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.models.orm import BackupRecord, Run
from app.services.backup_service import prune_backups
from app.services.strava_bulk_importer import ActivityRecord, import_activities

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_profile_id_st = st.sampled_from([1, 2])

# Number of backup records to create: 0–60 (covers both ≤30 and >30 cases)
_backup_count_st = st.integers(min_value=0, max_value=60)

# Strava activity ID: positive integer
_activity_id_st = st.integers(min_value=1, max_value=10_000_000)

# Valid distance: 1 km to 100 km (in metres)
_distance_st = st.floats(
    min_value=1_000.0,
    max_value=100_000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Valid duration: 5 minutes to 6 hours (in seconds)
_duration_st = st.integers(min_value=300, max_value=21_600)

# A single ActivityRecord strategy
_activity_record_st = st.builds(
    ActivityRecord,
    strava_activity_id=_activity_id_st,
    name=st.just("Test Run"),
    date=st.dates(min_value=date(2020, 1, 1), max_value=date(2024, 12, 31)),
    distance_metres=_distance_st,
    duration_seconds=_duration_st,
    avg_heart_rate=st.none(),
    elevation_gain_metres=st.none(),
    summary_polyline=st.none(),
    run_type=st.none(),
)

# A list of ActivityRecords with unique strava_activity_ids (1–20 records)
_activity_list_st = st.lists(
    _activity_record_st,
    min_size=1,
    max_size=20,
).map(
    # Deduplicate by strava_activity_id to ensure a clean unique set
    lambda records: list({r.strava_activity_id: r for r in records}.values())
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clear_backup_records(db_session) -> None:
    """Delete all BackupRecord rows to isolate each Hypothesis example."""
    db_session.query(BackupRecord).delete()
    db_session.flush()


def _clear_runs_for_profile(db_session, profile_id: int) -> None:
    """Delete all Run rows for a profile to isolate each Hypothesis example."""
    db_session.query(Run).filter(Run.profile_id == profile_id).delete()
    db_session.flush()


def _make_backup_records(db_session, n: int) -> list[BackupRecord]:
    """
    Insert N successful BackupRecord rows with distinct completed_at timestamps.
    Returns the list of inserted records ordered oldest-first.
    """
    base_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    records = []
    for i in range(n):
        record = BackupRecord(
            completed_at=base_time + timedelta(hours=i),
            file_path=f"/backups/backup_{i:04d}.db",
            size_bytes=1024,
            success=True,
        )
        db_session.add(record)
        records.append(record)
    db_session.flush()
    return records


# ---------------------------------------------------------------------------
# Property 26a: prune_backups retains exactly min(N, 30) records
# ---------------------------------------------------------------------------


@given(n=_backup_count_st)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_prune_backups_retains_exactly_min_n_30(
    db_session,
    n: int,
):
    """
    Property 26: prune_backups(db, retain=30) SHALL retain exactly min(N, 30)
    backup records after pruning.

    For any N backup records:
      - If N ≤ 30: all N records are retained (nothing deleted)
      - If N > 30: exactly 30 records are retained

    # Feature: personal-running-coach, Property 26: backup pruning
    **Validates: Requirements 14.2**
    """
    # Isolate this example from any records left by prior Hypothesis examples
    _clear_backup_records(db_session)
    _make_backup_records(db_session, n)

    # Patch Path.exists and Path.unlink so prune_backups doesn't fail on
    # missing files — we're testing the DB retention logic, not file I/O.
    with (
        patch("app.services.backup_service.Path.exists", return_value=True),
        patch("app.services.backup_service.Path.unlink"),
    ):
        prune_backups(db_session, retain=30)

    # Count remaining successful backup records
    remaining = (
        db_session.query(BackupRecord)
        .filter(BackupRecord.success == True)
        .count()
    )

    expected = min(n, 30)
    assert remaining == expected, (
        f"After prune_backups with N={n} records, expected {expected} remaining "
        f"(min({n}, 30)), but got {remaining}."
    )


# ---------------------------------------------------------------------------
# Property 26b: prune_backups retains the most recent records
# ---------------------------------------------------------------------------


@given(n=st.integers(min_value=31, max_value=60))
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_prune_backups_retains_most_recent_records(
    db_session,
    n: int,
):
    """
    Property 26 (ordering): When N > 30, prune_backups SHALL retain the 30
    records with the most recent completed_at timestamps and delete the oldest.

    # Feature: personal-running-coach, Property 26: backup pruning
    **Validates: Requirements 14.2**
    """
    _clear_backup_records(db_session)
    records = _make_backup_records(db_session, n)
    # records is ordered oldest-first; the 30 most recent are the last 30
    expected_retained_ids = {r.id for r in records[n - 30:]}
    expected_deleted_ids = {r.id for r in records[:n - 30]}

    with (
        patch("app.services.backup_service.Path.exists", return_value=True),
        patch("app.services.backup_service.Path.unlink"),
    ):
        prune_backups(db_session, retain=30)

    db_session.expire_all()

    # Retained records must still exist
    for record_id in expected_retained_ids:
        row = db_session.query(BackupRecord).filter(BackupRecord.id == record_id).first()
        assert row is not None, (
            f"BackupRecord id={record_id} should have been retained "
            f"(it is among the 30 most recent), but it was deleted. N={n}"
        )

    # Deleted records must be gone
    for record_id in expected_deleted_ids:
        row = db_session.query(BackupRecord).filter(BackupRecord.id == record_id).first()
        assert row is None, (
            f"BackupRecord id={record_id} should have been deleted "
            f"(it is among the oldest N-30={n-30} records), but it still exists. N={n}"
        )


# ---------------------------------------------------------------------------
# Property 26c: prune_backups with N ≤ 30 deletes nothing
# ---------------------------------------------------------------------------


@given(n=st.integers(min_value=0, max_value=30))
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_prune_backups_deletes_nothing_when_n_le_30(
    db_session,
    n: int,
):
    """
    Property 26 (no-op case): When N ≤ 30, prune_backups SHALL delete no
    records and return 0.

    # Feature: personal-running-coach, Property 26: backup pruning
    **Validates: Requirements 14.2**
    """
    _clear_backup_records(db_session)
    records = _make_backup_records(db_session, n)
    original_ids = {r.id for r in records}

    with (
        patch("app.services.backup_service.Path.exists", return_value=True),
        patch("app.services.backup_service.Path.unlink"),
    ):
        deleted_count = prune_backups(db_session, retain=30)

    assert deleted_count == 0, (
        f"prune_backups should delete 0 records when N={n} ≤ 30, "
        f"but deleted {deleted_count}."
    )

    db_session.expire_all()
    for record_id in original_ids:
        row = db_session.query(BackupRecord).filter(BackupRecord.id == record_id).first()
        assert row is not None, (
            f"BackupRecord id={record_id} should not have been deleted "
            f"when N={n} ≤ 30."
        )


# ---------------------------------------------------------------------------
# Property 27a: import_activities is idempotent — same count after two imports
# ---------------------------------------------------------------------------


@given(
    profile_id=_profile_id_st,
    activity_records=_activity_list_st,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_import_activities_idempotent_run_count(
    db_session,
    profile_id: int,
    activity_records: list[ActivityRecord],
):
    """
    Property 27: import_activities(records, profile_id, db) SHALL be idempotent.
    Importing the same list of ActivityRecord objects twice SHALL result in the
    same number of Run records as importing once.

    # Feature: personal-running-coach, Property 27: bulk import idempotency
    **Validates: Requirements 15.5**
    """
    # Isolate this example from any runs left by prior Hypothesis examples
    _clear_runs_for_profile(db_session, profile_id)

    # First import
    import_activities(activity_records, profile_id, db_session)

    count_after_first = (
        db_session.query(Run)
        .filter(Run.profile_id == profile_id)
        .count()
    )

    # Second import with the same records
    import_activities(activity_records, profile_id, db_session)

    count_after_second = (
        db_session.query(Run)
        .filter(Run.profile_id == profile_id)
        .count()
    )

    assert count_after_first == count_after_second, (
        f"Run count changed after second import: "
        f"after first={count_after_first}, after second={count_after_second}. "
        f"profile_id={profile_id}, records={len(activity_records)}"
    )


# ---------------------------------------------------------------------------
# Property 27b: second import reports all records as duplicates
# ---------------------------------------------------------------------------


@given(
    profile_id=_profile_id_st,
    activity_records=_activity_list_st,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_import_activities_second_import_all_skipped(
    db_session,
    profile_id: int,
    activity_records: list[ActivityRecord],
):
    """
    Property 27 (duplicate reporting): On the second import of the same records,
    import_activities SHALL report imported=0 and skipped_duplicates equal to
    the number of records that were successfully imported in the first pass.

    # Feature: personal-running-coach, Property 27: bulk import idempotency
    **Validates: Requirements 15.5**
    """
    # Isolate this example from any runs left by prior Hypothesis examples
    _clear_runs_for_profile(db_session, profile_id)

    # First import
    result1 = import_activities(activity_records, profile_id, db_session)
    first_imported = result1["imported"]

    # Second import
    result2 = import_activities(activity_records, profile_id, db_session)

    assert result2["imported"] == 0, (
        f"Second import should import 0 new records, "
        f"but imported {result2['imported']}. "
        f"profile_id={profile_id}, records={len(activity_records)}"
    )

    assert result2["skipped_duplicates"] == first_imported, (
        f"Second import should skip exactly {first_imported} duplicates "
        f"(the number imported in the first pass), "
        f"but skipped {result2['skipped_duplicates']}. "
        f"profile_id={profile_id}"
    )


# ---------------------------------------------------------------------------
# Property 27c: no duplicate Run rows for same (strava_activity_id, profile_id)
# ---------------------------------------------------------------------------


@given(
    profile_id=_profile_id_st,
    activity_records=_activity_list_st,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_import_activities_no_duplicate_run_rows(
    db_session,
    profile_id: int,
    activity_records: list[ActivityRecord],
):
    """
    Property 27 (uniqueness): After two imports of the same records, there
    SHALL be at most one Run row per (strava_activity_id, profile_id) pair.
    No duplicate rows SHALL exist.

    # Feature: personal-running-coach, Property 27: bulk import idempotency
    **Validates: Requirements 15.5**
    """
    # Isolate this example from any runs left by prior Hypothesis examples
    _clear_runs_for_profile(db_session, profile_id)

    # Import twice
    import_activities(activity_records, profile_id, db_session)
    import_activities(activity_records, profile_id, db_session)

    # Check for duplicates: each strava_activity_id should appear at most once
    # for this profile
    for record in activity_records:
        count = (
            db_session.query(Run)
            .filter(
                Run.profile_id == profile_id,
                Run.strava_activity_id == record.strava_activity_id,
            )
            .count()
        )
        assert count <= 1, (
            f"Found {count} Run rows for strava_activity_id="
            f"{record.strava_activity_id}, profile_id={profile_id}. "
            f"Expected at most 1 (idempotent import)."
        )
