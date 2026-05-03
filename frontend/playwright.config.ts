import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright E2E test configuration.
 *
 * Tests use page.route() to mock all backend API calls, so no real server
 * is required. The webServer block starts the SvelteKit dev server locally
 * when running tests.
 *
 * @see https://playwright.dev/docs/test-configuration
 */
export default defineConfig({
	testDir: './e2e',
	/* Maximum time one test can run */
	timeout: 30_000,
	/* Fail the build on CI if you accidentally left test.only in the source code */
	forbidOnly: !!process.env.CI,
	/* Retry on CI only */
	retries: process.env.CI ? 2 : 0,
	/* Reporter to use */
	reporter: 'html',

	use: {
		/* Base URL to use in actions like `await page.goto('/')` */
		baseURL: 'http://localhost:5173',
		/* Collect trace when retrying the failed test */
		trace: 'on-first-retry',
	},

	projects: [
		{
			name: 'chromium',
			use: { ...devices['Desktop Chrome'] },
		},
	],

	/* Start the SvelteKit dev server before running tests */
	webServer: {
		command: 'npm run dev',
		url: 'http://localhost:5173',
		reuseExistingServer: !process.env.CI,
		timeout: 120_000,
	},
});
