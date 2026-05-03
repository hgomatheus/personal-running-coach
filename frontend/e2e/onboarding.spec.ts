/**
 * Playwright E2E tests for the onboarding flow.
 *
 * All backend API calls are intercepted with page.route() so no real server
 * is required. The tests cover:
 *   1. Profile 1 full onboarding flow → redirect to dashboard
 *   2. Profile 2 full onboarding flow → redirect to dashboard
 *   3. Required field validation (step 1, 2, 3)
 *   4. Step navigation (Next / Back buttons)
 *   5. Bulk import optional logic (fitness fields become optional after upload)
 */

import { test, expect, type Page } from '@playwright/test';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Future date string (YYYY-MM-DD) used as a valid race date. */
function futureDateString(daysAhead = 90): string {
	const d = new Date();
	d.setDate(d.getDate() + daysAhead);
	return d.toISOString().split('T')[0];
}

/** Past date string (YYYY-MM-DD) used as a valid date of birth. */
function pastDateString(yearsAgo = 30): string {
	const d = new Date();
	d.setFullYear(d.getFullYear() - yearsAgo);
	return d.toISOString().split('T')[0];
}

/**
 * Register all API route mocks needed for the onboarding flow.
 * Accepts a profileId so the same helper works for both profiles.
 */
async function mockOnboardingApis(page: Page, profileId: 1 | 2 = 1) {
	// PUT /api/v1/profiles/:id  — profile update
	await page.route(`**/api/v1/profiles/${profileId}`, (route) => {
		if (route.request().method() === 'PUT') {
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					id: profileId,
					display_name: `Profile ${profileId}`,
					date_of_birth: pastDateString(),
					biological_sex: 'male',
					current_weekly_km: 30,
					longest_recent_run_km: 15,
					injury_notes: null,
					created_at: null,
					updated_at: null,
				}),
			});
		} else {
			route.continue();
		}
	});

	// POST /api/v1/profiles/:id/race-goals  — create race goal
	await page.route(`**/api/v1/profiles/${profileId}/race-goals`, (route) => {
		if (route.request().method() === 'POST') {
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					id: 1,
					profile_id: profileId,
					distance_metres: 10000,
					target_date: futureDateString(),
					label: null,
					is_active: true,
					created_at: null,
				}),
			});
		} else {
			route.continue();
		}
	});

	// POST /api/v1/profiles/:id/plans  — generate training plan
	await page.route(`**/api/v1/profiles/${profileId}/plans`, (route) => {
		if (route.request().method() === 'POST') {
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					id: 1,
					profile_id: profileId,
					race_goal_id: 1,
					start_date: new Date().toISOString().split('T')[0],
					end_date: futureDateString(),
					status: 'active',
					gemini_prompt_hash: null,
					created_at: null,
					updated_at: null,
				}),
			});
		} else {
			route.continue();
		}
	});

	// GET /api/v1/profiles  — list profiles (used by layout)
	await page.route('**/api/v1/profiles', (route) => {
		if (route.request().method() === 'GET') {
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify([
					{ id: 1, display_name: 'Profile 1', date_of_birth: null, biological_sex: null, current_weekly_km: null, longest_recent_run_km: null, injury_notes: null, created_at: null, updated_at: null },
					{ id: 2, display_name: 'Profile 2', date_of_birth: null, biological_sex: null, current_weekly_km: null, longest_recent_run_km: null, injury_notes: null, created_at: null, updated_at: null },
				]),
			});
		} else {
			route.continue();
		}
	});

	// GET /api/v1/profiles/:id/plans  — used by dashboard after redirect
	await page.route(`**/api/v1/profiles/${profileId}/plans`, (route) => {
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

	// GET /api/v1/profiles/:id/taper  — used by dashboard
	await page.route(`**/api/v1/profiles/${profileId}/taper`, (route) => {
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({
				taper_active: false,
				days_until_race: null,
				taper_week: null,
				volume_reduction_pct: null,
				guidance: null,
			}),
		});
	});

	// GET /api/v1/settings  — used by layout/dashboard
	await page.route('**/api/v1/settings', (route) => {
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({
				id: 1,
				strava_sync_interval_minutes: 15,
				backup_enabled: true,
				backup_retention_days: 30,
			}),
		});
	});
}

/**
 * Set the active profile in localStorage before navigating.
 * This simulates the user having selected a profile.
 */
async function setActiveProfile(page: Page, profileId: 1 | 2) {
	await page.addInitScript((id) => {
		localStorage.setItem('activeProfileId', String(id));
	}, profileId);
}

/**
 * Fill in Step 1 fields with valid data.
 */
async function fillStep1(page: Page, profileName = 'Test Runner') {
	await page.fill('#profile-name', profileName);
	await page.fill('#dob', pastDateString(28));
	await page.selectOption('#bio-sex', 'female');
}

/**
 * Fill in Step 2 fields with valid data.
 */
async function fillStep2(page: Page) {
	// Select 10 km preset (value = 10000)
	await page.selectOption('#race-distance', '10000');
	await page.fill('#race-date', futureDateString(120));
}

/**
 * Fill in Step 3 manual fitness fields.
 */
async function fillStep3Manual(page: Page) {
	await page.fill('#weekly-km', '35');
	await page.fill('#longest-run', '18');
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe('Onboarding flow', () => {

	// -------------------------------------------------------------------------
	// 1. Profile 1 — full onboarding flow
	// -------------------------------------------------------------------------

	test('Profile 1: completes full onboarding and redirects to dashboard', async ({ page }) => {
		await setActiveProfile(page, 1);
		await mockOnboardingApis(page, 1);

		await page.goto('/onboarding');

		// --- Step 1 ---
		await expect(page.getByRole('heading', { name: 'Profile Setup' })).toBeVisible();
		await expect(page.getByText('Step 1 of 3')).toBeVisible();

		await fillStep1(page, 'Alice');
		await page.click('button:has-text("Next")');

		// --- Step 2 ---
		await expect(page.getByRole('heading', { name: 'Race Goal' })).toBeVisible();
		await expect(page.getByText('Step 2 of 3')).toBeVisible();

		await fillStep2(page);
		await page.click('button:has-text("Next")');

		// --- Step 3 ---
		await expect(page.getByRole('heading', { name: 'Fitness Baseline' })).toBeVisible();
		await expect(page.getByText('Step 3 of 3')).toBeVisible();

		await fillStep3Manual(page);
		await page.click('button:has-text("Create Plan")');

		// --- Loading screen ---
		await expect(page.getByText('Creating your training plan')).toBeVisible();

		// --- Redirect to dashboard ---
		await expect(page).toHaveURL('/');
	});

	// -------------------------------------------------------------------------
	// 2. Profile 2 — full onboarding flow
	// -------------------------------------------------------------------------

	test('Profile 2: completes full onboarding and redirects to dashboard', async ({ page }) => {
		await setActiveProfile(page, 2);
		await mockOnboardingApis(page, 2);

		await page.goto('/onboarding');

		// --- Step 1 ---
		await expect(page.getByRole('heading', { name: 'Profile Setup' })).toBeVisible();

		await fillStep1(page, 'Bob');
		await page.click('button:has-text("Next")');

		// --- Step 2 ---
		await expect(page.getByRole('heading', { name: 'Race Goal' })).toBeVisible();

		// Use a custom distance
		await page.selectOption('#race-distance', 'custom');
		await page.fill('#race-distance-custom', '21.1');
		await page.fill('#race-date', futureDateString(180));
		await page.fill('#race-label', 'City Half Marathon 2026');
		await page.click('button:has-text("Next")');

		// --- Step 3 ---
		await expect(page.getByRole('heading', { name: 'Fitness Baseline' })).toBeVisible();

		await fillStep3Manual(page);
		await page.click('button:has-text("Create Plan")');

		// --- Loading screen ---
		await expect(page.getByText('Creating your training plan')).toBeVisible();

		// --- Redirect to dashboard ---
		await expect(page).toHaveURL('/');
	});

	// -------------------------------------------------------------------------
	// 3. Required field validation
	// -------------------------------------------------------------------------

	test.describe('Required field validation', () => {

		test('Step 1: shows errors when required fields are empty', async ({ page }) => {
			await setActiveProfile(page, 1);
			await page.goto('/onboarding');

			// Click Next without filling anything
			await page.click('button:has-text("Next")');

			// All three required fields should show errors
			await expect(page.locator('#profile-name-error')).toBeVisible();
			await expect(page.locator('#profile-name-error')).toContainText('required');

			await expect(page.locator('#dob-error')).toBeVisible();
			await expect(page.locator('#dob-error')).toContainText('required');

			await expect(page.locator('#bio-sex-error')).toBeVisible();
			await expect(page.locator('#bio-sex-error')).toContainText('required');

			// Should still be on step 1
			await expect(page.getByText('Step 1 of 3')).toBeVisible();
		});

		test('Step 1: shows error for missing profile name only', async ({ page }) => {
			await setActiveProfile(page, 1);
			await page.goto('/onboarding');

			// Fill DOB and sex but leave name empty
			await page.fill('#dob', pastDateString(25));
			await page.selectOption('#bio-sex', 'male');
			await page.click('button:has-text("Next")');

			await expect(page.locator('#profile-name-error')).toBeVisible();
			// DOB and sex errors should NOT appear
			await expect(page.locator('#dob-error')).not.toBeVisible();
			await expect(page.locator('#bio-sex-error')).not.toBeVisible();

			// Still on step 1
			await expect(page.getByText('Step 1 of 3')).toBeVisible();
		});

		test('Step 2: shows error when race date is missing', async ({ page }) => {
			await setActiveProfile(page, 1);
			await page.goto('/onboarding');

			// Complete step 1
			await fillStep1(page);
			await page.click('button:has-text("Next")');

			// On step 2 — click Next without filling race date
			await page.click('button:has-text("Next")');

			await expect(page.locator('#race-date-error')).toBeVisible();
			await expect(page.locator('#race-date-error')).toContainText('required');

			// Still on step 2
			await expect(page.getByText('Step 2 of 3')).toBeVisible();
		});

		test('Step 2: shows error when custom distance is invalid', async ({ page }) => {
			await setActiveProfile(page, 1);
			await page.goto('/onboarding');

			// Complete step 1
			await fillStep1(page);
			await page.click('button:has-text("Next")');

			// Select custom distance but leave it empty
			await page.selectOption('#race-distance', 'custom');
			await page.fill('#race-date', futureDateString(90));
			await page.click('button:has-text("Next")');

			await expect(page.locator('#race-distance-error')).toBeVisible();
			await expect(page.locator('#race-distance-error')).toContainText('valid race distance');

			// Still on step 2
			await expect(page.getByText('Step 2 of 3')).toBeVisible();
		});

		test('Step 3: shows errors when fitness fields are empty (no bulk import)', async ({ page }) => {
			await setActiveProfile(page, 1);
			await page.goto('/onboarding');

			// Complete steps 1 and 2
			await fillStep1(page);
			await page.click('button:has-text("Next")');
			await fillStep2(page);
			await page.click('button:has-text("Next")');

			// On step 3 — click Create Plan without filling fitness fields
			await page.click('button:has-text("Create Plan")');

			await expect(page.locator('#weekly-km-error')).toBeVisible();
			await expect(page.locator('#weekly-km-error')).toContainText('required');

			await expect(page.locator('#longest-run-error')).toBeVisible();
			await expect(page.locator('#longest-run-error')).toContainText('required');

			// Still on step 3
			await expect(page.getByText('Step 3 of 3')).toBeVisible();
		});

	});

	// -------------------------------------------------------------------------
	// 4. Step navigation (Next / Back)
	// -------------------------------------------------------------------------

	test.describe('Step navigation', () => {

		test('Back button returns to previous step', async ({ page }) => {
			await setActiveProfile(page, 1);
			await page.goto('/onboarding');

			// Step 1 → Step 2
			await fillStep1(page);
			await page.click('button:has-text("Next")');
			await expect(page.getByText('Step 2 of 3')).toBeVisible();

			// Back to Step 1
			await page.click('button:has-text("Back")');
			await expect(page.getByText('Step 1 of 3')).toBeVisible();
			await expect(page.getByRole('heading', { name: 'Profile Setup' })).toBeVisible();
		});

		test('Back button is not shown on step 1', async ({ page }) => {
			await setActiveProfile(page, 1);
			await page.goto('/onboarding');

			await expect(page.getByRole('button', { name: /back/i })).not.toBeVisible();
		});

		test('Next button advances through all three steps', async ({ page }) => {
			await setActiveProfile(page, 1);
			await page.goto('/onboarding');

			// Step 1
			await expect(page.getByText('Step 1 of 3')).toBeVisible();
			await fillStep1(page);
			await page.click('button:has-text("Next")');

			// Step 2
			await expect(page.getByText('Step 2 of 3')).toBeVisible();
			await fillStep2(page);
			await page.click('button:has-text("Next")');

			// Step 3
			await expect(page.getByText('Step 3 of 3')).toBeVisible();
			await expect(page.getByRole('heading', { name: 'Fitness Baseline' })).toBeVisible();
		});

		test('Step 3 shows "Create Plan" button instead of "Next"', async ({ page }) => {
			await setActiveProfile(page, 1);
			await page.goto('/onboarding');

			await fillStep1(page);
			await page.click('button:has-text("Next")');
			await fillStep2(page);
			await page.click('button:has-text("Next")');

			// On step 3 the forward button should say "Create Plan"
			await expect(page.getByRole('button', { name: /create plan/i })).toBeVisible();
			await expect(page.getByRole('button', { name: /^next/i })).not.toBeVisible();
		});

		test('Step indicator highlights the current step', async ({ page }) => {
			await setActiveProfile(page, 1);
			await page.goto('/onboarding');

			// Step 1 indicator should have aria-current="step"
			const step1Indicator = page.locator('[aria-current="step"]');
			await expect(step1Indicator).toContainText('1');

			await fillStep1(page);
			await page.click('button:has-text("Next")');

			// Step 2 indicator should now have aria-current="step"
			await expect(step1Indicator).toContainText('2');
		});

		test('Back from step 3 returns to step 2', async ({ page }) => {
			await setActiveProfile(page, 1);
			await page.goto('/onboarding');

			await fillStep1(page);
			await page.click('button:has-text("Next")');
			await fillStep2(page);
			await page.click('button:has-text("Next")');

			// Now on step 3
			await expect(page.getByText('Step 3 of 3')).toBeVisible();

			// Go back
			await page.click('button:has-text("Back")');
			await expect(page.getByText('Step 2 of 3')).toBeVisible();
			await expect(page.getByRole('heading', { name: 'Race Goal' })).toBeVisible();
		});

	});

	// -------------------------------------------------------------------------
	// 5. Bulk import optional logic
	// -------------------------------------------------------------------------

	test.describe('Bulk import optional logic', () => {

		test('Fitness fields are marked required when no bulk import provided', async ({ page }) => {
			await setActiveProfile(page, 1);
			await page.goto('/onboarding');

			await fillStep1(page);
			await page.click('button:has-text("Next")');
			await fillStep2(page);
			await page.click('button:has-text("Next")');

			// Without bulk import, the required asterisks should be visible
			// and aria-required should be true
			const weeklyKmInput = page.locator('#weekly-km');
			const longestRunInput = page.locator('#longest-run');

			await expect(weeklyKmInput).toHaveAttribute('aria-required', 'true');
			await expect(longestRunInput).toHaveAttribute('aria-required', 'true');
		});

		test('Fitness fields become optional after successful bulk import', async ({ page }) => {
			await setActiveProfile(page, 1);

			// Mock the bulk import endpoint
			await page.route('**/api/v1/profiles/1/strava/bulk-import', (route) => {
				route.fulfill({
					status: 200,
					contentType: 'application/json',
					body: JSON.stringify({
						imported: 42,
						skipped_duplicates: 3,
						parse_errors: 0,
						vdot: 45.2,
						pace_zones_updated: true,
					}),
				});
			});

			await mockOnboardingApis(page, 1);
			await page.goto('/onboarding');

			await fillStep1(page);
			await page.click('button:has-text("Next")');
			await fillStep2(page);
			await page.click('button:has-text("Next")');

			// Simulate a successful bulk import by directly triggering the upload
			// We create a minimal ZIP file buffer and attach it via the file input
			const zipContent = Buffer.from('PK\x05\x06' + '\x00'.repeat(18)); // minimal ZIP end-of-central-directory
			await page.locator('#strava-zip').setInputFiles({
				name: 'strava-export.zip',
				mimeType: 'application/zip',
				buffer: zipContent,
			});

			// Click the Upload button that appears after file selection
			await page.click('button:has-text("Upload")');

			// Wait for the import success message
			await expect(page.locator('[role="status"]')).toContainText('Import successful');
			await expect(page.locator('[role="status"]')).toContainText('42');

			// After successful import, fitness fields should be optional
			const weeklyKmInput = page.locator('#weekly-km');
			const longestRunInput = page.locator('#longest-run');

			await expect(weeklyKmInput).toHaveAttribute('aria-required', 'false');
			await expect(longestRunInput).toHaveAttribute('aria-required', 'false');

			// The "(optional)" label text should now be visible
			await expect(page.locator('label[for="weekly-km"]')).toContainText('optional');
			await expect(page.locator('label[for="longest-run"]')).toContainText('optional');
		});

		test('Can proceed without fitness fields after successful bulk import', async ({ page }) => {
			await setActiveProfile(page, 1);

			// Mock the bulk import endpoint
			await page.route('**/api/v1/profiles/1/strava/bulk-import', (route) => {
				route.fulfill({
					status: 200,
					contentType: 'application/json',
					body: JSON.stringify({
						imported: 15,
						skipped_duplicates: 0,
						parse_errors: 0,
						vdot: 38.5,
						pace_zones_updated: true,
					}),
				});
			});

			await mockOnboardingApis(page, 1);
			await page.goto('/onboarding');

			await fillStep1(page);
			await page.click('button:has-text("Next")');
			await fillStep2(page);
			await page.click('button:has-text("Next")');

			// Upload a bulk import file
			const zipContent = Buffer.from('PK\x05\x06' + '\x00'.repeat(18));
			await page.locator('#strava-zip').setInputFiles({
				name: 'strava-export.zip',
				mimeType: 'application/zip',
				buffer: zipContent,
			});
			await page.click('button:has-text("Upload")');
			await expect(page.locator('[role="status"]')).toContainText('Import successful');

			// Click Create Plan WITHOUT filling in fitness fields
			await page.click('button:has-text("Create Plan")');

			// Should NOT show validation errors for fitness fields
			await expect(page.locator('#weekly-km-error')).not.toBeVisible();
			await expect(page.locator('#longest-run-error')).not.toBeVisible();

			// Should proceed to loading screen
			await expect(page.getByText('Creating your training plan')).toBeVisible();

			// Should redirect to dashboard
			await expect(page).toHaveURL('/');
		});

		test('Shows error when non-ZIP file is selected', async ({ page }) => {
			await setActiveProfile(page, 1);
			await page.goto('/onboarding');

			await fillStep1(page);
			await page.click('button:has-text("Next")');
			await fillStep2(page);
			await page.click('button:has-text("Next")');

			// Try to upload a non-ZIP file
			await page.locator('#strava-zip').setInputFiles({
				name: 'activities.csv',
				mimeType: 'text/csv',
				buffer: Buffer.from('date,distance\n2024-01-01,5000'),
			});

			// Error message should appear
			await expect(page.locator('[role="alert"]')).toContainText('.zip');
		});

	});

	// -------------------------------------------------------------------------
	// 6. Step indicator progress
	// -------------------------------------------------------------------------

	test('Step indicator shows completed steps with checkmark', async ({ page }) => {
		await setActiveProfile(page, 1);
		await page.goto('/onboarding');

		// Complete step 1
		await fillStep1(page);
		await page.click('button:has-text("Next")');

		// Step 1 should now show a checkmark (SVG path for checkmark)
		// The completed step div has bg-green-500 class
		const completedStep = page.locator('[aria-label="Onboarding progress"] div.bg-green-500').first();
		await expect(completedStep).toBeVisible();

		// Complete step 2
		await fillStep2(page);
		await page.click('button:has-text("Next")');

		// Two completed steps should now be visible
		const completedSteps = page.locator('[aria-label="Onboarding progress"] div.bg-green-500');
		await expect(completedSteps).toHaveCount(2);
	});

	// -------------------------------------------------------------------------
	// 7. Plan generation error handling
	// -------------------------------------------------------------------------

	test('Shows error and retry button when plan generation fails', async ({ page }) => {
		await setActiveProfile(page, 1);

		// Mock profile update to succeed
		await page.route('**/api/v1/profiles/1', (route) => {
			if (route.request().method() === 'PUT') {
				route.fulfill({
					status: 200,
					contentType: 'application/json',
					body: JSON.stringify({ id: 1, display_name: 'Test', date_of_birth: null, biological_sex: null, current_weekly_km: null, longest_recent_run_km: null, injury_notes: null, created_at: null, updated_at: null }),
				});
			} else {
				route.continue();
			}
		});

		// Mock race goal creation to succeed
		await page.route('**/api/v1/profiles/1/race-goals', (route) => {
			if (route.request().method() === 'POST') {
				route.fulfill({
					status: 200,
					contentType: 'application/json',
					body: JSON.stringify({ id: 1, profile_id: 1, distance_metres: 10000, target_date: futureDateString(), label: null, is_active: true, created_at: null }),
				});
			} else {
				route.continue();
			}
		});

		// Mock plan creation to FAIL
		await page.route('**/api/v1/profiles/1/plans', (route) => {
			if (route.request().method() === 'POST') {
				route.fulfill({
					status: 500,
					contentType: 'application/json',
					body: JSON.stringify({ detail: 'Gemini API unavailable' }),
				});
			} else {
				route.continue();
			}
		});

		await page.goto('/onboarding');

		await fillStep1(page);
		await page.click('button:has-text("Next")');
		await fillStep2(page);
		await page.click('button:has-text("Next")');
		await fillStep3Manual(page);
		await page.click('button:has-text("Create Plan")');

		// Should show error state
		await expect(page.getByRole('heading', { name: 'Plan generation failed' })).toBeVisible();
		// The plan error paragraph has role="alert"
		await expect(page.locator('p[role="alert"]')).toContainText('Gemini API unavailable');

		// Retry button should be visible
		await expect(page.getByRole('button', { name: /retry/i })).toBeVisible();
	});

});
