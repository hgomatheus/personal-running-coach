<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { activeProfile } from '$lib/stores';
	import {
		workoutsApi,
		routesApi,
		type Workout,
		type WorkoutStep,
		type WeatherForecast,
		type RouteRecord
	} from '$lib/api';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let loading = true;
	let error: string | null = null;
	let workout: Workout | null = null;
	let weather: WeatherForecast | null = null;
	let routes: RouteRecord[] = [];

	// RPE modal state
	let showRpeModal = false;
	let selectedRpe: number | null = null;
	let submittingRpe = false;
	let rpeError: string | null = null;

	// Garmin download state
	let downloadingFit = false;
	let fitError: string | null = null;
	let showGarminModal = false;

	// Mark complete/skip state
	let markingStatus: 'completed' | 'skipped' | null = null;
	let statusError: string | null = null;

	// ---------------------------------------------------------------------------
	// Workout type helpers (matching plan page colour coding)
	// ---------------------------------------------------------------------------

	const WORKOUT_TYPE_LABELS: Record<string, string> = {
		easy: 'Easy',
		tempo: 'Tempo',
		interval: 'Intervals',
		hills: 'Hills',
		long: 'Long Run',
		race: 'Race',
		rest: 'Rest',
		recovery: 'Recovery'
	};

	function workoutTypeColor(type: string): string {
		const colors: Record<string, string> = {
			easy: 'bg-green-100 text-green-800 border-green-200',
			tempo: 'bg-orange-100 text-orange-800 border-orange-200',
			interval: 'bg-red-100 text-red-800 border-red-200',
			hills: 'bg-purple-100 text-purple-800 border-purple-200',
			long: 'bg-blue-100 text-blue-800 border-blue-200',
			race: 'bg-yellow-100 text-yellow-800 border-yellow-200',
			rest: 'bg-gray-100 text-gray-500 border-gray-200',
			recovery: 'bg-emerald-100 text-emerald-700 border-emerald-200'
		};
		return colors[type] ?? 'bg-gray-100 text-gray-700 border-gray-200';
	}

	function workoutTypeLabel(type: string): string {
		return WORKOUT_TYPE_LABELS[type] ?? type;
	}

	// ---------------------------------------------------------------------------
	// RPE scale labels
	// ---------------------------------------------------------------------------

	const RPE_LABELS: Record<number, string> = {
		1: 'Very Easy',
		2: 'Easy',
		3: 'Moderate',
		4: 'Somewhat Hard',
		5: 'Hard',
		6: 'Hard',
		7: 'Very Hard',
		8: 'Very Hard',
		9: 'Very Hard',
		10: 'Maximum'
	};

	// ---------------------------------------------------------------------------
	// Formatting helpers
	// ---------------------------------------------------------------------------

	function formatDistanceKm(metres: number | null | undefined): string {
		if (metres == null) return '—';
		return `${(metres / 1000).toFixed(1)} km`;
	}

	function formatDuration(seconds: number | null | undefined): string {
		if (seconds == null) return '—';
		const h = Math.floor(seconds / 3600);
		const m = Math.floor((seconds % 3600) / 60);
		const s = seconds % 60;
		if (h > 0) return `${h}h ${m}m`;
		if (m > 0) return `${m}m ${s > 0 ? `${s}s` : ''}`.trim();
		return `${s}s`;
	}

	function formatDate(dateStr: string | null | undefined): string {
		if (!dateStr) return '—';
		return new Date(dateStr).toLocaleDateString(undefined, {
			weekday: 'long',
			day: 'numeric',
			month: 'long',
			year: 'numeric'
		});
	}

	function formatPaceZone(zone: string | null | undefined): string {
		if (!zone) return '—';
		return zone.charAt(0).toUpperCase() + zone.slice(1);
	}

	function weatherConditionIcon(conditions: string): string {
		const c = conditions.toLowerCase();
		if (c.includes('rain') || c.includes('drizzle')) return '🌧️';
		if (c.includes('snow')) return '❄️';
		if (c.includes('thunder') || c.includes('storm')) return '⛈️';
		if (c.includes('cloud')) return '☁️';
		if (c.includes('clear') || c.includes('sunny')) return '☀️';
		if (c.includes('wind')) return '💨';
		if (c.includes('fog') || c.includes('mist')) return '🌫️';
		return '🌤️';
	}

	// ---------------------------------------------------------------------------
	// Step grouping for Intervals / Hills (task 19.2)
	// ---------------------------------------------------------------------------

	interface StepGroup {
		isRepeat: boolean;
		repeatLabel: string | null;
		repeatCount: number;
		steps: WorkoutStep[];
	}

	/**
	 * Groups steps into repeat blocks for Intervals/Hills workouts.
	 * Detects patterns like "Interval 1", "Interval 2", "Hill 1", "Hill 2" etc.
	 * Non-repeating steps (warmup, cooldown, recovery) are kept as individual groups.
	 */
	function groupSteps(steps: WorkoutStep[], workoutType: string): StepGroup[] {
		if (workoutType !== 'interval' && workoutType !== 'hills') {
			// For other types, each step is its own group
			return steps.map((s) => ({
				isRepeat: false,
				repeatLabel: null,
				repeatCount: 1,
				steps: [s]
			}));
		}

		// Detect numbered repeat steps: label matches "Word N" pattern
		const repeatPattern = /^(.+?)\s+(\d+)$/;

		// Group consecutive steps with the same base label
		const groups: StepGroup[] = [];
		let i = 0;

		while (i < steps.length) {
			const step = steps[i];
			const match = step.label.match(repeatPattern);

			if (match) {
				const baseLabel = match[1];
				// Collect all consecutive steps with the same base label
				const repeatSteps: WorkoutStep[] = [step];
				let j = i + 1;
				while (j < steps.length) {
					const nextMatch = steps[j].label.match(repeatPattern);
					if (nextMatch && nextMatch[1] === baseLabel) {
						repeatSteps.push(steps[j]);
						j++;
					} else {
						break;
					}
				}

				if (repeatSteps.length > 1) {
					groups.push({
						isRepeat: true,
						repeatLabel: baseLabel,
						repeatCount: repeatSteps.length,
						steps: repeatSteps
					});
					i = j;
				} else {
					// Single numbered step — treat as non-repeat
					groups.push({ isRepeat: false, repeatLabel: null, repeatCount: 1, steps: [step] });
					i++;
				}
			} else {
				groups.push({ isRepeat: false, repeatLabel: null, repeatCount: 1, steps: [step] });
				i++;
			}
		}

		return groups;
	}

	$: stepGroups = workout ? groupSteps(workout.steps ?? [], workout.workout_type) : [];

	// ---------------------------------------------------------------------------
	// Mark complete / skip (task 19.3 — RPE modal shown after complete)
	// ---------------------------------------------------------------------------

	async function markWorkout(status: 'completed' | 'skipped') {
		if (!workout) return;
		markingStatus = status;
		statusError = null;
		try {
			const updated = await workoutsApi.patch(workout.id, { status }, $activeProfile);
			workout = updated;
			if (status === 'completed') {
				// Show RPE modal after marking complete
				selectedRpe = null;
				rpeError = null;
				showRpeModal = true;
			}
		} catch (e) {
			statusError = 'Failed to update workout status. Please try again.';
		} finally {
			markingStatus = null;
		}
	}

	async function submitRpe() {
		if (!workout || selectedRpe === null) return;
		submittingRpe = true;
		rpeError = null;
		try {
			const updated = await workoutsApi.patch(workout.id, { rpe_score: selectedRpe }, $activeProfile);
			workout = updated;
			showRpeModal = false;
		} catch (e) {
			rpeError = 'Failed to save RPE. Please try again.';
		} finally {
			submittingRpe = false;
		}
	}

	function closeRpeModal() {
		if (submittingRpe) return;
		showRpeModal = false;
	}

	// ---------------------------------------------------------------------------
	// Garmin FIT download (task 19.4)
	// ---------------------------------------------------------------------------

	async function downloadFit() {
		if (!workout) return;
		downloadingFit = true;
		fitError = null;
		try {
			const url = workoutsApi.exportFit(workout.id, $activeProfile);
			const res = await fetch(url);
			if (!res.ok) {
				throw new Error(`HTTP ${res.status}`);
			}
			const blob = await res.blob();
			const blobUrl = URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = blobUrl;
			a.download = `${workout.workout_type}_${workout.scheduled_date ?? 'workout'}.fit`;
			document.body.appendChild(a);
			a.click();
			document.body.removeChild(a);
			URL.revokeObjectURL(blobUrl);
			// Show transfer instructions modal
			showGarminModal = true;
		} catch (e) {
			fitError = 'Failed to download FIT file. Please try again.';
		} finally {
			downloadingFit = false;
		}
	}

	function closeGarminModal() {
		showGarminModal = false;
	}

	// ---------------------------------------------------------------------------
	// Data loading
	// ---------------------------------------------------------------------------

	async function loadWorkout(workoutId: number, profileId: number) {
		loading = true;
		error = null;
		workout = null;
		weather = null;
		routes = [];

		try {
			workout = await workoutsApi.get(workoutId, profileId);

			// Load weather and routes in parallel (both optional)
			const [weatherResult, routesResult] = await Promise.allSettled([
				workoutsApi.getWeather(workoutId, profileId),
				routesApi.getSuggestions(workoutId, profileId)
			]);

			if (weatherResult.status === 'fulfilled') {
				weather = weatherResult.value;
			}
			if (routesResult.status === 'fulfilled') {
				routes = routesResult.value.slice(0, 3);
			}
		} catch (e) {
			error = 'Failed to load workout. Please try again.';
		} finally {
			loading = false;
		}
	}

	// ---------------------------------------------------------------------------
	// Lifecycle
	// ---------------------------------------------------------------------------

	onMount(() => {
		const idParam = $page.params.id;
		const workoutId = parseInt(idParam, 10);
		if (isNaN(workoutId)) {
			error = 'Invalid workout ID.';
			loading = false;
			return;
		}
		loadWorkout(workoutId, $activeProfile);
	});
</script>

<!-- =========================================================================
     Template
     ========================================================================= -->

<div class="p-4 sm:p-6 max-w-3xl mx-auto space-y-6">

	<!-- Back link -->
	<a
		href="/plan"
		class="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 transition-colors"
		aria-label="Back to training plan"
	>
		← Back to Plan
	</a>

	<!-- Loading state -->
	{#if loading}
		<div class="flex items-center justify-center py-20" role="status" aria-live="polite">
			<div class="flex flex-col items-center gap-3 text-gray-500">
				<div
					class="h-8 w-8 animate-spin rounded-full border-4 border-gray-200 border-t-blue-600"
					aria-hidden="true"
				></div>
				<span class="text-sm">Loading workout…</span>
			</div>
		</div>

	<!-- Error state -->
	{:else if error}
		<div
			class="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700"
			role="alert"
		>
			{error}
		</div>

	{:else if workout}
		<!-- ===================================================================
		     Workout Header (task 19.1)
		     =================================================================== -->
		<div class="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
			<!-- Type banner -->
			<div
				class="px-5 py-3 border-b border-gray-100 flex items-center justify-between gap-3 flex-wrap"
			>
				<div class="flex items-center gap-3">
					<span
						class="inline-flex items-center rounded-full border px-3 py-1 text-sm font-semibold {workoutTypeColor(workout.workout_type)}"
					>
						{workoutTypeLabel(workout.workout_type)}
					</span>
					<span class="text-sm text-gray-500">{formatDate(workout.scheduled_date)}</span>
				</div>

				<!-- Weather badge (task 19.1) -->
				{#if weather}
					<div
						class="flex items-center gap-1.5 rounded-lg bg-sky-50 border border-sky-100 px-3 py-1.5"
						aria-label="Weather: {weather.conditions}, {Math.round(weather.temperature_c)}°C"
						title="{weather.conditions} · {Math.round(weather.temperature_c)}°C · {weather.wind_kmh} km/h wind"
					>
						<span class="text-lg leading-none" aria-hidden="true">
							{weatherConditionIcon(weather.conditions)}
						</span>
						<div class="text-xs">
							<span class="font-semibold text-sky-700">{Math.round(weather.temperature_c)}°C</span>
							<span class="text-sky-600 ml-1">{weather.conditions}</span>
							{#if weather.wind_kmh > 0}
								<span class="text-sky-500 ml-1">· {weather.wind_kmh} km/h</span>
							{/if}
						</div>
						{#if weather.advisories.length > 0}
							<span class="text-amber-500 text-sm" aria-label="Weather advisory">⚠️</span>
						{/if}
					</div>
				{/if}
			</div>

			<!-- Stats row -->
			<div class="grid grid-cols-2 sm:grid-cols-4 divide-x divide-y sm:divide-y-0 divide-gray-100">
				<div class="px-5 py-4">
					<p class="text-xs font-medium uppercase tracking-wide text-gray-400">Distance</p>
					<p class="mt-1 text-xl font-bold text-gray-900">
						{formatDistanceKm(workout.target_distance_metres)}
					</p>
				</div>
				<div class="px-5 py-4">
					<p class="text-xs font-medium uppercase tracking-wide text-gray-400">Est. Duration</p>
					<p class="mt-1 text-xl font-bold text-gray-900">
						{formatDuration(workout.estimated_duration_seconds)}
					</p>
				</div>
				<div class="px-5 py-4">
					<p class="text-xs font-medium uppercase tracking-wide text-gray-400">Pace Zone</p>
					<p class="mt-1 text-xl font-bold text-gray-900">
						{formatPaceZone(workout.target_pace_zone)}
					</p>
				</div>
				<div class="px-5 py-4">
					<p class="text-xs font-medium uppercase tracking-wide text-gray-400">HR Zone</p>
					<p class="mt-1 text-xl font-bold text-gray-900">
						{workout.target_hr_zone != null ? `Zone ${workout.target_hr_zone}` : '—'}
					</p>
				</div>
			</div>

			<!-- Status + actions row -->
			<div class="px-5 py-3 border-t border-gray-100 bg-gray-50 flex items-center justify-between gap-3 flex-wrap">
				<div class="flex items-center gap-2">
					<span
						class="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium
						{workout.status === 'completed' ? 'bg-green-100 text-green-800' :
						 workout.status === 'skipped' ? 'bg-gray-100 text-gray-600' :
						 workout.status === 'missed' ? 'bg-red-100 text-red-700' :
						 'bg-blue-100 text-blue-700'}"
					>
						{workout.status.charAt(0).toUpperCase() + workout.status.slice(1)}
					</span>
					{#if workout.rpe_score != null}
						<span class="text-xs text-gray-500">
							RPE {workout.rpe_score}/10 — {RPE_LABELS[workout.rpe_score] ?? ''}
						</span>
					{/if}
				</div>

				{#if workout.status === 'scheduled'}
					<div class="flex items-center gap-2">
						<button
							on:click={() => markWorkout('completed')}
							disabled={markingStatus !== null}
							class="inline-flex items-center gap-1.5 rounded-lg bg-green-600 px-3 py-1.5 text-xs font-medium text-white
							       hover:bg-green-700 transition-colors focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-2
							       disabled:opacity-50 disabled:cursor-not-allowed"
						>
							{#if markingStatus === 'completed'}
								<span class="h-3 w-3 animate-spin rounded-full border-2 border-white/30 border-t-white" aria-hidden="true"></span>
								Marking…
							{:else}
								✓ Mark Complete
							{/if}
						</button>
						<button
							on:click={() => markWorkout('skipped')}
							disabled={markingStatus !== null}
							class="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700
							       hover:bg-gray-50 transition-colors focus:outline-none focus:ring-2 focus:ring-gray-400 focus:ring-offset-2
							       disabled:opacity-50 disabled:cursor-not-allowed"
						>
							Skip
						</button>
					</div>
				{/if}

				{#if statusError}
					<p class="w-full text-xs text-red-600" role="alert">{statusError}</p>
				{/if}
			</div>
		</div>

		<!-- ===================================================================
		     Session Structure (tasks 19.1 + 19.2)
		     =================================================================== -->

		{#if workout.workout_type === 'rest'}
			<!-- Rest day indicator (task 19.2) -->
			<div
				class="rounded-xl border border-gray-200 bg-white shadow-sm p-8 text-center"
				role="region"
				aria-label="Rest day"
			>
				<div class="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-gray-100">
					<span class="text-3xl" aria-hidden="true">😴</span>
				</div>
				<h2 class="text-lg font-semibold text-gray-700">Rest Day</h2>
				<p class="mt-1 text-sm text-gray-500">
					Recovery is part of training. Take it easy today.
				</p>
			</div>

		{:else if workout.steps && workout.steps.length > 0}
			<section aria-label="Session structure">
				<h2 class="text-base font-semibold text-gray-900 mb-3">Session Structure</h2>

				<div class="space-y-3">
					{#each stepGroups as group, gi (gi)}
						{#if group.isRepeat}
							<!-- Repeat block (Intervals / Hills) -->
							<div class="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
								<!-- Repeat header -->
								<div class="flex items-center gap-2 px-4 py-2.5 bg-gray-50 border-b border-gray-100">
									<span class="text-sm font-semibold text-gray-700">
										{group.repeatLabel}
									</span>
									<span class="rounded-full bg-indigo-100 px-2 py-0.5 text-xs font-medium text-indigo-700">
										× {group.repeatCount}
									</span>
									<span class="text-xs text-gray-400 ml-auto">
										{formatDistanceKm(group.steps[0].distance_metres)} each
									</span>
								</div>
								<!-- Individual repeat steps -->
								<div class="divide-y divide-gray-50">
									{#each group.steps as step (step.sequence)}
										<div class="flex items-start gap-3 px-4 py-3">
											<span
												class="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-xs font-bold text-indigo-700"
												aria-hidden="true"
											>
												{step.sequence}
											</span>
											<div class="min-w-0 flex-1">
												<div class="flex items-center gap-2 flex-wrap">
													<span class="text-sm font-medium text-gray-900">{step.label}</span>
													<span class="text-xs text-gray-500">{formatDistanceKm(step.distance_metres)}</span>
													{#if step.pace_zone}
														<span class="rounded-full bg-blue-50 border border-blue-100 px-1.5 py-0.5 text-xs text-blue-700">
															{formatPaceZone(step.pace_zone)}
														</span>
													{/if}
													{#if step.hr_zone != null}
														<span class="rounded-full bg-red-50 border border-red-100 px-1.5 py-0.5 text-xs text-red-700">
															HR Z{step.hr_zone}
														</span>
													{/if}
													{#if step.estimated_duration_seconds}
														<span class="text-xs text-gray-400">~{formatDuration(step.estimated_duration_seconds)}</span>
													{/if}
												</div>
												{#if step.description}
													<p class="mt-1 text-xs text-gray-500">{step.description}</p>
												{/if}
											</div>
										</div>
									{/each}
								</div>
							</div>

						{:else}
							<!-- Single step -->
							{@const step = group.steps[0]}
							<div class="rounded-xl border border-gray-200 bg-white shadow-sm">
								<div class="flex items-start gap-3 px-4 py-3.5">
									<span
										class="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-gray-100 text-xs font-bold text-gray-600"
										aria-hidden="true"
									>
										{step.sequence}
									</span>
									<div class="min-w-0 flex-1">
										<div class="flex items-center gap-2 flex-wrap">
											<span class="text-sm font-semibold text-gray-900">{step.label}</span>
											<span class="text-xs text-gray-500">{formatDistanceKm(step.distance_metres)}</span>
											{#if step.pace_zone}
												<span class="rounded-full bg-blue-50 border border-blue-100 px-1.5 py-0.5 text-xs text-blue-700">
													{formatPaceZone(step.pace_zone)}
												</span>
											{/if}
											{#if step.hr_zone != null}
												<span class="rounded-full bg-red-50 border border-red-100 px-1.5 py-0.5 text-xs text-red-700">
													HR Z{step.hr_zone}
												</span>
											{/if}
											{#if step.estimated_duration_seconds}
												<span class="text-xs text-gray-400">~{formatDuration(step.estimated_duration_seconds)}</span>
											{/if}
										</div>
										{#if step.description}
											<p class="mt-1 text-xs text-gray-500">{step.description}</p>
										{/if}
									</div>
								</div>
							</div>
						{/if}
					{/each}
				</div>
			</section>
		{/if}

		<!-- ===================================================================
		     Coaching Note (task 19.1 — weather advisory appended if applicable)
		     =================================================================== -->
		{#if workout.coaching_note || (weather && weather.advisories.length > 0)}
			<section
				class="rounded-xl border border-amber-100 bg-amber-50 p-4"
				aria-label="Coaching note"
			>
				<div class="flex items-start gap-3">
					<span class="text-xl shrink-0" aria-hidden="true">💬</span>
					<div class="space-y-2">
						{#if workout.coaching_note}
							<p class="text-sm text-amber-900">{workout.coaching_note}</p>
						{/if}
						{#if weather && weather.advisories.length > 0}
							<div class="space-y-1">
								{#each weather.advisories as advisory (advisory)}
									<p class="text-sm text-amber-800 flex items-start gap-1.5">
										<span aria-hidden="true">⚠️</span>
										{advisory}
									</p>
								{/each}
							</div>
						{/if}
					</div>
				</div>
			</section>
		{/if}

		<!-- ===================================================================
		     Download for Garmin (task 19.4)
		     =================================================================== -->
		{#if workout.workout_type !== 'rest'}
			<section aria-label="Garmin export">
				<button
					on:click={downloadFit}
					disabled={downloadingFit}
					class="inline-flex items-center gap-2 rounded-lg border border-indigo-200 bg-indigo-50 px-4 py-2.5 text-sm font-medium text-indigo-700
					       hover:bg-indigo-100 hover:border-indigo-300 transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2
					       disabled:opacity-50 disabled:cursor-not-allowed"
				>
					{#if downloadingFit}
						<span class="h-4 w-4 animate-spin rounded-full border-2 border-indigo-300 border-t-indigo-700" aria-hidden="true"></span>
						Downloading…
					{:else}
						<span aria-hidden="true">⌚</span>
						Download for Garmin
					{/if}
				</button>
				{#if fitError}
					<p class="mt-2 text-xs text-red-600" role="alert">{fitError}</p>
				{/if}
			</section>
		{/if}

		<!-- ===================================================================
		     Route Suggestions (task 19.5)
		     =================================================================== -->
		{#if routes.length > 0}
			<section aria-label="Route suggestions">
				<h2 class="text-base font-semibold text-gray-900 mb-3">Suggested Routes</h2>
				<div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
					{#each routes as route (route.id)}
						<div
							class="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden"
							role="article"
							aria-label="Route: {route.typical_distance_km.toFixed(1)} km, run {route.run_count} times"
						>
							<!-- Map thumbnail -->
							{#if route.thumbnail_url}
								<div class="aspect-video bg-gray-100 overflow-hidden">
									<img
										src={route.thumbnail_url}
										alt="Map thumbnail for {route.typical_distance_km.toFixed(1)} km route"
										class="w-full h-full object-cover"
										loading="lazy"
									/>
								</div>
							{:else}
								<div
									class="aspect-video bg-gradient-to-br from-gray-100 to-gray-200 flex items-center justify-center"
									aria-hidden="true"
								>
									<span class="text-3xl">🗺️</span>
								</div>
							{/if}

							<!-- Route info -->
							<div class="px-3 py-2.5">
								<p class="text-sm font-semibold text-gray-900">
									{route.typical_distance_km.toFixed(1)} km
								</p>
								<p class="text-xs text-gray-500 mt-0.5">
									Run {route.run_count} {route.run_count === 1 ? 'time' : 'times'}
								</p>
								{#if route.workout_type_affinity}
									<span class="mt-1.5 inline-block rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
										{workoutTypeLabel(route.workout_type_affinity)}
									</span>
								{/if}
							</div>
						</div>
					{/each}
				</div>
			</section>
		{/if}

	{/if}
</div>

<!-- =============================================================================
     RPE Logging Modal (task 19.3)
     ============================================================================= -->
{#if showRpeModal}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
		role="dialog"
		aria-modal="true"
		aria-labelledby="rpe-modal-title"
		on:click|self={closeRpeModal}
		on:keydown={(e) => e.key === 'Escape' && closeRpeModal()}
	>
		<div class="w-full max-w-md rounded-xl bg-white shadow-xl">
			<!-- Modal header -->
			<div class="px-6 pt-6 pb-2">
				<h2 id="rpe-modal-title" class="text-lg font-semibold text-gray-900">
					How hard was that? 💪
				</h2>
				<p class="mt-1 text-sm text-gray-500">
					Rate your perceived exertion (RPE) for this workout.
				</p>
			</div>

			<!-- RPE scale -->
			<div class="px-6 py-4">
				<div class="grid grid-cols-5 gap-2" role="radiogroup" aria-label="RPE scale 1 to 10">
					{#each [1, 2, 3, 4, 5, 6, 7, 8, 9, 10] as rpe (rpe)}
						<button
							role="radio"
							aria-checked={selectedRpe === rpe}
							on:click={() => (selectedRpe = rpe)}
							class="flex flex-col items-center gap-1 rounded-lg border-2 p-2 transition-all focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1
							{selectedRpe === rpe
								? 'border-blue-500 bg-blue-50 text-blue-700'
								: 'border-gray-200 bg-white text-gray-700 hover:border-gray-300 hover:bg-gray-50'}"
						>
							<span class="text-lg font-bold leading-none">{rpe}</span>
							<span class="text-center text-xs leading-tight text-gray-500" style="font-size: 0.6rem;">
								{RPE_LABELS[rpe]}
							</span>
						</button>
					{/each}
				</div>

				{#if selectedRpe !== null}
					<p class="mt-3 text-center text-sm font-medium text-blue-700">
						{selectedRpe}/10 — {RPE_LABELS[selectedRpe]}
					</p>
				{/if}

				{#if rpeError}
					<p class="mt-2 text-sm text-red-600 text-center" role="alert">{rpeError}</p>
				{/if}
			</div>

			<!-- Modal footer -->
			<div class="flex justify-end gap-3 border-t border-gray-100 px-6 py-4">
				<button
					on:click={closeRpeModal}
					disabled={submittingRpe}
					class="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700
					       hover:bg-gray-50 transition-colors focus:outline-none focus:ring-2 focus:ring-gray-400 focus:ring-offset-2
					       disabled:opacity-50 disabled:cursor-not-allowed"
				>
					Skip
				</button>
				<button
					on:click={submitRpe}
					disabled={selectedRpe === null || submittingRpe}
					class="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white
					       hover:bg-blue-700 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2
					       disabled:opacity-50 disabled:cursor-not-allowed"
				>
					{#if submittingRpe}
						<span class="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" aria-hidden="true"></span>
						Saving…
					{:else}
						Save RPE
					{/if}
				</button>
			</div>
		</div>
	</div>
{/if}

<!-- =============================================================================
     Garmin Transfer Instructions Modal (task 19.4)
     ============================================================================= -->
{#if showGarminModal}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
		role="dialog"
		aria-modal="true"
		aria-labelledby="garmin-modal-title"
		on:click|self={closeGarminModal}
		on:keydown={(e) => e.key === 'Escape' && closeGarminModal()}
	>
		<div class="w-full max-w-md rounded-xl bg-white shadow-xl">
			<!-- Modal header -->
			<div class="px-6 pt-6 pb-2">
				<div class="flex items-center gap-3">
					<span class="text-2xl" aria-hidden="true">⌚</span>
					<h2 id="garmin-modal-title" class="text-lg font-semibold text-gray-900">
						Transfer to Forerunner 970
					</h2>
				</div>
			</div>

			<!-- Instructions -->
			<div class="px-6 py-4">
				<p class="text-sm text-gray-600 mb-4">
					Your FIT file has been downloaded. Follow these steps to transfer it to your Garmin:
				</p>
				<ol class="space-y-3" aria-label="Transfer instructions">
					<li class="flex items-start gap-3">
						<span
							class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-xs font-bold text-indigo-700"
							aria-hidden="true"
						>1</span>
						<span class="text-sm text-gray-700">
							Connect your <strong>Forerunner 970</strong> to your computer via USB
						</span>
					</li>
					<li class="flex items-start gap-3">
						<span
							class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-xs font-bold text-indigo-700"
							aria-hidden="true"
						>2</span>
						<span class="text-sm text-gray-700">
							Copy the downloaded <code class="rounded bg-gray-100 px-1 py-0.5 text-xs font-mono">.fit</code> file to
							<code class="rounded bg-gray-100 px-1 py-0.5 text-xs font-mono">GARMIN/NEWFILES</code>
						</span>
					</li>
					<li class="flex items-start gap-3">
						<span
							class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-xs font-bold text-indigo-700"
							aria-hidden="true"
						>3</span>
						<span class="text-sm text-gray-700">
							Safely eject the device — the workout will appear in your training calendar
						</span>
					</li>
				</ol>
			</div>

			<!-- Modal footer -->
			<div class="flex justify-end border-t border-gray-100 px-6 py-4">
				<button
					on:click={closeGarminModal}
					class="rounded-lg bg-indigo-600 px-5 py-2 text-sm font-medium text-white
					       hover:bg-indigo-700 transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2"
				>
					Got it
				</button>
			</div>
		</div>
	</div>
{/if}
