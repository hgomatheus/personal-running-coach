/**
 * Personal Record (PR) detection utilities for the Personal Running Coach app.
 *
 * A PR is the best (lowest) pace among all runs whose distance is within 5%
 * of a target distance. Tracked distances: 1 km, 5 km, 10 km, half marathon
 * (21.0975 km), marathon (42.195 km).
 *
 * All distances are in metres internally.
 */

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Tracked PR distances in metres */
export const PR_DISTANCES_METRES = {
	'1km': 1000,
	'5km': 5000,
	'10km': 10000,
	halfMarathon: 21097.5,
	marathon: 42195
} as const;

export type PrDistanceKey = keyof typeof PR_DISTANCES_METRES;

/** Tolerance band: a run is a PR candidate if its distance is within 5% of the target */
export const PR_TOLERANCE = 0.05;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * Minimal run record needed for PR detection.
 */
export interface RunRecord {
	id: number;
	/** Distance in metres */
	distanceMetres: number;
	/** Average pace in seconds per km (lower = faster) */
	avgPaceSecPerKm: number;
}

/**
 * Result of a PR lookup for a single distance.
 */
export interface PrResult {
	/** The distance key this PR is for */
	distance: PrDistanceKey;
	/** The run that holds the PR, or null if no qualifying run exists */
	run: RunRecord | null;
	/** Best pace in sec/km, or null if no qualifying run */
	bestPaceSecPerKm: number | null;
}

// ---------------------------------------------------------------------------
// Core logic
// ---------------------------------------------------------------------------

/**
 * Returns true if the given distance (in metres) is within 5% of the target
 * distance (in metres).
 *
 * A run is a PR candidate for a distance if:
 *   target * 0.95 ≤ runDistance ≤ target * 1.05
 */
export function isPrCandidate(runDistanceMetres: number, targetDistanceMetres: number): boolean {
	const lower = targetDistanceMetres * (1 - PR_TOLERANCE);
	const upper = targetDistanceMetres * (1 + PR_TOLERANCE);
	return runDistanceMetres >= lower && runDistanceMetres <= upper;
}

/**
 * Finds the personal record for a specific target distance from a list of runs.
 *
 * The PR is the run with the lowest avg_pace_sec_per_km among all runs whose
 * distance is within 5% of the target distance.
 *
 * @param runs                  All run records to search.
 * @param targetDistanceMetres  The target distance in metres.
 * @returns                     The PR run and its pace, or null values if no
 *                              qualifying run exists.
 */
export function findPrForDistance(
	runs: RunRecord[],
	targetDistanceMetres: number
): { run: RunRecord | null; bestPaceSecPerKm: number | null } {
	const candidates = runs.filter((r) => isPrCandidate(r.distanceMetres, targetDistanceMetres));

	if (candidates.length === 0) {
		return { run: null, bestPaceSecPerKm: null };
	}

	// Best pace = lowest seconds per km
	const best = candidates.reduce((prev, curr) =>
		curr.avgPaceSecPerKm < prev.avgPaceSecPerKm ? curr : prev
	);

	return { run: best, bestPaceSecPerKm: best.avgPaceSecPerKm };
}

/**
 * Returns all personal records for all tracked distances.
 *
 * @param runs  All run records for the profile.
 * @returns     A map from distance key to PR result.
 */
export function getAllPrs(runs: RunRecord[]): Record<PrDistanceKey, PrResult> {
	const result = {} as Record<PrDistanceKey, PrResult>;

	for (const [key, targetMetres] of Object.entries(PR_DISTANCES_METRES) as [
		PrDistanceKey,
		number
	][]) {
		const { run, bestPaceSecPerKm } = findPrForDistance(runs, targetMetres);
		result[key] = { distance: key, run, bestPaceSecPerKm };
	}

	return result;
}

/**
 * Determines whether a new run sets a new PR for a given target distance.
 *
 * A new PR is set when:
 * 1. The new run is a PR candidate (within 5% of target distance), AND
 * 2. Either there is no existing PR, OR the new run's pace is strictly better
 *    (lower) than the existing PR pace.
 *
 * @param newRun                The newly completed run.
 * @param existingPrPaceSecPerKm  The current PR pace (null if no PR exists yet).
 * @param targetDistanceMetres  The target distance in metres.
 * @returns                     true if the new run sets a new PR.
 */
export function isNewPr(
	newRun: RunRecord,
	existingPrPaceSecPerKm: number | null,
	targetDistanceMetres: number
): boolean {
	if (!isPrCandidate(newRun.distanceMetres, targetDistanceMetres)) {
		return false;
	}
	if (existingPrPaceSecPerKm === null) {
		// No existing PR — any qualifying run is a new PR
		return true;
	}
	return newRun.avgPaceSecPerKm < existingPrPaceSecPerKm;
}
