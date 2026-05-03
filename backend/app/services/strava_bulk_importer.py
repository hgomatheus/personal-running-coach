"""Strava bulk import — parse Strava export ZIP and import Run records."""
import csv
import io
import logging
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.orm import ImportRecord, PaceZones, Run
from app.services.vdot import calculate_vdot, derive_pace_zones

logger = logging.getLogger(__name__)


@dataclass
class ActivityRecord:
    """Parsed activity record from a Strava export ZIP."""

    strava_activity_id: int
    name: str
    date: object  # datetime.date
    distance_metres: float
    duration_seconds: int
    avg_heart_rate: Optional[int] = None
    elevation_gain_metres: Optional[float] = None
    summary_polyline: Optional[str] = None
    run_type: Optional[str] = None


def parse_zip(file_bytes: bytes) -> list[ActivityRecord]:
    """
    Open a Strava export ZIP in memory, read activities.csv,
    filter to type == "Run", and return a list of ActivityRecord objects.
    Falls back to GPX data for missing distance/duration.
    """
    records: list[ActivityRecord] = []
    parse_errors = 0

    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
            # Find activities.csv (may be in a subdirectory)
            csv_name = next(
                (n for n in zf.namelist() if n.endswith("activities.csv")), None
            )
            if csv_name is None:
                raise ValueError("activities.csv not found in ZIP")

            with zf.open(csv_name) as csv_file:
                reader = csv.DictReader(io.TextIOWrapper(csv_file, encoding="utf-8"))
                for row in reader:
                    activity_type = row.get("Activity Type", "").strip()
                    if activity_type != "Run":
                        continue

                    try:
                        record = _parse_csv_row(row, zf)
                        if record is not None:
                            records.append(record)
                    except Exception as e:
                        logger.warning(f"Failed to parse activity row: {e}")
                        parse_errors += 1

    except zipfile.BadZipFile as e:
        raise ValueError(f"Invalid ZIP file: {e}")

    logger.info(f"Parsed {len(records)} run records from ZIP ({parse_errors} errors)")
    return records


def _parse_csv_row(row: dict, zf: zipfile.ZipFile) -> Optional[ActivityRecord]:
    """Parse a single CSV row into an ActivityRecord."""
    activity_id_str = row.get("Activity ID", "").strip()
    if not activity_id_str:
        return None

    try:
        activity_id = int(activity_id_str)
    except ValueError:
        return None

    # Parse date
    date_str = row.get("Activity Date", "").strip()
    activity_date = None
    for fmt in ("%b %d, %Y, %I:%M:%S %p", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
            activity_date = dt.date()
            break
        except ValueError:
            continue

    if activity_date is None:
        return None

    # Distance (km in CSV → metres)
    distance_m = 0.0
    try:
        distance_m = float(row.get("Distance", 0) or 0) * 1000
    except (ValueError, TypeError):
        pass

    # Duration (seconds)
    duration_s = 0
    try:
        duration_s = int(float(row.get("Moving Time", 0) or 0))
    except (ValueError, TypeError):
        pass

    # GPX fallback for missing distance/duration
    if distance_m <= 0 or duration_s <= 0:
        gpx_data = _try_gpx_fallback(activity_id, zf)
        if gpx_data:
            if distance_m <= 0:
                distance_m = gpx_data.get("distance_m", distance_m)
            if duration_s <= 0:
                duration_s = gpx_data.get("duration_s", duration_s)

    if distance_m <= 0 or duration_s <= 0:
        return None

    # Activity name
    name = row.get("Activity Name", "").strip() or f"Run {activity_id}"

    return ActivityRecord(
        strava_activity_id=activity_id,
        name=name,
        date=activity_date,
        distance_metres=distance_m,
        duration_seconds=duration_s,
        avg_heart_rate=_safe_int(row.get("Average Heart Rate")),
        elevation_gain_metres=_safe_float(row.get("Elevation Gain")),
        summary_polyline=None,  # Not available in CSV export
        run_type=None,          # Not reliably available in CSV; can be inferred later
    )


def _try_gpx_fallback(activity_id: int, zf: zipfile.ZipFile) -> Optional[dict]:
    """Attempt to read distance/duration from a GPX file for the activity."""
    gpx_name = next(
        (n for n in zf.namelist() if str(activity_id) in n and n.endswith(".gpx")),
        None,
    )
    if gpx_name is None:
        return None

    try:
        with zf.open(gpx_name) as gpx_file:
            content = gpx_file.read().decode("utf-8", errors="ignore")
            import re

            # Extract timestamps to compute duration
            times = re.findall(r"<time>(.+?)</time>", content)
            duration_s = None
            if len(times) >= 2:
                try:
                    t_start = datetime.fromisoformat(times[0].replace("Z", "+00:00"))
                    t_end = datetime.fromisoformat(times[-1].replace("Z", "+00:00"))
                    computed = int((t_end - t_start).total_seconds())
                    if computed > 0:
                        duration_s = computed
                except ValueError:
                    pass

            result: dict = {}
            if duration_s is not None:
                result["duration_s"] = duration_s
            return result if result else None

    except Exception as e:
        logger.debug(f"GPX fallback failed for activity {activity_id}: {e}")

    return None


def _safe_int(value) -> Optional[int]:
    try:
        return int(float(value)) if value else None
    except (ValueError, TypeError):
        return None


def _safe_float(value) -> Optional[float]:
    try:
        return float(value) if value else None
    except (ValueError, TypeError):
        return None


def import_activities(
    records: list[ActivityRecord],
    profile_id: int,
    db: Session,
    source_filename: Optional[str] = None,
) -> dict:
    """
    Idempotent import of ActivityRecord objects for a profile.

    - Skips any record whose (strava_activity_id, profile_id) already exists in Run.
    - Computes avg_pace_sec_per_km for each new Run.
    - After all inserts, recalculates VDOT from the run with the highest VDOT score
      (distance >= 1000 m and duration > 0) and updates PaceZones.
    - Creates an ImportRecord summarising the operation.

    Returns:
        {
            "imported": int,
            "skipped_duplicates": int,
            "parse_errors": int,
            "vdot": float | None,
            "pace_zones_updated": bool,
        }
    """
    imported = 0
    skipped_duplicates = 0
    parse_errors = 0

    for record in records:
        # Idempotency check
        existing = (
            db.query(Run)
            .filter(
                Run.profile_id == profile_id,
                Run.strava_activity_id == record.strava_activity_id,
            )
            .first()
        )
        if existing:
            skipped_duplicates += 1
            continue

        if record.distance_metres <= 0 or record.duration_seconds <= 0:
            parse_errors += 1
            continue

        avg_pace = (
            (record.duration_seconds / 60.0) / (record.distance_metres / 1000.0) * 60.0
            if record.distance_metres > 0
            else None
        )

        run = Run(
            profile_id=profile_id,
            source="strava",
            strava_activity_id=record.strava_activity_id,
            date=record.date,
            started_at=None,
            distance_metres=float(record.distance_metres),
            duration_seconds=int(record.duration_seconds),
            avg_pace_sec_per_km=avg_pace,
            avg_heart_rate=record.avg_heart_rate,
            elevation_gain_metres=record.elevation_gain_metres,
            run_type=record.run_type,
            notes=None,
        )
        db.add(run)
        imported += 1

    db.flush()  # flush so the new runs are visible in subsequent queries

    # -----------------------------------------------------------------------
    # Recalculate VDOT from the run with the highest VDOT score
    # Candidates: distance >= 1000 m and duration > 0
    # -----------------------------------------------------------------------
    vdot: Optional[float] = None
    pace_zones_updated = False

    # Require at least 3 km to get a meaningful VDOT estimate.
    # Short efforts (e.g. 200 m strides) produce astronomically inflated scores.
    MIN_VDOT_DISTANCE_M = 3000

    candidate_runs = (
        db.query(Run)
        .filter(
            Run.profile_id == profile_id,
            Run.distance_metres >= MIN_VDOT_DISTANCE_M,
            Run.duration_seconds > 0,
        )
        .all()
    )

    best_vdot: Optional[float] = None
    for run in candidate_runs:
        try:
            v = calculate_vdot(run.distance_metres, run.duration_seconds)
            # Sanity-check: realistic VDOT range is roughly 20–85
            if 20 <= v <= 85:
                if best_vdot is None or v > best_vdot:
                    best_vdot = v
        except Exception:
            pass

    if best_vdot is not None:
        try:
            vdot = best_vdot
            zones = derive_pace_zones(vdot)

            pace_zone_record = (
                db.query(PaceZones)
                .filter(PaceZones.profile_id == profile_id)
                .first()
            )
            if pace_zone_record is None:
                pace_zone_record = PaceZones(profile_id=profile_id)
                db.add(pace_zone_record)

            pace_zone_record.vdot = vdot
            pace_zone_record.easy_min_sec_per_km = zones.easy_min_sec_per_km
            pace_zone_record.easy_max_sec_per_km = zones.easy_max_sec_per_km
            pace_zone_record.moderate_min_sec_per_km = zones.moderate_min_sec_per_km
            pace_zone_record.moderate_max_sec_per_km = zones.moderate_max_sec_per_km
            pace_zone_record.threshold_min_sec_per_km = zones.threshold_min_sec_per_km
            pace_zone_record.threshold_max_sec_per_km = zones.threshold_max_sec_per_km
            pace_zone_record.vo2max_min_sec_per_km = zones.vo2max_min_sec_per_km
            pace_zone_record.vo2max_max_sec_per_km = zones.vo2max_max_sec_per_km
            pace_zone_record.anaerobic_min_sec_per_km = zones.anaerobic_min_sec_per_km
            pace_zone_record.anaerobic_max_sec_per_km = zones.anaerobic_max_sec_per_km
            pace_zones_updated = True
            logger.info(f"VDOT recalculated for profile {profile_id}: {vdot:.1f}")
        except Exception as e:
            logger.warning(f"VDOT recalculation failed: {e}")
            vdot = None

    # -----------------------------------------------------------------------
    # Record the import in ImportRecord
    # -----------------------------------------------------------------------
    import_record = ImportRecord(
        profile_id=profile_id,
        activities_imported=imported,
        duplicates_skipped=skipped_duplicates,
        parse_errors=parse_errors,
        vdot_calculated=vdot,
        source_filename=source_filename,
    )
    db.add(import_record)
    db.commit()

    return {
        "imported": imported,
        "skipped_duplicates": skipped_duplicates,
        "parse_errors": parse_errors,
        "vdot": vdot,
        "pace_zones_updated": pace_zones_updated,
    }
