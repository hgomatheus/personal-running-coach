from dataclasses import dataclass


@dataclass
class HRZoneValues:
    max_hr: int
    zone1_max: int   # 60% max HR
    zone2_max: int   # 70% max HR
    zone3_max: int   # 80% max HR
    zone4_max: int   # 90% max HR
    zone5_max: int   # 100% max HR


def calculate_hr_zones(max_hr: int) -> HRZoneValues:
    """Calculate 5 HR zones based on max HR using percentage model."""
    return HRZoneValues(
        max_hr=max_hr,
        zone1_max=round(max_hr * 0.60),
        zone2_max=round(max_hr * 0.70),
        zone3_max=round(max_hr * 0.80),
        zone4_max=round(max_hr * 0.90),
        zone5_max=max_hr,
    )


def estimate_max_hr(age_years: int, biological_sex: str) -> int:
    """
    Estimate max HR using the Tanaka formula (more accurate than 220-age):
    Max HR = 208 - (0.7 × age)

    The sex parameter is accepted for future refinement but the Tanaka formula
    is sex-neutral and widely used.
    """
    return round(208 - 0.7 * age_years)


def age_from_dob(date_of_birth) -> int:
    """Calculate age in years from date of birth."""
    from datetime import date
    today = date.today()
    return today.year - date_of_birth.year - (
        (today.month, today.day) < (date_of_birth.month, date_of_birth.day)
    )
