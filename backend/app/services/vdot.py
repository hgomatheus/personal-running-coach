import math
from dataclasses import dataclass


@dataclass
class PaceZoneValues:
    easy_min_sec_per_km: int      # slower bound (higher number)
    easy_max_sec_per_km: int      # faster bound (lower number)
    moderate_min_sec_per_km: int
    moderate_max_sec_per_km: int
    threshold_min_sec_per_km: int
    threshold_max_sec_per_km: int
    vo2max_min_sec_per_km: int
    vo2max_max_sec_per_km: int
    anaerobic_min_sec_per_km: int
    anaerobic_max_sec_per_km: int


def calculate_vdot(distance_metres: float, duration_seconds: int) -> float:
    """
    Calculate VDOT from a race result using Jack Daniels formula.

    v = speed in m/min
    t = duration in minutes
    VO2 = -4.60 + 0.182258 * v + 0.000104 * v^2
    pct_vo2max = 0.8 + 0.1894393 * e^(-0.012778 * t) + 0.2989558 * e^(-0.1932605 * t)
    VDOT = VO2 / pct_vo2max
    """
    t = duration_seconds / 60.0  # minutes
    v = distance_metres / t      # m/min
    vo2 = -4.60 + 0.182258 * v + 0.000104 * v ** 2
    pct_vo2max = (
        0.8
        + 0.1894393 * math.exp(-0.012778 * t)
        + 0.2989558 * math.exp(-0.1932605 * t)
    )
    return vo2 / pct_vo2max


def derive_pace_zones(vdot: float) -> PaceZoneValues:
    """
    Derive training pace zones from VDOT using Jack Daniels percentage bands.

    Zone percentages of VDOT-equivalent velocity:
    - Easy:      62–70%
    - Moderate (Marathon): 75–84%
    - Threshold: 86–88%
    - VO2 Max:   95–100%
    - Anaerobic: 105–110%

    VDOT-equivalent velocity (m/min) is derived by inverting the VO2 formula
    at 100% VO2max (t → ∞, so pct_vo2max → 0.8 + 0 + 0 = 0.8... but we use
    a simpler approximation: v_eq = (vdot + 4.60) / 0.182258 for the linear term).

    For practical purposes, use the established lookup approach:
    vdot_velocity_m_per_min = solve for v where VO2(v) = vdot (at pct_vo2max=1.0)
    Use Newton's method or the quadratic formula on:
    0.000104*v^2 + 0.182258*v - (vdot + 4.60) = 0
    """
    # Solve quadratic: 0.000104*v^2 + 0.182258*v - (vdot + 4.60) = 0
    a = 0.000104
    b = 0.182258
    c = -(vdot + 4.60)
    discriminant = b ** 2 - 4 * a * c
    v_eq = (-b + math.sqrt(discriminant)) / (2 * a)  # m/min at 100% VO2max

    def v_to_sec_per_km(v_m_per_min: float) -> int:
        """Convert m/min to sec/km."""
        return int(round(60000 / v_m_per_min))

    # Zone boundaries as (min_pct, max_pct) of v_eq
    # Note: min_pct produces the SLOWER pace (higher sec/km)
    #       max_pct produces the FASTER pace (lower sec/km)
    zones = {
        "easy":      (0.62, 0.70),
        "moderate":  (0.75, 0.84),
        "threshold": (0.86, 0.88),
        "vo2max":    (0.95, 1.00),
        "anaerobic": (1.05, 1.10),
    }

    return PaceZoneValues(
        easy_min_sec_per_km=v_to_sec_per_km(v_eq * zones["easy"][0]),
        easy_max_sec_per_km=v_to_sec_per_km(v_eq * zones["easy"][1]),
        moderate_min_sec_per_km=v_to_sec_per_km(v_eq * zones["moderate"][0]),
        moderate_max_sec_per_km=v_to_sec_per_km(v_eq * zones["moderate"][1]),
        threshold_min_sec_per_km=v_to_sec_per_km(v_eq * zones["threshold"][0]),
        threshold_max_sec_per_km=v_to_sec_per_km(v_eq * zones["threshold"][1]),
        vo2max_min_sec_per_km=v_to_sec_per_km(v_eq * zones["vo2max"][0]),
        vo2max_max_sec_per_km=v_to_sec_per_km(v_eq * zones["vo2max"][1]),
        anaerobic_min_sec_per_km=v_to_sec_per_km(v_eq * zones["anaerobic"][0]),
        anaerobic_max_sec_per_km=v_to_sec_per_km(v_eq * zones["anaerobic"][1]),
    )


def get_pace_zone_bounds(zone_name: str, pace_zones) -> tuple[int, int]:
    """
    Return (min_sec_per_km, max_sec_per_km) for a named pace zone.
    min = faster bound (lower number), max = slower bound (higher number).
    pace_zones can be a PaceZones ORM object or PaceZoneValues dataclass.
    """
    zone_map = {
        "easy":      ("easy_max_sec_per_km", "easy_min_sec_per_km"),
        "moderate":  ("moderate_max_sec_per_km", "moderate_min_sec_per_km"),
        "threshold": ("threshold_max_sec_per_km", "threshold_min_sec_per_km"),
        "vo2max":    ("vo2max_max_sec_per_km", "vo2max_min_sec_per_km"),
        "anaerobic": ("anaerobic_max_sec_per_km", "anaerobic_min_sec_per_km"),
    }
    fast_attr, slow_attr = zone_map.get(
        zone_name, ("easy_max_sec_per_km", "easy_min_sec_per_km")
    )
    fast = getattr(pace_zones, fast_attr, None) or 300
    slow = getattr(pace_zones, slow_attr, None) or 420
    return (fast, slow)  # (faster_bound, slower_bound)


def pace_zone_velocity_m_per_s(zone_name: str, pace_zones) -> float:
    """Return the midpoint velocity in m/s for a pace zone (used for duration estimates)."""
    fast, slow = get_pace_zone_bounds(zone_name, pace_zones)
    mid_sec_per_km = (fast + slow) / 2
    return 1000 / mid_sec_per_km  # m/s
