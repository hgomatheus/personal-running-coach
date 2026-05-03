/**
 * Unit tests for Personal Record (PR) detection logic.
 *
 * A PR is the best (lowest) pace among all runs whose distance is within 5%
 * of a target distance. Tracked distances: 1 km, 5 km, 10 km, half marathon
 * (21.0975 km), marathon (42.195 km).
 *
 * Tests cover:
 *  1. A run at exactly 5 km is a PR candidate for the 5 km distance
 *  2. A run within 5% of 5 km (4.75 km to 5.25 km) is a PR candidate
 *  3. A run outside 5% of 5 km is NOT a PR candidate
 *  4. The PR is the run with the best (lowest) pace among all PR candidates
 *  5. A new run that beats the existing PR is detected as a new PR
 *  6. A new run that doesn't beat the existing PR is NOT a new PR
 */

import { describe, it, expect } from 'vitest';
import {
	isPrCandidate,
	findPrForDistance,
	getAllPrs,
	isNewPr,
	PR_DISTANCES_METRES,
	PR_TOLERANCE,
	type RunRecord
} from './prUtils';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

let nextId = 1;

/** Creates a minimal RunRecord with the given distance (km) and pace (sec/km). */
function run(distanceKm: number, paceSecPerKm: number): RunRecord {
	return {
		id: nextId++,
		distanceMetres: distanceKm * 1000,
		avgPaceSecPerKm: paceSecPerKm
	};
}

// Reset id counter before each test suite
beforeEach(() => {
	nextId = 1;
});

// ---------------------------------------------------------------------------
// isPrCandidate
// ---------------------------------------------------------------------------

describe('isPrCandidate', () => {
	const target5km = PR_DISTANCES_METRES['5km']; // 5000 m

	// 1. Exact distance
	it('returns true for a run at exactly 5 km', () => {
		expect(isPrCandidate(5000, target5km)).toBe(true);
	});

	// 2. Within 5% tolerance
	it('returns true for a run at the lower boundary (4.75 km = 5% below 5 km)', () => {
		expect(isPrCandidate(4750, target5km)).toBe(true);
	});

	it('returns true for a run at the upper boundary (5.25 km = 5% above 5 km)', () => {
		expect(isPrCandidate(5250, target5km)).toBe(true);
	});

	it('returns true for a run at 4.8 km (within 5% of 5 km)', () => {
		expect(isPrCandidate(4800, target5km)).toBe(true);
	});

	it('returns true for a run at 5.2 km (within 5% of 5 km)', () => {
		expect(isPrCandidate(5200, target5km)).toBe(true);
	});

	// 3. Outside 5% tolerance
	it('returns false for a run at 4.74 km (just outside 5% below 5 km)', () => {
		expect(isPrCandidate(4740, target5km)).toBe(false);
	});

	it('returns false for a run at 5.26 km (just outside 5% above 5 km)', () => {
		expect(isPrCandidate(5260, target5km)).toBe(false);
	});

	it('returns false for a run at 3 km (well outside 5% of 5 km)', () => {
		expect(isPrCandidate(3000, target5km)).toBe(false);
	});

	it('returns false for a run at 10 km (well outside 5% of 5 km)', () => {
		expect(isPrCandidate(10000, target5km)).toBe(false);
	});

	// Other tracked distances
	it('returns true for a run at exactly 1 km for the 1 km distance', () => {
		expect(isPrCandidate(1000, PR_DISTANCES_METRES['1km'])).toBe(true);
	});

	it('returns true for a run at exactly 10 km for the 10 km distance', () => {
		expect(isPrCandidate(10000, PR_DISTANCES_METRES['10km'])).toBe(true);
	});

	it('returns true for a run at exactly half marathon distance', () => {
		expect(isPrCandidate(PR_DISTANCES_METRES.halfMarathon, PR_DISTANCES_METRES.halfMarathon)).toBe(
			true
		);
	});

	it('returns true for a run at exactly marathon distance', () => {
		expect(isPrCandidate(PR_DISTANCES_METRES.marathon, PR_DISTANCES_METRES.marathon)).toBe(true);
	});

	// Tolerance boundary precision
	it('uses exactly 5% tolerance (not 4.9% or 5.1%)', () => {
		const target = 10000; // 10 km
		const lowerBound = target * (1 - PR_TOLERANCE); // 9500 m
		const upperBound = target * (1 + PR_TOLERANCE); // 10500 m
		expect(isPrCandidate(lowerBound, target)).toBe(true);
		expect(isPrCandidate(upperBound, target)).toBe(true);
		expect(isPrCandidate(lowerBound - 1, target)).toBe(false);
		expect(isPrCandidate(upperBound + 1, target)).toBe(false);
	});
});

// ---------------------------------------------------------------------------
// findPrForDistance
// ---------------------------------------------------------------------------

describe('findPrForDistance', () => {
	const target5km = PR_DISTANCES_METRES['5km'];

	it('returns null when there are no runs', () => {
		const { run: prRun, bestPaceSecPerKm } = findPrForDistance([], target5km);
		expect(prRun).toBeNull();
		expect(bestPaceSecPerKm).toBeNull();
	});

	it('returns null when no runs are within 5% of the target distance', () => {
		const runs = [run(3, 300), run(8, 280)]; // neither near 5 km
		const { run: prRun, bestPaceSecPerKm } = findPrForDistance(runs, target5km);
		expect(prRun).toBeNull();
		expect(bestPaceSecPerKm).toBeNull();
	});

	it('returns the single qualifying run as the PR', () => {
		const r = run(5, 300); // exactly 5 km, 5:00/km
		const { run: prRun, bestPaceSecPerKm } = findPrForDistance([r], target5km);
		expect(prRun).toBe(r);
		expect(bestPaceSecPerKm).toBe(300);
	});

	// 4. PR is the run with the best (lowest) pace
	it('returns the run with the lowest pace among multiple PR candidates', () => {
		const slow = run(5, 360); // 6:00/km
		const fast = run(5, 280); // 4:40/km — best
		const medium = run(5, 320); // 5:20/km
		const { run: prRun, bestPaceSecPerKm } = findPrForDistance([slow, fast, medium], target5km);
		expect(prRun).toBe(fast);
		expect(bestPaceSecPerKm).toBe(280);
	});

	it('ignores runs outside the 5% tolerance when finding the PR', () => {
		const outsideRange = run(3, 200); // very fast but wrong distance
		const inRange = run(5, 300);
		const { run: prRun } = findPrForDistance([outsideRange, inRange], target5km);
		expect(prRun).toBe(inRange);
	});

	it('considers runs within 5% tolerance (not just exact distance)', () => {
		const nearLower = run(4.8, 290); // 4.8 km — within 5% of 5 km
		const nearUpper = run(5.2, 310); // 5.2 km — within 5% of 5 km
		const { run: prRun, bestPaceSecPerKm } = findPrForDistance(
			[nearLower, nearUpper],
			target5km
		);
		expect(prRun).toBe(nearLower); // 290 < 310
		expect(bestPaceSecPerKm).toBe(290);
	});
});

// ---------------------------------------------------------------------------
// getAllPrs
// ---------------------------------------------------------------------------

describe('getAllPrs', () => {
	it('returns null PR for all distances when there are no runs', () => {
		const prs = getAllPrs([]);
		expect(prs['1km'].run).toBeNull();
		expect(prs['5km'].run).toBeNull();
		expect(prs['10km'].run).toBeNull();
		expect(prs.halfMarathon.run).toBeNull();
		expect(prs.marathon.run).toBeNull();
	});

	it('correctly identifies PRs for multiple distances from the same run list', () => {
		const run5k = run(5, 300);
		const run10k = run(10, 320);
		const prs = getAllPrs([run5k, run10k]);
		expect(prs['5km'].run).toBe(run5k);
		expect(prs['10km'].run).toBe(run10k);
		expect(prs['1km'].run).toBeNull();
	});

	it('returns the correct distance key for each PR', () => {
		const prs = getAllPrs([]);
		expect(prs['1km'].distance).toBe('1km');
		expect(prs['5km'].distance).toBe('5km');
		expect(prs['10km'].distance).toBe('10km');
		expect(prs.halfMarathon.distance).toBe('halfMarathon');
		expect(prs.marathon.distance).toBe('marathon');
	});
});

// ---------------------------------------------------------------------------
// isNewPr
// ---------------------------------------------------------------------------

describe('isNewPr', () => {
	const target5km = PR_DISTANCES_METRES['5km'];

	// 5. New run beats existing PR
	it('returns true when the new run is faster than the existing PR', () => {
		const newRun = run(5, 280); // 4:40/km — faster
		expect(isNewPr(newRun, 300, target5km)).toBe(true);
	});

	it('returns true when there is no existing PR and the run is a candidate', () => {
		const newRun = run(5, 300);
		expect(isNewPr(newRun, null, target5km)).toBe(true);
	});

	// 6. New run does not beat existing PR
	it('returns false when the new run is slower than the existing PR', () => {
		const newRun = run(5, 320); // 5:20/km — slower
		expect(isNewPr(newRun, 300, target5km)).toBe(false);
	});

	it('returns false when the new run matches the existing PR pace exactly', () => {
		const newRun = run(5, 300); // same pace — not strictly better
		expect(isNewPr(newRun, 300, target5km)).toBe(false);
	});

	it('returns false when the new run is outside the 5% tolerance', () => {
		const newRun = run(3, 200); // very fast but wrong distance
		expect(isNewPr(newRun, 300, target5km)).toBe(false);
	});

	it('returns false when the new run is outside tolerance even with no existing PR', () => {
		const newRun = run(3, 200); // wrong distance
		expect(isNewPr(newRun, null, target5km)).toBe(false);
	});

	it('returns true for a run within tolerance that beats the existing PR', () => {
		const newRun = run(4.9, 290); // 4.9 km — within 5% of 5 km, faster
		expect(isNewPr(newRun, 300, target5km)).toBe(true);
	});

	it('returns false for a run within tolerance that does not beat the existing PR', () => {
		const newRun = run(5.1, 310); // 5.1 km — within 5% of 5 km, slower
		expect(isNewPr(newRun, 300, target5km)).toBe(false);
	});

	// Edge cases for other distances
	it('correctly detects a new PR for the marathon distance', () => {
		const marathonRun = run(42.195, 280); // exactly marathon, fast
		expect(isNewPr(marathonRun, 300, PR_DISTANCES_METRES.marathon)).toBe(true);
	});

	it('correctly detects a new PR for the half marathon distance', () => {
		const hmRun = run(21.0975, 270); // exactly half marathon, fast
		expect(isNewPr(hmRun, 280, PR_DISTANCES_METRES.halfMarathon)).toBe(true);
	});
});
