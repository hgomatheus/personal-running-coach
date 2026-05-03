"""Pydantic request/response schemas for the Personal Running Coach API."""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

class ProfileUpdate(BaseModel):
    display_name: str = Field(min_length=1, max_length=50)
    date_of_birth: date | None = None
    biological_sex: Literal["male", "female", "other"] | None = None
    current_weekly_km: float | None = Field(None, gt=0)
    longest_recent_run_km: float | None = Field(None, gt=0)
    injury_notes: str | None = None


class ProfileResponse(BaseModel):
    id: int
    display_name: str
    date_of_birth: date | None
    biological_sex: str | None
    current_weekly_km: float | None
    longest_recent_run_km: float | None
    injury_notes: str | None
    created_at: datetime | None
    updated_at: datetime | None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Profile Settings
# ---------------------------------------------------------------------------

class ProfileSettingsUpdate(BaseModel):
    notification_enabled: bool
    notification_time: time | None = None
    push_subscription: dict | None = None


class ProfileSettingsResponse(BaseModel):
    id: int
    profile_id: int
    notification_enabled: bool
    notification_time: time | None
    push_subscription: dict | None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Race Goal
# ---------------------------------------------------------------------------

class RaceGoalCreate(BaseModel):
    distance_metres: float = Field(gt=0)
    target_date: date
    label: str | None = None
    is_active: bool = True


class RaceGoalResponse(BaseModel):
    id: int
    profile_id: int
    distance_metres: float
    target_date: date
    label: str | None
    is_active: bool
    created_at: datetime | None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Training Plan / Block
# ---------------------------------------------------------------------------

class TrainingPlanResponse(BaseModel):
    id: int
    profile_id: int
    race_goal_id: int | None
    start_date: date
    end_date: date
    status: str
    gemini_prompt_hash: str | None
    created_at: datetime | None
    updated_at: datetime | None

    model_config = {"from_attributes": True}


class TrainingBlockResponse(BaseModel):
    id: int
    profile_id: int
    plan_id: int
    name: str
    start_date: date
    end_date: date
    sequence: int

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Workout
# ---------------------------------------------------------------------------

class WorkoutStepResponse(BaseModel):
    sequence: int
    label: str
    distance_metres: float
    estimated_duration_seconds: int  # computed: distance_metres / pace_zone_velocity; read-only
    pace_zone: str | None
    hr_zone: int | None
    description: str | None


class WorkoutResponse(BaseModel):
    id: int
    profile_id: int
    block_id: int | None
    plan_id: int
    scheduled_date: date
    workout_type: str
    target_distance_metres: float | None
    estimated_duration_seconds: int | None  # computed: target_distance_metres / pace_zone_velocity
    target_pace_zone: str | None
    target_hr_zone: int | None
    steps: list[WorkoutStepResponse]
    coaching_note: str | None
    status: str
    rpe_score: int | None
    matched_run_id: int | None
    created_at: datetime | None
    updated_at: datetime | None

    model_config = {"from_attributes": True}


class WorkoutPatch(BaseModel):
    status: Literal["completed", "skipped"] | None = None
    rpe_score: int | None = Field(None, ge=1, le=10)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

class RunCreate(BaseModel):
    date: date
    distance_metres: float = Field(gt=0)
    duration_seconds: int = Field(gt=0)
    avg_heart_rate: int | None = Field(None, ge=30, le=250)
    elevation_gain_metres: float | None = None
    run_type: str | None = None
    notes: str | None = None


class RunUpdate(BaseModel):
    date: Optional[date] = None
    distance_metres: float | None = Field(None, gt=0)
    duration_seconds: int | None = Field(None, gt=0)
    avg_heart_rate: int | None = Field(None, ge=30, le=250)
    elevation_gain_metres: float | None = None
    run_type: str | None = None
    notes: str | None = None


class RunResponse(BaseModel):
    id: int
    profile_id: int
    source: str
    strava_activity_id: int | None
    date: date
    started_at: datetime | None
    distance_metres: float
    duration_seconds: int
    avg_pace_sec_per_km: float | None
    avg_heart_rate: int | None
    elevation_gain_metres: float | None
    run_type: str | None
    notes: str | None
    created_at: datetime | None
    updated_at: datetime | None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Pace Zones / HR Zones
# ---------------------------------------------------------------------------

class PaceZonesResponse(BaseModel):
    id: int
    profile_id: int
    vdot: float | None
    easy_min_sec_per_km: int | None
    easy_max_sec_per_km: int | None
    moderate_min_sec_per_km: int | None
    moderate_max_sec_per_km: int | None
    threshold_min_sec_per_km: int | None
    threshold_max_sec_per_km: int | None
    vo2max_min_sec_per_km: int | None
    vo2max_max_sec_per_km: int | None
    anaerobic_min_sec_per_km: int | None
    anaerobic_max_sec_per_km: int | None
    updated_at: datetime | None

    model_config = {"from_attributes": True}


class HRZonesResponse(BaseModel):
    id: int
    profile_id: int
    max_hr: int
    zone1_max: int
    zone2_max: int
    zone3_max: int
    zone4_max: int
    zone5_max: int
    updated_at: datetime | None

    model_config = {"from_attributes": True}


class ZoneRecalculateRequest(BaseModel):
    """Provide a recent race result to recalculate VDOT and pace zones."""
    distance_metres: float = Field(gt=0)
    duration_seconds: int = Field(gt=0)
    max_hr: int | None = Field(None, ge=100, le=250)


# ---------------------------------------------------------------------------
# Bulk Import
# ---------------------------------------------------------------------------

class BulkImportResponse(BaseModel):
    imported: int
    skipped_duplicates: int
    parse_errors: int
    vdot: float | None
    pace_zones_updated: bool


# ---------------------------------------------------------------------------
# Post-Run Analysis
# ---------------------------------------------------------------------------

class KmSplit(BaseModel):
    km: int
    pace_sec_per_km: float | None
    avg_hr: int | None


class PostRunAnalysisResponse(BaseModel):
    run_id: int
    workout_id: int
    target_distance_km: float
    actual_distance_km: float
    target_pace_zone: str
    actual_avg_pace_sec_per_km: float | None
    pace_on_target: bool | None          # None if pace data unavailable
    pace_comparison: str | None          # "on_target" | "faster" | "slower"
    target_hr_zone: int | None
    actual_avg_hr: int | None
    actual_elevation_gain_metres: float | None
    km_splits: list[KmSplit]             # per-km pace + HR (empty if no GPS data)
    coaching_summary: str                # AI-generated plain-language summary


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------

class WeatherForecastResponse(BaseModel):
    workout_id: int
    forecast_date: date
    temperature_c: float
    humidity_pct: float
    wind_kmh: float
    conditions: str
    advisories: list[str]                # e.g. ["heat", "wind"] — empty if no advisories
    cached: bool


class ProfileWeatherSettingsUpdate(BaseModel):
    location_name: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    weather_advisories_enabled: bool = True


class ProfileWeatherSettingsResponse(BaseModel):
    id: int
    profile_id: int
    location_name: str | None
    latitude: float | None
    longitude: float | None
    weather_advisories_enabled: bool

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Route Suggestions
# ---------------------------------------------------------------------------

class RouteRecordResponse(BaseModel):
    id: int
    polyline: str
    typical_distance_km: float
    run_count: int
    last_used_at: datetime
    workout_type_affinity: str | None
    thumbnail_url: str | None            # Static map tile URL rendered from polyline


# ---------------------------------------------------------------------------
# Taper
# ---------------------------------------------------------------------------

class TaperGuidance(BaseModel):
    target_mileage_reduction_pct: int
    sleep_nutrition_reminder: str
    sluggishness_note: str


class TaperStatusResponse(BaseModel):
    taper_active: bool
    days_until_race: int | None
    taper_week: int | None               # 1-indexed week within taper (1 = first taper week)
    volume_reduction_pct: int | None     # e.g. 30 for 30% reduction
    guidance: TaperGuidance | None


# ---------------------------------------------------------------------------
# Data Export / Import
# ---------------------------------------------------------------------------

class ProfileDataExport(BaseModel):
    schema_version: str          # e.g. "1.0"
    exported_at: datetime
    profile: dict                # full Profile record
    pace_zones: dict | None
    hr_zones: dict | None
    race_goals: list[dict]
    training_plans: list[dict]   # each plan includes its blocks and workouts
    runs: list[dict]
    import_history: list[dict]


class ImportDataRequest(BaseModel):
    mode: Literal["merge", "replace"]  # "replace" deletes all existing data first


# ---------------------------------------------------------------------------
# App Settings
# ---------------------------------------------------------------------------

class AppSettingsResponse(BaseModel):
    id: int
    strava_sync_interval_minutes: int
    backup_enabled: bool
    backup_retention_days: int

    model_config = {"from_attributes": True}


class AppSettingsUpdate(BaseModel):
    strava_sync_interval_minutes: int | None = Field(None, ge=5, le=60)
    backup_enabled: bool | None = None
    backup_retention_days: int | None = Field(None, ge=1, le=365)


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------

class BackupRecordResponse(BaseModel):
    id: int
    completed_at: datetime
    file_path: str
    size_bytes: int
    success: bool
    error_message: str | None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str
    database: str
