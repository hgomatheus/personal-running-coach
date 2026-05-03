# Design Document — Personal Running Coach

## Overview

The Personal Running Coach is a single-user web application that runs on a Raspberry Pi 4 (ARM64) via Docker Compose and is accessible only over the home WiFi network. It provides a training experience comparable to premium apps like Runna: AI-generated multi-week training plans, Strava activity sync, structured workout detail, running history, and adaptive plan management.

### Key Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Backend language | Python / FastAPI | Mature async framework, excellent ARM64 Docker support, rich ecosystem for scheduling and data science |
| Frontend framework | SvelteKit (static adapter) | Lightweight compiled output, minimal runtime overhead on Pi, excellent DX |
| Database | SQLite via SQLAlchemy | Zero-config, single-file, sufficient for two-profile workload, survives volume mounts |
| Background scheduler | APScheduler (in-process) | No Redis/Celery overhead; fits within 1 GB RAM constraint |
| AI provider | Google Gemini API (gemini-2.0-flash) | Free tier (15 RPM / 1,000 RPD), sufficient for plan generation and adaptation |
| Strava sync | Polling (configurable interval) | Webhook registration requires a public URL; polling is simpler for a local-only deployment |
| Pace zone formula | Jack Daniels VDOT | Established, well-documented, deterministic — suitable for unit testing |
| Distance units | Kilometres only | All distances stored internally in metres, displayed exclusively in km — no unit conversion logic required |
| Multi-profile | Two fixed profiles | Exactly two independent profiles share one app instance; no authentication required |

### Backend Python Dependencies (key packages)

| Package | Purpose |
|---|---|
| `fastapi` | Async REST API framework |
| `uvicorn` | ASGI server |
| `sqlalchemy` | ORM + SQLite driver |
| `pydantic-settings` | Environment-based configuration |
| `apscheduler` | In-process background scheduler |
| `httpx` | Async HTTP client (Strava, Gemini) |
| `google-generativeai` | Gemini API SDK |
| `python-multipart` | Multipart file upload support |
| `python-jose` | JWT / token utilities |
| `python-json-logger` | Structured JSON logging |
| `hypothesis` | Property-based testing |
| `garmin-fit-sdk` | Garmin FIT binary file generation (workout export) |

### Research Findings

**Strava API** ([developers.strava.com](https://developers.strava.com/docs/authentication)): Default rate limits are 100 requests per 15 minutes and 1,000 per day for a single-athlete app. A personal app registered by the user is capped at 1 connected athlete (themselves), which is exactly what we need. OAuth 2.0 with `activity:read_all` scope covers all run imports. Webhooks require a publicly reachable callback URL, so polling is the correct approach for a local-network deployment.

**Gemini API** ([ai.google.dev](https://ai.google.dev/gemini-api/docs/rate-limits)): The free tier for `gemini-2.0-flash` provides approximately 15 requests per minute and 1,000 requests per day. Plan generation and adaptation are infrequent operations (a few times per week at most), so the free tier is more than sufficient. All AI calls must go through the Gemini API — no other paid AI service is used.

**VDOT Formula** ([running-calculator.com](https://running-calculator.com/vdot-calculator/)): VDOT is derived from a race result using:
- `VO2 = -4.60 + 0.182258 × v + 0.000104 × v²` (v = speed in m/min)
- `%VO2max = 0.8 + 0.1894393 × e^(-0.012778 × t) + 0.2989558 × e^(-0.1932605 × t)` (t = race duration in minutes)
- `VDOT = VO2 / %VO2max`

Training pace zones are then derived as percentages of VDOT-equivalent velocity: Easy 62–70%, Marathon 75–84%, Threshold 86–88%, Interval 95–100%, Repetition >105%.

**ARM64 / Raspberry Pi**: FastAPI with `python:3.12-slim` and SvelteKit with `node:20-alpine` both have official ARM64 images. SQLite is bundled with Python. Total idle RAM footprint is estimated at 200–400 MB, well within the 1 GB constraint.

---

## Architecture

The system is composed of three Docker services orchestrated by Docker Compose:

```
┌─────────────────────────────────────────────────────────────────┐
│  Docker Compose (ARM64)                                         │
│                                                                 │
│  ┌──────────────────┐    ┌──────────────────────────────────┐  │
│  │  frontend        │    │  backend (FastAPI)               │  │
│  │  SvelteKit       │───▶│                                  │  │
│  │  (static, nginx) │    │  ┌────────────┐  ┌───────────┐  │  │
│  │  :3000           │    │  │ REST API   │  │ APScheduler│  │  │
│  └──────────────────┘    │  │ /api/v1/   │  │ (in-proc) │  │  │
│                           │  └────────────┘  └───────────┘  │  │
│                           │         │                         │  │
│                           │  ┌──────▼──────┐                 │  │
│                           │  │ SQLAlchemy  │                 │  │
│                           │  │ (SQLite)    │                 │  │
│                           │  └─────────────┘                 │  │
│                           │  :8000                           │  │
│                           └──────────────────────────────────┘  │
│                                                                 │
│  Named volumes: db-data, logs, backups                          │
└─────────────────────────────────────────────────────────────────┘
         │                          │
         ▼                          ▼
   Browser (LAN)            External APIs
                            ├── Strava API
                            └── Gemini API
```

### Network Security

The frontend nginx container binds only to the local network interface. An IP-allowlist middleware in FastAPI rejects requests from outside the RFC-1918 address space (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16) with HTTP 403. The Docker Compose `ports` directive uses `127.0.0.1` binding for the backend and the Pi's LAN IP for the frontend.

### Request Flow

1. Browser on LAN → nginx (frontend, :3000) → serves static SvelteKit bundle
2. SvelteKit app → `fetch('/api/v1/...')` → nginx reverse-proxies to backend (:8000)
3. Backend processes request, reads/writes SQLite, optionally calls Gemini or Strava
4. APScheduler runs background jobs (Strava poll, notifications, backups) inside the backend process

---

## Components and Interfaces

### Backend — FastAPI Application

```
backend/
├── app/
│   ├── main.py                  # FastAPI app factory, middleware, lifespan
│   ├── config.py                # Settings (pydantic-settings, env vars)
│   ├── database.py              # SQLAlchemy engine, session factory
│   ├── scheduler.py             # APScheduler setup and job registration
│   ├── middleware/
│   │   └── ip_filter.py         # LAN-only IP allowlist middleware
│   ├── routers/
│   │   ├── profiles.py          # GET /api/v1/profiles, GET/PUT /api/v1/profiles/{profile_id}
│   │   ├── plans.py             # CRUD /api/v1/profiles/{profile_id}/plans, …/workouts
│   │   ├── workouts.py          # GET/PATCH /api/v1/workouts/{id}
│   │   ├── runs.py              # CRUD /api/v1/profiles/{profile_id}/runs
│   │   ├── strava.py            # OAuth flow + /api/v1/profiles/{profile_id}/strava/*
│   │   ├── stats.py             # GET /api/v1/profiles/{profile_id}/stats/*
│   │   ├── zones.py             # GET/POST /api/v1/profiles/{profile_id}/zones
│   │   ├── settings.py          # GET/PUT /api/v1/settings (shared) + profile settings
│   │   ├── backup.py            # POST /api/v1/backup
│   │   ├── export.py            # GET /api/v1/workouts/{id}/export/fit (FIT file download)
│   │   ├── data_export.py       # GET /api/v1/profiles/{profile_id}/export/json + POST …/import/json
│   │   ├── analysis.py          # GET /api/v1/profiles/{profile_id}/runs/{run_id}/analysis
│   │   ├── weather.py           # GET /api/v1/profiles/{profile_id}/workouts/{id}/weather + weather settings
│   │   ├── routes.py            # GET /api/v1/profiles/{profile_id}/routes (GPX route suggestions)
│   │   ├── taper.py             # GET /api/v1/profiles/{profile_id}/taper
│   │   └── health.py            # GET /health
│   ├── services/
│   │   ├── ai_coach.py          # Gemini API integration — plan generation & adaptation
│   │   ├── strava_client.py     # Strava OAuth + activity fetch
│   │   ├── strava_bulk_importer.py  # Strava export ZIP parsing and bulk import
│   │   ├── workout_matcher.py   # Match imported runs to scheduled workouts
│   │   ├── vdot.py              # Jack Daniels VDOT calculation
│   │   ├── zones_calculator.py  # Pace zone + HR zone derivation
│   │   ├── backup_service.py    # SQLite backup logic
│   │   ├── notification.py      # Web Push notification dispatch
│   │   ├── fit_exporter.py      # Garmin FIT file generation from Workout records
│   │   ├── post_run_analyzer.py # Compare actual run metrics to workout targets; call Gemini for coaching summary
│   │   ├── weather_service.py   # Open-Meteo API client with 3-hour cache; heat/humidity/wind advisory logic
│   │   ├── route_extractor.py   # Extract and deduplicate GPS polylines from Strava run data; store in DB
│   │   ├── taper_calculator.py  # Detect taper phase; calculate volume reduction; generate taper guidance
│   │   └── data_export_service.py  # Serialise all profile data to JSON for export; validate and restore on import
│   └── models/
│       ├── orm.py               # SQLAlchemy ORM models
│       └── schemas.py           # Pydantic request/response schemas
```

### Frontend — SvelteKit

```
frontend/
├── src/
│   ├── routes/
│   │   ├── +layout.svelte       # Shell: nav, notification permission, profile switcher
│   │   ├── +page.svelte         # Dashboard (with profile switcher component)
│   │   ├── onboarding/          # First-run onboarding flow (includes bulk import step)
│   │   ├── plan/                # Training plan calendar view
│   │   ├── workout/[id]/        # Workout detail
│   │   ├── runs/                # Run history + manual log form
│   │   ├── runs/[id]/analysis/  # Post-run analysis screen
│   │   ├── stats/               # Statistics, charts, PRs
│   │   ├── zones/               # Pace & HR zones screen
│   │   └── settings/            # Settings screen (includes bulk import trigger)
│   ├── lib/
│   │   ├── api.ts               # Typed fetch wrapper for /api/v1/* (profile_id aware)
│   │   ├── stores.ts            # Svelte stores (activeProfile, plan, settings)
│   │   ├── charts/              # Chart.js wrappers (weekly mileage bar, progress)
│   │   └── notifications.ts     # Service worker + Web Push registration
│   └── service-worker.ts        # Push notification handler
```

### REST API Surface

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/api/v1/profiles` | List both profiles (for switcher) |
| GET/PUT | `/api/v1/profiles/{profile_id}` | Runner profile data |
| GET/POST | `/api/v1/profiles/{profile_id}/plans` | List / create training plan |
| GET | `/api/v1/profiles/{profile_id}/plans/{id}` | Plan detail with workouts |
| POST | `/api/v1/profiles/{profile_id}/plans/{id}/regenerate` | Trigger AI plan regeneration |
| DELETE | `/api/v1/profiles/{profile_id}/plans/{id}` | Delete plan and all associated blocks/workouts; returns 409 if plan has completed workouts unless `?force=true` |
| GET/PATCH | `/api/v1/workouts/{id}` | Workout detail / mark complete / skip |
| GET/POST | `/api/v1/profiles/{profile_id}/runs` | Run history / create manual run |
| GET/PUT/DELETE | `/api/v1/profiles/{profile_id}/runs/{id}` | Run detail |
| GET | `/api/v1/profiles/{profile_id}/stats/weekly` | Weekly mileage data |
| GET | `/api/v1/profiles/{profile_id}/stats/monthly` | Monthly summary |
| GET | `/api/v1/profiles/{profile_id}/stats/prs` | Personal records |
| GET/POST | `/api/v1/profiles/{profile_id}/zones` | Pace & HR zones |
| GET | `/api/v1/profiles/{profile_id}/strava/auth` | Initiate Strava OAuth |
| GET | `/api/v1/profiles/{profile_id}/strava/callback` | OAuth callback |
| DELETE | `/api/v1/profiles/{profile_id}/strava/disconnect` | Revoke Strava token |
| GET | `/api/v1/profiles/{profile_id}/strava/status` | Sync status + last sync time |
| POST | `/api/v1/profiles/{profile_id}/strava/bulk-import` | Upload Strava export ZIP for bulk activity import |
| GET | `/api/v1/profiles/{profile_id}/strava/import-history` | List past bulk import records |
| GET/PUT | `/api/v1/settings` | Shared app settings (sync interval, backup) |
| GET/PUT | `/api/v1/profiles/{profile_id}/settings` | Per-profile settings (notifications, push subscription) |
| POST | `/api/v1/backup` | Trigger manual backup |
| GET | `/api/v1/profiles/{profile_id}/export/csv` | Export runs as CSV |
| GET | `/api/v1/profiles/{profile_id}/export/ical` | Export plan as iCal |
| GET | `/api/v1/profiles/{profile_id}/export/json` | Export all profile data as a portable JSON file |
| POST | `/api/v1/profiles/{profile_id}/import/json` | Import a previously exported JSON file; restores all profile data |
| GET | `/api/v1/workouts/{id}/export/fit` | Download workout as Garmin FIT file |
| GET | `/api/v1/profiles/{profile_id}/runs/{run_id}/analysis` | Post-run analysis: target vs actual metrics + AI coaching summary |
| GET | `/api/v1/profiles/{profile_id}/workouts/{id}/weather` | Weather forecast for a specific workout date |
| GET/PUT | `/api/v1/profiles/{profile_id}/settings/weather` | Per-profile weather location and advisory preferences |
| GET | `/api/v1/profiles/{profile_id}/routes` | GPX route suggestions for a workout (query param: `workout_id`) |
| GET | `/api/v1/profiles/{profile_id}/taper` | Taper phase status and guidance for the active Training_Plan |

---

## Data Models

### SQLAlchemy ORM Models

```python
class Profile(Base):
    __tablename__ = "profile"
    id: int (PK, 1 or 2 — exactly two profiles)
    display_name: str            # default "Profile 1" / "Profile 2"
    date_of_birth: date
    biological_sex: str          # "male" | "female" | "other"
    current_weekly_km: float | None   # optional when bulk import provided
    longest_recent_run_km: float | None  # optional when bulk import provided
    injury_notes: str | None
    created_at: datetime
    updated_at: datetime

class ProfileSettings(Base):
    __tablename__ = "profile_settings"
    id: int (PK)
    profile_id: int (FK → profile, unique)  # one record per profile
    notification_enabled: bool
    notification_time: time      # default 20:00
    push_subscription: JSON | None  # Web Push subscription object

class RaceGoal(Base):
    __tablename__ = "race_goal"
    id: int (PK)
    profile_id: int (FK → profile)
    distance_metres: float
    target_date: date
    label: str | None            # e.g. "London Marathon 2026"
    is_active: bool
    created_at: datetime

class TrainingPlan(Base):
    __tablename__ = "training_plan"
    id: int (PK)
    profile_id: int (FK → profile)
    race_goal_id: int (FK → race_goal)
    start_date: date
    end_date: date
    status: str                  # "active" | "archived" | "draft"
    gemini_prompt_hash: str      # SHA-256 of the prompt used — for cache/dedup
    created_at: datetime
    updated_at: datetime

class TrainingBlock(Base):
    __tablename__ = "training_block"
    id: int (PK)
    profile_id: int (FK → profile)
    plan_id: int (FK → training_plan)
    name: str                    # "Base Building", "Threshold Development", etc.
    start_date: date
    end_date: date
    sequence: int

class Workout(Base):
    __tablename__ = "workout"
    id: int (PK)
    profile_id: int (FK → profile)
    block_id: int (FK → training_block)
    plan_id: int (FK → training_plan)
    scheduled_date: date
    workout_type: str            # "easy" | "tempo" | "interval" | "hills" | "long" | "race" | "rest" | "recovery"
    target_distance_metres: float | None  # primary target field
    # estimated_duration_seconds is a computed property: target_distance_metres / pace_zone_velocity
    # it is NOT stored in the database
    target_pace_zone: str        # "easy" | "moderate" | "threshold" | "vo2max" | "anaerobic"
    target_hr_zone: int | None   # 1–5
    steps: JSON                  # list of WorkoutStep dicts; each step's distance_metres is required
    coaching_note: str | None
    status: str                  # "scheduled" | "completed" | "skipped" | "missed"
    rpe_score: int | None        # 1–10
    matched_run_id: int | None   # FK → run
    created_at: datetime
    updated_at: datetime

class Run(Base):
    __tablename__ = "run"
    id: int (PK)
    profile_id: int (FK → profile)
    source: str                  # "strava" | "manual"
    strava_activity_id: int | None  # unique per profile
    date: date
    started_at: datetime | None
    distance_metres: float
    duration_seconds: int
    avg_pace_sec_per_km: float | None
    avg_heart_rate: int | None
    elevation_gain_metres: float | None
    run_type: str | None         # "easy" | "tempo" | "interval" | "long" | "race"
    notes: str | None
    raw_strava_data: JSON | None
    created_at: datetime
    updated_at: datetime

class PaceZones(Base):
    __tablename__ = "pace_zones"
    id: int (PK)
    profile_id: int (FK → profile, unique)  # one record per profile
    vdot: float | None
    easy_min_sec_per_km: int
    easy_max_sec_per_km: int
    moderate_min_sec_per_km: int
    moderate_max_sec_per_km: int
    threshold_min_sec_per_km: int
    threshold_max_sec_per_km: int
    vo2max_min_sec_per_km: int
    vo2max_max_sec_per_km: int
    anaerobic_min_sec_per_km: int
    anaerobic_max_sec_per_km: int
    updated_at: datetime

class HeartRateZones(Base):
    __tablename__ = "hr_zones"
    id: int (PK)
    profile_id: int (FK → profile, unique)  # one record per profile
    max_hr: int
    zone1_max: int               # 50–60% max HR
    zone2_max: int               # 60–70%
    zone3_max: int               # 70–80%
    zone4_max: int               # 80–90%
    zone5_max: int               # 90–100%
    updated_at: datetime

class StravaToken(Base):
    __tablename__ = "strava_token"
    id: int (PK)
    profile_id: int (FK → profile, unique)  # one token per profile
    athlete_id: int
    access_token: str            # encrypted at rest
    refresh_token: str           # encrypted at rest
    expires_at: datetime
    last_sync_at: datetime | None
    sync_error: str | None

class AppSettings(Base):
    __tablename__ = "app_settings"
    id: int (PK, always 1 — single shared record)
    strava_sync_interval_minutes: int  # 5–60, default 15; shared across both profiles
    backup_enabled: bool         # default True
    backup_retention_days: int   # default 30

class BackupRecord(Base):
    __tablename__ = "backup_record"
    id: int (PK)
    completed_at: datetime
    file_path: str
    size_bytes: int
    success: bool
    error_message: str | None

class ImportRecord(Base):
    __tablename__ = "import_record"
    id: int (PK)
    profile_id: int (FK → profile)
    imported_at: datetime
    activities_imported: int
    duplicates_skipped: int
    parse_errors: int
    vdot_calculated: float | None  # VDOT computed from this import, null if no qualifying effort
    source_filename: str | None

class RouteRecord(Base):
    __tablename__ = "route_record"
    id: int (PK)
    profile_id: int (FK → profile)
    polyline: str                # Encoded GPS polyline (Google Polyline format)
    typical_distance_metres: float
    run_count: int               # Number of times this profile has run this route
    last_used_at: datetime
    workout_type_affinity: str | None  # Most common workout type run on this route

class WeatherCache(Base):
    __tablename__ = "weather_cache"
    id: int (PK)
    location_key: str            # Normalised "lat,lon" or city name used as cache key
    forecast_date: date
    fetched_at: datetime         # Used to enforce 3-hour TTL
    temperature_c: float
    humidity_pct: float
    wind_kmh: float
    conditions: str              # e.g. "rain", "clear", "cloudy"
    raw_response: JSON | None    # Full Open-Meteo response for debugging

class ProfileWeatherSettings(Base):
    __tablename__ = "profile_weather_settings"
    id: int (PK)
    profile_id: int (FK → profile, unique)  # one record per profile
    location_name: str | None    # City name (used for display)
    latitude: float | None
    longitude: float | None
    weather_advisories_enabled: bool  # default True
```

### WorkoutStep (embedded JSON)

```json
{
  "sequence": 1,
  "label": "Warm-up",
  "distance_metres": 1600,
  "pace_zone": "easy",
  "hr_zone": 2,
  "description": "Easy jog to warm up — estimated duration is derived from distance ÷ pace zone velocity and shown in the UI as a secondary value"
}
```

`duration_seconds` is not stored on WorkoutStep. Estimated step duration is computed on the fly in the API response as `distance_metres / pace_zone_velocity_m_per_s` and returned as a read-only `estimated_duration_seconds` field.

### Pydantic Schemas (key examples)

```python
class ProfileUpdate(BaseModel):
    display_name: str = Field(min_length=1, max_length=50)
    date_of_birth: date
    biological_sex: Literal["male", "female", "other"]
    current_weekly_km: float | None = Field(None, gt=0)   # optional if bulk import provided
    longest_recent_run_km: float | None = Field(None, gt=0)  # optional if bulk import provided
    injury_notes: str | None = None

class ProfileSettingsUpdate(BaseModel):
    notification_enabled: bool
    notification_time: time
    push_subscription: dict | None = None

class RunCreate(BaseModel):
    date: date
    distance_metres: float = Field(gt=0)
    duration_seconds: int = Field(gt=0)
    avg_heart_rate: int | None = Field(None, ge=30, le=250)
    notes: str | None = None

class WorkoutPatch(BaseModel):
    status: Literal["completed", "skipped"] | None = None
    rpe_score: int | None = Field(None, ge=1, le=10)

class WorkoutStepResponse(BaseModel):
    sequence: int
    label: str
    distance_metres: float
    estimated_duration_seconds: int  # computed: distance_metres / pace_zone_velocity; read-only
    pace_zone: str
    hr_zone: int | None
    description: str | None

class WorkoutResponse(BaseModel):
    id: int
    profile_id: int
    workout_type: str
    target_distance_metres: float | None
    estimated_duration_seconds: int | None  # computed: target_distance_metres / pace_zone_velocity
    target_pace_zone: str
    target_hr_zone: int | None
    steps: list[WorkoutStepResponse]
    coaching_note: str | None
    status: str
    rpe_score: int | None
    matched_run_id: int | None

class BulkImportResponse(BaseModel):
    imported: int
    skipped_duplicates: int
    parse_errors: int
    vdot: float | None
    pace_zones_updated: bool

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

class KmSplit(BaseModel):
    km: int
    pace_sec_per_km: float | None
    avg_hr: int | None

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

class RouteRecordResponse(BaseModel):
    id: int
    polyline: str
    typical_distance_km: float
    run_count: int
    last_used_at: datetime
    workout_type_affinity: str | None
    thumbnail_url: str | None            # Static map tile URL rendered from polyline

class TaperStatusResponse(BaseModel):
    taper_active: bool
    days_until_race: int | None
    taper_week: int | None               # 1-indexed week within taper (1 = first taper week)
    volume_reduction_pct: int | None     # e.g. 30 for 30% reduction
    guidance: TaperGuidance | None

class TaperGuidance(BaseModel):
    target_mileage_reduction_pct: int
    sleep_nutrition_reminder: str
    sluggishness_note: str

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
```

---

## AI Coach Design (Gemini Integration)

### Plan Generation Prompt Strategy

The `ai_coach.py` service constructs a structured prompt containing:
1. Runner profile (age, sex, current fitness, injury notes)
2. Race goal (distance, date, weeks remaining)
3. Current VDOT and pace zones
4. Instruction to return a JSON-structured training plan
5. Explicit instruction to use **only** the following workout types: `"easy"` (Easy Run — low intensity, conversational pace, easy zone), `"tempo"` (Tempo — sustained effort at threshold pace zone), `"interval"` (Intervals — repeated high-intensity efforts with recovery steps, e.g. 6 × 400 m), `"hills"` (Hills — repeated hill repeats with recovery jog back down), `"long"` (Long Run — extended easy/moderate effort, the week's longest run), `"race"` (Race — race-day workout type), `"rest"` (Rest — full rest day, no steps), `"recovery"` (Recovery — very easy active recovery). The prompt SHALL explicitly state that no other workout type values are permitted.

The response is parsed as structured JSON using Gemini's `response_mime_type: "application/json"` feature, eliminating fragile text parsing.

```python
PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "blocks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "start_date": {"type": "string"},
                    "end_date": {"type": "string"},
                    "workouts": {
                        "type": "array",
                        "items": { ... }  # WorkoutStep schema
                    }
                }
            }
        }
    }
}
```

### Adaptation Triggers

| Trigger | Action |
|---|---|
| Workout marked skipped | Re-prompt Gemini with remaining plan + skip context |
| Run deviates >20% from target | Adjust following week's load (Gemini prompt) |
| RPE > 8 for 2 consecutive same-type workouts | Reduce next same-type workout intensity |
| Injury reported | Remove high-intensity workouts for recovery period |
| Fitness change >5% | Offer to recalculate pace zones |

### Rate Limit Handling

All Gemini calls are wrapped in an async retry with exponential backoff (max 3 attempts). A simple in-memory token bucket enforces ≤15 RPM to stay within the free tier. Plan generation is queued and non-blocking — the UI shows a "Generating plan…" state while the backend processes the request.

---

## Strava OAuth Flow

Each profile has its own independent Strava OAuth connection. The `profile_id` is threaded through the entire OAuth flow via the `state` parameter.

```
User clicks "Connect Strava" for Profile N
        │
        ▼
GET /api/v1/profiles/{profile_id}/strava/auth
  → redirect to https://www.strava.com/oauth/authorize
    ?client_id=...&redirect_uri=http://pi.local:3000/api/v1/profiles/{profile_id}/strava/callback
    &scope=activity:read_all&response_type=code&state={profile_id}
        │
        ▼ (user approves on Strava)
GET /api/v1/profiles/{profile_id}/strava/callback?code=...&state={profile_id}
  → POST https://www.strava.com/oauth/token (exchange code for tokens)
  → store encrypted access_token + refresh_token in strava_token table for this profile_id
  → trigger initial 90-day activity import for this profile_id
  → redirect to settings screen
```

Token refresh is handled transparently: before every Strava API call for a profile, the service checks `expires_at` and refreshes if within 5 minutes of expiry. Each profile's token is refreshed independently.

---

## Strava Bulk Import

### Overview

The bulk import feature allows each profile to upload their own Strava data export ZIP (produced by Strava's "Download your data" feature) via the onboarding flow or the settings screen. This populates the full run history for that profile and calculates an accurate initial VDOT baseline without requiring manual data entry or a live Strava OAuth connection. Each profile's import is fully independent.

### Endpoint

```
POST /api/v1/profiles/{profile_id}/strava/bulk-import
Content-Type: multipart/form-data
Body: file=<strava_export.zip>
```

Response (202 Accepted — processing is synchronous but may take several seconds):

```json
{
  "imported": 142,
  "skipped_duplicates": 3,
  "parse_errors": 0,
  "vdot": 48.2,
  "pace_zones_updated": true
}
```

Import history is available at:

```
GET /api/v1/profiles/{profile_id}/strava/import-history
```

Returns a list of `ImportRecord` objects for the given profile, ordered by `imported_at` descending.

### Service: `strava_bulk_importer.py`

The `StravaBulkImporter` service handles all ZIP parsing and import logic:

```
StravaBulkImporter
├── parse_zip(file: UploadFile) → list[ActivityRecord]
│   ├── Open ZIP in memory (zipfile.ZipFile)
│   ├── Locate activities.csv (required)
│   ├── Parse activities.csv → list of raw activity dicts
│   ├── Filter to type == "Run" rows only
│   └── For each run row:
│       ├── Extract strava_activity_id, date, distance, duration, avg_hr, elevation
│       └── If distance or duration is missing: attempt GPX/FIT fallback (see below)
│
├── gpx_fallback(activity_id: str, zip_ref: ZipFile) → ActivityRecord | None
│   ├── Locate matching .gpx or .fit.gz file by activity_id in ZIP
│   ├── Parse GPX trackpoints to derive distance and duration
│   └── Return ActivityRecord or None if file not found
│
└── import_activities(records: list[ActivityRecord], profile_id: int, db: Session) → ImportResult
    ├── For each ActivityRecord:
    │   ├── Check if Run with strava_activity_id AND profile_id already exists → skip if so (idempotent)
    │   └── Insert new Run record with profile_id set
    ├── After all inserts: select best race-like effort for this profile (longest run ≥ 5 km with pace ≤ 8:00/km)
    ├── Recalculate VDOT from best effort using vdot.py
    ├── Update PaceZones record for this profile_id with new zones
    └── Insert ImportRecord for this profile_id with summary statistics
```

### ZIP Structure

A standard Strava export ZIP contains:

```
strava_export_<athlete_id>.zip
├── activities.csv          ← summary of all activities (always present)
├── activities/
│   ├── <activity_id>.gpx   ← GPS track (present for GPS-recorded activities)
│   ├── <activity_id>.fit.gz
│   └── ...
└── ...
```

The importer reads `activities.csv` first (fast, no file-by-file iteration). GPX/FIT parsing is only attempted as a fallback when a run row in the CSV is missing distance or duration data.

### Idempotency

The import is idempotent on `(strava_activity_id, profile_id)`. Before inserting any Run record, the service queries:

```sql
SELECT id FROM run WHERE strava_activity_id = :activity_id AND profile_id = :profile_id
```

If a row is found, the activity is counted as a duplicate and skipped. Re-uploading the same ZIP for the same profile produces no new Run records and leaves the total Run count for that profile unchanged.

Uploading the same ZIP for a *different* profile will create new Run records for that profile, since the deduplication key is scoped to `(strava_activity_id, profile_id)`.

### VDOT Recalculation After Import

After all activities are inserted, the importer selects the best race-like effort from the imported data for the given profile:

- Candidate runs: distance ≥ 5,000 m, avg_pace_sec_per_km ≤ 480 (8:00/km), run within the past 12 months
- Selection criterion: the candidate with the highest implied VDOT score
- The selected run is passed to `vdot.py` to compute a new VDOT and derive updated pace zones
- The `PaceZones` record for this `profile_id` is updated and the result is returned in the import response

### Error Handling

| Condition | Response |
|---|---|
| File is not a valid ZIP | HTTP 422, descriptive error, no data modified |
| ZIP contains no `activities.csv` | HTTP 422, descriptive error |
| ZIP contains no running activities | HTTP 200, `imported: 0`, no data modified |
| Individual activity row is malformed | Skip row, increment `parse_errors` counter, continue |
| No race-like effort found for VDOT | Import succeeds; VDOT not updated; response notes `vdot: null` |
| profile_id not in {1, 2} | HTTP 404 |

---

## Garmin FIT File Export

### Overview

The FIT export feature allows each profile to download any scheduled Workout as a structured `.fit` file that can be loaded directly onto a Garmin Forerunner 970 (and compatible devices) via USB. No Garmin Connect API approval is required — the file is generated locally and transferred manually.

The backend uses the **Garmin FIT SDK for Python** (`garmin-fit-sdk`) to write binary FIT files. The library is available on PyPI and supports ARM64.

### FIT Message Structure

A generated FIT file contains the following message sequence:

```
file_id message          ← type=workout, manufacturer=development
workout message          ← wkt_name, sport=running, num_valid_steps
wkt_step messages × N   ← one per WorkoutStep (or repeat marker)
```

**`workout` message fields:**
- `wkt_name`: the Workout's `workout_type` (e.g., "Interval")
- `sport`: `running`
- `num_valid_steps`: total count of `wkt_step` messages (including repeat markers)

**`wkt_step` message fields (per WorkoutStep):**

| FIT field | Source |
|---|---|
| `wkt_step_name` | `WorkoutStep.label` |
| `duration_type` | `distance` |
| `duration_distance` | `WorkoutStep.distance_metres` (in metres, as uint32) |
| `target_type` | `speed` if `pace_zone` is set, else `open` |
| `custom_target_speed_low` | lower bound of pace zone converted to m/s (1000 / pace_max_sec_per_km) |
| `custom_target_speed_high` | upper bound of pace zone converted to m/s (1000 / pace_min_sec_per_km) |
| `secondary_target_type` | `heart_rate` if `hr_zone` is set |
| `secondary_target_hr_zone` | `WorkoutStep.hr_zone` (1–5) |
| `intensity` | mapped from label: "warm-up" → `warmup`, "cool-down" → `cooldown`, "recovery" → `rest`, all others → `active` |

**Interval repeat encoding:**

When a Workout contains a repeat block (e.g., 6 × 400 m intervals), the steps are encoded as:

```
wkt_step[0]: warm-up step
wkt_step[1]: interval step (the repeated step)
wkt_step[2]: recovery step (the repeated step)
wkt_step[3]: repeat marker
  duration_type = repeat_until_steps_cmplt
  duration_step  = wkt_step_index of first step in the block (e.g., 1)
  target_value   = repeat count (e.g., 6)
wkt_step[4]: cool-down step
```

The `steps` JSON on the Workout record encodes repeat blocks using an optional `repeat_count` field on the first step of the block and an `is_repeat_end` flag on the last step. The `FitExporter` service reads these markers to emit the correct repeat step.

### Service: `fit_exporter.py`

```
FitExporter
├── export(workout: Workout, pace_zones: PaceZones) → bytes
│   ├── Validate all steps have distance_metres set; raise ValueError if any are missing
│   ├── Build file_id message
│   ├── Build workout message (name, sport, num_valid_steps)
│   ├── For each WorkoutStep:
│   │   ├── Map pace_zone → speed range (m/s) using PaceZones record
│   │   ├── Map label → FIT intensity enum
│   │   └── Emit wkt_step message
│   ├── For each repeat block: emit repeat wkt_step after the block's last step
│   └── Serialise to bytes using garmin-fit-sdk FitWriter
│
└── _pace_zone_to_speed_range(zone: str, pace_zones: PaceZones) → tuple[float, float]
    └── Returns (speed_low_m_per_s, speed_high_m_per_s) for the given zone name
```

### File Naming and Delivery

The export endpoint returns the file with:
- `Content-Type: application/octet-stream`
- `Content-Disposition: attachment; filename="{workout_type}_{scheduled_date}.fit"`

Example: `interval_2026-05-10.fit`

### Transfer Instructions (shown in UI)

> Connect your Forerunner 970 via USB → copy to the `GARMIN/NEWFILES` folder → eject → the workout will appear in your Training menu.

---

## Post-Run Analyzer

### Overview

The `post_run_analyzer.py` service compares a completed Run's actual metrics against the matched Workout's targets and calls Gemini to generate a plain-language coaching summary.

### Service: `post_run_analyzer.py`

```
PostRunAnalyzer
├── analyze(run: Run, workout: Workout, pace_zones: PaceZones) → PostRunAnalysisResult
│   ├── Compute target_distance_km and actual_distance_km
│   ├── Determine pace_comparison:
│   │   ├── Retrieve pace zone boundaries from PaceZones for workout.target_pace_zone
│   │   ├── If run.avg_pace_sec_per_km is within [zone_min, zone_max] → "on_target"
│   │   ├── If run.avg_pace_sec_per_km < zone_min → "faster"
│   │   └── If run.avg_pace_sec_per_km > zone_max → "slower"
│   ├── Extract km_splits from run.raw_strava_data (polyline/GPS laps) if available
│   ├── Call Gemini with structured prompt containing all metrics → coaching_summary
│   └── Return PostRunAnalysisResult
│
└── _build_gemini_prompt(run, workout, pace_comparison, km_splits) → str
    └── Constructs a prompt asking for a 2–3 sentence plain-language summary
        with one actionable coaching observation
```

### Pace Comparison Logic

The pace comparison is determined by comparing `run.avg_pace_sec_per_km` against the target pace zone boundaries stored in the `PaceZones` record:

- `on_target`: `zone_min_sec_per_km ≤ actual_pace ≤ zone_max_sec_per_km`
- `faster`: `actual_pace < zone_min_sec_per_km` (lower sec/km = faster)
- `slower`: `actual_pace > zone_max_sec_per_km`

---

## Weather Service

### Overview

The `weather_service.py` service fetches weather forecasts from the Open-Meteo free API (no API key required) and applies advisory logic for heat, humidity, rain, and wind conditions.

### Open-Meteo API

Open-Meteo ([open-meteo.com](https://open-meteo.com)) provides free weather forecasts with no API key. The relevant endpoint is:

```
GET https://api.open-meteo.com/v1/forecast
  ?latitude={lat}&longitude={lon}
  &daily=temperature_2m_max,precipitation_sum,windspeed_10m_max,relativehumidity_2m_max
  &forecast_days=7
  &timezone=auto
```

### Service: `weather_service.py`

```
WeatherService
├── get_forecast(profile_id: int, forecast_date: date, db: Session) → WeatherForecast
│   ├── Load ProfileWeatherSettings for profile_id
│   ├── If weather_advisories_enabled is False → return None
│   ├── Build location_key from lat/lon or city name
│   ├── Check WeatherCache for (location_key, forecast_date) with fetched_at within 3 hours
│   │   └── If cache hit → return cached forecast
│   ├── Call Open-Meteo API with lat/lon
│   ├── Parse response → WeatherForecast
│   ├── Store in WeatherCache
│   └── Return WeatherForecast
│
├── build_advisories(forecast: WeatherForecast) → list[str]
│   ├── If temperature_c > 25 or humidity_pct > 80 → append "heat_humidity" advisory
│   ├── If conditions contains "rain" → append "rain" advisory
│   ├── If wind_kmh > 30 → append "wind" advisory
│   └── Return list of advisory keys
│
└── format_advisory_text(advisory_key: str) → str
    └── Maps advisory keys to human-readable coaching text:
        "heat_humidity" → "Start 10–15 sec/km slower than target pace and prioritise hydration"
        "rain"          → "Expect slippery surfaces — shorten stride and reduce pace slightly"
        "wind"          → "Run into the wind on the outward leg to benefit from a tailwind on the return"
```

### Cache Strategy

Weather forecasts are cached in the `WeatherCache` table keyed on `(location_key, forecast_date)`. A cache entry is considered fresh if `fetched_at` is within 3 hours of the current time. Stale entries are overwritten on the next fetch. The daily `weather_prefetch` scheduler job pre-warms the cache for all profiles' upcoming workouts.

---

## Route Extractor

### Overview

The `route_extractor.py` service extracts unique GPS polylines from Strava-synced Run records, deduplicates them, and stores them as `RouteRecord` entries for use in route suggestions.

### Service: `route_extractor.py`

```
RouteExtractor
├── extract_routes(profile_id: int, db: Session) → int
│   ├── Query all Run records for profile_id where raw_strava_data contains a polyline
│   ├── For each Run:
│   │   ├── Decode polyline from raw_strava_data["map"]["summary_polyline"]
│   │   ├── Compute a route fingerprint (hash of simplified polyline)
│   │   ├── Check if RouteRecord with same fingerprint exists for this profile_id
│   │   │   ├── If exists: update run_count, last_used_at, workout_type_affinity
│   │   │   └── If not exists: insert new RouteRecord
│   └── Return count of new RouteRecord rows inserted
│
└── get_suggestions(workout: Workout, profile_id: int, db: Session) → list[RouteRecord]
    ├── Query RouteRecord for profile_id where:
    │   typical_distance_metres BETWEEN workout.target_distance_metres * 0.8
    │                                AND workout.target_distance_metres * 1.2
    ├── Order by: workout_type_affinity match DESC, run_count DESC, last_used_at DESC
    └── Return top 3 results
```

### Route Deduplication

Routes are deduplicated using a fingerprint derived from the Strava `summary_polyline` field. The fingerprint is a SHA-256 hash of the decoded and simplified polyline (Douglas-Peucker with ε = 10 m). Two runs with the same fingerprint are considered the same route.

### Map Thumbnails

Route thumbnails are rendered client-side using the encoded polyline and a free static map tile service (e.g., OpenStreetMap via Leaflet). The `thumbnail_url` field in `RouteRecordResponse` is constructed by the API layer as a URL to a static tile endpoint, not stored in the database.

---

## Taper Calculator

### Overview

The `taper_calculator.py` service detects whether the active Training_Plan is in its taper phase and generates guidance for the Dashboard.

### Taper Phase Detection

The taper phase is active when:
1. The Active_Profile has an active `TrainingPlan` with an associated `RaceGoal`
2. `(race_goal.target_date - today).days ≤ 21`

### Taper Duration by Race Distance

| Race Distance | Taper Duration |
|---|---|
| ≤ 10,000 m (5k/10k) | 1 week |
| ≤ 21,097 m (half marathon) | 2 weeks |
| > 21,097 m (marathon+) | 3 weeks |

The default is derived from `race_goal.distance_metres`. The User can override this per Race_Goal.

### Service: `taper_calculator.py`

```
TaperCalculator
├── get_taper_status(profile_id: int, db: Session) → TaperStatus
│   ├── Load active TrainingPlan and RaceGoal for profile_id
│   ├── If no active plan or no race goal → return TaperStatus(taper_active=False)
│   ├── Compute days_until_race = (race_goal.target_date - today).days
│   ├── If days_until_race > 21 → return TaperStatus(taper_active=False)
│   ├── Determine taper_duration_weeks from race_goal.distance_metres
│   ├── Compute taper_week = taper_duration_weeks - (days_until_race // 7)
│   ├── Compute volume_reduction_pct based on taper week (week 1: 20%, week 2: 30%, week 3: 40%)
│   └── Return TaperStatus(taper_active=True, days_until_race, taper_week, volume_reduction_pct, guidance)
│
└── should_block_volume_increase(profile_id: int, db: Session) → bool
    └── Returns True if taper phase is active for this profile — used by ai_coach.py
        to suppress plan adaptations that would increase training volume
```

### Taper Block Generation (AI Coach Integration)

When `ai_coach.py` generates a Training_Plan that spans ≥ 8 weeks, it includes a `Taper` Training_Block as the final block. The prompt instructs Gemini to:
- Reduce weekly volume by 20–40% from the peak week
- Maintain workout intensity (pace zones unchanged)
- Include the appropriate number of taper weeks based on race distance

The `taper_calculator.py` service is also consulted by `ai_coach.py` during plan adaptation: if `should_block_volume_increase()` returns `True`, the adaptation prompt explicitly instructs Gemini not to increase volume.

---

## Background Scheduler Jobs

| Job | Schedule | Description |
|---|---|---|
| `strava_sync` | Every N minutes (configurable, shared interval) | Poll Strava for new activities for each connected profile; match to that profile's workouts |
| `workout_reminder` | Daily at each profile's configured time | Send Web Push notification for next-day workout per profile |
| `inactivity_check` | Daily at 09:00 | Check for 3-day inactivity per profile, send motivational push |
| `daily_backup` | Daily at 02:00 | SQLite backup to `/data/backups/`, prune >30 files |
| `plan_adaptation_check` | After each strava_sync | Evaluate if plan adaptation is needed for each profile |
| `weather_prefetch` | Daily at 06:00 | Pre-fetch and cache weather forecasts for each profile's next 7 days of workouts |
| `route_extraction` | After each strava_sync | Extract and store GPS polylines from newly imported Strava runs |

---

## Error Handling

### API Error Responses

All errors follow a consistent envelope:

```json
{
  "error": {
    "code": "STRAVA_SYNC_FAILED",
    "message": "Strava API returned 429 Too Many Requests",
    "detail": null
  }
}
```

### Error Categories

| Category | Strategy |
|---|---|
| Strava API errors (4xx/5xx) | Log error, update `strava_token.sync_error`, display sync status indicator, retry at next interval |
| Gemini API errors | Retry with exponential backoff (3 attempts), surface error to UI if all retries fail |
| Database errors | Log to file, return 500 with generic message (no internal details exposed) |
| Validation errors | FastAPI/Pydantic returns 422 with field-level detail |
| Network-origin rejection | IP filter middleware returns 403 immediately |
| Backup failures | Log failure, update `backup_record.success = false`, display warning on settings screen |

### Logging

- Structured JSON logs via Python `logging` + `python-json-logger`
- Log level configurable via `LOG_LEVEL` env var (default: `INFO`)
- Logs written to `/data/logs/app.log` (Docker volume) with daily rotation, 30-day retention
- Errors also written to stderr for Docker log capture

---

## Testing Strategy

### Unit Tests (pytest)

Focus on pure business logic that does not require external services:

- **`vdot.py`**: VDOT calculation from race results, pace zone derivation
- **`zones_calculator.py`**: HR zone calculation from max HR
- **`workout_matcher.py`**: Run-to-workout matching logic
- **`backup_service.py`**: Backup file naming, pruning logic
- **`ip_filter.py`**: LAN IP detection and rejection logic
- **`schemas.py`**: Pydantic validation (invalid distances, RPE out of range, etc.)

### Integration Tests (pytest + httpx AsyncClient)

- Full API endpoint tests using an in-memory SQLite database
- Strava OAuth flow with mocked `httpx` responses
- Gemini plan generation with mocked responses
- Strava sync job with mocked Strava API

### Property-Based Tests (Hypothesis)

See Correctness Properties section below. Each property test uses `@given` decorators with Hypothesis strategies and runs a minimum of 100 examples.

### Frontend Tests (Vitest + Testing Library)

- Component unit tests for form validation (onboarding, manual run entry)
- Store logic tests (unit conversion, streak calculation)
- API mock tests for key data-fetching routes

### End-to-End (Playwright, optional)

- Onboarding flow
- Manual run entry and history display
- Settings unit toggle

### Test Configuration

```toml
# pyproject.toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.hypothesis]
max_examples = 100
```

Property tests are tagged with comments in the format:
`# Feature: personal-running-coach, Property N: <property text>`

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: LAN IP filter rejects all public addresses

*For any* IP address that does not fall within the RFC-1918 private address ranges (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16), the IP filter middleware SHALL return HTTP 403 and SHALL NOT forward the request to any handler.

**Validates: Requirements 1.2**

---

### Property 2: Profile round-trip preserves all fields

*For any* valid runner profile (with all required fields populated with valid values), submitting the profile via PUT /api/v1/profile and then retrieving it via GET /api/v1/profile SHALL return data that is field-for-field identical to what was submitted.

**Validates: Requirements 2.2, 2.4**

---

### Property 3: Profile validation rejects incomplete submissions

*For any* profile submission where one or more required fields (date_of_birth, biological_sex, current_weekly_mileage, longest_recent_run, preferred_unit) are absent or null, the API SHALL return HTTP 422 with a response body that identifies each missing field by name.

**Validates: Requirements 2.5**

---

### Property 4: Generated plan spans the correct date range

*For any* race goal with a target date in the future, the generated Training_Plan SHALL have a start_date on or before today and an end_date equal to the race goal target_date.

**Validates: Requirements 3.1**

---

### Property 5: Generated plan contains at least one named Training_Block

*For any* generated Training_Plan, the plan SHALL contain at least one Training_Block with a non-empty name, and every Workout in the plan SHALL belong to exactly one Training_Block.

**Validates: Requirements 3.2**

---

### Property 6: No day has more than one quality workout

*For any* generated Training_Plan, no calendar date SHALL contain more than one Workout whose type is `"interval"`, `"tempo"`, `"hills"`, or `"long"`.

**Validates: Requirements 3.3**

---

### Property 7: Every calendar week contains at least one rest or recovery day

*For any* generated Training_Plan, every 7-day calendar week that falls within the plan's date range SHALL contain at least one Workout whose type is "rest" or "recovery".

**Validates: Requirements 3.4**

---

### Property 8: VDOT-derived pace zones are within expected percentage bands

*For any* valid race result (distance in metres, duration in seconds, where the implied pace is between 3:00/km and 12:00/km), computing the VDOT score and deriving the five pace zones SHALL produce zones whose boundaries fall within the Jack Daniels percentage bands: Easy 62–70%, Moderate (Marathon) 75–84%, Threshold 86–88%, VO2 Max 95–100%, Anaerobic >105% of VDOT-equivalent velocity.

**Validates: Requirements 3.5, 10.1, 10.3**

---

### Property 9: Fitness change detection triggers at the correct threshold

*For any* pair of VDOT values (baseline and current), the system SHALL flag a recalculation prompt if and only if `|current - baseline| / baseline > 0.05`.

**Validates: Requirements 3.6**

---

### Property 10: Workout API response contains all required fields

*For any* Workout stored in the database, the GET /api/v1/workouts/{id} response SHALL include: workout_type, target_distance_metres, target_duration_seconds (estimated), target_pace_zone, coaching_note (non-empty string), and a steps array where each step contains sequence, label, pace_zone, and a required distance_metres value (duration_seconds on each step is null or an estimate only).

**Validates: Requirements 3.8, 5.1, 5.2, 5.3**

---

### Property 11: Workout total distance equals sum of step distances

*For any* Workout, the Workout's target_distance_metres SHALL equal the sum of the distance_metres values across all steps (within floating-point tolerance of 1 metre). The target_duration_seconds field is a derived estimate only and is not a primary target.

**Validates: Requirements 5.4**

---

### Property 12: RPE adaptation triggers after two consecutive high-effort same-type workouts

*For any* sequence of completed Workouts of the same type where exactly two consecutive workouts have rpe_score > 8, the system SHALL flag the next Workout of that type for intensity reduction. For sequences where fewer than two consecutive workouts have rpe_score > 8, no intensity reduction SHALL be flagged.

**Validates: Requirements 5.6**

---

### Property 13: Run deviation adaptation triggers at the correct threshold

*For any* completed Run and its matched scheduled Workout, the system SHALL trigger a plan adaptation if and only if `|run.distance_metres - workout.target_distance_metres| / workout.target_distance_metres > 0.20`.

**Validates: Requirements 4.2**

---

### Property 14: Race goal date is preserved across all plan adaptations

*For any* plan adaptation trigger (skipped workout, run deviation, RPE threshold, injury report), the active Training_Plan's end_date SHALL remain equal to the associated RaceGoal's target_date after the adaptation completes.

**Validates: Requirements 4.5**

---

### Property 15: Run import and matching is triggered for every Strava or manual run

*For any* Run record created (whether via Strava import or manual entry), the workout matching service SHALL be invoked exactly once for that run, and if a Workout exists on the same date with a compatible type, the Workout's matched_run_id SHALL be set to the Run's id.

**Validates: Requirements 6.4, 7.4**

---

### Property 16: Strava API errors are handled gracefully without crashing

*For any* Strava API error response (HTTP 4xx or 5xx, including 429 rate-limit responses), the sync job SHALL: (a) not raise an unhandled exception, (b) record the error in strava_token.sync_error, and (c) schedule a retry at the next configured interval.

**Validates: Requirements 6.6**

---

### Property 17: Manual run validation rejects non-positive distance or duration

*For any* manual run submission where distance_metres ≤ 0 or duration_seconds ≤ 0, the API SHALL return HTTP 422 with a field-level error identifying the invalid field. For any submission where both distance_metres > 0 and duration_seconds > 0 (and all other fields are valid), the API SHALL return HTTP 201.

**Validates: Requirements 7.1, 7.2**

---

### Property 18: Run history is returned in chronological order

*For any* set of Run records inserted in arbitrary order, GET /api/v1/runs (without filters) SHALL return all runs sorted by date ascending, with no runs omitted.

**Validates: Requirements 8.1**

---

### Property 19: Run API response contains all required metric fields

*For any* Run record, the API response SHALL include: date, distance_metres, duration_seconds, avg_pace_sec_per_km (computed if not stored), and — where the data was provided — avg_heart_rate and elevation_gain_metres.

**Validates: Requirements 8.2**

---

### Property 20: Aggregation totals equal the sum of constituent runs

*For any* set of Run records spanning multiple weeks and months, the weekly mileage total for each week SHALL equal the sum of distance_metres for all runs whose date falls within that calendar week, and the monthly total SHALL equal the sum for all runs in that calendar month.

**Validates: Requirements 8.3, 8.4**

---

### Property 21: Streak calculation is correct for any run sequence

*For any* sequence of Run records, the current streak SHALL equal the number of consecutive calendar weeks ending with the most recent week in which at least one run was completed, and the all-time streak SHALL equal the maximum such consecutive sequence in the entire history.

**Validates: Requirements 8.5**

---

### Property 22: Personal records are correctly identified

*For any* set of Run records, the personal record for each tracked distance (1 km, 5 km, 10 km, half marathon, marathon) SHALL be the Run with the minimum avg_pace_sec_per_km among all runs whose distance_metres is within 5% of the target distance.

**Validates: Requirements 8.6**

---

### Property 23: Run history filters return only matching records

*For any* combination of filter parameters (date_range, run_type, distance_range), every Run returned by GET /api/v1/runs SHALL satisfy all applied filter criteria, and no Run that satisfies all criteria SHALL be omitted from the response.

**Validates: Requirements 8.8**

---

### Property 24: Heart rate zones are within expected percentage bands

*For any* maximum heart rate value between 120 and 220 bpm, the five computed HR zones SHALL have boundaries at approximately: Zone 1 ≤ 60%, Zone 2 ≤ 70%, Zone 3 ≤ 80%, Zone 4 ≤ 90%, Zone 5 ≤ 100% of max HR (within ±2 bpm rounding tolerance).

**Validates: Requirements 10.2**

---

### Property 25: Pace zone updates propagate to all future workouts

*For any* pace zone update, every Workout in the active Training_Plan whose scheduled_date is after the update timestamp SHALL have its target_pace_zone reference updated to reflect the new zone boundaries. Workouts with scheduled_date before the update SHALL remain unchanged.

**Validates: Requirements 10.5**

---

### Property 26: Backup pruning retains exactly the 30 most recent backups

*For any* list of backup records of length N, after pruning: if N ≤ 30, all records SHALL be retained; if N > 30, exactly the 30 records with the most recent completed_at timestamps SHALL be retained and all others SHALL be deleted.

**Validates: Requirements 14.2**

---

### Property 27: Bulk import is idempotent

*For any* Strava export ZIP file, uploading it a second time (after a prior successful import) SHALL produce zero new Run records and the total Run count in the database SHALL remain unchanged. Specifically, for every ActivityRecord in the ZIP whose strava_activity_id already exists in the run table, the importer SHALL skip that record and increment the skipped_duplicates counter rather than inserting a duplicate row.

**Validates: Requirements 15.5**

---

### Property 28: FIT file step count and distance sum match the Workout

*For any* Workout whose steps all have `distance_metres` defined, the FIT_File generated by `FitExporter.export()` SHALL contain exactly one `wkt_step` message per WorkoutStep (excluding repeat marker steps), and the sum of `duration_distance` values across all non-repeat `wkt_step` messages SHALL equal the Workout's `target_distance_metres` within 1 metre tolerance.

**Validates: Requirements 17.2, 17.3**

---

### Property 29: Post-run pace comparison correctly classifies any pace relative to zone boundaries

*For any* actual average pace value (in sec/km) and any target pace zone with defined min/max boundaries, the post-run analyzer SHALL classify the pace as "on_target" if and only if `zone_min_sec_per_km ≤ actual_pace ≤ zone_max_sec_per_km`, as "faster" if `actual_pace < zone_min_sec_per_km`, and as "slower" if `actual_pace > zone_max_sec_per_km`. No pace value SHALL produce an ambiguous or missing classification.

**Validates: Requirements 18.4**

---

### Property 30: Weather advisory triggers at correct thresholds for any forecast value

*For any* weather forecast with a given temperature (°C), humidity (%), wind speed (km/h), and conditions string, the `WeatherService.build_advisories()` function SHALL include the "heat_humidity" advisory if and only if `temperature_c > 25` OR `humidity_pct > 80`, the "wind" advisory if and only if `wind_kmh > 30`, and the "rain" advisory if and only if the conditions string indicates precipitation. For forecast values strictly below all thresholds, the advisory list SHALL be empty.

**Validates: Requirements 19.3, 19.4**

---

### Property 31: Taper phase activates at the correct day threshold and never increases volume

*For any* active Training_Plan with a Race_Goal, the taper phase SHALL be active if and only if `(race_goal.target_date - today).days ≤ 21`. When the taper phase is active, `should_block_volume_increase()` SHALL return `True` for all inputs, ensuring no plan adaptation can produce a weekly volume higher than the current taper week's target.

**Validates: Requirements 22.1, 22.6**

---

### Property 32: Route suggestions only return routes within 20% distance tolerance

*For any* Workout with a `target_distance_metres` value and any set of `RouteRecord` entries for the same profile, `RouteExtractor.get_suggestions()` SHALL return only routes where `typical_distance_metres` is within the range `[target_distance_metres × 0.8, target_distance_metres × 1.2]`. No route outside this range SHALL appear in the suggestions, and no route inside this range SHALL be omitted due to ordering logic.

**Validates: Requirements 21.2**

---

### Property 33: Workout type is always one of the eight permitted values

*For any* Workout record created by the AI_Coach or stored in the database, the `workout_type` field SHALL be one of: `"easy"`, `"tempo"`, `"interval"`, `"hills"`, `"long"`, `"race"`, `"rest"`, `"recovery"`. Any Workout with a `workout_type` outside this set SHALL be rejected with HTTP 422.

**Validates: Requirements 3.5, 5.1**

---

### Property 34: Plan reset deletes plan, blocks, and workouts but preserves completed runs

*For any* active Training_Plan with associated Training_Blocks and Workouts, after a confirmed reset via `DELETE /api/v1/profiles/{profile_id}/plans/{id}`, the Training_Plan record, all associated Training_Block records, and all associated Workout records SHALL be absent from the database. All Run records for the same profile SHALL remain unchanged and their count SHALL equal the pre-reset count.

**Validates: Requirements 4.8, 4.10**

---

### Property 35: Data export round-trip preserves all profile data

*For any* profile with a non-empty dataset (runs, plans, zones), exporting via `GET /api/v1/profiles/{profile_id}/export/json` and then importing the resulting file via `POST /api/v1/profiles/{profile_id}/import/json` with `mode="replace"` SHALL produce a database state that is field-for-field equivalent to the pre-export state for all exported entity types (profile, runs, plans, blocks, workouts, pace zones, HR zones, race goals, import history).

**Validates: Requirements 23.1, 23.3, 23.5**

---

### Property 36: Import validation rejects any JSON that does not conform to the export schema

*For any* JSON payload that is missing required top-level fields (`schema_version`, `exported_at`, `profile`, `runs`, `training_plans`) or contains fields with incorrect types, `POST /api/v1/profiles/{profile_id}/import/json` SHALL return HTTP 422 with a descriptive error and SHALL make no changes to the database. For any valid export JSON, the endpoint SHALL accept the payload and proceed with the import.

**Validates: Requirements 23.4**
