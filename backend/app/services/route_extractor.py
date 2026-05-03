"""Route extractor — extract and deduplicate GPS polylines from Strava run data."""
import hashlib
import logging
import math
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.orm import Run, RouteRecord

logger = logging.getLogger(__name__)

try:
    import polyline as polyline_lib
    _HAS_POLYLINE = True
except ImportError:
    _HAS_POLYLINE = False
    logger.warning("polyline package not available — route extraction disabled")


def _decode_polyline(encoded: str) -> list[tuple[float, float]]:
    """Decode a Google encoded polyline string to list of (lat, lon) tuples."""
    if _HAS_POLYLINE:
        return polyline_lib.decode(encoded)
    # Minimal fallback decoder
    coords = []
    index = 0
    lat = 0
    lng = 0
    while index < len(encoded):
        for is_lng in (False, True):
            result = 0
            shift = 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            value = ~(result >> 1) if result & 1 else result >> 1
            if is_lng:
                lng += value
            else:
                lat += value
        coords.append((lat / 1e5, lng / 1e5))
    return coords


def _douglas_peucker(points: list[tuple[float, float]], epsilon: float) -> list[tuple[float, float]]:
    """
    Simplify a polyline using the Douglas-Peucker algorithm.
    epsilon is in metres.
    """
    if len(points) <= 2:
        return points

    # Find the point with the maximum distance from the line between first and last
    max_dist = 0.0
    max_idx = 0
    start = points[0]
    end = points[-1]

    for i in range(1, len(points) - 1):
        dist = _point_to_line_distance(points[i], start, end)
        if dist > max_dist:
            max_dist = dist
            max_idx = i

    if max_dist > epsilon:
        left = _douglas_peucker(points[:max_idx + 1], epsilon)
        right = _douglas_peucker(points[max_idx:], epsilon)
        return left[:-1] + right
    else:
        return [start, end]


def _point_to_line_distance(
    point: tuple[float, float],
    line_start: tuple[float, float],
    line_end: tuple[float, float],
) -> float:
    """Calculate perpendicular distance from a point to a line (in metres, approx)."""
    # Convert lat/lon differences to approximate metres
    lat_m = 111320.0  # metres per degree latitude
    lon_m = 111320.0 * math.cos(math.radians(line_start[0]))

    px = (point[1] - line_start[1]) * lon_m
    py = (point[0] - line_start[0]) * lat_m
    dx = (line_end[1] - line_start[1]) * lon_m
    dy = (line_end[0] - line_start[0]) * lat_m

    line_len_sq = dx * dx + dy * dy
    if line_len_sq == 0:
        return math.sqrt(px * px + py * py)

    t = max(0, min(1, (px * dx + py * dy) / line_len_sq))
    proj_x = t * dx
    proj_y = t * dy
    return math.sqrt((px - proj_x) ** 2 + (py - proj_y) ** 2)


def _polyline_fingerprint(points: list[tuple[float, float]]) -> str:
    """Compute SHA-256 fingerprint of a simplified polyline."""
    coords_str = ";".join(f"{lat:.5f},{lon:.5f}" for lat, lon in points)
    return hashlib.sha256(coords_str.encode()).hexdigest()


def _haversine_distance(points: list[tuple[float, float]]) -> float:
    """Calculate total distance of a polyline in metres using haversine formula."""
    total = 0.0
    R = 6371000  # Earth radius in metres
    for i in range(len(points) - 1):
        lat1, lon1 = math.radians(points[i][0]), math.radians(points[i][1])
        lat2, lon2 = math.radians(points[i + 1][0]), math.radians(points[i + 1][1])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        total += 2 * R * math.asin(math.sqrt(a))
    return total


def extract_routes(profile_id: int, db: Session) -> int:
    """
    Extract GPS routes from Run records with raw_strava_data containing map.summary_polyline.
    Computes SHA-256 fingerprint of simplified polyline (Douglas-Peucker ε=10m).
    Upserts RouteRecord (run_count, last_used_at, workout_type_affinity).
    Returns the number of routes upserted.
    """
    runs = (
        db.query(Run)
        .filter(
            Run.profile_id == profile_id,
            Run.raw_strava_data.isnot(None),
        )
        .all()
    )

    upserted = 0
    for run in runs:
        raw = run.raw_strava_data or {}
        polyline_str = (raw.get("map") or {}).get("summary_polyline", "")
        if not polyline_str:
            continue

        try:
            points = _decode_polyline(polyline_str)
            if len(points) < 2:
                continue

            simplified = _douglas_peucker(points, epsilon=10.0)
            fingerprint = _polyline_fingerprint(simplified)
            distance_m = _haversine_distance(points)

            # Upsert RouteRecord
            existing = (
                db.query(RouteRecord)
                .filter(
                    RouteRecord.profile_id == profile_id,
                    RouteRecord.fingerprint == fingerprint,
                )
                .first()
            )

            if existing:
                existing.run_count += 1
                existing.last_used_at = run.started_at or datetime.now(timezone.utc)
                if run.run_type:
                    existing.workout_type_affinity = run.run_type
            else:
                route = RouteRecord(
                    profile_id=profile_id,
                    polyline=polyline_str,
                    fingerprint=fingerprint,
                    typical_distance_metres=distance_m,
                    run_count=1,
                    last_used_at=run.started_at or datetime.now(timezone.utc),
                    workout_type_affinity=run.run_type,
                )
                db.add(route)
                upserted += 1

        except Exception as e:
            logger.warning(f"Route extraction failed for run {run.id}: {e}")
            continue

    db.commit()
    logger.info(f"Route extraction for profile {profile_id}: {upserted} new routes")
    return upserted


def get_suggestions(workout, profile_id: int, db: Session) -> list:
    """
    Get route suggestions for a workout.
    Filters by ±20% of workout target distance.
    Ranks by type affinity, then run_count, then recency.
    Returns top 3 RouteRecord objects.
    """
    target_distance = workout.target_distance_metres or 0
    if target_distance <= 0:
        return []

    low = target_distance * 0.80
    high = target_distance * 1.20

    routes = (
        db.query(RouteRecord)
        .filter(
            RouteRecord.profile_id == profile_id,
            RouteRecord.typical_distance_metres >= low,
            RouteRecord.typical_distance_metres <= high,
        )
        .all()
    )

    # Rank: type affinity match first, then run_count desc, then recency desc
    workout_type = workout.workout_type

    def rank_key(r: RouteRecord):
        affinity_match = 1 if r.workout_type_affinity == workout_type else 0
        return (-affinity_match, -r.run_count, -r.last_used_at.timestamp())

    routes.sort(key=rank_key)
    return routes[:3]
