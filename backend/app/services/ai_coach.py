"""AI Coach service — Gemini API integration for plan generation and adaptation."""
import hashlib
import json
import asyncio
import logging
import time
from datetime import date, timedelta
from typing import Any

import google.generativeai as genai
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.orm import (
    Profile, RaceGoal, TrainingPlan, TrainingBlock, Workout, PaceZones
)
from app.services.vdot import get_pace_zone_bounds

logger = logging.getLogger(__name__)

ALLOWED_WORKOUT_TYPES = {"easy", "tempo", "interval", "hills", "long", "race", "rest", "recovery"}

# Simple in-memory token bucket for Gemini rate limiting (≤15 RPM)
_last_call_times: list[float] = []
_RPM_LIMIT = 14  # stay safely under 15


async def _rate_limited_generate(model, prompt: str, generation_config=None) -> str:
    """Call Gemini with rate limiting and exponential backoff retry."""
    global _last_call_times
    now = time.time()
    # Remove calls older than 60 seconds
    _last_call_times = [t for t in _last_call_times if now - t < 60]
    if len(_last_call_times) >= _RPM_LIMIT:
        wait = 60 - (now - _last_call_times[0]) + 1
        logger.info(f"Rate limit: waiting {wait:.1f}s before Gemini call")
        await asyncio.sleep(wait)

    for attempt in range(3):
        try:
            _last_call_times.append(time.time())
            response = model.generate_content(prompt, generation_config=generation_config)
            return response.text
        except Exception as e:
            if attempt == 2:
                raise
            wait = 2 ** attempt
            logger.warning(f"Gemini attempt {attempt+1} failed: {e}. Retrying in {wait}s")
            await asyncio.sleep(wait)


def _get_model():
    settings = get_settings()
    genai.configure(api_key=settings.gemini_api_key)
    return genai.GenerativeModel("gemini-2.0-flash")


def _build_plan_prompt(profile: Profile, race_goal: RaceGoal, pace_zones: PaceZones | None) -> str:
    weeks_to_race = max(1, (race_goal.target_date - date.today()).days // 7)
    distance_km = race_goal.distance_metres / 1000

    pace_info = ""
    if pace_zones and pace_zones.easy_min_sec_per_km:
        easy_min = pace_zones.easy_min_sec_per_km
        easy_max = pace_zones.easy_max_sec_per_km
        pace_info = f"Current pace zones: Easy {easy_max//60}:{easy_max%60:02d}–{easy_min//60}:{easy_min%60:02d} min/km"

    return f"""You are an expert running coach. Generate a structured training plan as JSON.

Runner profile:
- Age: {_age(profile.date_of_birth)} years
- Sex: {profile.biological_sex or 'not specified'}
- Current weekly km: {profile.current_weekly_km or 'unknown'}
- Longest recent run: {profile.longest_recent_run_km or 'unknown'} km
- Injury notes: {profile.injury_notes or 'none'}
{pace_info}

Race goal: {distance_km:.1f} km on {race_goal.target_date.isoformat()} ({weeks_to_race} weeks away)
Label: {race_goal.label or 'Race'}

Generate a {weeks_to_race}-week training plan with Training Blocks.

CRITICAL RULES:
1. Use ONLY these workout_type values: easy, tempo, interval, hills, long, race, rest, recovery
2. All distances in metres (integers)
3. Each workout must have distance_metres as primary target (no time-based workouts)
4. Include at least 1 rest or recovery day per week
5. No more than 1 quality workout (interval/tempo/hills/long) per day
6. For plans ≥ 8 weeks, include a final "Taper" block with 20-40% volume reduction
7. Each workout step must have: sequence, label, distance_metres, pace_zone, description
8. pace_zone must be one of: easy, moderate, threshold, vo2max, anaerobic

Return ONLY valid JSON matching this schema:
{{
  "blocks": [
    {{
      "name": "Base Building",
      "start_date": "YYYY-MM-DD",
      "end_date": "YYYY-MM-DD",
      "workouts": [
        {{
          "scheduled_date": "YYYY-MM-DD",
          "workout_type": "easy",
          "target_distance_metres": 8000,
          "target_pace_zone": "easy",
          "target_hr_zone": 2,
          "coaching_note": "Easy conversational run to build aerobic base.",
          "steps": [
            {{
              "sequence": 1,
              "label": "Easy Run",
              "distance_metres": 8000,
              "pace_zone": "easy",
              "hr_zone": 2,
              "description": "Run at a comfortable conversational pace throughout."
            }}
          ]
        }}
      ]
    }}
  ]
}}"""


def _age(dob) -> int:
    if not dob:
        return 30
    from datetime import date as d
    today = d.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


async def generate_plan(profile_id: int, race_goal_id: int, db: Session) -> TrainingPlan:
    """Generate a new training plan for the given profile and race goal."""
    profile = db.query(Profile).filter(Profile.id == profile_id).first()
    race_goal = db.query(RaceGoal).filter(
        RaceGoal.id == race_goal_id, RaceGoal.profile_id == profile_id
    ).first()
    pace_zones = db.query(PaceZones).filter(PaceZones.profile_id == profile_id).first()

    if not profile or not race_goal:
        raise ValueError("Profile or race goal not found")

    prompt = _build_plan_prompt(profile, race_goal, pace_zones)
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()

    model = _get_model()
    generation_config = genai.types.GenerationConfig(
        response_mime_type="application/json",
        temperature=0.3,
    )

    raw_json = await _rate_limited_generate(model, prompt, generation_config)
    plan_data = json.loads(raw_json)

    # Validate workout types — replace invalid types with "easy"
    for block in plan_data.get("blocks", []):
        for workout in block.get("workouts", []):
            wtype = workout.get("workout_type", "easy")
            if wtype not in ALLOWED_WORKOUT_TYPES:
                workout["workout_type"] = "easy"
                logger.warning(f"Invalid workout type '{wtype}' replaced with 'easy'")

    # Archive any existing active plan
    existing = db.query(TrainingPlan).filter(
        TrainingPlan.profile_id == profile_id,
        TrainingPlan.status == "active"
    ).first()
    if existing:
        existing.status = "archived"

    # Create new plan
    plan = TrainingPlan(
        profile_id=profile_id,
        race_goal_id=race_goal_id,
        start_date=date.today(),
        end_date=race_goal.target_date,
        status="active",
        gemini_prompt_hash=prompt_hash,
    )
    db.add(plan)
    db.flush()

    for seq, block_data in enumerate(plan_data.get("blocks", [])):
        block = TrainingBlock(
            profile_id=profile_id,
            plan_id=plan.id,
            name=block_data["name"],
            start_date=date.fromisoformat(block_data["start_date"]),
            end_date=date.fromisoformat(block_data["end_date"]),
            sequence=seq,
        )
        db.add(block)
        db.flush()

        for workout_data in block_data.get("workouts", []):
            workout = Workout(
                profile_id=profile_id,
                block_id=block.id,
                plan_id=plan.id,
                scheduled_date=date.fromisoformat(workout_data["scheduled_date"]),
                workout_type=workout_data.get("workout_type", "easy"),
                target_distance_metres=workout_data.get("target_distance_metres"),
                target_pace_zone=workout_data.get("target_pace_zone", "easy"),
                target_hr_zone=workout_data.get("target_hr_zone"),
                steps=workout_data.get("steps", []),
                coaching_note=workout_data.get("coaching_note"),
                status="scheduled",
            )
            db.add(workout)

    db.commit()
    db.refresh(plan)
    return plan


async def adapt_plan(trigger: str, context: dict, profile_id: int, db: Session) -> bool:
    """
    Adapt the active training plan based on a trigger event.
    Returns True if adaptation was applied.

    Triggers: "skipped_workout", "run_deviation", "rpe_high", "injury", "fitness_change"
    """
    from app.services.taper_calculator import should_block_volume_increase

    active_plan = db.query(TrainingPlan).filter(
        TrainingPlan.profile_id == profile_id,
        TrainingPlan.status == "active"
    ).first()

    if not active_plan:
        return False

    taper_active = should_block_volume_increase(profile_id, db)

    # Build taper instruction if taper is active
    taper_instruction = ""
    if taper_active:
        taper_instruction = (
            "\nIMPORTANT: The athlete is currently in their taper phase. "
            "Do NOT increase training volume. Maintain or reduce volume only.\n"
        )

    # Build adaptation prompt
    prompt = f"""You are an expert running coach. A training plan needs adaptation.
{taper_instruction}
Trigger: {trigger}
Context: {json.dumps(context)}

Rules:
- Use ONLY workout types: easy, tempo, interval, hills, long, race, rest, recovery
- All distances in metres
- {"Do NOT increase weekly volume — taper phase is active" if taper_active else "Adjust training load appropriately"}
- Preserve the race goal date
- Return JSON with the same plan schema as before, containing only the REMAINING workouts from today onwards

Return a brief JSON object with key "adaptation_applied": true/false and "message": "description of change"."""

    model = _get_model()
    try:
        raw = await _rate_limited_generate(model, prompt)
        result = json.loads(raw)
        logger.info(f"Plan adaptation for profile {profile_id}: {result.get('message', 'applied')}")
        return result.get("adaptation_applied", False)
    except Exception as e:
        logger.error(f"Plan adaptation failed: {e}")
        return False
