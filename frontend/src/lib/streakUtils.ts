/**
 * Streak calculation utilities for the Personal Running Coach app.
 *
 * A Streak is a consecutive sequence of calendar weeks in which the user
 * completed all scheduled Workouts. Weeks are identified by their ISO week
 * start (Monday). The current (in-progress) week does not break the streak
 * even if no workouts have been completed yet.
 *
 * All date arithmetic uses plain Date objects and avoids external dependencies
 * so these functions can be unit-tested without a Svelte runtime.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * A minimal representation of a scheduled workout for streak calculation.
 * Only the fields needed for streak logic are required.
 */
export interface WorkoutRecord {
	/** ISO date string (YYYY-MM-DD) of the scheduled date */
	scheduledDate: string;
	/** Whether the workout was completed */
	completed: boolean;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Returns the Monday (week start) for the given date as a UTC midnight Date.
 * ISO weeks start on Monday.
 */
export function getWeekStart(date: Date): Date {
	const d = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));
	const day = d.getUTCDay(); // 0 = Sunday, 1 = Monday, …
	const diff = day === 0 ? -6 : 1 - day; // shift to Monday
	d.setUTCDate(d.getUTCDate() + diff);
	return d;
}

/**
 * Returns a canonical string key for a week start date (YYYY-MM-DD).
 */
function weekKey(weekStart: Date): string {
	return weekStart.toISOString().slice(0, 10);
}

// ---------------------------------------------------------------------------
// Core logic
// ---------------------------------------------------------------------------

/**
 * Groups workouts by their ISO week start (Monday).
 * Returns a Map from week-key → array of WorkoutRecord.
 */
function groupByWeek(workouts: WorkoutRecord[]): Map<string, WorkoutRecord[]> {
	const map = new Map<string, WorkoutRecord[]>();
	for (const w of workouts) {
		const date = new Date(w.scheduledDate + 'T00:00:00Z');
		const key = weekKey(getWeekStart(date));
		const existing = map.get(key);
		if (existing) {
			existing.push(w);
		} else {
			map.set(key, [w]);
		}
	}
	return map;
}

/**
 * Returns true if all scheduled workouts in the given list were completed.
 * An empty list is treated as "no scheduled workouts" → not a completed week.
 */
function weekIsComplete(workoutsInWeek: WorkoutRecord[]): boolean {
	if (workoutsInWeek.length === 0) return false;
	return workoutsInWeek.every((w) => w.completed);
}

/**
 * Calculates the current streak from a list of workout records.
 *
 * Rules:
 * - A week "counts" if all scheduled workouts in that week were completed.
 * - The current (in-progress) week is excluded from the streak check — it
 *   does not break the streak even if no workouts have been completed yet.
 * - Weeks with no scheduled workouts are treated as gap weeks and break the
 *   streak.
 * - The streak is counted backwards from the most recent completed week.
 *
 * @param workouts  All workout records for the profile (any order).
 * @param today     Reference date for "current week" (defaults to now).
 * @returns         Current streak in weeks.
 */
export function calculateStreak(workouts: WorkoutRecord[], today: Date = new Date()): number {
	if (workouts.length === 0) return 0;

	const byWeek = groupByWeek(workouts);
	const currentWeekKey = weekKey(getWeekStart(today));

	// Collect all week keys that have scheduled workouts, sorted descending
	const allWeekKeys = Array.from(byWeek.keys()).sort().reverse();

	// Remove the current week from consideration (it's in progress)
	const pastWeekKeys = allWeekKeys.filter((k) => k !== currentWeekKey);

	if (pastWeekKeys.length === 0) return 0;

	// Walk backwards through consecutive weeks, counting completed ones
	let streak = 0;

	// Start from the most recent past week and walk backwards
	// We need to check that weeks are truly consecutive (no gap weeks)
	let expectedWeekStart: Date | null = null;

	for (const key of pastWeekKeys) {
		const weekStart = new Date(key + 'T00:00:00Z');

		if (expectedWeekStart !== null) {
			// Check if this week is exactly 7 days before the previous one
			const expectedKey = weekKey(expectedWeekStart);
			if (key !== expectedKey) {
				// There's a gap — streak is broken
				break;
			}
		}

		const weekWorkouts = byWeek.get(key)!;
		if (!weekIsComplete(weekWorkouts)) {
			// This week had scheduled workouts but not all were completed
			break;
		}

		streak++;
		// Next expected week is 7 days earlier
		expectedWeekStart = new Date(weekStart.getTime() - 7 * 24 * 60 * 60 * 1000);
	}

	return streak;
}
