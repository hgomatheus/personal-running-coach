"""Post-run analysis service — compare actual run metrics to workout targets."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.models.orm import Run, Workout, PaceZones
from app.services.vdot import get_pace_zone_bounds

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class KmSplit:
    km: int
    pace_sec_per_km: float | None
    avg_hr: int | None


@dataclass
class PostRunAnalysisResult:
    run_id: int
    workout_id: int
    target_distance_km: float
    actual_distance_km: float
    target_pace_zone: str
    actual_avg_pace_sec_per_km: float | None
    pace_on_target: bool | None          # None if pace data unavailable
    pace_comparison: str | None          # "on_target" | "faster" | "slower" | None
    target_hr_zone: int | None
    actual_avg_hr: int | None
    actual_elevation_gain_metres: float | None
    km_splits: list[KmSplit] = field(default_factory=list)
    coaching_summary: str = ""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _classify_pace(
    actual_pace: float | None,
    zone_name: str | None,
    pace_zones: PaceZones | None,
) -> tuple[bool | None, str | None]:
    """
    Classify actual pace vs zone bounds.

    Returns (on_target: bool | None, comparison: str | None).
    - "on_target" if pace falls within the target pace zone range
    - "faster"    if pace is faster than the zone's min (lower sec/km)
    - "slower"    if pace is slower than the zone's max (higher sec/km)
    """
    if actual_pace is None or pace_zones is None or not zone_name:
        return None, None

    zone_name = zone_name.lower()
    fast_bound, slow_bound = get_pace_zone_bounds(zone_name, pace_zones)
    # fast_bound = lower sec/km (faster end), slow_bound = higher sec/km (slower end)

    if fast_bound <= actual_pace <= slow_bound:
        return True, "on_target"
    elif actual_pace < fast_bound:
        return False, "faster"
    else:
        return False, "slower"


def _extract_km_splits(raw_strava_data: dict | None) -> list[KmSplit]:
    """
    Extract per-km splits from raw Strava activity data.

    Strava stores splits in ``splits_metric`` as a list of objects with:
      - ``split``            : 1-indexed km number
      - ``moving_time``      : seconds (not used for pace here)
      - ``average_speed``    : m/s  → pace_sec_per_km = 1000 / average_speed
      - ``average_heartrate``: bpm (optional)
    """
    if not raw_strava_data:
        return []

    splits_metric = raw_strava_data.get("splits_metric", [])
    if not splits_metric:
        return []

    result: list[KmSplit] = []
    for entry in splits_metric:
        km_number = entry.get("split", len(result) + 1)
        avg_speed = entry.get("average_speed")  # m/s

        if avg_speed and avg_speed > 0:
            pace_sec_per_km = 1000.0 / avg_speed
        else:
            pace_sec_per_km = None

        avg_hr_raw = entry.get("average_heartrate")
        avg_hr = int(round(avg_hr_raw)) if avg_hr_raw is not None else None

        result.append(KmSplit(
            km=int(km_number),
            pace_sec_per_km=pace_sec_per_km,
            avg_hr=avg_hr,
        ))

    return result


async def _get_coaching_summary(
    run: Run,
    workout: Workout,
    pace_comparison: str | None,
    km_splits: list[KmSplit],
) -> str:
    """
    Call Gemini (gemini-2.0-flash) for a 2–3 sentence coaching summary.
    Falls back to a canned message if the API call fails.
    """
    actual_km = run.distance_metres / 1000
    target_km = (workout.target_distance_metres or 0) / 1000

    pace_str = ""
    if run.avg_pace_sec_per_km:
        mins = int(run.avg_pace_sec_per_km // 60)
        secs = int(run.avg_pace_sec_per_km % 60)
        pace_str = f"{mins}:{secs:02d} min/km"

    try:
        import google.generativeai as genai
        from app.config import get_settings
        from app.services.ai_coach import _rate_limited_generate, _get_model

        prompt = (
            "You are a supportive running coach. Write a 2-3 sentence coaching summary "
            "for this completed run. Be encouraging, specific, and actionable.\n\n"
            f"Workout type: {workout.workout_type}\n"
            f"Target distance: {target_km:.1f} km\n"
            f"Actual distance: {actual_km:.1f} km\n"
            f"Target pace zone: {workout.target_pace_zone or 'easy'}\n"
            f"Pace comparison: {pace_comparison or 'unknown'}\n"
            f"Average pace: {pace_str or 'not recorded'}\n"
            f"Average HR: {run.avg_heart_rate or 'not recorded'}\n"
            f"Elevation gain: {run.elevation_gain_metres or 0:.0f} m\n"
            f"Number of km splits recorded: {len(km_splits)}\n\n"
            "Focus on what went well and one area to improve. "
            "Keep it to exactly 2-3 sentences."
        )

        model = _get_model()
        summary = await _rate_limited_generate(model, prompt)
        return summary.strip()

    except Exception as exc:
        logger.warning("Gemini coaching summary failed: %s", exc)

    # Fallback summary
    if pace_comparison == "on_target":
        return (
            f"Great work hitting your {target_km:.1f} km target at the right pace. "
            "Consistency like this builds fitness over time. "
            "Keep it up!"
        )
    elif pace_comparison == "faster":
        return (
            f"You ran {actual_km:.1f} km faster than the target pace today. "
            "Remember that easy days should feel easy — saving energy now pays off "
            "in quality sessions later."
        )
    elif pace_comparison == "slower":
        return (
            f"You completed {actual_km:.1f} km today. "
            "Don't worry about pace — focus on completing the distance and recovery. "
            "Every run counts towards your goal."
        )
    else:
        return (
            f"You completed {actual_km:.1f} km today. "
            "Keep up the consistent training — it all adds up!"
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def analyze(
    run: Run,
    workout: Workout,
    pace_zones: PaceZones | None,
) -> PostRunAnalysisResult:
    """
    Analyse a completed run against its matched workout.

    Parameters
    ----------
    run:
        The ``Run`` ORM record for the completed activity.
    workout:
        The ``Workout`` ORM record the run was matched to.
    pace_zones:
        The ``PaceZones`` ORM record for the runner's profile, or ``None``
        if zones have not been calculated yet.

    Returns
    -------
    PostRunAnalysisResult
        A dataclass containing distance comparison, pace comparison,
        per-km splits, and an AI-generated coaching summary.
    """
    target_distance_km = (workout.target_distance_metres or 0) / 1000
    actual_distance_km = run.distance_metres / 1000

    pace_on_target, pace_comparison = _classify_pace(
        run.avg_pace_sec_per_km,
        workout.target_pace_zone,
        pace_zones,
    )

    km_splits = _extract_km_splits(run.raw_strava_data)

    coaching_summary = await _get_coaching_summary(
        run,
        workout,
        pace_comparison,
        km_splits,
    )

    return PostRunAnalysisResult(
        run_id=run.id,
        workout_id=workout.id,
        target_distance_km=target_distance_km,
        actual_distance_km=actual_distance_km,
        target_pace_zone=workout.target_pace_zone or "easy",
        actual_avg_pace_sec_per_km=run.avg_pace_sec_per_km,
        pace_on_target=pace_on_target,
        pace_comparison=pace_comparison,
        target_hr_zone=workout.target_hr_zone,
        actual_avg_hr=run.avg_heart_rate,
        actual_elevation_gain_metres=run.elevation_gain_metres,
        km_splits=km_splits,
        coaching_summary=coaching_summary,
    )
