<script lang="ts">
	import { onMount } from 'svelte';
	import { activeProfile } from '$lib/stores';
	import {
		profilesApi,
		settingsApi,
		stravaApi,
		exportApi,
		backupApi,
		type Profile,
		type ProfileUpdate,
		type ProfileSettings,
		type ProfileSettingsUpdate,
		type AppSettings,
		type AppSettingsUpdate,
		type ProfileWeatherSettings,
		type ProfileWeatherSettingsUpdate,
		type StravaStatus,
		type BackupRecord,
		type BulkImportResponse
	} from '$lib/api';

	// ---------------------------------------------------------------------------
	// Section feedback helpers
	// ---------------------------------------------------------------------------

	type FeedbackState = { type: 'success' | 'error'; message: string } | null;

	let profileFeedback: FeedbackState = null;
	let stravaFeedback: FeedbackState = null;
	let notifFeedback: FeedbackState = null;
	let weatherFeedback: FeedbackState = null;
	let dataFeedback: FeedbackState = null;

	function setFeedback(
		setter: (v: FeedbackState) => void,
		type: 'success' | 'error',
		message: string
	) {
		setter({ type, message });
		setTimeout(() => setter(null), 5000);
	}

	// ---------------------------------------------------------------------------
	// Loading state
	// ---------------------------------------------------------------------------

	let loading = true;
	let loadError: string | null = null;

	// ---------------------------------------------------------------------------
	// Section 1 — Profile
	// ---------------------------------------------------------------------------

	let profileName = '';
	let dateOfBirth = '';
	let biologicalSex: 'male' | 'female' | 'other' | '' = '';
	let injuryNotes = '';
	let profileSaving = false;

	async function loadProfile() {
		const p = await profilesApi.get($activeProfile);
		profileName = p.display_name ?? '';
		dateOfBirth = p.date_of_birth ?? '';
		biologicalSex = (p.biological_sex as 'male' | 'female' | 'other' | '') ?? '';
		injuryNotes = p.injury_notes ?? '';
	}

	async function saveProfile() {
		profileSaving = true;
		profileFeedback = null;
		try {
			const body: ProfileUpdate = {
				display_name: profileName.trim(),
				date_of_birth: dateOfBirth || null,
				biological_sex: (biologicalSex as 'male' | 'female' | 'other') || null,
				injury_notes: injuryNotes.trim() || null
			};
			await profilesApi.update($activeProfile, body);
			setFeedback((v) => (profileFeedback = v), 'success', 'Profile saved.');
		} catch (e) {
			setFeedback(
				(v) => (profileFeedback = v),
				'error',
				e instanceof Error ? e.message : 'Failed to save profile.'
			);
		} finally {
			profileSaving = false;
		}
	}

	// ---------------------------------------------------------------------------
	// Section 2 — Strava Integration
	// ---------------------------------------------------------------------------

	let stravaStatus: StravaStatus | null = null;
	let stravaLoading = false;
	let stravaDisconnecting = false;
	let showDisconnectConfirm = false;

	// Sync interval (shared app setting)
	let syncIntervalMinutes = 30;
	let syncIntervalSaving = false;

	// Bulk import
	let bulkImportFile: File | null = null;
	let bulkImportUploading = false;
	let bulkImportProgress = 0;
	let bulkImportResult: BulkImportResponse | null = null;
	let bulkImportError: string | null = null;

	async function loadStravaStatus() {
		stravaLoading = true;
		try {
			stravaStatus = await stravaApi.status($activeProfile);
		} catch {
			stravaStatus = null;
		} finally {
			stravaLoading = false;
		}
	}

	async function loadAppSettings() {
		try {
			const s = await settingsApi.getApp();
			syncIntervalMinutes = s.strava_sync_interval_minutes ?? 30;
		} catch {
			// keep default
		}
	}

	function connectStrava() {
		window.location.href = stravaApi.authUrl($activeProfile);
	}

	async function disconnectStrava() {
		stravaDisconnecting = true;
		stravaFeedback = null;
		try {
			await stravaApi.disconnect($activeProfile);
			stravaStatus = { ...stravaStatus!, connected: false, last_sync_at: null, athlete_id: null, sync_error: null };
			showDisconnectConfirm = false;
			setFeedback((v) => (stravaFeedback = v), 'success', 'Strava disconnected.');
		} catch (e) {
			setFeedback(
				(v) => (stravaFeedback = v),
				'error',
				e instanceof Error ? e.message : 'Failed to disconnect Strava.'
			);
		} finally {
			stravaDisconnecting = false;
		}
	}

	async function saveSyncInterval() {
		syncIntervalSaving = true;
		stravaFeedback = null;
		try {
			const body: AppSettingsUpdate = { strava_sync_interval_minutes: syncIntervalMinutes };
			await settingsApi.updateApp(body);
			setFeedback((v) => (stravaFeedback = v), 'success', 'Sync interval saved.');
		} catch (e) {
			setFeedback(
				(v) => (stravaFeedback = v),
				'error',
				e instanceof Error ? e.message : 'Failed to save sync interval.'
			);
		} finally {
			syncIntervalSaving = false;
		}
	}

	function handleBulkImportFileChange(event: Event) {
		const input = event.target as HTMLInputElement;
		const file = input.files?.[0] ?? null;
		if (file && !file.name.toLowerCase().endsWith('.zip')) {
			bulkImportError = 'Please select a .zip file (Strava data export).';
			bulkImportFile = null;
			input.value = '';
			return;
		}
		bulkImportFile = file;
		bulkImportError = null;
		bulkImportResult = null;
	}

	async function uploadBulkImport() {
		if (!bulkImportFile) return;
		bulkImportUploading = true;
		bulkImportProgress = 0;
		bulkImportError = null;
		bulkImportResult = null;

		try {
			const form = new FormData();
			form.append('file', bulkImportFile);

			// Use XMLHttpRequest for progress tracking
			await new Promise<void>((resolve, reject) => {
				const xhr = new XMLHttpRequest();
				xhr.open('POST', `/api/v1/profiles/${$activeProfile}/strava/bulk-import`);

				xhr.upload.addEventListener('progress', (e) => {
					if (e.lengthComputable) {
						bulkImportProgress = Math.round((e.loaded / e.total) * 100);
					}
				});

				xhr.addEventListener('load', () => {
					if (xhr.status >= 200 && xhr.status < 300) {
						try {
							bulkImportResult = JSON.parse(xhr.responseText) as BulkImportResponse;
							resolve();
						} catch {
							reject(new Error('Invalid response from server.'));
						}
					} else {
						let detail = `Upload failed (${xhr.status})`;
						try {
							const json = JSON.parse(xhr.responseText);
							detail = json.detail ?? detail;
						} catch {
							// ignore
						}
						reject(new Error(detail));
					}
				});

				xhr.addEventListener('error', () => reject(new Error('Network error during upload.')));
				xhr.send(form);
			});
		} catch (e) {
			bulkImportError = e instanceof Error ? e.message : 'Upload failed. Please try again.';
		} finally {
			bulkImportUploading = false;
		}
	}

	// ---------------------------------------------------------------------------
	// Section 3 — Notifications
	// ---------------------------------------------------------------------------

	let notifEnabled = false;
	let notifTime = '20:00';
	let notifSaving = false;

	async function loadNotifSettings() {
		try {
			const s = await settingsApi.getProfile($activeProfile);
			notifEnabled = s.notification_enabled;
			notifTime = s.notification_time ?? '20:00';
		} catch {
			// keep defaults
		}
	}

	async function saveNotifSettings() {
		notifSaving = true;
		notifFeedback = null;
		try {
			const body: ProfileSettingsUpdate = {
				notification_enabled: notifEnabled,
				notification_time: notifEnabled ? notifTime : null
			};
			await settingsApi.updateProfile(body, $activeProfile);
			setFeedback((v) => (notifFeedback = v), 'success', 'Notification settings saved.');
		} catch (e) {
			setFeedback(
				(v) => (notifFeedback = v),
				'error',
				e instanceof Error ? e.message : 'Failed to save notification settings.'
			);
		} finally {
			notifSaving = false;
		}
	}

	// ---------------------------------------------------------------------------
	// Section 4 — Weather
	// ---------------------------------------------------------------------------

	let weatherLocationName = '';
	let weatherLatitude = '';
	let weatherLongitude = '';
	let weatherAdvisoriesEnabled = true;
	let weatherSaving = false;

	async function loadWeatherSettings() {
		try {
			const s = await settingsApi.getWeather($activeProfile);
			weatherLocationName = s.location_name ?? '';
			weatherLatitude = s.latitude != null ? String(s.latitude) : '';
			weatherLongitude = s.longitude != null ? String(s.longitude) : '';
			weatherAdvisoriesEnabled = s.weather_advisories_enabled;
		} catch {
			// keep defaults
		}
	}

	async function saveWeatherSettings() {
		weatherSaving = true;
		weatherFeedback = null;
		try {
			const lat = weatherLatitude !== '' ? parseFloat(weatherLatitude) : null;
			const lon = weatherLongitude !== '' ? parseFloat(weatherLongitude) : null;
			const body: ProfileWeatherSettingsUpdate = {
				location_name: weatherLocationName.trim() || null,
				latitude: isNaN(lat as number) ? null : lat,
				longitude: isNaN(lon as number) ? null : lon,
				weather_advisories_enabled: weatherAdvisoriesEnabled
			};
			await settingsApi.updateWeather(body, $activeProfile);
			setFeedback((v) => (weatherFeedback = v), 'success', 'Weather settings saved.');
		} catch (e) {
			setFeedback(
				(v) => (weatherFeedback = v),
				'error',
				e instanceof Error ? e.message : 'Failed to save weather settings.'
			);
		} finally {
			weatherSaving = false;
		}
	}

	// ---------------------------------------------------------------------------
	// Section 5 — Data
	// ---------------------------------------------------------------------------

	let importJsonFile: File | null = null;
	let importJsonMode: 'merge' | 'replace' = 'merge';
	let importJsonUploading = false;
	let importJsonResult: { imported?: number; message?: string } | null = null;
	let importJsonError: string | null = null;
	let showImportConfirm = false;

	let backupTriggering = false;
	let lastBackup: BackupRecord | null = null;

	async function loadLastBackup() {
		try {
			const records = await backupApi.list();
			if (records.length > 0) {
				// Sort by completed_at descending and take the first successful one
				const sorted = records
					.filter((r) => r.success)
					.sort((a, b) => new Date(b.completed_at).getTime() - new Date(a.completed_at).getTime());
				lastBackup = sorted[0] ?? null;
			}
		} catch {
			// ignore
		}
	}

	function downloadExport(url: string, filename: string) {
		const a = document.createElement('a');
		a.href = url;
		a.download = filename;
		a.click();
	}

	function handleImportJsonFileChange(event: Event) {
		const input = event.target as HTMLInputElement;
		importJsonFile = input.files?.[0] ?? null;
		importJsonError = null;
		importJsonResult = null;
	}

	async function importJson() {
		if (!importJsonFile) return;
		importJsonUploading = true;
		importJsonError = null;
		importJsonResult = null;
		try {
			const result = await exportApi.importJson(importJsonFile, importJsonMode, $activeProfile);
			importJsonResult = result;
			setFeedback((v) => (dataFeedback = v), 'success', 'Import completed successfully.');
		} catch (e) {
			importJsonError = e instanceof Error ? e.message : 'Import failed.';
			setFeedback(
				(v) => (dataFeedback = v),
				'error',
				e instanceof Error ? e.message : 'Import failed.'
			);
		} finally {
			importJsonUploading = false;
		}
	}

	async function triggerBackup() {
		backupTriggering = true;
		dataFeedback = null;
		try {
			const record = await backupApi.trigger();
			lastBackup = record;
			setFeedback((v) => (dataFeedback = v), 'success', 'Backup completed successfully.');
		} catch (e) {
			setFeedback(
				(v) => (dataFeedback = v),
				'error',
				e instanceof Error ? e.message : 'Backup failed.'
			);
		} finally {
			backupTriggering = false;
		}
	}

	// ---------------------------------------------------------------------------
	// Helpers
	// ---------------------------------------------------------------------------

	function formatDateTime(iso: string | null): string {
		if (!iso) return 'Never';
		return new Date(iso).toLocaleString(undefined, {
			dateStyle: 'medium',
			timeStyle: 'short'
		});
	}

	function formatBytes(bytes: number): string {
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
		return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
	}

	// ---------------------------------------------------------------------------
	// Mount — load all data
	// ---------------------------------------------------------------------------

	onMount(async () => {
		loading = true;
		loadError = null;
		try {
			await Promise.all([
				loadProfile(),
				loadStravaStatus(),
				loadAppSettings(),
				loadNotifSettings(),
				loadWeatherSettings(),
				loadLastBackup()
			]);
		} catch (e) {
			loadError = e instanceof Error ? e.message : 'Failed to load settings.';
		} finally {
			loading = false;
		}

		// Handle Strava OAuth callback redirect (?strava=connected or ?strava=error)
		const params = new URLSearchParams(window.location.search);
		const stravaParam = params.get('strava');
		if (stravaParam === 'connected') {
			setFeedback((v) => (stravaFeedback = v), 'success', 'Strava connected successfully!');
			// Clean up the URL without reloading
			const url = new URL(window.location.href);
			url.searchParams.delete('strava');
			window.history.replaceState({}, '', url.toString());
		} else if (stravaParam === 'error') {
			setFeedback((v) => (stravaFeedback = v), 'error', 'Strava connection failed. Please try again.');
			const url = new URL(window.location.href);
			url.searchParams.delete('strava');
			window.history.replaceState({}, '', url.toString());
		}
	});

	// Reload profile-specific data when active profile changes
	$: if ($activeProfile) {
		if (!loading) {
			Promise.all([
				loadProfile(),
				loadStravaStatus(),
				loadNotifSettings(),
				loadWeatherSettings(),
				loadLastBackup()
			]).catch(() => {});
		}
	}
</script>

<!-- =========================================================================
     Settings Page
     ========================================================================= -->

<!-- Loading state -->
{#if loading}
  <div class="flex items-center justify-center py-20">
    <div class="h-8 w-8 animate-spin rounded-full border-4 border-blue-200 border-t-blue-600" aria-hidden="true"></div>
    <span class="ml-3 text-sm text-gray-500">Loading settings...</span>
  </div>
{:else if loadError}
  <div class="mx-auto max-w-2xl px-4 py-8">
    <div class="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
      {loadError}
    </div>
  </div>
{:else}
<div class="mx-auto max-w-2xl space-y-8 px-4 py-8">
  <h1 class="text-2xl font-bold text-gray-900">Settings</h1>
  <p class="text-sm text-gray-500">Manage your profile, integrations, and preferences.</p>

  <!-- ======================================================================
       SECTION 1 � Profile
       ====================================================================== -->
  <section aria-labelledby="section-profile">
    <div class="rounded-2xl border border-gray-200 bg-white shadow-sm">
      <div class="border-b border-gray-100 px-6 py-4">
        <h2 id="section-profile" class="text-base font-semibold text-gray-900">Profile</h2>
        <p class="mt-0.5 text-sm text-gray-500">Your personal details used by the AI coach.</p>
      </div>
      <div class="space-y-5 p-6">

        <!-- Profile name -->
        <div>
          <label for="profile-name" class="block text-sm font-medium text-gray-700">
            Display name <span class="text-red-500" aria-hidden="true">*</span>
          </label>
          <input
            id="profile-name"
            type="text"
            bind:value={profileName}
            maxlength="50"
            placeholder="e.g. Profile 1"
            class="mt-1 block w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm shadow-sm
                   focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <!-- Date of birth -->
        <div>
          <label for="dob" class="block text-sm font-medium text-gray-700">Date of birth</label>
          <input
            id="dob"
            type="date"
            bind:value={dateOfBirth}
            max={new Date().toISOString().split('T')[0]}
            class="mt-1 block w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm shadow-sm
                   focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <!-- Biological sex -->
        <div>
          <label for="bio-sex" class="block text-sm font-medium text-gray-700">Biological sex</label>
          <select
            id="bio-sex"
            bind:value={biologicalSex}
            class="mt-1 block w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm shadow-sm
                   focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">Select...</option>
            <option value="male">Male</option>
            <option value="female">Female</option>
            <option value="other">Other / prefer not to say</option>
          </select>
          <p class="mt-1 text-xs text-gray-400">Used to estimate max heart rate for training zones.</p>
        </div>

        <!-- Injury notes -->
        <div>
          <label for="injury-notes" class="block text-sm font-medium text-gray-700">
            Injury history <span class="text-gray-400 font-normal">(optional)</span>
          </label>
          <textarea
            id="injury-notes"
            bind:value={injuryNotes}
            rows="3"
            placeholder="e.g. Previous knee injury, avoid high-impact intervals"
            class="mt-1 block w-full resize-none rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm shadow-sm
                   focus:outline-none focus:ring-2 focus:ring-blue-500"
          ></textarea>
          <p class="mt-1 text-xs text-gray-400">Your AI coach will take this into account when generating your plan.</p>
        </div>

        <!-- Feedback -->
        {#if profileFeedback}
          <div
            class="rounded-lg px-3 py-2 text-sm {profileFeedback.type === 'success'
              ? 'border border-green-200 bg-green-50 text-green-800'
              : 'border border-red-200 bg-red-50 text-red-700'}"
            role="alert"
            aria-live="polite"
          >
            {profileFeedback.message}
          </div>
        {/if}

        <!-- Save button -->
        <div class="flex justify-end">
          <button
            type="button"
            on:click={saveProfile}
            disabled={profileSaving}
            class="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white
                   hover:bg-blue-700 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500
                   disabled:opacity-60 disabled:cursor-not-allowed"
            aria-busy={profileSaving}
          >
            {#if profileSaving}
              <span class="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" aria-hidden="true"></span>
              Saving...
            {:else}
              Save Profile
            {/if}
          </button>
        </div>
      </div>
    </div>
  </section>


  <!-- ======================================================================
       SECTION 2 � Strava Integration
       ====================================================================== -->
  <section aria-labelledby="section-strava">
    <div class="rounded-2xl border border-gray-200 bg-white shadow-sm">
      <div class="border-b border-gray-100 px-6 py-4">
        <h2 id="section-strava" class="text-base font-semibold text-gray-900">Strava Integration</h2>
        <p class="mt-0.5 text-sm text-gray-500">Connect your Strava account to sync runs automatically.</p>
      </div>
      <div class="space-y-6 p-6">

        <!-- Connect / Disconnect -->
        <div class="flex items-start justify-between gap-4">
          <div>
            {#if stravaStatus?.connected}
              <p class="text-sm font-medium text-gray-900">Connected to Strava</p>
              {#if stravaStatus.athlete_id}
                <p class="mt-0.5 text-xs text-gray-500">Athlete ID: {stravaStatus.athlete_id}</p>
              {/if}
              <p class="mt-0.5 text-xs text-gray-500">
                Last sync: {formatDateTime(stravaStatus.last_sync_at)}
              </p>
              {#if stravaStatus.sync_error}
                <p class="mt-1 text-xs text-red-600" role="alert">Sync error: {stravaStatus.sync_error}</p>
              {/if}
            {:else if stravaLoading}
              <p class="text-sm text-gray-500">Checking Strava status...</p>
            {:else}
              <p class="text-sm font-medium text-gray-900">Not connected</p>
              <p class="mt-0.5 text-xs text-gray-500">Connect to sync your runs automatically.</p>
            {/if}
          </div>

          <div class="shrink-0">
            {#if stravaStatus?.connected}
              {#if showDisconnectConfirm}
                <div class="flex items-center gap-2">
                  <span class="text-xs text-gray-600">Are you sure?</span>
                  <button
                    type="button"
                    on:click={disconnectStrava}
                    disabled={stravaDisconnecting}
                    class="rounded-lg bg-red-600 px-3 py-1.5 text-xs font-medium text-white
                           hover:bg-red-700 transition-colors focus:outline-none focus:ring-2 focus:ring-red-500
                           disabled:opacity-60 disabled:cursor-not-allowed"
                    aria-busy={stravaDisconnecting}
                  >
                    {stravaDisconnecting ? 'Disconnecting...' : 'Yes, disconnect'}
                  </button>
                  <button
                    type="button"
                    on:click={() => (showDisconnectConfirm = false)}
                    class="rounded-lg border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-700
                           hover:bg-gray-50 transition-colors focus:outline-none focus:ring-2 focus:ring-gray-400"
                  >
                    Cancel
                  </button>
                </div>
              {:else}
                <button
                  type="button"
                  on:click={() => (showDisconnectConfirm = true)}
                  class="rounded-lg border border-red-300 px-3 py-1.5 text-xs font-medium text-red-700
                         hover:bg-red-50 transition-colors focus:outline-none focus:ring-2 focus:ring-red-400"
                >
                  Disconnect
                </button>
              {/if}
            {:else}
              <button
                type="button"
                on:click={connectStrava}
                class="inline-flex items-center gap-2 rounded-lg bg-orange-500 px-4 py-2 text-sm font-medium text-white
                       hover:bg-orange-600 transition-colors focus:outline-none focus:ring-2 focus:ring-orange-400"
              >
                <svg class="h-4 w-4" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                  <path d="M15.387 17.944l-2.089-4.116h-3.065L15.387 24l5.15-10.172h-3.066m-7.008-5.599l2.836 5.598h4.172L10.463 0l-7 13.828h4.169" />
                </svg>
                Connect Strava
              </button>
            {/if}
          </div>
        </div>

        <!-- Sync interval slider -->
        <div>
          <label for="sync-interval" class="block text-sm font-medium text-gray-700">
            Sync interval: <span class="font-semibold text-blue-700">{syncIntervalMinutes} min</span>
          </label>
          <p class="mt-0.5 text-xs text-gray-400">Shared across both profiles. How often to poll Strava for new activities.</p>
          <div class="mt-2 flex items-center gap-3">
            <span class="text-xs text-gray-500">5</span>
            <input
              id="sync-interval"
              type="range"
              bind:value={syncIntervalMinutes}
              min="5"
              max="60"
              step="5"
              class="flex-1 accent-blue-600"
              aria-valuemin="5"
              aria-valuemax="60"
              aria-valuenow={syncIntervalMinutes}
            />
            <span class="text-xs text-gray-500">60</span>
          </div>
          <div class="mt-3 flex justify-end">
            <button
              type="button"
              on:click={saveSyncInterval}
              disabled={syncIntervalSaving}
              class="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white
                     hover:bg-blue-700 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500
                     disabled:opacity-60 disabled:cursor-not-allowed"
              aria-busy={syncIntervalSaving}
            >
              {syncIntervalSaving ? 'Saving...' : 'Save Interval'}
            </button>
          </div>
        </div>

        <!-- Bulk import -->
        <div class="rounded-xl border border-gray-200 bg-gray-50 p-4">
          <div class="flex items-start gap-3">
            <span class="mt-0.5 shrink-0 text-xl" aria-hidden="true">??</span>
            <div class="flex-1 min-w-0">
              <p class="text-sm font-medium text-gray-800">Bulk Import from Strava Export</p>
              <p class="mt-0.5 text-xs text-gray-500">
                Upload your Strava data export ZIP to import your full run history.
                Get it from Strava: Settings &rarr; My Account &rarr; Download or Delete Your Data.
              </p>

              <div class="mt-3">
                <label for="bulk-import-zip" class="sr-only">Upload Strava export ZIP</label>
                <input
                  id="bulk-import-zip"
                  type="file"
                  accept=".zip"
                  on:change={handleBulkImportFileChange}
                  disabled={bulkImportUploading}
                  class="block w-full text-sm text-gray-600
                         file:mr-3 file:rounded-lg file:border-0
                         file:bg-blue-50 file:px-3 file:py-1.5
                         file:text-sm file:font-medium file:text-blue-700
                         hover:file:bg-blue-100
                         disabled:opacity-50 disabled:cursor-not-allowed"
                  aria-label="Upload Strava export ZIP file"
                />
              </div>

              {#if bulkImportFile && !bulkImportResult}
                <button
                  type="button"
                  on:click={uploadBulkImport}
                  disabled={bulkImportUploading}
                  class="mt-3 inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white
                         hover:bg-blue-700 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500
                         disabled:opacity-60 disabled:cursor-not-allowed"
                  aria-busy={bulkImportUploading}
                >
                  {#if bulkImportUploading}
                    <span class="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" aria-hidden="true"></span>
                    Uploading {bulkImportProgress}%...
                  {:else}
                    Upload
                  {/if}
                </button>
              {/if}

              {#if bulkImportUploading && bulkImportProgress > 0}
                <div class="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-gray-200" role="progressbar" aria-valuenow={bulkImportProgress} aria-valuemin="0" aria-valuemax="100">
                  <div class="h-full rounded-full bg-blue-500 transition-all" style="width: {bulkImportProgress}%"></div>
                </div>
              {/if}

              {#if bulkImportError}
                <div class="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700" role="alert">
                  {bulkImportError}
                </div>
              {/if}

              {#if bulkImportResult}
                <div class="mt-3 rounded-lg border border-green-200 bg-green-50 p-3 text-xs text-green-800" role="status" aria-live="polite">
                  <p class="mb-1 font-semibold text-green-900">Import successful!</p>
                  <ul class="space-y-0.5">
                    <li>Imported: <strong>{bulkImportResult.imported}</strong> activities</li>
                    <li>Skipped duplicates: <strong>{bulkImportResult.skipped_duplicates}</strong></li>
                    {#if bulkImportResult.parse_errors > 0}
                      <li class="text-amber-700">Parse errors: <strong>{bulkImportResult.parse_errors}</strong></li>
                    {/if}
                    {#if bulkImportResult.vdot !== null}
                      <li>VDOT score: <strong>{bulkImportResult.vdot?.toFixed(1)}</strong></li>
                    {/if}
                    {#if bulkImportResult.pace_zones_updated}
                      <li>Pace zones updated</li>
                    {/if}
                  </ul>
                </div>
              {/if}
            </div>
          </div>
        </div>

        <!-- Strava section feedback -->
        {#if stravaFeedback}
          <div
            class="rounded-lg px-3 py-2 text-sm {stravaFeedback.type === 'success'
              ? 'border border-green-200 bg-green-50 text-green-800'
              : 'border border-red-200 bg-red-50 text-red-700'}"
            role="alert"
            aria-live="polite"
          >
            {stravaFeedback.message}
          </div>
        {/if}
      </div>
    </div>
  </section>


  <!-- ======================================================================
       SECTION 3 � Notifications
       ====================================================================== -->
  <section aria-labelledby="section-notifications">
    <div class="rounded-2xl border border-gray-200 bg-white shadow-sm">
      <div class="border-b border-gray-100 px-6 py-4">
        <h2 id="section-notifications" class="text-base font-semibold text-gray-900">Notifications</h2>
        <p class="mt-0.5 text-sm text-gray-500">Configure workout reminders for this profile.</p>
      </div>
      <div class="space-y-5 p-6">

        <!-- Enable toggle -->
        <div class="flex items-center justify-between">
          <div>
            <p class="text-sm font-medium text-gray-900">Enable workout reminders</p>
            <p class="mt-0.5 text-xs text-gray-500">Receive a push notification the evening before each scheduled workout.</p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={notifEnabled}
            on:click={() => (notifEnabled = !notifEnabled)}
            class="relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent
                   transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2
                   {notifEnabled ? 'bg-blue-600' : 'bg-gray-200'}"
          >
            <span
              class="pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition-transform
                     {notifEnabled ? 'translate-x-5' : 'translate-x-0'}"
              aria-hidden="true"
            ></span>
          </button>
        </div>

        <!-- Time picker -->
        {#if notifEnabled}
          <div>
            <label for="notif-time" class="block text-sm font-medium text-gray-700">Reminder time</label>
            <p class="mt-0.5 text-xs text-gray-400">The time you will receive the reminder notification each evening.</p>
            <input
              id="notif-time"
              type="time"
              bind:value={notifTime}
              class="mt-1 block w-40 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm shadow-sm
                     focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        {/if}

        <!-- Feedback -->
        {#if notifFeedback}
          <div
            class="rounded-lg px-3 py-2 text-sm {notifFeedback.type === 'success'
              ? 'border border-green-200 bg-green-50 text-green-800'
              : 'border border-red-200 bg-red-50 text-red-700'}"
            role="alert"
            aria-live="polite"
          >
            {notifFeedback.message}
          </div>
        {/if}

        <!-- Save button -->
        <div class="flex justify-end">
          <button
            type="button"
            on:click={saveNotifSettings}
            disabled={notifSaving}
            class="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white
                   hover:bg-blue-700 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500
                   disabled:opacity-60 disabled:cursor-not-allowed"
            aria-busy={notifSaving}
          >
            {#if notifSaving}
              <span class="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" aria-hidden="true"></span>
              Saving...
            {:else}
              Save Notifications
            {/if}
          </button>
        </div>
      </div>
    </div>
  </section>

  <!-- ======================================================================
       SECTION 4 � Weather
       ====================================================================== -->
  <section aria-labelledby="section-weather">
    <div class="rounded-2xl border border-gray-200 bg-white shadow-sm">
      <div class="border-b border-gray-100 px-6 py-4">
        <h2 id="section-weather" class="text-base font-semibold text-gray-900">Weather</h2>
        <p class="mt-0.5 text-sm text-gray-500">Set your location for weather-aware coaching notes.</p>
      </div>
      <div class="space-y-5 p-6">

        <!-- Location name -->
        <div>
          <label for="weather-location" class="block text-sm font-medium text-gray-700">Location name</label>
          <input
            id="weather-location"
            type="text"
            bind:value={weatherLocationName}
            placeholder="e.g. London, UK"
            class="mt-1 block w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm shadow-sm
                   focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <p class="mt-1 text-xs text-gray-400">Used for display only. Provide lat/lon for accurate forecasts.</p>
        </div>

        <!-- Lat / Lon -->
        <div class="grid grid-cols-2 gap-4">
          <div>
            <label for="weather-lat" class="block text-sm font-medium text-gray-700">Latitude</label>
            <input
              id="weather-lat"
              type="number"
              bind:value={weatherLatitude}
              step="0.0001"
              min="-90"
              max="90"
              placeholder="e.g. 51.5074"
              class="mt-1 block w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm shadow-sm
                     focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label for="weather-lon" class="block text-sm font-medium text-gray-700">Longitude</label>
            <input
              id="weather-lon"
              type="number"
              bind:value={weatherLongitude}
              step="0.0001"
              min="-180"
              max="180"
              placeholder="e.g. -0.1278"
              class="mt-1 block w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm shadow-sm
                     focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        </div>

        <!-- Advisory toggle -->
        <div class="flex items-center justify-between">
          <div>
            <p class="text-sm font-medium text-gray-900">Weather advisories</p>
            <p class="mt-0.5 text-xs text-gray-500">Show heat, wind, and rain warnings on workout coaching notes.</p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={weatherAdvisoriesEnabled}
            on:click={() => (weatherAdvisoriesEnabled = !weatherAdvisoriesEnabled)}
            class="relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent
                   transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2
                   {weatherAdvisoriesEnabled ? 'bg-blue-600' : 'bg-gray-200'}"
          >
            <span
              class="pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition-transform
                     {weatherAdvisoriesEnabled ? 'translate-x-5' : 'translate-x-0'}"
              aria-hidden="true"
            ></span>
          </button>
        </div>

        <!-- Feedback -->
        {#if weatherFeedback}
          <div
            class="rounded-lg px-3 py-2 text-sm {weatherFeedback.type === 'success'
              ? 'border border-green-200 bg-green-50 text-green-800'
              : 'border border-red-200 bg-red-50 text-red-700'}"
            role="alert"
            aria-live="polite"
          >
            {weatherFeedback.message}
          </div>
        {/if}

        <!-- Save button -->
        <div class="flex justify-end">
          <button
            type="button"
            on:click={saveWeatherSettings}
            disabled={weatherSaving}
            class="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white
                   hover:bg-blue-700 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500
                   disabled:opacity-60 disabled:cursor-not-allowed"
            aria-busy={weatherSaving}
          >
            {#if weatherSaving}
              <span class="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" aria-hidden="true"></span>
              Saving...
            {:else}
              Save Weather
            {/if}
          </button>
        </div>
      </div>
    </div>
  </section>


  <!-- ======================================================================
       SECTION 5 � Data
       ====================================================================== -->
  <section aria-labelledby="section-data">
    <div class="rounded-2xl border border-gray-200 bg-white shadow-sm">
      <div class="border-b border-gray-100 px-6 py-4">
        <h2 id="section-data" class="text-base font-semibold text-gray-900">Data</h2>
        <p class="mt-0.5 text-sm text-gray-500">Export, import, and back up your training data.</p>
      </div>
      <div class="space-y-6 p-6">

        <!-- Export buttons -->
        <div>
          <p class="mb-3 text-sm font-medium text-gray-700">Export</p>
          <div class="flex flex-wrap gap-3">
            <button
              type="button"
              on:click={() => downloadExport(exportApi.jsonUrl($activeProfile), 'profile-export.json')}
              class="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700
                     hover:bg-gray-50 transition-colors focus:outline-none focus:ring-2 focus:ring-gray-400"
            >
              <svg class="h-4 w-4 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
              Export JSON
            </button>
            <button
              type="button"
              on:click={() => downloadExport(exportApi.csvUrl($activeProfile), 'runs.csv')}
              class="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700
                     hover:bg-gray-50 transition-colors focus:outline-none focus:ring-2 focus:ring-gray-400"
            >
              <svg class="h-4 w-4 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              Export CSV
            </button>
            <button
              type="button"
              on:click={() => downloadExport(exportApi.icalUrl($activeProfile), 'training-plan.ical')}
              class="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700
                     hover:bg-gray-50 transition-colors focus:outline-none focus:ring-2 focus:ring-gray-400"
            >
              <svg class="h-4 w-4 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
              </svg>
              Export iCal
            </button>
          </div>
        </div>

        <hr class="border-gray-100" />

        <!-- Import JSON -->
        <div>
          <p class="mb-1 text-sm font-medium text-gray-700">Import JSON</p>
          <p class="mb-3 text-xs text-gray-400">Restore a previously exported JSON file. Choose merge to add data alongside existing records, or replace to overwrite all data.</p>

          <div class="space-y-3">
            <!-- File picker -->
            <div>
              <label for="import-json-file" class="sr-only">Select JSON file to import</label>
              <input
                id="import-json-file"
                type="file"
                accept=".json"
                on:change={handleImportJsonFileChange}
                disabled={importJsonUploading}
                class="block w-full text-sm text-gray-600
                       file:mr-3 file:rounded-lg file:border-0
                       file:bg-gray-100 file:px-3 file:py-1.5
                       file:text-sm file:font-medium file:text-gray-700
                       hover:file:bg-gray-200
                       disabled:opacity-50 disabled:cursor-not-allowed"
                aria-label="Select JSON file to import"
              />
            </div>

            <!-- Mode selector -->
            <div class="flex items-center gap-4">
              <span class="text-sm text-gray-600">Import mode:</span>
              <label class="flex items-center gap-1.5 text-sm text-gray-700 cursor-pointer">
                <input
                  type="radio"
                  bind:group={importJsonMode}
                  value="merge"
                  class="accent-blue-600"
                />
                Merge
              </label>
              <label class="flex items-center gap-1.5 text-sm text-gray-700 cursor-pointer">
                <input
                  type="radio"
                  bind:group={importJsonMode}
                  value="replace"
                  class="accent-blue-600"
                />
                Replace
              </label>
              {#if importJsonMode === 'replace'}
                <span class="rounded-md bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700 border border-amber-200">
                  Overwrites all existing data
                </span>
              {/if}
            </div>

            <!-- Import button -->
            {#if importJsonFile}
              <div>
                <button
                  type="button"
                  on:click={() => { showImportConfirm = true; }}
                  disabled={importJsonUploading}
                  class="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white
                         hover:bg-blue-700 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500
                         disabled:opacity-60 disabled:cursor-not-allowed"
                >
                  Import {importJsonFile.name}
                </button>
              </div>
            {/if}

            <!-- Import result -->
            {#if importJsonResult}
              <div class="rounded-lg border border-green-200 bg-green-50 px-3 py-2 text-xs text-green-800" role="status" aria-live="polite">
                Import completed successfully.
              </div>
            {/if}

            {#if importJsonError}
              <div class="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700" role="alert">
                {importJsonError}
              </div>
            {/if}
          </div>
        </div>

        <hr class="border-gray-100" />

        <!-- Backup -->
        <div>
          <div class="flex items-start justify-between gap-4">
            <div>
              <p class="text-sm font-medium text-gray-700">Manual Backup</p>
              <p class="mt-0.5 text-xs text-gray-400">
                Last backup:
                {#if lastBackup}
                  <span class="font-medium text-gray-600">{formatDateTime(lastBackup.completed_at)}</span>
                  ({formatBytes(lastBackup.size_bytes)})
                {:else}
                  <span class="text-gray-400">Never</span>
                {/if}
              </p>
            </div>
            <button
              type="button"
              on:click={triggerBackup}
              disabled={backupTriggering}
              class="shrink-0 inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700
                     hover:bg-gray-50 transition-colors focus:outline-none focus:ring-2 focus:ring-gray-400
                     disabled:opacity-60 disabled:cursor-not-allowed"
              aria-busy={backupTriggering}
            >
              {#if backupTriggering}
                <span class="h-4 w-4 animate-spin rounded-full border-2 border-gray-300 border-t-gray-600" aria-hidden="true"></span>
                Backing up...
              {:else}
                <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4" />
                </svg>
                Backup Now
              {/if}
            </button>
          </div>
        </div>

        <!-- Data section feedback -->
        {#if dataFeedback}
          <div
            class="rounded-lg px-3 py-2 text-sm {dataFeedback.type === 'success'
              ? 'border border-green-200 bg-green-50 text-green-800'
              : 'border border-red-200 bg-red-50 text-red-700'}"
            role="alert"
            aria-live="polite"
          >
            {dataFeedback.message}
          </div>
        {/if}
      </div>
    </div>
  </section>

</div>
{/if}

<!-- =========================================================================
     Import Confirmation Dialog
     ========================================================================= -->
{#if showImportConfirm}
  <!-- Backdrop -->
  <div
    class="fixed inset-0 z-40 flex items-center justify-center bg-black/50 px-4"
    role="dialog"
    aria-modal="true"
    aria-labelledby="import-confirm-title"
  >
    <div class="w-full max-w-sm rounded-2xl bg-white p-6 shadow-xl">
      <h3 id="import-confirm-title" class="text-base font-semibold text-gray-900">
        Confirm Import
      </h3>
      <p class="mt-2 text-sm text-gray-600">
        {#if importJsonMode === 'replace'}
          This will <strong>permanently replace all existing data</strong> for this profile with the contents of the imported file. This cannot be undone.
        {:else}
          This will merge the imported data with your existing records. Duplicate entries will be skipped.
        {/if}
      </p>
      <p class="mt-2 text-sm text-gray-500">File: <span class="font-medium">{importJsonFile?.name}</span></p>
      <div class="mt-5 flex justify-end gap-3">
        <button
          type="button"
          on:click={() => (showImportConfirm = false)}
          class="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700
                 hover:bg-gray-50 transition-colors focus:outline-none focus:ring-2 focus:ring-gray-400"
        >
          Cancel
        </button>
        <button
          type="button"
          on:click={async () => { showImportConfirm = false; await importJson(); }}
          disabled={importJsonUploading}
          class="inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium text-white
                 transition-colors focus:outline-none focus:ring-2
                 {importJsonMode === 'replace'
                   ? 'bg-red-600 hover:bg-red-700 focus:ring-red-500'
                   : 'bg-blue-600 hover:bg-blue-700 focus:ring-blue-500'}
                 disabled:opacity-60 disabled:cursor-not-allowed"
          aria-busy={importJsonUploading}
        >
          {#if importJsonUploading}
            <span class="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" aria-hidden="true"></span>
            Importing...
          {:else}
            {importJsonMode === 'replace' ? 'Replace & Import' : 'Merge & Import'}
          {/if}
        </button>
      </div>
    </div>
  </div>
{/if}
