<script lang="ts">
	import { goto } from '$app/navigation';
	import { runsApi, statsApi, type RunCreate, type PersonalRecord } from '$lib/api';
	import { validateRunForm, parseDuration, isValid } from '$lib/runFormValidation';

	// ---------------------------------------------------------------------------
	// Form state
	// ---------------------------------------------------------------------------

	let date = new Date().toISOString().split('T')[0]; // default to today
	let distanceKm = '';
	let duration = ''; // accepts mm:ss or hh:mm:ss
	let avgHeartRate = '';
	let notes = '';

	let submitting = false;
	let submitError: string | null = null;

	// PR celebration state
	let newPRs: PersonalRecord[] = [];
	let showPRBanner = false;

	// Field-level errors
	let errors: Record<string, string> = {};

	// ---------------------------------------------------------------------------
	// Validation
	// ---------------------------------------------------------------------------

	function validate(): boolean {
		errors = validateRunForm({ date, distanceKm, duration, avgHeartRate, notes });
		return isValid(errors);
	}

	// ---------------------------------------------------------------------------
	// Submission
	// ---------------------------------------------------------------------------

	async function handleSubmit() {
		if (!validate()) return;

		submitting = true;
		submitError = null;

		try {
			const km = parseFloat(distanceKm);
			const secs = parseDuration(duration)!;
			const hr = avgHeartRate.trim() !== '' ? parseInt(avgHeartRate, 10) : null;

			const body: RunCreate = {
				date,
				distance_metres: Math.round(km * 1000 * 100) / 100, // preserve precision
				duration_seconds: secs,
				avg_heart_rate: hr,
				notes: notes.trim() || null
			};

			// Snapshot PRs before saving so we can detect new ones
			let previousPRs: PersonalRecord[] = [];
			try {
				const prevResponse = await statsApi.prs();
				previousPRs = prevResponse.records;
			} catch {
				// Non-fatal — proceed without PR comparison
			}

			await runsApi.create(body);

			// Fetch updated PRs and compare
			try {
				const updatedResponse = await statsApi.prs();
				const updatedPRs = updatedResponse.records;
				newPRs = detectNewPRs(previousPRs, updatedPRs);
			} catch {
				// Non-fatal — skip PR celebration
			}

			if (newPRs.length > 0) {
				showPRBanner = true;
				// Auto-dismiss after 3 seconds then redirect
				setTimeout(() => {
					showPRBanner = false;
					goto('/runs');
				}, 3000);
			} else {
				goto('/runs');
			}
		} catch (e) {
			submitError = e instanceof Error ? e.message : 'Failed to save run. Please try again.';
		} finally {
			submitting = false;
		}
	}

	// ---------------------------------------------------------------------------
	// PR detection
	// ---------------------------------------------------------------------------

	/**
	 * Compare previous and updated PR records to find newly set personal records.
	 * A PR is "new" when the updated record has a better (lower) pace than before,
	 * or when a distance previously had no record but now does.
	 */
	function detectNewPRs(
		previous: PersonalRecord[],
		updated: PersonalRecord[]
	): PersonalRecord[] {
		const prevMap = new Map<string, PersonalRecord>();
		for (const pr of previous) {
			prevMap.set(pr.distance_label, pr);
		}

		const detected: PersonalRecord[] = [];
		for (const pr of updated) {
			if (pr.avg_pace_sec_per_km === null) continue;
			const prev = prevMap.get(pr.distance_label);
			if (!prev || prev.avg_pace_sec_per_km === null) {
				// New record for a distance that had none before
				detected.push(pr);
			} else if (pr.avg_pace_sec_per_km < prev.avg_pace_sec_per_km) {
				// Pace improved (lower sec/km = faster)
				detected.push(pr);
			}
		}
		return detected;
	}

	// ---------------------------------------------------------------------------
	// PR formatting helpers
	// ---------------------------------------------------------------------------

	function formatPace(secPerKm: number | null): string {
		if (secPerKm === null) return '';
		const mins = Math.floor(secPerKm / 60);
		const secs = Math.round(secPerKm % 60);
		return `${mins}:${secs.toString().padStart(2, '0')} /km`;
	}

	// ---------------------------------------------------------------------------
	// Helpers
	// ---------------------------------------------------------------------------

	function inputClass(field: string): string {
		const base =
			'block w-full rounded-lg border px-3 py-2 text-sm shadow-sm transition-colors ' +
			'focus:outline-none focus:ring-2 focus:ring-blue-500 ';
		return base + (errors[field] ? 'border-red-400 bg-red-50' : 'border-gray-300 bg-white');
	}
</script>

<div class="p-4 sm:p-6 lg:p-8">
	<!-- PR celebration banner -->
	{#if showPRBanner}
		<div
			class="pr-banner fixed inset-x-0 top-0 z-50 flex flex-col items-center gap-1 bg-gradient-to-r from-yellow-400 via-amber-400 to-orange-400 px-4 py-4 text-center shadow-lg"
			role="status"
			aria-live="polite"
			aria-label="New personal record achieved"
		>
			<p class="text-lg font-bold text-white drop-shadow">🏅 New Personal Record!</p>
			<ul class="flex flex-wrap justify-center gap-x-4 gap-y-1">
				{#each newPRs as pr (pr.distance_label)}
					<li class="text-sm font-semibold text-white/90">
						{pr.distance_label}
						{#if pr.avg_pace_sec_per_km !== null}
							— {formatPace(pr.avg_pace_sec_per_km)}
						{/if}
					</li>
				{/each}
			</ul>
			<p class="mt-0.5 text-xs text-white/75">Redirecting to your runs…</p>
		</div>
	{/if}

	<!-- Page header -->
	<div class="mb-6">
		<a
			href="/runs"
			class="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700 transition-colors focus:outline-none"
			aria-label="Back to run history"
		>
			← Back to runs
		</a>
		<h1 class="mt-2 text-xl font-semibold text-gray-900">Log a Run</h1>
		<p class="mt-0.5 text-sm text-gray-500">Manually record a completed run.</p>
	</div>

	<!-- Form card -->
	<div class="mx-auto max-w-lg rounded-2xl border border-gray-200 bg-white shadow-sm">
		<form
			on:submit|preventDefault={handleSubmit}
			novalidate
			aria-label="Log run form"
			class="p-6 sm:p-8"
		>
			<div class="space-y-5">

				<!-- Date -->
				<div>
					<label for="run-date" class="block text-sm font-medium text-gray-700">
						Date <span class="text-red-500" aria-hidden="true">*</span>
					</label>
					<input
						id="run-date"
						type="date"
						bind:value={date}
						max={new Date().toISOString().split('T')[0]}
						class="mt-1 {inputClass('date')}"
						aria-required="true"
						aria-describedby={errors.date ? 'run-date-error' : undefined}
						aria-invalid={!!errors.date}
					/>
					{#if errors.date}
						<p id="run-date-error" class="mt-1 text-xs text-red-600" role="alert">
							{errors.date}
						</p>
					{/if}
				</div>

				<!-- Distance -->
				<div>
					<label for="run-distance" class="block text-sm font-medium text-gray-700">
						Distance <span class="text-red-500" aria-hidden="true">*</span>
					</label>
					<div class="mt-1 flex items-center gap-2">
						<input
							id="run-distance"
							type="number"
							bind:value={distanceKm}
							min="0.01"
							step="0.01"
							placeholder="e.g. 10.5"
							class="{inputClass('distanceKm')}"
							aria-required="true"
							aria-describedby={errors.distanceKm ? 'run-distance-error' : undefined}
							aria-invalid={!!errors.distanceKm}
						/>
						<span class="shrink-0 text-sm text-gray-500">km</span>
					</div>
					{#if errors.distanceKm}
						<p id="run-distance-error" class="mt-1 text-xs text-red-600" role="alert">
							{errors.distanceKm}
						</p>
					{/if}
				</div>

				<!-- Duration -->
				<div>
					<label for="run-duration" class="block text-sm font-medium text-gray-700">
						Duration <span class="text-red-500" aria-hidden="true">*</span>
					</label>
					<input
						id="run-duration"
						type="text"
						bind:value={duration}
						placeholder="mm:ss or hh:mm:ss — e.g. 52:30"
						inputmode="numeric"
						class="mt-1 {inputClass('duration')}"
						aria-required="true"
						aria-describedby="run-duration-hint{errors.duration ? ' run-duration-error' : ''}"
						aria-invalid={!!errors.duration}
					/>
					<p id="run-duration-hint" class="mt-1 text-xs text-gray-400">
						Format: mm:ss (e.g. 52:30) or hh:mm:ss (e.g. 1:05:00)
					</p>
					{#if errors.duration}
						<p id="run-duration-error" class="mt-1 text-xs text-red-600" role="alert">
							{errors.duration}
						</p>
					{/if}
				</div>

				<!-- Average heart rate (optional) -->
				<div>
					<label for="run-hr" class="block text-sm font-medium text-gray-700">
						Average heart rate
						<span class="font-normal text-gray-400">(optional)</span>
					</label>
					<div class="mt-1 flex items-center gap-2">
						<input
							id="run-hr"
							type="number"
							bind:value={avgHeartRate}
							min="30"
							max="250"
							step="1"
							placeholder="e.g. 155"
							class="{inputClass('avgHeartRate')}"
							aria-describedby={errors.avgHeartRate ? 'run-hr-error' : 'run-hr-hint'}
							aria-invalid={!!errors.avgHeartRate}
						/>
						<span class="shrink-0 text-sm text-gray-500">bpm</span>
					</div>
					{#if errors.avgHeartRate}
						<p id="run-hr-error" class="mt-1 text-xs text-red-600" role="alert">
							{errors.avgHeartRate}
						</p>
					{:else}
						<p id="run-hr-hint" class="mt-1 text-xs text-gray-400">Between 30 and 250 bpm.</p>
					{/if}
				</div>

				<!-- Notes (optional) -->
				<div>
					<label for="run-notes" class="block text-sm font-medium text-gray-700">
						Notes
						<span class="font-normal text-gray-400">(optional)</span>
					</label>
					<textarea
						id="run-notes"
						bind:value={notes}
						rows="3"
						placeholder="How did it feel? Any observations…"
						class="mt-1 block w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm shadow-sm
						       focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
					></textarea>
				</div>

			</div>

			<!-- Submit error -->
			{#if submitError}
				<div
					class="mt-5 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
					role="alert"
				>
					{submitError}
				</div>
			{/if}

			<!-- Actions -->
			<div class="mt-6 flex items-center justify-between gap-3 border-t border-gray-100 pt-5">
				<a
					href="/runs"
					class="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700
					       hover:bg-gray-50 transition-colors focus:outline-none focus:ring-2 focus:ring-gray-400"
				>
					Cancel
				</a>
				<button
					type="submit"
					disabled={submitting}
					class="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-5 py-2 text-sm font-medium text-white
					       hover:bg-blue-700 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500
					       disabled:opacity-60 disabled:cursor-not-allowed"
					aria-busy={submitting}
				>
					{#if submitting}
						<span
							class="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white"
							aria-hidden="true"
						></span>
						Saving…
					{:else}
						Save Run
					{/if}
				</button>
			</div>
		</form>
	</div>
</div>

<style>
	/* Slide-in from top animation for the PR celebration banner */
	@keyframes slide-in-from-top {
		from {
			transform: translateY(-100%);
			opacity: 0;
		}
		to {
			transform: translateY(0);
			opacity: 1;
		}
	}

	.pr-banner {
		animation: slide-in-from-top 0.4s cubic-bezier(0.16, 1, 0.3, 1) both;
	}
</style>
