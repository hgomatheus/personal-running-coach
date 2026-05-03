from sqlalchemy import (
    Column, Integer, String, Float, Boolean, Date, DateTime,
    Time, JSON, ForeignKey, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class Profile(Base):
    __tablename__ = "profile"
    id = Column(Integer, primary_key=True)  # 1 or 2 only
    display_name = Column(String(50), nullable=False, default="Profile 1")
    date_of_birth = Column(Date, nullable=True)
    biological_sex = Column(String(10), nullable=True)  # "male" | "female" | "other"
    current_weekly_km = Column(Float, nullable=True)
    longest_recent_run_km = Column(Float, nullable=True)
    injury_notes = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class ProfileSettings(Base):
    __tablename__ = "profile_settings"
    __table_args__ = (UniqueConstraint("profile_id"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    profile_id = Column(Integer, ForeignKey("profile.id"), nullable=False)
    notification_enabled = Column(Boolean, default=True)
    notification_time = Column(Time, nullable=True)  # default 20:00
    push_subscription = Column(JSON, nullable=True)


class RaceGoal(Base):
    __tablename__ = "race_goal"
    id = Column(Integer, primary_key=True, autoincrement=True)
    profile_id = Column(Integer, ForeignKey("profile.id"), nullable=False)
    distance_metres = Column(Float, nullable=False)
    target_date = Column(Date, nullable=False)
    label = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)


class TrainingPlan(Base):
    __tablename__ = "training_plan"
    id = Column(Integer, primary_key=True, autoincrement=True)
    profile_id = Column(Integer, ForeignKey("profile.id"), nullable=False)
    race_goal_id = Column(Integer, ForeignKey("race_goal.id"), nullable=True)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    status = Column(String(20), default="active")  # "active" | "archived" | "draft"
    gemini_prompt_hash = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class TrainingBlock(Base):
    __tablename__ = "training_block"
    id = Column(Integer, primary_key=True, autoincrement=True)
    profile_id = Column(Integer, ForeignKey("profile.id"), nullable=False)
    plan_id = Column(Integer, ForeignKey("training_plan.id"), nullable=False)
    name = Column(String, nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    sequence = Column(Integer, nullable=False)


class Run(Base):
    __tablename__ = "run"
    id = Column(Integer, primary_key=True, autoincrement=True)
    profile_id = Column(Integer, ForeignKey("profile.id"), nullable=False)
    source = Column(String(10), nullable=False)  # "strava" | "manual"
    strava_activity_id = Column(Integer, nullable=True)
    date = Column(Date, nullable=False)
    started_at = Column(DateTime, nullable=True)
    distance_metres = Column(Float, nullable=False)
    duration_seconds = Column(Integer, nullable=False)
    avg_pace_sec_per_km = Column(Float, nullable=True)
    avg_heart_rate = Column(Integer, nullable=True)
    elevation_gain_metres = Column(Float, nullable=True)
    run_type = Column(String(20), nullable=True)
    notes = Column(String, nullable=True)
    raw_strava_data = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class Workout(Base):
    __tablename__ = "workout"
    id = Column(Integer, primary_key=True, autoincrement=True)
    profile_id = Column(Integer, ForeignKey("profile.id"), nullable=False)
    block_id = Column(Integer, ForeignKey("training_block.id"), nullable=True)
    plan_id = Column(Integer, ForeignKey("training_plan.id"), nullable=False)
    scheduled_date = Column(Date, nullable=False)
    workout_type = Column(String(20), nullable=False)
    # easy|tempo|interval|hills|long|race|rest|recovery
    target_distance_metres = Column(Float, nullable=True)
    target_pace_zone = Column(String(20), nullable=True)
    # easy|moderate|threshold|vo2max|anaerobic
    target_hr_zone = Column(Integer, nullable=True)  # 1-5
    steps = Column(JSON, default=list)
    coaching_note = Column(String, nullable=True)
    status = Column(String(20), default="scheduled")
    # scheduled|completed|skipped|missed
    rpe_score = Column(Integer, nullable=True)
    matched_run_id = Column(Integer, ForeignKey("run.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class PaceZones(Base):
    __tablename__ = "pace_zones"
    __table_args__ = (UniqueConstraint("profile_id"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    profile_id = Column(Integer, ForeignKey("profile.id"), nullable=False)
    vdot = Column(Float, nullable=True)
    easy_min_sec_per_km = Column(Integer, nullable=True)
    easy_max_sec_per_km = Column(Integer, nullable=True)
    moderate_min_sec_per_km = Column(Integer, nullable=True)
    moderate_max_sec_per_km = Column(Integer, nullable=True)
    threshold_min_sec_per_km = Column(Integer, nullable=True)
    threshold_max_sec_per_km = Column(Integer, nullable=True)
    vo2max_min_sec_per_km = Column(Integer, nullable=True)
    vo2max_max_sec_per_km = Column(Integer, nullable=True)
    anaerobic_min_sec_per_km = Column(Integer, nullable=True)
    anaerobic_max_sec_per_km = Column(Integer, nullable=True)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class HeartRateZones(Base):
    __tablename__ = "hr_zones"
    __table_args__ = (UniqueConstraint("profile_id"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    profile_id = Column(Integer, ForeignKey("profile.id"), nullable=False)
    max_hr = Column(Integer, nullable=False)
    zone1_max = Column(Integer, nullable=False)
    zone2_max = Column(Integer, nullable=False)
    zone3_max = Column(Integer, nullable=False)
    zone4_max = Column(Integer, nullable=False)
    zone5_max = Column(Integer, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class StravaToken(Base):
    __tablename__ = "strava_token"
    __table_args__ = (UniqueConstraint("profile_id"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    profile_id = Column(Integer, ForeignKey("profile.id"), nullable=False)
    athlete_id = Column(Integer, nullable=False)
    access_token = Column(String, nullable=False)   # encrypted
    refresh_token = Column(String, nullable=False)  # encrypted
    expires_at = Column(DateTime, nullable=False)
    last_sync_at = Column(DateTime, nullable=True)
    sync_error = Column(String, nullable=True)


class AppSettings(Base):
    __tablename__ = "app_settings"
    id = Column(Integer, primary_key=True)  # always 1
    strava_sync_interval_minutes = Column(Integer, default=15)
    backup_enabled = Column(Boolean, default=True)
    backup_retention_days = Column(Integer, default=30)


class BackupRecord(Base):
    __tablename__ = "backup_record"
    id = Column(Integer, primary_key=True, autoincrement=True)
    completed_at = Column(DateTime, nullable=False)
    file_path = Column(String, nullable=False)
    size_bytes = Column(Integer, nullable=False)
    success = Column(Boolean, nullable=False)
    error_message = Column(String, nullable=True)


class ImportRecord(Base):
    __tablename__ = "import_record"
    id = Column(Integer, primary_key=True, autoincrement=True)
    profile_id = Column(Integer, ForeignKey("profile.id"), nullable=False)
    imported_at = Column(DateTime, default=utcnow)
    activities_imported = Column(Integer, default=0)
    duplicates_skipped = Column(Integer, default=0)
    parse_errors = Column(Integer, default=0)
    vdot_calculated = Column(Float, nullable=True)
    source_filename = Column(String, nullable=True)


class RouteRecord(Base):
    __tablename__ = "route_record"
    id = Column(Integer, primary_key=True, autoincrement=True)
    profile_id = Column(Integer, ForeignKey("profile.id"), nullable=False)
    polyline = Column(String, nullable=False)
    fingerprint = Column(String(64), nullable=False)  # SHA-256 of simplified polyline
    typical_distance_metres = Column(Float, nullable=False)
    run_count = Column(Integer, default=1)
    last_used_at = Column(DateTime, nullable=False)
    workout_type_affinity = Column(String(20), nullable=True)


class WeatherCache(Base):
    __tablename__ = "weather_cache"
    id = Column(Integer, primary_key=True, autoincrement=True)
    location_key = Column(String, nullable=False)
    forecast_date = Column(Date, nullable=False)
    fetched_at = Column(DateTime, nullable=False)
    temperature_c = Column(Float, nullable=False)
    humidity_pct = Column(Float, nullable=False)
    wind_kmh = Column(Float, nullable=False)
    conditions = Column(String, nullable=False)
    raw_response = Column(JSON, nullable=True)


class ProfileWeatherSettings(Base):
    __tablename__ = "profile_weather_settings"
    __table_args__ = (UniqueConstraint("profile_id"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    profile_id = Column(Integer, ForeignKey("profile.id"), nullable=False)
    location_name = Column(String, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    weather_advisories_enabled = Column(Boolean, default=True)
