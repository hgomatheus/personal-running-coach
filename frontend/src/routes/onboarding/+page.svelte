<script lang="ts">
	import { goto } from '$app/navigation';
	import { activeProfile } from '$lib/stores';
	import {
		profilesApi,
		raceGoalsApi,
		plansApi,
		type ProfileUpdate,
		type RaceGoalCreate,
		type BulkImportResponse
	} from '$lib/api';
	import {
		validateStep1 as _validateStep1,
		validateStep2 as _validateStep2,
		validateStep3 as _validateStep3
	} from '$lib/onboardingValidation';

	// ---------------------------------------------------------------------------
	// Step management (1-3 user-facing + step 4 = loading screen)
	// ---------------------------------------------------------------------------

	let currentStep = 1;
	const TOTAL_STEPS = 3; // user-facing steps

	// ---------------------------------------------------------------------------
	// Step 1 — Profile Setup
	// ---------------------------------------------------------------------------

	let profileName = '';
	let dateOfBirth = '';
	let biologicalSex: 'male' | 'female' | 'other' | '' = '';
	let injuryNotes = '';

	let step1Errors: Record<string, string> = {};

	function validateStep1(): boolean {
		step1Errors = _validateStep1({ profileName, dateOfBirth, biologicalSex });
		return Object.keys(step1Errors).length === 0;
	}

	// ---------------------------------------------------------------------------
	// Step 2 — Race Goal
	// ---------------------------------------------------------------------------

	const PRESET_DISTANCES = [
		{ label: '5 km', metres: 5000 },
		{ label: '10 km', metres: 10000 },
		{ label: 'Half Marathon', metres: 21097 },
		{ label: 'Marathon', metres: 42195 }
	];

	let raceDistancePreset: number | 'custom' = 5000;
	let raceDistanceCustomKm = '';
	let raceDate = '';
	let raceLabel = '';

	let step2Errors: Record<string, string> = {};

	$: raceDistanceMetres = (() => {
		if (raceDistancePreset === 'custom') {
			const km = parseFloat(raceDistanceCustomKm);
			return isNaN(km) || km <= 0 ? null : Math.round(km * 1000);
		}
		return raceDistancePreset as number;
	})();

	function validateStep2(): boolean {
		step2Errors = _validateStep2({ raceDistancePreset, raceDistanceCustomKm, raceDate });
		return Object.keys(step2Errors).length === 0;
	}

	// ---------------------------------------------------------------------------
	// Step 3 — Fitness Data
	// ---------------------------------------------------------------------------

	let bulkImportFile: File | null = null;
	let bulkImportUploading = false;
	let bulkImportResult: BulkImportResponse | null = null;
	let bulkImportError: string | null = null;

	let currentWeeklyKm = '';
	let longestRecentRunKm = '';

	let step3Errors: Record<string, string> = {};

	$: bulkImportSuccess = bulkImportResult !== null;
	$: fitnessFieldsRequired = !bulkImportSuccess;

	function handleFileChange(event: Event) {
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
		bulkImportError = null;
		bulkImportResult = null;

		try {
			const form = new FormData();
			form.append('file', bulkImportFile);
			const res = await fetch(`/api/v1/profiles/${$activeProfile}/strava/bulk-import`, {
				method: 'POST',
				body: form
			});
			if (!res.ok) {
				const json = await res.json().catch(() => ({}));
				throw new Error(json.detail ?? `Upload failed (${res.status})`);
			}
			bulkImportResult = (await res.json()) as BulkImportResponse;
		} catch (e) {
			bulkImportError = e instanceof Error ? e.message : 'Upload failed. Please try again.';
		} finally {
			bulkImportUploading = false;
		}
	}

	function validateStep3(): boolean {
		step3Errors = _validateStep3({
			currentWeeklyKm,
			longestRecentRunKm,
			bulkImportSuccess
		});
		return Object.keys(step3Errors).length === 0;
	}

	// ---------------------------------------------------------------------------
	// Step 4 — Generating Plan (loading screen)
	// ---------------------------------------------------------------------------

	let planGenerating = false;
	let planError: string | null = null;
	let createdRaceGoalId: number | null = null;

	// ---------------------------------------------------------------------------
	// Navigation
	// ---------------------------------------------------------------------------

	function goNext() {
		if (currentStep === 1) {
			if (!validateStep1()) return;
			currentStep = 2;
		} else if (currentStep === 2) {
			if (!validateStep2()) return;
			currentStep = 3;
		} else if (currentStep === 3) {
			if (!validateStep3()) return;
			submitOnboarding();
		}
	}

	function goBack() {
		if (currentStep > 1) currentStep -= 1;
	}

	// ---------------------------------------------------------------------------
	// Submission
	// ---------------------------------------------------------------------------

	async function submitOnboarding() {
		currentStep = 4; // loading screen
		planGenerating = true;
		planError = null;

		try {
			// 1. Update profile
			const profileUpdate: ProfileUpdate = {
				display_name: profileName.trim(),
				date_of_birth: dateOfBirth,
				biological_sex: biologicalSex as 'male' | 'female' | 'other',
				injury_notes: injuryNotes.trim() || null
			};

			// Include manual fitness fields only if no bulk import
			if (!bulkImportSuccess) {
				const wkly = parseFloat(currentWeeklyKm);
				const longest = parseFloat(longestRecentRunKm);
				profileUpdate.current_weekly_km = isNaN(wkly) ? null : wkly;
				profileUpdate.longest_recent_run_km = isNaN(longest) ? null : longest;
			}

			await profilesApi.update($activeProfile, profileUpdate);

			// 2. Create race goal
			const raceGoalBody: RaceGoalCreate = {
				distance_metres: raceDistanceMetres!,
				target_date: raceDate,
				label: raceLabel.trim() || null,
				is_active: true
			};
			const raceGoal = await raceGoalsApi.create(raceGoalBody, $activeProfile);
			createdRaceGoalId = raceGoal.id;

			// 3. Generate training plan
			await plansApi.create(raceGoal.id, $activeProfile);

			// 4. Redirect to dashboard
			goto('/');
		} catch (e) {
			planError = e instanceof Error ? e.message : 'Something went wrong. Please try again.';
			planGenerating = false;
		}
	}

	async function retryPlanGeneration() {
		if (!createdRaceGoalId) {
			// Full retry from submission
			currentStep = 3;
			return;
		}
		planGenerating = true;
		planError = null;
		try {
			await plansApi.create(createdRaceGoalId, $activeProfile);
			goto('/');
		} catch (e) {
			planError = e instanceof Error ? e.message : 'Something went wrong. Please try again.';
			planGenerating = false;
		}
	}

	// ---------------------------------------------------------------------------
	// Helpers
	// ---------------------------------------------------------------------------

	function formatVdot(v: number | null): string {
		if (v === null) return '—';
		return v.toFixed(1);
	}
</script>

<!-- =========================================================================
     Template
     ========================================================================= -->

<!-- Full-page wizard overlay — sits inside the layout shell but styled as a
     focused, centred wizard so it doesn't feel like a regular page. -->
<div class="min-h-screen bg-gray-50 flex flex-col items-center justify-start py-10 px-4">
	<div class="w-full max-w-lg">

		<!-- ------------------------------------------------------------------ -->
		<!-- Header / branding                                                   -->
		<!-- ------------------------------------------------------------------ -->
		<div class="mb-8 text-center">
			<span class="text-4xl" aria-hidden="true">🏃</span>
			<h1 class="mt-2 text-2xl font-bold text-gray-900">Personal Running Coach</h1>
			<p class="mt-1 text-sm text-gray-500">Let's set up your profile and training plan.</p>
		</div>

		<!-- ------------------------------------------------------------------ -->
		<!-- Step indicator (steps 1–3 only; step 4 is the loading screen)       -->
		<!-- ------------------------------------------------------------------ -->
		{#if currentStep <= 3}
			<div class="mb-6 flex items-center justify-center gap-2" aria-label="Onboarding progress">
				{#each [1, 2, 3] as step (step)}
					<div class="flex items-center gap-2">
						<div
							class="flex h-8 w-8 items-center justify-center rounded-full text-sm font-semibold transition-colors
							       {currentStep === step
								? 'bg-blue-600 text-white'
								: currentStep > step
									? 'bg-green-500 text-white'
									: 'bg-gray-200 text-gray-500'}"
							aria-current={currentStep === step ? 'step' : undefined}
						>
							{#if currentStep > step}
								<svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7" />
								</svg>
							{:else}
								{step}
							{/if}
						</div>
						{#if step < 3}
							<div
								class="h-0.5 w-10 rounded-full transition-colors
								       {currentStep > step ? 'bg-green-400' : 'bg-gray-200'}"
								aria-hidden="true"
							></div>
						{/if}
					</div>
				{/each}
			</div>
			<p class="mb-6 text-center text-xs text-gray-400">
				Step {currentStep} of {TOTAL_STEPS}
			</p>
		{/if}

		<!-- ------------------------------------------------------------------ -->
		<!-- Card wrapper                                                         -->
		<!-- ------------------------------------------------------------------ -->
		<div class="rounded-2xl border border-gray-200 bg-white shadow-sm">

			<!-- ============================================================== -->
			<!-- STEP 1 — Profile Setup                                          -->
			<!-- ============================================================== -->
			{#if currentStep === 1}
				<div class="p-6 sm:p-8">
					<h2 class="mb-1 text-lg font-semibold text-gray-900">Profile Setup</h2>
					<p class="mb-6 text-sm text-gray-500">Tell us a bit about yourself.</p>

					<div class="space-y-5">
						<!-- Profile name -->
						<div>
							<label for="profile-name" class="block text-sm font-medium text-gray-700">
								Profile name <span class="text-red-500" aria-hidden="true">*</span>
							</label>
							<input
								id="profile-name"
								type="text"
								bind:value={profileName}
								maxlength="50"
								placeholder="e.g. Profile 1"
								autocomplete="name"
								class="mt-1 block w-full rounded-lg border px-3 py-2 text-sm shadow-sm transition-colors
								       focus:outline-none focus:ring-2 focus:ring-blue-500
								       {step1Errors.profileName ? 'border-red-400 bg-red-50' : 'border-gray-300 bg-white'}"
								aria-required="true"
								aria-describedby={step1Errors.profileName ? 'profile-name-error' : undefined}
								aria-invalid={!!step1Errors.profileName}
							/>
							{#if step1Errors.profileName}
								<p id="profile-name-error" class="mt-1 text-xs text-red-600" role="alert">
									{step1Errors.profileName}
								</p>
							{/if}
						</div>

						<!-- Date of birth -->
						<div>
							<label for="dob" class="block text-sm font-medium text-gray-700">
								Date of birth <span class="text-red-500" aria-hidden="true">*</span>
							</label>
							<input
								id="dob"
								type="date"
								bind:value={dateOfBirth}
								max={new Date().toISOString().split('T')[0]}
								class="mt-1 block w-full rounded-lg border px-3 py-2 text-sm shadow-sm transition-colors
								       focus:outline-none focus:ring-2 focus:ring-blue-500
								       {step1Errors.dateOfBirth ? 'border-red-400 bg-red-50' : 'border-gray-300 bg-white'}"
								aria-required="true"
								aria-describedby={step1Errors.dateOfBirth ? 'dob-error' : undefined}
								aria-invalid={!!step1Errors.dateOfBirth}
							/>
							{#if step1Errors.dateOfBirth}
								<p id="dob-error" class="mt-1 text-xs text-red-600" role="alert">
									{step1Errors.dateOfBirth}
								</p>
							{/if}
						</div>

						<!-- Biological sex -->
						<div>
							<label for="bio-sex" class="block text-sm font-medium text-gray-700">
								Biological sex <span class="text-red-500" aria-hidden="true">*</span>
							</label>
							<select
								id="bio-sex"
								bind:value={biologicalSex}
								class="mt-1 block w-full rounded-lg border px-3 py-2 text-sm shadow-sm transition-colors
								       focus:outline-none focus:ring-2 focus:ring-blue-500
								       {step1Errors.biologicalSex ? 'border-red-400 bg-red-50' : 'border-gray-300 bg-white'}"
								aria-required="true"
								aria-describedby={step1Errors.biologicalSex ? 'bio-sex-error' : undefined}
								aria-invalid={!!step1Errors.biologicalSex}
							>
								<option value="">Select…</option>
								<option value="male">Male</option>
								<option value="female">Female</option>
								<option value="other">Other / prefer not to say</option>
							</select>
							{#if step1Errors.biologicalSex}
								<p id="bio-sex-error" class="mt-1 text-xs text-red-600" role="alert">
									{step1Errors.biologicalSex}
								</p>
							{/if}
							<p class="mt-1 text-xs text-gray-400">
								Used to estimate max heart rate for training zones.
							</p>
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
								class="mt-1 block w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm shadow-sm
								       focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
							></textarea>
							<p class="mt-1 text-xs text-gray-400">
								Your AI coach will take this into account when generating your plan.
							</p>
						</div>
					</div>
				</div>

			<!-- ============================================================== -->
			<!-- STEP 2 — Race Goal                                              -->
			<!-- ============================================================== -->
			{:else if currentStep === 2}
				<div class="p-6 sm:p-8">
					<h2 class="mb-1 text-lg font-semibold text-gray-900">Race Goal</h2>
					<p class="mb-6 text-sm text-gray-500">What race are you training for?</p>

					<div class="space-y-5">
						<!-- Race distance -->
						<div>
							<label for="race-distance" class="block text-sm font-medium text-gray-700">
								Race distance <span class="text-red-500" aria-hidden="true">*</span>
							</label>
							<select
								id="race-distance"
								bind:value={raceDistancePreset}
								class="mt-1 block w-full rounded-lg border px-3 py-2 text-sm shadow-sm transition-colors
								       focus:outline-none focus:ring-2 focus:ring-blue-500
								       {step2Errors.raceDistance ? 'border-red-400 bg-red-50' : 'border-gray-300 bg-white'}"
								aria-required="true"
								aria-describedby={step2Errors.raceDistance ? 'race-distance-error' : undefined}
								aria-invalid={!!step2Errors.raceDistance}
							>
								{#each PRESET_DISTANCES as preset (preset.metres)}
									<option value={preset.metres}>{preset.label}</option>
								{/each}
								<option value="custom">Custom distance…</option>
							</select>

							{#if raceDistancePreset === 'custom'}
								<div class="mt-2 flex items-center gap-2">
									<input
										id="race-distance-custom"
										type="number"
										bind:value={raceDistanceCustomKm}
										min="0.1"
										step="0.1"
										placeholder="e.g. 15"
										class="block w-full rounded-lg border px-3 py-2 text-sm shadow-sm transition-colors
										       focus:outline-none focus:ring-2 focus:ring-blue-500
										       {step2Errors.raceDistance ? 'border-red-400 bg-red-50' : 'border-gray-300 bg-white'}"
										aria-label="Custom race distance in kilometres"
										aria-required="true"
									/>
									<span class="shrink-0 text-sm text-gray-500">km</span>
								</div>
							{/if}

							{#if step2Errors.raceDistance}
								<p id="race-distance-error" class="mt-1 text-xs text-red-600" role="alert">
									{step2Errors.raceDistance}
								</p>
							{/if}
						</div>

						<!-- Target race date -->
						<div>
							<label for="race-date" class="block text-sm font-medium text-gray-700">
								Target race date <span class="text-red-500" aria-hidden="true">*</span>
							</label>
							<input
								id="race-date"
								type="date"
								bind:value={raceDate}
								min={new Date(Date.now() + 86400000).toISOString().split('T')[0]}
								class="mt-1 block w-full rounded-lg border px-3 py-2 text-sm shadow-sm transition-colors
								       focus:outline-none focus:ring-2 focus:ring-blue-500
								       {step2Errors.raceDate ? 'border-red-400 bg-red-50' : 'border-gray-300 bg-white'}"
								aria-required="true"
								aria-describedby={step2Errors.raceDate ? 'race-date-error' : undefined}
								aria-invalid={!!step2Errors.raceDate}
							/>
							{#if step2Errors.raceDate}
								<p id="race-date-error" class="mt-1 text-xs text-red-600" role="alert">
									{step2Errors.raceDate}
								</p>
							{/if}
						</div>

						<!-- Race label -->
						<div>
							<label for="race-label" class="block text-sm font-medium text-gray-700">
								Race name <span class="text-gray-400 font-normal">(optional)</span>
							</label>
							<input
								id="race-label"
								type="text"
								bind:value={raceLabel}
								maxlength="100"
								placeholder="e.g. London Marathon 2026"
								class="mt-1 block w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm shadow-sm
								       focus:outline-none focus:ring-2 focus:ring-blue-500"
							/>
						</div>
					</div>
				</div>

			<!-- ============================================================== -->
			<!-- STEP 3 — Fitness Data                                           -->
			<!-- ============================================================== -->
			{:else if currentStep === 3}
				<div class="p-6 sm:p-8">
					<h2 class="mb-1 text-lg font-semibold text-gray-900">Fitness Baseline</h2>
					<p class="mb-6 text-sm text-gray-500">
						Upload your Strava data export to auto-populate your fitness baseline, or enter manually
						below.
					</p>

					<!-- Strava bulk import -->
					<div class="mb-6 rounded-xl border border-gray-200 bg-gray-50 p-4">
						<div class="flex items-start gap-3">
							<span class="mt-0.5 text-xl shrink-0" aria-hidden="true">📦</span>
							<div class="flex-1 min-w-0">
								<p class="text-sm font-medium text-gray-800">Strava Data Export</p>
								<p class="mt-0.5 text-xs text-gray-500">
									Export your data from Strava (Settings → My Account → Download or Delete Your Data)
									and upload the ZIP file here.
								</p>

								<!-- File input -->
								<div class="mt-3">
									<label for="strava-zip" class="sr-only">Upload Strava export ZIP</label>
									<input
										id="strava-zip"
										type="file"
										accept=".zip"
										on:change={handleFileChange}
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

								<!-- Upload button -->
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
											<span
												class="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white"
												aria-hidden="true"
											></span>
											Uploading…
										{:else}
											Upload
										{/if}
									</button>
								{/if}

								<!-- Upload error -->
								{#if bulkImportError}
									<div
										class="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700"
										role="alert"
									>
										{bulkImportError}
									</div>
								{/if}

								<!-- Import summary -->
								{#if bulkImportResult}
									<div
										class="mt-3 rounded-lg border border-green-200 bg-green-50 p-3 text-xs text-green-800"
										role="status"
										aria-live="polite"
									>
										<p class="font-semibold text-green-900 mb-1">✅ Import successful!</p>
										<ul class="space-y-0.5">
											<li>Imported: <strong>{bulkImportResult.imported}</strong> activities</li>
											<li>Skipped duplicates: <strong>{bulkImportResult.skipped_duplicates}</strong></li>
											{#if bulkImportResult.parse_errors > 0}
												<li class="text-amber-700">Parse errors: <strong>{bulkImportResult.parse_errors}</strong></li>
											{/if}
											{#if bulkImportResult.vdot !== null}
												<li>VDOT score: <strong>{formatVdot(bulkImportResult.vdot)}</strong></li>
											{/if}
											{#if bulkImportResult.pace_zones_updated}
												<li>Pace zones updated ✓</li>
											{/if}
										</ul>
										<p class="mt-2 text-green-700">
											The fields below are now optional — your fitness baseline has been set from your
											Strava data.
										</p>
									</div>
								{/if}
							</div>
						</div>
					</div>

					<!-- Manual fitness fields -->
					<div class="space-y-5">
						<div>
							<label for="weekly-km" class="block text-sm font-medium text-gray-700">
								Current weekly mileage
								{#if fitnessFieldsRequired}
									<span class="text-red-500" aria-hidden="true">*</span>
								{:else}
									<span class="text-gray-400 font-normal">(optional)</span>
								{/if}
							</label>
							<div class="mt-1 flex items-center gap-2">
								<input
									id="weekly-km"
									type="number"
									bind:value={currentWeeklyKm}
									min="0"
									step="0.1"
									placeholder="e.g. 30"
									class="block w-full rounded-lg border px-3 py-2 text-sm shadow-sm transition-colors
									       focus:outline-none focus:ring-2 focus:ring-blue-500
									       {step3Errors.currentWeeklyKm ? 'border-red-400 bg-red-50' : 'border-gray-300 bg-white'}"
									aria-required={fitnessFieldsRequired}
									aria-describedby={step3Errors.currentWeeklyKm ? 'weekly-km-error' : undefined}
									aria-invalid={!!step3Errors.currentWeeklyKm}
								/>
								<span class="shrink-0 text-sm text-gray-500">km / week</span>
							</div>
							{#if step3Errors.currentWeeklyKm}
								<p id="weekly-km-error" class="mt-1 text-xs text-red-600" role="alert">
									{step3Errors.currentWeeklyKm}
								</p>
							{/if}
						</div>

						<div>
							<label for="longest-run" class="block text-sm font-medium text-gray-700">
								Longest recent run
								{#if fitnessFieldsRequired}
									<span class="text-red-500" aria-hidden="true">*</span>
								{:else}
									<span class="text-gray-400 font-normal">(optional)</span>
								{/if}
							</label>
							<div class="mt-1 flex items-center gap-2">
								<input
									id="longest-run"
									type="number"
									bind:value={longestRecentRunKm}
									min="0.1"
									step="0.1"
									placeholder="e.g. 15"
									class="block w-full rounded-lg border px-3 py-2 text-sm shadow-sm transition-colors
									       focus:outline-none focus:ring-2 focus:ring-blue-500
									       {step3Errors.longestRecentRunKm ? 'border-red-400 bg-red-50' : 'border-gray-300 bg-white'}"
									aria-required={fitnessFieldsRequired}
									aria-describedby={step3Errors.longestRecentRunKm ? 'longest-run-error' : undefined}
									aria-invalid={!!step3Errors.longestRecentRunKm}
								/>
								<span class="shrink-0 text-sm text-gray-500">km</span>
							</div>
							{#if step3Errors.longestRecentRunKm}
								<p id="longest-run-error" class="mt-1 text-xs text-red-600" role="alert">
									{step3Errors.longestRecentRunKm}
								</p>
							{/if}
						</div>
					</div>
				</div>

			<!-- ============================================================== -->
			<!-- STEP 4 — Generating Plan (loading screen)                       -->
			<!-- ============================================================== -->
			{:else if currentStep === 4}
				<div class="p-8 text-center">
					{#if planGenerating}
						<div
							class="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-blue-50"
							role="status"
							aria-live="polite"
						>
							<div
								class="h-10 w-10 animate-spin rounded-full border-4 border-blue-200 border-t-blue-600"
								aria-hidden="true"
							></div>
						</div>
						<h2 class="text-lg font-semibold text-gray-900">Creating your training plan…</h2>
						<p class="mt-2 text-sm text-gray-500">
							Your AI coach is building a personalised plan. This may take a moment.
						</p>
					{:else if planError}
						<div
							class="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-red-50"
						>
							<span class="text-3xl" aria-hidden="true">⚠️</span>
						</div>
						<h2 class="text-lg font-semibold text-gray-900">Plan generation failed</h2>
						<p
							class="mt-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
							role="alert"
						>
							{planError}
						</p>
						<button
							type="button"
							on:click={retryPlanGeneration}
							class="mt-4 inline-flex items-center gap-2 rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-medium text-white
							       hover:bg-blue-700 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500"
						>
							↻ Retry
						</button>
					{/if}
				</div>
			{/if}

			<!-- ============================================================== -->
			<!-- Navigation buttons (steps 1–3)                                  -->
			<!-- ============================================================== -->
			{#if currentStep <= 3}
				<div
					class="flex items-center justify-between border-t border-gray-100 px-6 py-4 sm:px-8"
				>
					{#if currentStep > 1}
						<button
							type="button"
							on:click={goBack}
							class="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700
							       hover:bg-gray-50 transition-colors focus:outline-none focus:ring-2 focus:ring-gray-400"
						>
							← Back
						</button>
					{:else}
						<div></div>
					{/if}

					<button
						type="button"
						on:click={goNext}
						class="rounded-lg bg-blue-600 px-5 py-2 text-sm font-medium text-white
						       hover:bg-blue-700 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500"
					>
						{currentStep === 3 ? 'Create Plan →' : 'Next →'}
					</button>
				</div>
			{/if}

		</div>
		<!-- /card -->

	</div>
</div>
