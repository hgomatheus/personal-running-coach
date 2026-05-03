/**
 * Playwright E2E tests for profile switching on the dashboard.
 *
 * All backend API calls are intercepted with page.route() so no real server
 * is required. The tests cover:
 *   1. Dashboard shows Profile 1's data when Profile 1 is active
 *   2. Dashboard shows Profile 2's data when Profile 2 is active
 *   3. Clicking Profile 2 in the switcher switches to Profile 2 and shows Profile 2's data
 *   4. Clicking Profile 1 in the switcher switches back to Profile 1 and shows Profile 1's data
 *   5. Profile switcher highlights the currently active profile
 *   6. After switching profiles, the active profile is persisted in localStorage
 *   7. Data from Profile 1 is never shown when Profile 2 is active (isolation)
 *
 * Validates: Requirement 16 (Multi-Profile Support)
 */

import { test, expect, type Page } from '@playwright/test';

// ---------------------------------------------------------------------------
// Fixture data — each profile returns distinct data so tests can verify
// the correct profile's data is displayed.
// ---------------------------------------------------------------------------

const PROFILE_1 = {
	id: 1,
	display_name: 'Alice Runner',
	date_of_birth: '1990-03-15',
	biological_sex: 'female',
	current_weekly_km: 40,
	longest_recent_run_km: 20,
	injury_notes: null,
	created_at: null,
	updated_at: null,
};

const PROFILE_2 = {
	id: 2,
	display_name: 'Bob Jogger',
	date_of_birth: '1985-07-22',
	biological_sex: 'male',
	current_weekly_km: 55,
	longest_recent_run_km: 28,
	injury_notes: null,
	created_at: null,
	updated_at: null,
};

/** A future date string (YYYY-MM-DD) used for race goals. */
function futureDateString(daysAhead = 90): string {
	const d = new Date();
	d.setDate(d.getDate() + daysAhead);
	return d.toISOString().split('T')[0];
}

/** A past date string (YYYY-MM-DD) used for run dates. */
function pastDateString(daysAgo = 3): string {
	const d = new Date();
	d.setDate(d.getDate() - daysAgo);
	return d.toISOString().split('T')[0];
}

// ---------------------------------------------------------------------------
// Mock data factories
// ---------------------------------------------------------------------------

function makeRaceGoal(profileId: 1 | 2) {
	return {
		id: profileId,
		profile_id: profileId,
		distance_metres: profileId === 1 ? 10000 : 21097,
		target_date: futureDateString(profileId === 1 ? 60 : 120),
		label: profileId === 1 ? 'Alice 10k Race' : 'Bob Half Marathon',
		is_active: true,
		created_at: null,
	};
}

function makePlan(profileId: 1 | 2) {
	return {
		id: profileId,
		profile_id: profileId,
		race_goal_id: profileId,
		start_date: new Date().toISOString().split('T')[0],
		end_date: futureDateString(profileId === 1 ? 60 : 120),
		status: 'active',
		gemini_prompt_hash: null,
		created_at: null,
		updated_at: null,
	};
}

function makeNextWorkout(profileId: 1 | 2) {
	const tomorrow = new Date();
	tomorrow.setDate(tomorrow.getDate() + 1);
	const scheduledDate = tomorrow.toISOString().split('T')[0];

	return {
		id: profileId * 100,
		profile_id: profileId,
		block_id: profileId,
		plan_id: profileId,
		scheduled_date: scheduledDate,
		workout_type: profileId === 1 ? 'easy' : 'tempo',
		target_distance_metres: profileId === 1 ? 8000 : 12000,
		estimated_duration_seconds: profileId === 1 ? 2880 : 3600,
		target_pace_zone: profileId === 1 ? 'easy' : 'threshold',
		target_hr_zone: null,
		steps: [],
		coaching_note: profileId === 1 ? 'Alice easy run note' : 'Bob tempo run note',
		status: 'scheduled',
		rpe_score: null,
		matched_run_id: null,
		created_at: null,
		updated_at: null,
	};
}

function makePlanDetail(profileId: 1 | 2) {
	const workout = makeNextWorkout(profileId);
	const tomorrow = new Date();
	tomorrow.setDate(tomorrow.getDate() + 1);

	return {
		...makePlan(profileId),
		blocks: [
			{
				id: profileId,
				profile_id: profileId,
				plan_id: profileId,
				name: profileId === 1 ? 'Alice Base Building' : 'Bob Speed Work',
				start_date: new Date().toISOString().split('T')[0],
				end_date: futureDateString(profileId === 1 ? 60 : 120),
				sequence: 1,
				workouts: [
					{
						id: workout.id,
						scheduled_date: workout.scheduled_date,
						workout_type: workout.workout_type,
						target_distance_metres: workout.target_distance_metres,
						target_pace_zone: workout.target_pace_zone,
						status: workout.status,
						coaching_note: workout.coaching_note,
					},
				],
			},
		],
	};
}

function makeRecentRuns(profileId: 1 | 2) {
	return [
		{
			id: profileId * 1000 + 1,
			profile_id: profileId,
			source: 'manual',
			strava_activity_id: null,
			date: pastDateString(1),
			started_at: null,
			distance_metres: profileId === 1 ? 8000 : 12000,
			duration_seconds: profileId === 1 ? 2880 : 3600,
			avg_pace_sec_per_km: profileId === 1 ? 360 : 300,
			avg_heart_rate: null,
			elevation_gain_metres: null,
			run_type: profileId === 1 ? 'easy' : 'tempo',
			notes: null,
			created_at: null,
			updated_at: null,
		},
	];
}

function makeWeeklyStats(profileId: 1 | 2) {
	return [
		{
			week_start: pastDateString(7),
			total_km: profileId === 1 ? 38.5 : 52.0,
			run_count: profileId === 1 ? 4 : 5,
		},
	];
}

function makeTaperStatus() {
	return {
		taper_active: false,
		days_until_race: null,
		taper_week: null,
		volume_reduction_pct: null,
		guidance: null,
	};
}

function makeSettings() {
	return {
		id: 1,
		strava_sync_interval_minutes: 15,
		backup_enabled: true,
		backup_retention_days: 30,
	};
}

// ---------------------------------------------------------------------------
// Route mock helpers
// ---------------------------------------------------------------------------

/**
 * Register all API route mocks for a given active profile.
 * The profiles list always returns both profiles; all profile-scoped
 * endpoints return data for the specified active profile.
 */
async function mockDashboardApis(page: Page, activeProfileId: 1 | 2) {
	// GET /api/v1/profiles — list both profiles (used by layout switcher)
	await page.route('**/api/v1/profiles', (route) => {
		if (route.request().method() === 'GET' && !route.request().url().includes('/profiles/')) {
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify([PROFILE_1, PROFILE_2]),
			});
		} else {
			route.continue();
		}
	});

	// GET /api/v1/settings
	await page.route('**/api/v1/settings', (route) => {
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify(makeSettings()),
		});
	});

	// Mock both profiles' data so switching works without re-navigating
	for (const profileId of [1, 2] as const) {
		// GET /api/v1/profiles/:id/plans
		await page.route(`**/api/v1/profiles/${profileId}/plans`, (route) => {
			if (route.request().method() === 'GET' && !route.request().url().match(/\/plans\/\d+/)) {
				route.fulfill({
					status: 200,
					contentType: 'application/json',
					body: JSON.stringify([makePlan(profileId)]),
				});
			} else {
				route.continue();
			}
		});

		// GET /api/v1/profiles/:id/plans/:planId
		await page.route(`**/api/v1/profiles/${profileId}/plans/${profileId}`, (route) => {
			if (route.request().method() === 'GET') {
				route.fulfill({
					status: 200,
					contentType: 'application/json',
					body: JSON.stringify(makePlanDetail(profileId)),
				});
			} else {
				route.continue();
			}
		});

		// GET /api/v1/profiles/:id/race-goals
		await page.route(`**/api/v1/profiles/${profileId}/race-goals`, (route) => {
			if (route.request().method() === 'GET') {
				route.fulfill({
					status: 200,
					contentType: 'application/json',
					body: JSON.stringify([makeRaceGoal(profileId)]),
				});
			} else {
				route.continue();
			}
		});

		// GET /api/v1/profiles/:id/taper
		await page.route(`**/api/v1/profiles/${profileId}/taper`, (route) => {
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(makeTaperStatus()),
			});
		});

		// GET /api/v1/profiles/:id/stats/weekly
		await page.route(`**/api/v1/profiles/${profileId}/stats/weekly`, (route) => {
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(makeWeeklyStats(profileId)),
			});
		});

		// GET /api/v1/profiles/:id/runs
		await page.route(`**/api/v1/profiles/${profileId}/runs`, (route) => {
			if (route.request().method() === 'GET') {
				route.fulfill({
					status: 200,
					contentType: 'application/json',
					body: JSON.stringify(makeRecentRuns(profileId)),
				});
			} else {
				route.continue();
			}
		});

		// GET /api/v1/profiles/:id/workouts/:workoutId/weather — optional, return 404
		await page.route(`**/api/v1/profiles/${profileId}/workouts/**/weather`, (route) => {
			route.fulfill({ status: 404, body: '' });
		});
	}
}

/**
 * Set the active profile in localStorage before navigating.
 */
async function setActiveProfile(page: Page, profileId: 1 | 2) {
	await page.addInitScript((id) => {
		localStorage.setItem('activeProfileId', String(id));
	}, profileId);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe('Profile switching on dashboard', () => {

	// -------------------------------------------------------------------------
	// 1. Dashboard shows Profile 1's data when Profile 1 is active
	// -------------------------------------------------------------------------

	test('shows Profile 1 data when Profile 1 is active', async ({ page }) => {
		await setActiveProfile(page, 1);
		await mockDashboardApis(page, 1);

		await page.goto('/');

		// Wait for loading to finish
		await expect(page.getByRole('status')).not.toBeVisible({ timeout: 10_000 });

		// Profile 1's next workout is an Easy Run
		await expect(page.getByText('Easy Run')).toBeVisible();

		// Profile 1's race goal label
		await expect(page.getByText('Alice 10k Race')).toBeVisible();

		// Profile 1's training block name
		await expect(page.getByText('Alice Base Building')).toBeVisible();
	});

	// -------------------------------------------------------------------------
	// 2. Dashboard shows Profile 2's data when Profile 2 is active
	// -------------------------------------------------------------------------

	test('shows Profile 2 data when Profile 2 is active', async ({ page }) => {
		await setActiveProfile(page, 2);
		await mockDashboardApis(page, 2);

		await page.goto('/');

		// Wait for loading to finish
		await expect(page.getByRole('status')).not.toBeVisible({ timeout: 10_000 });

		// Profile 2's next workout is a Tempo run
		await expect(page.getByText('Tempo')).toBeVisible();

		// Profile 2's race goal label
		await expect(page.getByText('Bob Half Marathon')).toBeVisible();

		// Profile 2's training block name
		await expect(page.getByText('Bob Speed Work')).toBeVisible();
	});

	// -------------------------------------------------------------------------
	// 3. Clicking Profile 2 in the switcher switches to Profile 2
	// -------------------------------------------------------------------------

	test('clicking Profile 2 in the switcher switches to Profile 2 and shows Profile 2 data', async ({ page }) => {
		// Start with Profile 1 active
		await setActiveProfile(page, 1);
		await mockDashboardApis(page, 1);

		await page.goto('/');

		// Wait for Profile 1 data to load
		await expect(page.getByRole('status')).not.toBeVisible({ timeout: 10_000 });
		await expect(page.getByText('Easy Run')).toBeVisible();

		// Click Profile 2 in the profile switcher
		await page.click('button:has-text("Bob Jogger")');

		// Wait for Profile 2 data to load
		await expect(page.getByText('Tempo')).toBeVisible({ timeout: 10_000 });

		// Profile 2's race goal and block should now be visible
		await expect(page.getByText('Bob Half Marathon')).toBeVisible();
		await expect(page.getByText('Bob Speed Work')).toBeVisible();
	});

	// -------------------------------------------------------------------------
	// 4. Clicking Profile 1 in the switcher switches back to Profile 1
	// -------------------------------------------------------------------------

	test('clicking Profile 1 in the switcher switches back to Profile 1 and shows Profile 1 data', async ({ page }) => {
		// Start with Profile 2 active
		await setActiveProfile(page, 2);
		await mockDashboardApis(page, 2);

		await page.goto('/');

		// Wait for Profile 2 data to load
		await expect(page.getByRole('status')).not.toBeVisible({ timeout: 10_000 });
		await expect(page.getByText('Tempo')).toBeVisible();

		// Click Profile 1 in the profile switcher
		await page.click('button:has-text("Alice Runner")');

		// Wait for Profile 1 data to load
		await expect(page.getByText('Easy Run')).toBeVisible({ timeout: 10_000 });

		// Profile 1's race goal and block should now be visible
		await expect(page.getByText('Alice 10k Race')).toBeVisible();
		await expect(page.getByText('Alice Base Building')).toBeVisible();
	});

	// -------------------------------------------------------------------------
	// 5. Profile switcher highlights the currently active profile
	// -------------------------------------------------------------------------

	test('profile switcher highlights the currently active profile', async ({ page }) => {
		await setActiveProfile(page, 1);
		await mockDashboardApis(page, 1);

		await page.goto('/');

		// Profile 1 button should be pressed (aria-pressed="true") and show "Active"
		const profile1Button = page.locator('button', { hasText: 'Alice Runner' });
		await expect(profile1Button).toHaveAttribute('aria-pressed', 'true');
		await expect(profile1Button).toContainText('Active');

		// Profile 2 button should NOT be pressed
		const profile2Button = page.locator('button', { hasText: 'Bob Jogger' });
		await expect(profile2Button).toHaveAttribute('aria-pressed', 'false');
		await expect(profile2Button).not.toContainText('Active');

		// Switch to Profile 2
		await profile2Button.click();

		// Now Profile 2 should be highlighted and Profile 1 should not
		await expect(profile2Button).toHaveAttribute('aria-pressed', 'true');
		await expect(profile2Button).toContainText('Active');
		await expect(profile1Button).toHaveAttribute('aria-pressed', 'false');
		await expect(profile1Button).not.toContainText('Active');
	});

	// -------------------------------------------------------------------------
	// 6. After switching profiles, the active profile is persisted in localStorage
	// -------------------------------------------------------------------------

	test('persists the active profile in localStorage after switching', async ({ page }) => {
		await setActiveProfile(page, 1);
		await mockDashboardApis(page, 1);

		await page.goto('/');

		// Wait for initial load
		await expect(page.getByRole('status')).not.toBeVisible({ timeout: 10_000 });

		// Switch to Profile 2
		await page.click('button:has-text("Bob Jogger")');

		// Wait for Profile 2 data to appear
		await expect(page.getByText('Tempo')).toBeVisible({ timeout: 10_000 });

		// Verify localStorage was updated
		const storedId = await page.evaluate(() => localStorage.getItem('activeProfileId'));
		expect(storedId).toBe('2');

		// Switch back to Profile 1
		await page.click('button:has-text("Alice Runner")');
		await expect(page.getByText('Easy Run')).toBeVisible({ timeout: 10_000 });

		// Verify localStorage reflects Profile 1
		const storedIdAfter = await page.evaluate(() => localStorage.getItem('activeProfileId'));
		expect(storedIdAfter).toBe('1');
	});

	// -------------------------------------------------------------------------
	// 7. Data from Profile 1 is never shown when Profile 2 is active (isolation)
	// -------------------------------------------------------------------------

	test('Profile 1 data is never shown when Profile 2 is active', async ({ page }) => {
		await setActiveProfile(page, 2);
		await mockDashboardApis(page, 2);

		await page.goto('/');

		// Wait for Profile 2 data to load
		await expect(page.getByRole('status')).not.toBeVisible({ timeout: 10_000 });

		// Profile 2's data should be visible
		await expect(page.getByText('Tempo')).toBeVisible();
		await expect(page.getByText('Bob Half Marathon')).toBeVisible();
		await expect(page.getByText('Bob Speed Work')).toBeVisible();

		// Profile 1's unique data should NOT be visible
		await expect(page.getByText('Alice 10k Race')).not.toBeVisible();
		await expect(page.getByText('Alice Base Building')).not.toBeVisible();
		// "Easy Run" is Profile 1's workout type — should not appear
		await expect(page.getByText('Easy Run')).not.toBeVisible();
	});

	// -------------------------------------------------------------------------
	// 8. Profile switcher shows both profile names
	// -------------------------------------------------------------------------

	test('profile switcher shows both profile display names', async ({ page }) => {
		await setActiveProfile(page, 1);
		await mockDashboardApis(page, 1);

		await page.goto('/');

		// Both profile names should be visible in the switcher
		await expect(page.locator('button', { hasText: 'Alice Runner' })).toBeVisible();
		await expect(page.locator('button', { hasText: 'Bob Jogger' })).toBeVisible();
	});

	// -------------------------------------------------------------------------
	// 9. Active profile persists across page reload
	// -------------------------------------------------------------------------

	test('active profile selection persists across page reload', async ({ page }) => {
		await setActiveProfile(page, 2);
		await mockDashboardApis(page, 2);

		await page.goto('/');

		// Wait for Profile 2 data to load
		await expect(page.getByRole('status')).not.toBeVisible({ timeout: 10_000 });
		await expect(page.getByText('Tempo')).toBeVisible();

		// Reload the page — localStorage should restore Profile 2
		await page.reload();

		// Profile 2 data should still be shown after reload
		await expect(page.getByRole('status')).not.toBeVisible({ timeout: 10_000 });
		await expect(page.getByText('Tempo')).toBeVisible();

		// Profile 2 button should still be highlighted
		const profile2Button = page.locator('button', { hasText: 'Bob Jogger' });
		await expect(profile2Button).toHaveAttribute('aria-pressed', 'true');
	});

	// -------------------------------------------------------------------------
	// 10. Dashboard shows "no plan" prompt for a profile with no active plan
	// -------------------------------------------------------------------------

	test('shows no-plan prompt when the active profile has no training plan', async ({ page }) => {
		await setActiveProfile(page, 1);

		// Override: Profile 1 has no plans
		await page.route('**/api/v1/profiles', (route) => {
			if (route.request().method() === 'GET' && !route.request().url().includes('/profiles/')) {
				route.fulfill({
					status: 200,
					contentType: 'application/json',
					body: JSON.stringify([PROFILE_1, PROFILE_2]),
				});
			} else {
				route.continue();
			}
		});

		await page.route('**/api/v1/profiles/1/plans', (route) => {
			if (route.request().method() === 'GET') {
				route.fulfill({
					status: 200,
					contentType: 'application/json',
					body: JSON.stringify([]), // no plans
				});
			} else {
				route.continue();
			}
		});

		await page.route('**/api/v1/profiles/1/race-goals', (route) => {
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify([]),
			});
		});

		await page.route('**/api/v1/profiles/1/taper', (route) => {
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(makeTaperStatus()),
			});
		});

		await page.route('**/api/v1/profiles/1/stats/weekly', (route) => {
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify([]),
			});
		});

		await page.route('**/api/v1/profiles/1/runs', (route) => {
			if (route.request().method() === 'GET') {
				route.fulfill({
					status: 200,
					contentType: 'application/json',
					body: JSON.stringify([]),
				});
			} else {
				route.continue();
			}
		});

		await page.route('**/api/v1/settings', (route) => {
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(makeSettings()),
			});
		});

		await page.goto('/');

		// Wait for loading to finish
		await expect(page.getByRole('status')).not.toBeVisible({ timeout: 10_000 });

		// Should show the "no plan" prompt
		await expect(page.getByRole('heading', { name: 'No training plan yet' })).toBeVisible();
		await expect(page.getByRole('link', { name: /create your first plan/i })).toBeVisible();
	});

});
