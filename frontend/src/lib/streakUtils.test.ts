/**
 * Unit tests for streak calculation logic.
 *
 * A Streak is a consecutive sequence of calendar weeks in which the user
 * completed all scheduled Workouts. The current (in-progress) week does not
 * break the streak.
 *
 * Tests cover:
 *  1. Empty workout history → streak = 0
 *  2. Single week with all workouts completed → streak = 1
 *  3. Multiple consecutive weeks with all workouts completed → streak = N
 *  4. A gap week (no scheduled workouts) breaks the streak
 *  5. Current week with no completed workouts doesn't break the streak
 *  6. Streak counts only weeks where ALL scheduled workouts were completed
 */

import { describe, it, expect } from 'vitest';
import { calculateStreak, getWeekStart, type WorkoutRecord } from './streakUtils';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Returns a Monday date string (YYYY-MM-DD) for the week that is `weeksAgo`
 * weeks before the reference date's week.
 *
 * weeksAgo = 0 → current week's Monday
 * weeksAgo = 1 → last week's Monday
 */
function mondayOf(weeksAgo: number, reference: Date = TODAY): string {
	const weekStart = getWeekStart(reference);
	const d = new Date(weekStart.getTime() - weeksAgo * 7 * 24 * 60 * 60 * 1000);
	return d.toISOString().slice(0, 10);
}

/**
 * Creates a workout record on the given date string with the given completion status.
 */
function workout(date: string, completed: boolean): WorkoutRecord {
	return { scheduledDate: date, completed };
}

/**
 * Creates a set of workouts for a given week (by weeksAgo offset), all with
 * the same completion status.
 */
function weekWorkouts(
	weeksAgo: number,
	completed: boolean,
	count = 3,
	reference: Date = TODAY
): WorkoutRecord[] {
	const monday = mondayOf(weeksAgo, reference);
	// Spread workouts across Mon/Wed/Fri of that week
	const offsets = [0, 2, 4].slice(0, count);
	return offsets.map((offset) => {
		const d = new Date(monday + 'T00:00:00Z');
		d.setUTCDate(d.getUTCDate() + offset);
		return workout(d.toISOString().slice(0, 10), completed);
	});
}

// Use a fixed "today" so tests are deterministic.
// Wednesday 2024-06-12 (week starts Monday 2024-06-10)
const TODAY = new Date('2024-06-12T12:00:00Z');

// ---------------------------------------------------------------------------
// getWeekStart helper
// ---------------------------------------------------------------------------

describe('getWeekStart', () => {
	it('returns Monday for a Wednesday', () => {
		const wed = new Date('2024-06-12T00:00:00Z');
		expect(getWeekStart(wed).toISOString().slice(0, 10)).toBe('2024-06-10');
	});

	it('returns Monday for a Monday', () => {
		const mon = new Date('2024-06-10T00:00:00Z');
		expect(getWeekStart(mon).toISOString().slice(0, 10)).toBe('2024-06-10');
	});

	it('returns Monday for a Sunday', () => {
		const sun = new Date('2024-06-16T00:00:00Z');
		expect(getWeekStart(sun).toISOString().slice(0, 10)).toBe('2024-06-10');
	});

	it('returns Monday for a Saturday', () => {
		const sat = new Date('2024-06-15T00:00:00Z');
		expect(getWeekStart(sat).toISOString().slice(0, 10)).toBe('2024-06-10');
	});
});

// ---------------------------------------------------------------------------
// 1. Empty workout history
// ---------------------------------------------------------------------------

describe('calculateStreak — empty history', () => {
	it('returns 0 for an empty workout list', () => {
		expect(calculateStreak([], TODAY)).toBe(0);
	});
});

// ---------------------------------------------------------------------------
// 2. Single week with all workouts completed
// ---------------------------------------------------------------------------

describe('calculateStreak — single completed week', () => {
	it('returns 1 when last week had all workouts completed', () => {
		const workouts = weekWorkouts(1, true);
		expect(calculateStreak(workouts, TODAY)).toBe(1);
	});

	it('returns 0 when last week had workouts but none were completed', () => {
		const workouts = weekWorkouts(1, false);
		expect(calculateStreak(workouts, TODAY)).toBe(0);
	});

	it('returns 0 when last week had some completed and some not', () => {
		const monday = mondayOf(1);
		const workouts: WorkoutRecord[] = [
			workout(monday, true),
			workout(monday, false) // not completed — breaks the week
		];
		expect(calculateStreak(workouts, TODAY)).toBe(0);
	});
});

// ---------------------------------------------------------------------------
// 3. Multiple consecutive weeks all completed
// ---------------------------------------------------------------------------

describe('calculateStreak — multiple consecutive completed weeks', () => {
	it('returns 2 for two consecutive completed weeks', () => {
		const workouts = [...weekWorkouts(1, true), ...weekWorkouts(2, true)];
		expect(calculateStreak(workouts, TODAY)).toBe(2);
	});

	it('returns 3 for three consecutive completed weeks', () => {
		const workouts = [
			...weekWorkouts(1, true),
			...weekWorkouts(2, true),
			...weekWorkouts(3, true)
		];
		expect(calculateStreak(workouts, TODAY)).toBe(3);
	});

	it('returns 5 for five consecutive completed weeks', () => {
		const workouts = [
			...weekWorkouts(1, true),
			...weekWorkouts(2, true),
			...weekWorkouts(3, true),
			...weekWorkouts(4, true),
			...weekWorkouts(5, true)
		];
		expect(calculateStreak(workouts, TODAY)).toBe(5);
	});
});

// ---------------------------------------------------------------------------
// 4. A gap week breaks the streak
// ---------------------------------------------------------------------------

describe('calculateStreak — gap week breaks streak', () => {
	it('returns 1 when week 1 is complete but week 2 has no scheduled workouts (gap)', () => {
		// Only week 1 has workouts; week 2 is a gap (no scheduled workouts at all)
		const workouts = weekWorkouts(1, true);
		// Week 2 has no workouts → gap → streak stops at 1
		expect(calculateStreak(workouts, TODAY)).toBe(1);
	});

	it('returns 1 when week 1 is complete but week 2 was not completed', () => {
		const workouts = [...weekWorkouts(1, true), ...weekWorkouts(2, false)];
		expect(calculateStreak(workouts, TODAY)).toBe(1);
	});

	it('returns 1 when weeks 1 and 3 are complete but week 2 was not completed', () => {
		const workouts = [
			...weekWorkouts(1, true),
			...weekWorkouts(2, false), // breaks streak
			...weekWorkouts(3, true)
		];
		expect(calculateStreak(workouts, TODAY)).toBe(1);
	});

	it('returns 0 when only week 2 is complete but week 1 was not completed', () => {
		const workouts = [...weekWorkouts(1, false), ...weekWorkouts(2, true)];
		expect(calculateStreak(workouts, TODAY)).toBe(0);
	});

	it('returns 2 when weeks 1 and 2 are complete but week 3 was not completed', () => {
		const workouts = [
			...weekWorkouts(1, true),
			...weekWorkouts(2, true),
			...weekWorkouts(3, false)
		];
		expect(calculateStreak(workouts, TODAY)).toBe(2);
	});
});

// ---------------------------------------------------------------------------
// 5. Current week does not break the streak
// ---------------------------------------------------------------------------

describe('calculateStreak — current week in progress', () => {
	it('does not break the streak when current week has no completed workouts', () => {
		// Last week complete, current week has scheduled but not completed workouts
		const currentWeekWorkouts = weekWorkouts(0, false);
		const lastWeekWorkouts = weekWorkouts(1, true);
		const workouts = [...currentWeekWorkouts, ...lastWeekWorkouts];
		expect(calculateStreak(workouts, TODAY)).toBe(1);
	});

	it('does not break the streak when current week has no workouts at all', () => {
		// Last week complete, current week has no scheduled workouts
		const workouts = weekWorkouts(1, true);
		expect(calculateStreak(workouts, TODAY)).toBe(1);
	});

	it('does not count current week toward the streak even if all workouts are done', () => {
		// Current week complete + last week complete → streak = 2 (both count)
		const workouts = [...weekWorkouts(0, true), ...weekWorkouts(1, true)];
		// Current week is excluded from streak counting (it's in progress)
		// So only week 1 counts → streak = 1
		expect(calculateStreak(workouts, TODAY)).toBe(1);
	});
});

// ---------------------------------------------------------------------------
// 6. Streak counts only weeks where ALL scheduled workouts were completed
// ---------------------------------------------------------------------------

describe('calculateStreak — partial completion does not count', () => {
	it('does not count a week where only some workouts were completed', () => {
		const monday = mondayOf(1);
		const workouts: WorkoutRecord[] = [
			workout(monday, true),
			workout(monday, true),
			workout(monday, false) // one incomplete — week doesn't count
		];
		expect(calculateStreak(workouts, TODAY)).toBe(0);
	});

	it('counts a week where a single workout was scheduled and completed', () => {
		const monday = mondayOf(1);
		const workouts: WorkoutRecord[] = [workout(monday, true)];
		expect(calculateStreak(workouts, TODAY)).toBe(1);
	});

	it('does not count a week where a single workout was scheduled but not completed', () => {
		const monday = mondayOf(1);
		const workouts: WorkoutRecord[] = [workout(monday, false)];
		expect(calculateStreak(workouts, TODAY)).toBe(0);
	});

	it('counts consecutive weeks only up to the first incomplete week', () => {
		// Weeks 1, 2, 3 complete; week 4 partially complete; week 5 complete
		const workouts = [
			...weekWorkouts(1, true),
			...weekWorkouts(2, true),
			...weekWorkouts(3, true),
			// Week 4: one incomplete
			workout(mondayOf(4), true),
			workout(mondayOf(4), false),
			...weekWorkouts(5, true)
		];
		expect(calculateStreak(workouts, TODAY)).toBe(3);
	});
});
