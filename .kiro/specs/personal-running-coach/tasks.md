# Implementation Tasks — Personal Running Coach

## Task Overview

This task list covers the full implementation of the personal running coach app: Docker/infrastructure setup, backend (FastAPI + SQLite), frontend (SvelteKit), all integrations (Strava, Gemini, Garmin FIT, Open-Meteo), and property-based tests.

---

## 1. Project Scaffold and Docker Infrastructure

- [x] 1.1 Create monorepo directory structure: `backend/`, `frontend/`, `docker/`, `.kiro/`
- [x] 1.2 Write `docker-compose.yml` with three services: `backend` (FastAPI, port 8000), `frontend` (nginx + SvelteKit static, port 3000), and named volumes `db-data`, `logs`, `backups`
- [x] 1.3 Write `backend/Dockerfile` using `python:3.12-slim` base image, ARM64-compatible, with `pip install` from `requirements.txt`
- [x] 1.4 Write `frontend/Dockerfile` using `node:20-alpine` for build stage and `nginx:alpine` for serve stage
- [x] 1.5 Write `nginx.conf` to serve SvelteKit static bundle and reverse-proxy `/api/` to backend
- [x] 1.6 Configure Docker Compose `restart: unless-stopped` on all services and bind frontend to LAN interface only
- [x] 1.7 Write `backend/requirements.txt` with pinned versions: fastapi, uvicorn, sqlalchemy, pydantic-settings, apscheduler, httpx, google-generativeai, python-multipart, python-jose, python-json-logger, hypothesis, garmin-fit-sdk, fitparse
- [x] 1.8 Write `frontend/package.json` with SvelteKit, TypeScript, Vitest, Playwright, Chart.js dependencies (pinned versions)
- [x] 1.9 Add `.env.example` documenting all required environment variables: `GEMINI_API_KEY`, `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET`, `SECRET_KEY`, `LOG_LEVEL`
- [x] 1.10 Write `README.md` with setup instructions: clone, copy `.env`, `docker compose up -d`, access at `http://<pi-ip>:3000`

---

## 2. Backend Foundation

- [x] 2.1 Create `backend/app/main.py`: FastAPI app factory, CORS config, lifespan handler (scheduler start/stop, DB init)
- [x] 2.2 Create `backend/app/config.py`: pydantic-settings `Settings` class reading all env vars
- [x] 2.3 Create `backend/app/database.py`: SQLAlchemy engine (SQLite at `/data/db/running_coach.db`), session factory, `get_db` dependency
- [x] 2.4 Create `backend/app/models/orm.py`: all SQLAlchemy ORM models — `Profile`, `ProfileSettings`, `RaceGoal`, `TrainingPlan`, `TrainingBlock`, `Workout`, `Run`, `PaceZones`, `HeartRateZones`, `StravaToken`, `AppSettings`, `BackupRecord`, `ImportRecord`, `RouteRecord`, `WeatherCache`, `ProfileWeatherSettings`
- [x] 2.5 Create `backend/app/models/schemas.py`: all Pydantic request/response schemas including `ProfileUpdate`, `RunCreate`, `WorkoutPatch`, `WorkoutResponse`, `WorkoutStepResponse`, `BulkImportResponse`, `PostRunAnalysisResponse`, `KmSplit`, `WeatherForecastResponse`, `RouteRecordResponse`, `TaperStatusResponse`, `TaperGuidance`, `ProfileDataExport`, `ImportDataRequest`
- [x] 2.6 Create `backend/app/middleware/ip_filter.py`: middleware that rejects requests from non-RFC-1918 addresses with HTTP 403
- [x] 2.7 Create `backend/app/scheduler.py`: APScheduler setup, register all background jobs (strava_sync, workout_reminder, inactivity_check, daily_backup, plan_adaptation_check, weather_prefetch, route_extraction)
- [x] 2.8 Write Alembic (or SQLAlchemy `create_all`) migration to initialise DB schema and seed two Profile rows (id=1 "Profile 1", id=2 "Profile 2") and one AppSettings row on first run
- [x] 2.9 Create `backend/app/routers/health.py`: `GET /health` returning `{"status": "ok"}` with HTTP 200

---

## 3. Core Business Logic Services

- [x] 3.1 Create `backend/app/services/vdot.py`: implement Jack Daniels VDOT formula — `calculate_vdot(distance_metres, duration_seconds) -> float` and `derive_pace_zones(vdot) -> PaceZoneValues`
- [x] 3.2 Create `backend/app/services/zones_calculator.py`: `calculate_hr_zones(max_hr) -> HRZoneValues` using 5-zone percentage model; `estimate_max_hr(date_of_birth, biological_sex) -> int` using age-predicted formula
- [x] 3.3 Create `backend/app/services/workout_matcher.py`: `match_run_to_workout(run, profile_id, db) -> Workout | None` — finds scheduled workout on same date with compatible type, sets `matched_run_id`
- [x] 3.4 Create `backend/app/services/backup_service.py`: `run_backup(db_path, backup_dir) -> BackupRecord`; `prune_backups(backup_dir, retain=30)` deletes oldest files beyond retention limit
- [x] 3.5 Create `backend/app/services/notification.py`: `send_push(subscription, title, body)` using Web Push protocol; `dispatch_workout_reminder(profile_id, db)`; `dispatch_inactivity_check(profile_id, db)`

---

## 4. Profile and Settings API

- [x] 4.1 Create `backend/app/routers/profiles.py`: `GET /api/v1/profiles` (list both), `GET /api/v1/profiles/{profile_id}`, `PUT /api/v1/profiles/{profile_id}`
- [x] 4.2 Create `backend/app/routers/settings.py`: `GET/PUT /api/v1/settings` (shared AppSettings); `GET/PUT /api/v1/profiles/{profile_id}/settings` (ProfileSettings); `GET/PUT /api/v1/profiles/{profile_id}/settings/weather` (ProfileWeatherSettings)

---

## 5. Pace Zones and HR Zones API

- [x] 5.1 Create `backend/app/routers/zones.py`: `GET /api/v1/profiles/{profile_id}/zones` returns PaceZones + HeartRateZones; `POST /api/v1/profiles/{profile_id}/zones/recalculate` accepts a race result and recalculates VDOT + zones
- [x] 5.2 On zone update, propagate new `target_pace_zone` references to all future Workouts in the active Training_Plan for that profile

---

## 6. AI Coach and Training Plan

- [x] 6.1 Create `backend/app/services/ai_coach.py`: `generate_plan(profile, race_goal, pace_zones, db) -> TrainingPlan` — builds Gemini prompt with profile data, calls `gemini-2.0-flash` with `response_mime_type: "application/json"`, parses structured JSON response into ORM objects
- [x] 6.2 Implement Gemini rate-limit token bucket (≤15 RPM) and async retry with exponential backoff (max 3 attempts) in `ai_coach.py`
- [x] 6.3 Implement plan schema validation in `ai_coach.py`: enforce only allowed workout types (`easy`, `tempo`, `interval`, `hills`, `long`, `race`, `rest`, `recovery`), reject any other type with a re-prompt
- [x] 6.4 Implement `adapt_plan(trigger, context, profile_id, db)` in `ai_coach.py`: handles skipped workout, run deviation >20%, RPE >8 for 2 consecutive same-type, injury report — re-prompts Gemini with remaining plan + context
- [x] 6.5 Implement taper block injection in `ai_coach.py`: for plans ≥ 8 weeks, include a Taper Training_Block as the final block with 20–40% volume reduction; taper duration based on race distance
- [x] 6.6 Create `backend/app/routers/plans.py`: `GET/POST /api/v1/profiles/{profile_id}/plans`, `GET /api/v1/profiles/{profile_id}/plans/{id}`, `POST /api/v1/profiles/{profile_id}/plans/{id}/regenerate`, `DELETE /api/v1/profiles/{profile_id}/plans/{id}` (plan reset — deletes plan + blocks + workouts, preserves run history)
- [x] 6.7 Create `backend/app/routers/workouts.py`: `GET /api/v1/workouts/{id}` (with computed `estimated_duration_seconds` on each step), `PATCH /api/v1/workouts/{id}` (mark complete/skip, log RPE)

---

## 7. Run Logging and History

- [x] 7.1 Create `backend/app/routers/runs.py`: `GET /api/v1/profiles/{profile_id}/runs` (with filters: date_range, run_type, distance_range), `POST /api/v1/profiles/{profile_id}/runs` (manual entry with validation), `GET/PUT/DELETE /api/v1/profiles/{profile_id}/runs/{id}`
- [x] 7.2 On manual run save, call `workout_matcher.match_run_to_workout()` and trigger `plan_adaptation_check` if deviation >20%
- [x] 7.3 Create `backend/app/routers/stats.py`: `GET /api/v1/profiles/{profile_id}/stats/weekly` (weekly km totals), `GET /api/v1/profiles/{profile_id}/stats/monthly` (monthly summary), `GET /api/v1/profiles/{profile_id}/stats/prs` (personal records for 1k/5k/10k/HM/marathon — best pace within 5% of target distance)

---

## 8. Strava Integration

- [x] 8.1 Create `backend/app/services/strava_client.py`: OAuth token exchange, token refresh (auto-refresh if within 5 min of expiry), `fetch_activities(profile_id, after_timestamp, db) -> list[StravaActivity]`, encrypt/decrypt tokens at rest using `SECRET_KEY`
- [x] 8.2 Create `backend/app/routers/strava.py`: `GET /api/v1/profiles/{profile_id}/strava/auth` (redirect to Strava OAuth), `GET /api/v1/profiles/{profile_id}/strava/callback` (exchange code, store token, trigger 90-day import), `DELETE /api/v1/profiles/{profile_id}/strava/disconnect` (revoke token, retain run data), `GET /api/v1/profiles/{profile_id}/strava/status`
- [x] 8.3 Implement `strava_sync` scheduler job: for each profile with a connected Strava account, fetch new activities, import as Run records, call `workout_matcher`, trigger `plan_adaptation_check`
- [x] 8.4 Create `backend/app/services/strava_bulk_importer.py`: `parse_zip(file) -> list[ActivityRecord]` (reads `activities.csv`, GPX fallback for missing data), `import_activities(records, profile_id, db) -> ImportResult` (idempotent on `strava_activity_id + profile_id`, recalculates VDOT after import)
- [x] 8.5 Create `backend/app/routers/strava.py` bulk import endpoints: `POST /api/v1/profiles/{profile_id}/strava/bulk-import` (multipart file upload), `GET /api/v1/profiles/{profile_id}/strava/import-history`

---

## 9. Garmin FIT Export

- [x] 9.1 Create `backend/app/services/fit_exporter.py`: `export(workout, pace_zones) -> bytes` — builds FIT file with `file_id`, `workout`, and `wkt_step` messages; maps pace zones to m/s speed ranges; encodes interval repeat blocks as FIT repeat steps; raises `ValueError` if any step missing `distance_metres`
- [x] 9.2 Create `backend/app/routers/export.py`: `GET /api/v1/workouts/{id}/export/fit` — calls `FitExporter.export()`, returns file with `Content-Disposition: attachment; filename="{workout_type}_{date}.fit"`, returns HTTP 404 if workout not found, HTTP 422 if step missing distance

---

## 10. Post-Run Analysis

- [x] 10.1 Create `backend/app/services/post_run_analyzer.py`: `analyze(run, workout, pace_zones) -> PostRunAnalysisResult` — computes distance comparison, pace comparison (on_target/faster/slower vs zone boundaries), extracts km splits from `raw_strava_data`, calls Gemini for 2–3 sentence coaching summary
- [x] 10.2 Create `backend/app/routers/analysis.py`: `GET /api/v1/profiles/{profile_id}/runs/{run_id}/analysis` — returns `PostRunAnalysisResponse`; HTTP 404 if run not matched to a workout

---

## 11. Weather-Aware Coaching

- [x] 11.1 Create `backend/app/services/weather_service.py`: `get_forecast(profile_id, forecast_date, db) -> WeatherForecast | None` — loads `ProfileWeatherSettings`, checks `WeatherCache` (3-hour TTL), calls Open-Meteo API, stores result in cache; `build_advisories(forecast) -> list[str]` — heat/humidity (>25°C or >80%), rain, wind (>30 km/h)
- [x] 11.2 Create `backend/app/routers/weather.py`: `GET /api/v1/profiles/{profile_id}/workouts/{id}/weather` returns `WeatherForecastResponse`; `GET/PUT /api/v1/profiles/{profile_id}/settings/weather`
- [x] 11.3 Implement `weather_prefetch` scheduler job: daily at 06:00, pre-fetch forecasts for each profile's next 7 days of scheduled workouts
- [x] 11.4 In workout detail API response, append weather advisory text to `coaching_note` when advisories are present and `weather_advisories_enabled` is true for the profile

---

## 12. GPX Route Suggestions

- [x] 12.1 Create `backend/app/services/route_extractor.py`: `extract_routes(profile_id, db) -> int` — decodes `summary_polyline` from `raw_strava_data`, computes SHA-256 fingerprint of simplified polyline (Douglas-Peucker ε=10m), upserts `RouteRecord` (run_count, last_used_at, workout_type_affinity); `get_suggestions(workout, profile_id, db) -> list[RouteRecord]` — filters by ±20% distance, ranks by type affinity then run_count then recency, returns top 3
- [x] 12.2 Create `backend/app/routers/routes.py`: `GET /api/v1/profiles/{profile_id}/routes?workout_id={id}` returns list of `RouteRecordResponse` with `thumbnail_url` constructed from polyline
- [x] 12.3 Implement `route_extraction` scheduler job: runs after each `strava_sync`, calls `extract_routes` for each profile

---

## 13. Taper Calculator

- [x] 13.1 Create `backend/app/services/taper_calculator.py`: `get_taper_status(profile_id, db) -> TaperStatus` — checks active plan + race goal, computes `days_until_race`, activates taper if ≤21 days, determines taper week and volume reduction %; `should_block_volume_increase(profile_id, db) -> bool`
- [x] 13.2 Create `backend/app/routers/taper.py`: `GET /api/v1/profiles/{profile_id}/taper` returns `TaperStatusResponse`
- [x] 13.3 In `ai_coach.adapt_plan()`, call `taper_calculator.should_block_volume_increase()` and include explicit instruction in Gemini prompt to not increase volume when taper is active

---

## 14. Data Export and Import

- [x] 14.1 Create `backend/app/services/data_export_service.py`: `export_profile(profile_id, db) -> ProfileDataExport` — serialises all profile data (profile, pace zones, HR zones, race goals, training plans with blocks and workouts, runs, import history) to a `ProfileDataExport` dict; `import_profile(data, profile_id, mode, db)` — validates schema version, supports `merge` (skip existing) and `replace` (delete all first) modes
- [x] 14.2 Create `backend/app/routers/data_export.py`: `GET /api/v1/profiles/{profile_id}/export/json` (returns JSON file download), `POST /api/v1/profiles/{profile_id}/import/json` (multipart JSON upload, validates and restores)
- [x] 14.3 Add `GET /api/v1/profiles/{profile_id}/export/csv` (runs as CSV) and `GET /api/v1/profiles/{profile_id}/export/ical` (active plan as iCal) to `data_export.py`

---

## 15. SvelteKit Frontend — Foundation

- [x] 15.1 Initialise SvelteKit project with TypeScript, static adapter, Tailwind CSS
- [x] 15.2 Create `src/lib/api.ts`: typed fetch wrapper for all `/api/v1/*` endpoints, profile_id-aware (reads from active profile store)
- [x] 15.3 Create `src/lib/stores.ts`: Svelte stores — `activeProfile` (persisted to localStorage), `plan`, `settings`, `taperStatus`
- [x] 15.4 Create `src/lib/notifications.ts`: service worker registration, Web Push subscription, permission request flow
- [x] 15.5 Create `src/service-worker.ts`: push notification handler
- [x] 15.6 Create `src/routes/+layout.svelte`: app shell with navigation sidebar, profile switcher component (shows both profile names, highlights active, switches on click), notification permission banner

---

## 16. Frontend — Dashboard

- [x] 16.1 Create `src/routes/+page.svelte` (Dashboard): profile switcher, next workout card (type, distance, pace zone, weather badge), training block + weeks-to-race, weekly mileage progress bar, streak display, 3 recent runs
- [x] 16.2 Implement race countdown widget: shown only when active Race_Goal exists — days remaining, motivational message by tier, dismiss button (session-only)
- [x] 16.3 Implement taper mode indicator: replaces training block name with "Taper Mode" badge + guidance panel when taper is active
- [x] 16.4 Show "Create your first plan" prompt when no active Training_Plan exists for the active profile

---

## 17. Frontend — Onboarding

- [x] 17.1 Create `src/routes/onboarding/+page.svelte`: multi-step onboarding flow — profile name, DOB, sex, injury notes, race goal (distance + date + label), optional Strava bulk import upload, optional manual fitness fields (required only if no bulk import)
- [x] 17.2 Implement Strava bulk import upload step: file picker for ZIP, progress indicator, import summary (imported/skipped/VDOT)
- [x] 17.3 On onboarding completion, redirect to plan generation loading screen, then Dashboard

---

## 18. Frontend — Training Plan

- [x] 18.1 Create `src/routes/plan/+page.svelte`: scrollable weekly calendar view of the active Training_Plan; each day shows workout type chip (colour-coded by type), distance, pace zone; weather badge on upcoming workouts
- [x] 18.2 Implement workout type colour coding: Easy=green, Tempo=orange, Intervals=red, Hills=purple, Long Run=blue, Race=gold, Rest=grey, Recovery=light-green
- [x] 18.3 Implement "Reset Plan" button: opens confirmation dialog with exact text "This will permanently delete your current training plan and all scheduled workouts. This cannot be undone. Are you sure?" with Cancel and Reset Plan buttons; calls `DELETE /api/v1/profiles/{profile_id}/plans/{id}` on confirm
- [x] 18.4 Implement "Regenerate Plan" button with loading state

---

## 19. Frontend — Workout Detail

- [x] 19.1 Create `src/routes/workout/[id]/+page.svelte`: workout header (type, date, total distance, estimated duration), step-by-step session structure (each step: label, distance km, pace zone, HR zone, description), coaching note (with weather advisory appended if applicable), weather badge
- [x] 19.2 Implement workout type-specific step display: Intervals and Hills show repeat count and individual step distances; Rest shows rest day indicator only
- [x] 19.3 Implement RPE logging modal: shown after marking workout complete, 1–10 scale with descriptive labels
- [x] 19.4 Implement "Download for Garmin" button: calls `GET /api/v1/workouts/{id}/export/fit`, triggers file download, shows transfer instructions modal ("Connect Forerunner 970 via USB → copy to GARMIN/NEWFILES → eject")
- [x] 19.5 Show route suggestions section (up to 3 cards with map thumbnail, distance, run count) when GPS routes are available for the profile

---

## 20. Frontend — Run History and Post-Run Analysis

- [x] 20.1 Create `src/routes/runs/+page.svelte`: chronological run list with filters (date range, run type, distance range); each row shows date, distance km, pace min/km, HR, elevation; PR badge when applicable
- [x] 20.2 Create manual run entry form (inline or modal): date, distance km, duration, optional HR, optional notes; client-side validation before submit
- [x] 20.3 Create `src/routes/runs/[id]/analysis/+page.svelte`: post-run analysis screen — target vs actual distance, pace comparison (on-target/faster/slower highlight), HR zone comparison, elevation, per-km splits table, AI coaching summary; accessible from run detail and matched workout detail

---

## 21. Frontend — Statistics

- [x] 21.1 Create `src/routes/stats/+page.svelte`: weekly mileage bar chart (Chart.js), monthly summary cards, streak display (current + all-time), personal records table (1k/5k/10k/HM/marathon)
- [x] 21.2 Implement PR highlight animation when a new PR is detected on run save

---

## 22. Frontend — Zones Screen

- [x] 22.1 Create `src/routes/zones/+page.svelte`: display 5 pace zones (min/km ranges + plain-language descriptions) and 5 HR zones (bpm ranges + descriptions) for the active profile; "Recalculate from race result" form (distance + time input)

---

## 23. Frontend — Settings

- [x] 23.1 Create `src/routes/settings/+page.svelte` with sections: Profile (name, DOB, sex, injury notes), Strava Integration (connect/disconnect button, last sync time, sync interval slider, bulk import upload), Notifications (enable toggle, time picker per profile), Weather (location input, advisory toggle), Data (export JSON, export CSV, export iCal, import JSON, manual backup trigger, last backup time)
- [x] 23.2 Implement Strava connect flow: redirect to `/api/v1/profiles/{profile_id}/strava/auth`, handle callback redirect back to settings
- [x] 23.3 Implement data export buttons: JSON (full profile data), CSV (runs), iCal (plan); import JSON with mode selector (merge/replace) and confirmation dialog

---

## 24. Property-Based Tests

- [x] 24.1 Set up `backend/tests/` with pytest, pytest-asyncio, httpx AsyncClient, Hypothesis; configure `pyproject.toml` with `asyncio_mode = "auto"` and `max_examples = 100`
- [x] 24.2 Write PBT for Property 1: IP filter rejects all non-RFC-1918 addresses
- [x] 24.3 Write PBT for Properties 2–3: profile round-trip and validation
- [x] 24.4 Write PBT for Properties 4–7: generated plan date range, training blocks, quality workout constraint, rest day invariant (mock Gemini responses)
- [x] 24.5 Write PBT for Properties 8–9: VDOT pace zone percentage bands, fitness change threshold
- [x] 24.6 Write PBT for Properties 10–11: workout API field completeness, step distance sum
- [x] 24.7 Write PBT for Properties 12–13: RPE adaptation trigger, run deviation threshold
- [x] 24.8 Write PBT for Property 14: race goal date preserved across all adaptation triggers
- [x] 24.9 Write PBT for Properties 15–16: run import/matching invocation, Strava error handling
- [x] 24.10 Write PBT for Property 17: manual run validation (non-positive distance/duration)
- [x] 24.11 Write PBT for Properties 18–20: run history ordering, metric fields, aggregation totals
- [x] 24.12 Write PBT for Properties 21–23: streak calculation, PR identification, filter correctness
- [x] 24.13 Write PBT for Property 24: HR zone percentage bands
- [x] 24.14 Write PBT for Property 25: pace zone updates propagate to future workouts only
- [x] 24.15 Write PBT for Properties 26–27: backup pruning retains exactly 30, bulk import idempotency
- [x] 24.16 Write PBT for Property 28: FIT file step count and distance sum match workout
- [x] 24.17 Write PBT for Property 29: post-run pace comparison classification
- [x] 24.18 Write PBT for Property 30: weather advisory threshold correctness
- [x] 24.19 Write PBT for Property 31: taper phase activation threshold and volume block
- [x] 24.20 Write PBT for Property 32: route suggestions distance tolerance

---

## 25. Frontend Tests

- [x] 25.1 Write Vitest unit tests for onboarding form validation (required fields, bulk import optional logic)
- [x] 25.2 Write Vitest unit tests for manual run entry form validation
- [x] 25.3 Write Vitest unit tests for streak calculation and PR detection in stores
- [x] 25.4 Write Vitest unit tests for reset plan confirmation dialog (cancel = no action, confirm = API call)
- [x] 25.5 Write Playwright E2E test for onboarding flow (profile 1 and profile 2)
- [x] 25.6 Write Playwright E2E test for profile switching on dashboard

---

## 26. Integration and Final Wiring

- [x] 26.1 Wire all routers into `main.py` with correct prefixes and tags
- [x] 26.2 Verify all `profile_id` scoping — no endpoint returns data from a different profile than requested
- [x] 26.3 Verify Docker Compose health checks: backend `/health` endpoint, frontend nginx status
- [x] 26.4 Test full Docker Compose build on ARM64 (or emulated): `docker compose build && docker compose up -d`
- [x] 26.5 Verify RAM usage under normal operation stays below 1 GB
- [x] 26.6 Write `SETUP.md` with Raspberry Pi deployment guide: install Docker, clone repo, configure `.env` (Gemini API key, Strava app credentials), `docker compose up -d`, access URL, how to upload Strava bulk export
