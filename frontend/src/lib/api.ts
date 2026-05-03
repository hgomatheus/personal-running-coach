/**
 * Typed fetch wrapper for all /api/v1/* endpoints.
 * Reads the active profile ID from the activeProfile store.
 */

import { get } from 'svelte/store';
import { activeProfile } from './stores';

const BASE = '/api/v1';

// ---------------------------------------------------------------------------
// Core fetch helper
// ---------------------------------------------------------------------------

class ApiError extends Error {
	constructor(
		public readonly status: number,
		message: string
	) {
		super(message);
		this.name = 'ApiError';
	}
}

async function request<T>(
	method: string,
	path: string,
	body?: unknown,
	extraHeaders?: Record<string, string>
): Promise<T> {
	const headers: Record<string, string> = {
		'Content-Type': 'application/json',
		...extraHeaders
	};

	const init: RequestInit = {
		method,
		headers,
		...(body !== undefined ? { body: JSON.stringify(body) } : {})
	};

	const res = await fetch(`${BASE}${path}`, init);

	if (!res.ok) {
		let detail = res.statusText;
		try {
			const json = await res.json();
			detail = json.detail ?? detail;
		} catch {
			// ignore parse errors
		}
		throw new ApiError(res.status, detail);
	}

	// 204 No Content
	if (res.status === 204) return undefined as unknown as T;

	return res.json() as Promise<T>;
}

const get_ = <T>(path: string) => request<T>('GET', path);
const post = <T>(path: string, body?: unknown) => request<T>('POST', path, body);
const put = <T>(path: string, body: unknown) => request<T>('PUT', path, body);
const patch = <T>(path: string, body: unknown) => request<T>('PATCH', path, body);
const del = <T>(path: string) => request<T>('DELETE', path);

/** Returns the currently active profile ID from the store. */
function pid(): number {
	return get(activeProfile);
}

// ---------------------------------------------------------------------------
// Types (mirroring backend Pydantic schemas)
// ---------------------------------------------------------------------------

export interface Profile {
	id: number;
	display_name: string;
	date_of_birth: string | null;
	biological_sex: string | null;
	current_weekly_km: number | null;
	longest_recent_run_km: number | null;
	injury_notes: string | null;
	created_at: string | null;
	updated_at: string | null;
}

export interface ProfileUpdate {
	display_name: string;
	date_of_birth?: string | null;
	biological_sex?: 'male' | 'female' | 'other' | null;
	current_weekly_km?: number | null;
	longest_recent_run_km?: number | null;
	injury_notes?: string | null;
}

export interface ProfileSettings {
	id: number;
	profile_id: number;
	notification_enabled: boolean;
	notification_time: string | null;
	push_subscription: Record<string, unknown> | null;
}

export interface ProfileSettingsUpdate {
	notification_enabled: boolean;
	notification_time?: string | null;
	push_subscription?: Record<string, unknown> | null;
}

export interface AppSettings {
	id: number;
	strava_sync_interval_minutes: number;
	backup_enabled: boolean;
	backup_retention_days: number;
}

export interface AppSettingsUpdate {
	strava_sync_interval_minutes?: number;
	backup_enabled?: boolean;
	backup_retention_days?: number;
}

export interface TrainingPlan {
	id: number;
	profile_id: number;
	race_goal_id: number | null;
	start_date: string;
	end_date: string;
	status: string;
	gemini_prompt_hash: string | null;
	created_at: string | null;
	updated_at: string | null;
}

export interface WorkoutSummary {
	id: number;
	scheduled_date: string;
	workout_type: string;
	target_distance_metres: number | null;
	target_pace_zone: string | null;
	status: string;
	coaching_note: string | null;
}

export interface TrainingBlock {
	id: number;
	profile_id: number;
	plan_id: number;
	name: string;
	start_date: string;
	end_date: string;
	sequence: number;
	workouts: WorkoutSummary[];
}

export interface TrainingPlanDetail extends TrainingPlan {
	blocks: TrainingBlock[];
}

export interface WorkoutStep {
	sequence: number;
	label: string;
	distance_metres: number;
	estimated_duration_seconds: number;
	pace_zone: string | null;
	hr_zone: number | null;
	description: string | null;
}

export interface Workout {
	id: number;
	profile_id: number;
	block_id: number | null;
	plan_id: number;
	scheduled_date: string;
	workout_type: string;
	target_distance_metres: number | null;
	estimated_duration_seconds: number | null;
	target_pace_zone: string | null;
	target_hr_zone: number | null;
	steps: WorkoutStep[];
	coaching_note: string | null;
	status: string;
	rpe_score: number | null;
	matched_run_id: number | null;
	created_at: string | null;
	updated_at: string | null;
}

export interface WorkoutPatch {
	status?: 'completed' | 'skipped';
	rpe_score?: number;
}

export interface Run {
	id: number;
	profile_id: number;
	source: string;
	strava_activity_id: number | null;
	date: string;
	started_at: string | null;
	distance_metres: number;
	duration_seconds: number;
	avg_pace_sec_per_km: number | null;
	avg_heart_rate: number | null;
	elevation_gain_metres: number | null;
	run_type: string | null;
	notes: string | null;
	created_at: string | null;
	updated_at: string | null;
}

export interface RunCreate {
	date: string;
	distance_metres: number;
	duration_seconds: number;
	avg_heart_rate?: number | null;
	elevation_gain_metres?: number | null;
	run_type?: string | null;
	notes?: string | null;
}

export interface RunUpdate {
	date?: string;
	distance_metres?: number;
	duration_seconds?: number;
	avg_heart_rate?: number | null;
	elevation_gain_metres?: number | null;
	run_type?: string | null;
	notes?: string | null;
}

export interface RunFilters {
	date_from?: string;
	date_to?: string;
	run_type?: string;
	min_distance_km?: number;
	max_distance_km?: number;
}

export interface WeeklyStats {
	week_start: string;
	total_km: number;
	run_count: number;
}

export interface MonthlyStats {
	year: number;
	month: number;
	total_km: number;
	total_duration_seconds: number;
	run_count: number;
}

export interface PersonalRecord {
	distance_label: string;
	target_distance_metres: number;
	run_id: number | null;
	run_date: string | null;
	distance_metres: number | null;
	duration_seconds: number | null;
	avg_pace_sec_per_km: number | null;
}

export interface PRsResponse {
	records: PersonalRecord[];
}

export interface PaceZones {
	id: number;
	profile_id: number;
	vdot: number | null;
	easy_min_sec_per_km: number | null;
	easy_max_sec_per_km: number | null;
	moderate_min_sec_per_km: number | null;
	moderate_max_sec_per_km: number | null;
	threshold_min_sec_per_km: number | null;
	threshold_max_sec_per_km: number | null;
	vo2max_min_sec_per_km: number | null;
	vo2max_max_sec_per_km: number | null;
	anaerobic_min_sec_per_km: number | null;
	anaerobic_max_sec_per_km: number | null;
	updated_at: string | null;
}

export interface HRZones {
	id: number;
	profile_id: number;
	max_hr: number;
	zone1_max: number;
	zone2_max: number;
	zone3_max: number;
	zone4_max: number;
	zone5_max: number;
	updated_at: string | null;
}

export interface ZonesResponse {
	pace_zones: PaceZones | null;
	hr_zones: HRZones | null;
}

export interface ZoneRecalculateRequest {
	distance_metres: number;
	duration_seconds: number;
	max_hr?: number | null;
}

export interface ZoneRecalculateResponse {
	pace_zones: PaceZones;
	hr_zones: HRZones | null;
	vdot: number;
}

export interface StravaStatus {
	connected: boolean;
	athlete_id: number | null;
	last_sync_at: string | null;
	sync_error: string | null;
}

export interface BulkImportResponse {
	imported: number;
	skipped_duplicates: number;
	parse_errors: number;
	vdot: number | null;
	pace_zones_updated: boolean;
}

export interface WeatherForecast {
	workout_id: number;
	forecast_date: string;
	temperature_c: number;
	humidity_pct: number;
	wind_kmh: number;
	conditions: string;
	advisories: string[];
	cached: boolean;
}

export interface ProfileWeatherSettings {
	id: number;
	profile_id: number;
	location_name: string | null;
	latitude: number | null;
	longitude: number | null;
	weather_advisories_enabled: boolean;
}

export interface ProfileWeatherSettingsUpdate {
	location_name?: string | null;
	latitude?: number | null;
	longitude?: number | null;
	weather_advisories_enabled?: boolean;
}

export interface RouteRecord {
	id: number;
	polyline: string;
	typical_distance_km: number;
	run_count: number;
	last_used_at: string;
	workout_type_affinity: string | null;
	thumbnail_url: string | null;
}

export interface TaperGuidance {
	target_mileage_reduction_pct: number;
	sleep_nutrition_reminder: string;
	sluggishness_note: string;
}

export interface TaperStatus {
	taper_active: boolean;
	days_until_race: number | null;
	taper_week: number | null;
	volume_reduction_pct: number | null;
	guidance: TaperGuidance | null;
}

export interface PostRunAnalysis {
	run_id: number;
	workout_id: number;
	target_distance_km: number;
	actual_distance_km: number;
	target_pace_zone: string;
	actual_avg_pace_sec_per_km: number | null;
	pace_on_target: boolean | null;
	pace_comparison: string | null;
	target_hr_zone: number | null;
	actual_avg_hr: number | null;
	actual_elevation_gain_metres: number | null;
	km_splits: Array<{ km: number; pace_sec_per_km: number | null; avg_hr: number | null }>;
	coaching_summary: string;
}

export interface RaceGoal {
	id: number;
	profile_id: number;
	distance_metres: number;
	target_date: string;
	label: string | null;
	is_active: boolean;
	created_at: string | null;
}

export interface RaceGoalCreate {
	distance_metres: number;
	target_date: string;
	label?: string | null;
	is_active?: boolean;
}

export interface BackupRecord {
	id: number;
	completed_at: string;
	file_path: string;
	size_bytes: number;
	success: boolean;
	error_message: string | null;
}

// ---------------------------------------------------------------------------
// Profiles API
// ---------------------------------------------------------------------------

export const profilesApi = {
	list: () => get_<Profile[]>('/profiles'),
	get: (profileId: number) => get_<Profile>(`/profiles/${profileId}`),
	update: (profileId: number, body: ProfileUpdate) =>
		put<Profile>(`/profiles/${profileId}`, body)
};

// ---------------------------------------------------------------------------
// Plans API
// ---------------------------------------------------------------------------

export const plansApi = {
	list: (profileId = pid()) => get_<TrainingPlan[]>(`/profiles/${profileId}/plans`),
	create: (raceGoalId: number, profileId = pid()) =>
		post<TrainingPlan>(`/profiles/${profileId}/plans`, { race_goal_id: raceGoalId }),
	get: (planId: number, profileId = pid()) =>
		get_<TrainingPlanDetail>(`/profiles/${profileId}/plans/${planId}`),
	regenerate: (planId: number, profileId = pid()) =>
		post<TrainingPlan>(`/profiles/${profileId}/plans/${planId}/regenerate`),
	delete: (planId: number, profileId = pid()) =>
		del<void>(`/profiles/${profileId}/plans/${planId}?confirm=true`)
};

// ---------------------------------------------------------------------------
// Workouts API
// ---------------------------------------------------------------------------

export const workoutsApi = {
	get: (workoutId: number, profileId = pid()) =>
		get_<Workout>(`/workouts/${workoutId}?profile_id=${profileId}`),
	patch: (workoutId: number, body: WorkoutPatch, profileId = pid()) =>
		patch<Workout>(`/workouts/${workoutId}?profile_id=${profileId}`, body),
	exportFit: (workoutId: number, profileId = pid()) =>
		`${BASE}/workouts/${workoutId}/export/fit?profile_id=${profileId}`,
	getWeather: (workoutId: number, profileId = pid()) =>
		get_<WeatherForecast>(`/profiles/${profileId}/workouts/${workoutId}/weather`)
};

// ---------------------------------------------------------------------------
// Runs API
// ---------------------------------------------------------------------------

export const runsApi = {
	list: (filters: RunFilters = {}, profileId = pid()) => {
		const params = new URLSearchParams();
		if (filters.date_from) params.set('date_from', filters.date_from);
		if (filters.date_to) params.set('date_to', filters.date_to);
		if (filters.run_type) params.set('run_type', filters.run_type);
		if (filters.min_distance_km != null)
			params.set('min_distance_km', String(filters.min_distance_km));
		if (filters.max_distance_km != null)
			params.set('max_distance_km', String(filters.max_distance_km));
		const qs = params.toString();
		return get_<Run[]>(`/profiles/${profileId}/runs${qs ? `?${qs}` : ''}`);
	},
	create: (body: RunCreate, profileId = pid()) =>
		post<Run>(`/profiles/${profileId}/runs`, body),
	get: (runId: number, profileId = pid()) =>
		get_<Run>(`/profiles/${profileId}/runs/${runId}`),
	update: (runId: number, body: RunUpdate, profileId = pid()) =>
		put<Run>(`/profiles/${profileId}/runs/${runId}`, body),
	delete: (runId: number, profileId = pid()) =>
		del<void>(`/profiles/${profileId}/runs/${runId}`)
};

// ---------------------------------------------------------------------------
// Stats API
// ---------------------------------------------------------------------------

export const statsApi = {
	weekly: (profileId = pid()) => get_<WeeklyStats[]>(`/profiles/${profileId}/stats/weekly`),
	monthly: (profileId = pid()) => get_<MonthlyStats[]>(`/profiles/${profileId}/stats/monthly`),
	prs: (profileId = pid()) => get_<PRsResponse>(`/profiles/${profileId}/stats/prs`)
};

// ---------------------------------------------------------------------------
// Zones API
// ---------------------------------------------------------------------------

export const zonesApi = {
	get: (profileId = pid()) => get_<ZonesResponse>(`/profiles/${profileId}/zones`),
	recalculate: (body: ZoneRecalculateRequest, profileId = pid()) =>
		post<ZoneRecalculateResponse>(`/profiles/${profileId}/zones/recalculate`, body)
};

// ---------------------------------------------------------------------------
// Strava API
// ---------------------------------------------------------------------------

export const stravaApi = {
	authUrl: (profileId = pid()) => `${BASE}/profiles/${profileId}/strava/auth`,
	status: (profileId = pid()) => get_<StravaStatus>(`/profiles/${profileId}/strava/status`),
	disconnect: (profileId = pid()) =>
		del<{ detail: string }>(`/profiles/${profileId}/strava/disconnect`),
	importHistory: (profileId = pid()) =>
		get_<unknown[]>(`/profiles/${profileId}/strava/import-history`)
};

// ---------------------------------------------------------------------------
// Settings API
// ---------------------------------------------------------------------------

export const settingsApi = {
	getApp: () => get_<AppSettings>('/settings'),
	updateApp: (body: AppSettingsUpdate) => put<AppSettings>('/settings', body),
	getProfile: (profileId = pid()) =>
		get_<ProfileSettings>(`/profiles/${profileId}/settings`),
	updateProfile: (body: ProfileSettingsUpdate, profileId = pid()) =>
		put<ProfileSettings>(`/profiles/${profileId}/settings`, body),
	getWeather: (profileId = pid()) =>
		get_<ProfileWeatherSettings>(`/profiles/${profileId}/settings/weather`),
	updateWeather: (body: ProfileWeatherSettingsUpdate, profileId = pid()) =>
		put<ProfileWeatherSettings>(`/profiles/${profileId}/settings/weather`, body)
};

// ---------------------------------------------------------------------------
// Export API
// ---------------------------------------------------------------------------

export const exportApi = {
	jsonUrl: (profileId = pid()) => `${BASE}/profiles/${profileId}/export/json`,
	csvUrl: (profileId = pid()) => `${BASE}/profiles/${profileId}/export/csv`,
	icalUrl: (profileId = pid()) => `${BASE}/profiles/${profileId}/export/ical`,
	importJson: async (file: File, mode: 'merge' | 'replace' = 'merge', profileId = pid()) => {
		const form = new FormData();
		form.append('file', file);
		const res = await fetch(`${BASE}/profiles/${profileId}/import/json?mode=${mode}`, {
			method: 'POST',
			body: form
		});
		if (!res.ok) {
			const json = await res.json().catch(() => ({}));
			throw new ApiError(res.status, json.detail ?? res.statusText);
		}
		return res.json();
	}
};

// ---------------------------------------------------------------------------
// Analysis API
// ---------------------------------------------------------------------------

export const analysisApi = {
	get: (runId: number, profileId = pid()) =>
		get_<PostRunAnalysis>(`/profiles/${profileId}/runs/${runId}/analysis`)
};

// ---------------------------------------------------------------------------
// Weather API
// ---------------------------------------------------------------------------

export const weatherApi = {
	getWorkoutForecast: (workoutId: number, profileId = pid()) =>
		get_<WeatherForecast>(`/profiles/${profileId}/workouts/${workoutId}/weather`)
};

// ---------------------------------------------------------------------------
// Routes API
// ---------------------------------------------------------------------------

export const routesApi = {
	getSuggestions: (workoutId: number, profileId = pid()) =>
		get_<RouteRecord[]>(`/profiles/${profileId}/routes?workout_id=${workoutId}`)
};

// ---------------------------------------------------------------------------
// Taper API
// ---------------------------------------------------------------------------

export const taperApi = {
	get: (profileId = pid()) => get_<TaperStatus>(`/profiles/${profileId}/taper`)
};

// ---------------------------------------------------------------------------
// Race Goals API
// ---------------------------------------------------------------------------

export const raceGoalsApi = {
	list: (profileId = pid()) => get_<RaceGoal[]>(`/profiles/${profileId}/race-goals`),
	create: (body: RaceGoalCreate, profileId = pid()) =>
		post<RaceGoal>(`/profiles/${profileId}/race-goals`, body)
};

// ---------------------------------------------------------------------------
// Backup API
// ---------------------------------------------------------------------------

export const backupApi = {
	list: () => get_<BackupRecord[]>('/backups'),
	trigger: () => post<BackupRecord>('/backups/trigger')
};

export { ApiError };
