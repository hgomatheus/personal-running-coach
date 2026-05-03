"""Taper calculator service.

Detects whether the active training plan is in a taper phase and provides
volume guidance.
"""
from datetime import date
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.orm import RaceGoal, TrainingPlan


@dataclass
class TaperGuidance:
    target_mileage_reduction_pct: int
    sleep_nutrition_reminder: str
    sluggishness_note: str


@dataclass
class TaperStatus:
    taper_active: bool
    days_until_race: int | None
    taper_week: int | None          # 1-indexed week within taper (1 = first taper week, days 15-21)
    volume_reduction_pct: int | None
    guidance: TaperGuidance | None


# Guidance text per taper week
_GUIDANCE: dict[int, TaperGuidance] = {
    1: TaperGuidance(
        target_mileage_reduction_pct=20,
        sleep_nutrition_reminder=(
            "Start prioritising sleep (8–9 hours) and increase carbohydrate intake "
            "to top up glycogen stores."
        ),
        sluggishness_note=(
            "Feeling sluggish or heavy-legged is completely normal during taper — "
            "your body is adapting and storing energy for race day."
        ),
    ),
    2: TaperGuidance(
        target_mileage_reduction_pct=30,
        sleep_nutrition_reminder=(
            "Maintain consistent sleep and keep nutrition clean. Avoid introducing "
            "new foods this week."
        ),
        sluggishness_note=(
            "Taper madness is real — restlessness and doubt are common. Trust your "
            "training and resist the urge to add extra miles."
        ),
    ),
    3: TaperGuidance(
        target_mileage_reduction_pct=40,
        sleep_nutrition_reminder=(
            "Race week: hydrate well, eat familiar foods, and aim for 8+ hours of "
            "sleep each night. Lay out your kit the night before."
        ),
        sluggishness_note=(
            "Your legs may feel unusually heavy or flat — this is a sign your muscles "
            "are fully loaded and ready. You are prepared."
        ),
    ),
}


def get_taper_status(profile_id: int, db: Session) -> TaperStatus:
    """
    Check the active plan's race goal and determine if taper is active.

    Taper activates when ≤21 days remain until the race.
    Taper weeks (1-indexed):
      - Week 1: days 15–21 remaining (20% volume reduction)
      - Week 2: days 8–14 remaining  (30% volume reduction)
      - Week 3: days 1–7 remaining   (40% volume reduction)
    """
    active_plan = (
        db.query(TrainingPlan)
        .filter(
            TrainingPlan.profile_id == profile_id,
            TrainingPlan.status == "active",
        )
        .first()
    )
    if not active_plan or not active_plan.race_goal_id:
        return TaperStatus(
            taper_active=False,
            days_until_race=None,
            taper_week=None,
            volume_reduction_pct=None,
            guidance=None,
        )

    race_goal = (
        db.query(RaceGoal)
        .filter(
            RaceGoal.id == active_plan.race_goal_id,
            RaceGoal.profile_id == profile_id,
            RaceGoal.is_active == True,  # noqa: E712
        )
        .first()
    )
    if not race_goal:
        return TaperStatus(
            taper_active=False,
            days_until_race=None,
            taper_week=None,
            volume_reduction_pct=None,
            guidance=None,
        )

    today = date.today()
    days_until_race = (race_goal.target_date - today).days

    if days_until_race > 21 or days_until_race < 0:
        return TaperStatus(
            taper_active=False,
            days_until_race=days_until_race,
            taper_week=None,
            volume_reduction_pct=None,
            guidance=None,
        )

    # Taper is active — determine which week (1-indexed from start of taper).
    # Week 1 = days 15–21 remaining, Week 2 = days 8–14, Week 3 = days 1–7.
    # days_into_taper counts from 0 (day 21) to 20 (day 1).
    # taper_week = (days_into_taper // 7) + 1, clamped to [1, 3].
    days_into_taper = 21 - days_until_race
    taper_week = min(3, (days_into_taper // 7) + 1)

    # Volume reduction increases as race approaches
    # Week 1: 20%, Week 2: 30%, Week 3: 40%
    reduction_map = {1: 20, 2: 30, 3: 40}
    volume_reduction_pct = reduction_map.get(taper_week, 40)

    guidance = _GUIDANCE.get(taper_week, _GUIDANCE[3])

    return TaperStatus(
        taper_active=True,
        days_until_race=days_until_race,
        taper_week=taper_week,
        volume_reduction_pct=volume_reduction_pct,
        guidance=guidance,
    )


def should_block_volume_increase(profile_id: int, db: Session) -> bool:
    """Return True if the taper phase is active and volume should not increase."""
    status = get_taper_status(profile_id, db)
    return status.taper_active
