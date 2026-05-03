/**
 * Svelte stores for the Personal Running Coach app.
 *
 * - activeProfile: persisted to localStorage, defaults to profile id=1
 * - plan:          active training plan (null until loaded)
 * - settings:      app-level settings (null until loaded)
 * - taperStatus:   taper phase status for the active profile (null until loaded)
 */

import { writable } from 'svelte/store';
import type { TrainingPlanDetail, AppSettings, TaperStatus } from './api';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const STORAGE_KEY_PROFILE = 'activeProfileId';

function readStoredProfileId(): number {
	if (typeof localStorage === 'undefined') return 1;
	const raw = localStorage.getItem(STORAGE_KEY_PROFILE);
	if (raw === null) return 1;
	const parsed = parseInt(raw, 10);
	// Only profiles 1 and 2 are valid
	return parsed === 1 || parsed === 2 ? parsed : 1;
}

// ---------------------------------------------------------------------------
// activeProfile — persisted writable store
// ---------------------------------------------------------------------------

function createActiveProfileStore() {
	const initial = readStoredProfileId();
	const { subscribe, set, update } = writable<number>(initial);

	return {
		subscribe,
		update,
		set(value: number) {
			const safe = value === 1 || value === 2 ? value : 1;
			if (typeof localStorage !== 'undefined') {
				localStorage.setItem(STORAGE_KEY_PROFILE, String(safe));
			}
			set(safe);
		}
	};
}

export const activeProfile = createActiveProfileStore();

// ---------------------------------------------------------------------------
// plan — active training plan for the current profile
// ---------------------------------------------------------------------------

export const plan = writable<TrainingPlanDetail | null>(null);

// ---------------------------------------------------------------------------
// settings — shared app settings
// ---------------------------------------------------------------------------

export const settings = writable<AppSettings | null>(null);

// ---------------------------------------------------------------------------
// taperStatus — taper phase status for the active profile
// ---------------------------------------------------------------------------

export const taperStatus = writable<TaperStatus | null>(null);
