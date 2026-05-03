<script lang="ts">
	import { onMount } from 'svelte';
	import { activeProfile } from '$lib/stores';
	import {
		plansApi,
		weatherApi,
		type TrainingPlan,
		type TrainingPlanDetail,
		type WorkoutSummary,
		type WeatherForecast
	} from '$lib/api';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let loading = true;
	let error: string | null = null;

	let activePlan: TrainingPlanDetail | null = null;

	/** Map of workoutId → WeatherForecast for upcoming workouts (next 7 days) */
	let weatherMap: Map<number, WeatherForecast> = new Map();

	// ---------------------------------------------------------------------------
	// Workout type helpers (task 18.2 colour coding)
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

	/**
	 * Returns Tailwind classes for the workout type chip.
	 * Easy=green, Tempo=orange, Intervals=red, Hills=purple,
	 * Long Run=blue, Race=gold, Rest=grey, Recovery=light-green
	 */
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
	// Status helpers
	// ---------------------------------------------------------------------------

	function statusDotColor(status: string): string {
		const colors: Record<string, string> = {
			completed: 'bg-green-500',
			skipped: 'bg-gray-400',
			missed: 'bg-red-400',
			scheduled: 'bg-blue-400'
		};
		return colors[status] ?? 'bg-gray-300';
	}

	function statusLabel(status: string): string {
		const labels: Record<string, string> = {
			completed: 'Completed',
			skipped: 'Skipped',
			missed: 'Missed',
			scheduled: 'Scheduled'
		};
		return labels[status] ?? status;
	}

	// ---------------------------------------------------------------------------
	// Formatting helpers
	// ---------------------------------------------------------------------------

	function formatDistanceKm(metres: number | null): string {
		if (metres === null) return '';
		return `${(metres / 1000).toFixed(1)} km`;
	}

	function formatPaceZone(zone: string | null): string {
		if (!zone) return '';
		// Capitalise first letter
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
	// Calendar building
	// ---------------------------------------------------------------------------

	interface DayCell {
		date: Date;
		dateStr: string; // YYYY-MM-DD
		isToday: boolean;
		isPast: boolean;
		workout: WorkoutSummary | null;
	}

	interface WeekRow {
		weekLabel: string; // e.g. "Week 1 · 3 Jun – 9 Jun"
		blockName: string | null;
		days: DayCell[]; // always 7 items, Mon–Sun
	}

	/**
	 * Build a flat map of dateStr → WorkoutSummary from all blocks.
	 * If multiple workouts fall on the same date, the first one wins.
	 */
	function buildWorkoutMap(plan: TrainingPlanDetail): Map<string, WorkoutSummary> {
		const map = new Map<string, WorkoutSummary>();
		for (const block of plan.blocks) {
			for (const w of block.workouts) {
				if (!map.has(w.scheduled_date)) {
					map.set(w.scheduled_date, w);
				}
			}
		}
		return map;
	}

	/**
	 * Build a map of dateStr → blockName so we can label each week row.
	 */
	function buildDateBlockMap(plan: TrainingPlanDetail): Map<string, string> {
		const map = new Map<string, string>();
		for (const block of plan.blocks) {
			for (const w of block.workouts) {
				map.set(w.scheduled_date, block.name);
			}
		}
		return map;
	}

	/**
	 * Given a date, return the Monday of that week.
	 */
	function getMondayOf(d: Date): Date {
		const day = d.getDay(); // 0=Sun, 1=Mon, …
		const diff = day === 0 ? -6 : 1 - day;
		const monday = new Date(d);
		monday.setDate(d.getDate() + diff);
		monday.setHours(0, 0, 0, 0);
		return monday;
	}

	function toDateStr(d: Date): string {
		const y = d.getFullYear();
		const m = String(d.getMonth() + 1).padStart(2, '0');
		const day = String(d.getDate()).padStart(2, '0');
		return `${y}-${m}-${day}`;
	}

	function formatWeekLabel(monday: Date, weekIndex: number): string {
		const sunday = new Date(monday);
		sunday.setDate(monday.getDate() + 6);

		const opts: Intl.DateTimeFormatOptions = { day: 'numeric', month: 'short' };
		const start = monday.toLocaleDateString(undefined, opts);
		const end = sunday.toLocaleDateString(undefined, opts);
		return `Week ${weekIndex + 1} · ${start} – ${end}`;
	}

	const DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

	$: weeks = (() => {
		if (!activePlan) return [];

		const workoutMap = buildWorkoutMap(activePlan);
		const dateBlockMap = buildDateBlockMap(activePlan);

		const todayStr = toDateStr(new Date());
		const today = new Date();
		today.setHours(0, 0, 0, 0);

		// Determine plan date range
		const planStart = new Date(activePlan.start_date);
		const planEnd = new Date(activePlan.end_date);
		planStart.setHours(0, 0, 0, 0);
		planEnd.setHours(0, 0, 0, 0);

		// Start from Monday of the plan start week
		const firstMonday = getMondayOf(planStart);
		// End at Sunday of the plan end week
		const lastMonday = getMondayOf(planEnd);

		const result: WeekRow[] = [];
		let weekIndex = 0;
		let cursor = new Date(firstMonday);

		while (cursor <= lastMonday) {
			const days: DayCell[] = [];
			let blockName: string | null = null;

			for (let i = 0; i < 7; i++) {
				const d = new Date(cursor);
				d.setDate(cursor.getDate() + i);
				const dateStr = toDateStr(d);
				const workout = workoutMap.get(dateStr) ?? null;

				if (workout && !blockName) {
					blockName = dateBlockMap.get(dateStr) ?? null;
				}

				days.push({
					date: d,
					dateStr,
					isToday: dateStr === todayStr,
					isPast: d < today,
					workout
				});
			}

			result.push({
				weekLabel: formatWeekLabel(cursor, weekIndex),
				blockName,
				days
			});

			cursor.setDate(cursor.getDate() + 7);
			weekIndex++;
		}

		return result;
	})();

	// ---------------------------------------------------------------------------
	// Weather: fetch for workouts in the next 7 days
	// ---------------------------------------------------------------------------

	async function fetchWeatherForUpcoming(plan: TrainingPlanDetail, profileId: number) {
		const today = new Date();
		today.setHours(0, 0, 0, 0);
		const cutoff = new Date(today);
		cutoff.setDate(today.getDate() + 7);

		const upcoming: WorkoutSummary[] = [];
		for (const block of plan.blocks) {
			for (const w of block.workouts) {
				const d = new Date(w.scheduled_date);
				if (d >= today && d <= cutoff && w.workout_type !== 'rest') {
					upcoming.push(w);
				}
			}
		}

		const results = await Promise.allSettled(
			upcoming.map((w) => weatherApi.getWorkoutForecast(w.id, profileId))
		);

		const newMap = new Map<number, WeatherForecast>();
		results.forEach((r, i) => {
			if (r.status === 'fulfilled') {
				newMap.set(upcoming[i].id, r.value);
			}
		});
		weatherMap = newMap;
	}

	// ---------------------------------------------------------------------------
	// Data loading
	// ---------------------------------------------------------------------------

	async function loadPlan(profileId: number) {
		loading = true;
		error = null;
		activePlan = null;
		weatherMap = new Map();

		try {
			const plans = await plansApi.list(profileId);
			const active = plans.find((p: TrainingPlan) => p.status === 'active') ?? plans[0] ?? null;

			if (active) {
				activePlan = await plansApi.get(active.id, profileId);
				// Fire weather fetches in background — don't block render
				fetchWeatherForUpcoming(activePlan, profileId).catch(() => {
					// Weather is optional — ignore errors
				});
			}
		} catch (e) {
			error = 'Failed to load training plan. Please try again.';
		} finally {
			loading = false;
		}
	}

	// ---------------------------------------------------------------------------
	// Regenerate Plan
	// ---------------------------------------------------------------------------

	let regenerating = false;
	let regenerateError: string | null = null;

	async function regeneratePlan() {
		if (!activePlan) return;
		regenerating = true;
		regenerateError = null;
		try {
			await plansApi.regenerate(activePlan.id, $activeProfile);
			// Reload plan data after successful regeneration
			await loadPlan($activeProfile);
		} catch (e) {
			regenerateError = 'Failed to regenerate plan. Please try again.';
		} finally {
			regenerating = false;
		}
	}

	// ---------------------------------------------------------------------------
	// Reset Plan
	// ---------------------------------------------------------------------------

	let showResetDialog = false;
	let resetting = false;
	let resetError: string | null = null;

	function openResetDialog() {
		resetError = null;
		showResetDialog = true;
	}

	function closeResetDialog() {
		if (resetting) return;
		showResetDialog = false;
		resetError = null;
	}

	async function confirmReset() {
		if (!activePlan) return;
		resetting = true;
		resetError = null;
		try {
			await plansApi.delete(activePlan.id, $activeProfile);
			showResetDialog = false;
			window.location.href = '/onboarding';
		} catch (e) {
			resetError = 'Failed to reset plan. Please try again.';
		} finally {
			resetting = false;
		}
	}

	// ---------------------------------------------------------------------------
	// Lifecycle
	// ---------------------------------------------------------------------------

	let mounted = false;

	onMount(() => {
		mounted = true;
		loadPlan($activeProfile);
	});

	$: if (mounted) {
		loadPlan($activeProfile);
	}
</script>

<!-- =========================================================================
     Template
     ========================================================================= -->

<div class="p-4 sm:p-6 max-w-5xl mx-auto space-y-6">

	<!-- Page header -->
	<div class="flex items-center justify-between">
		<h1 class="text-2xl font-bold text-gray-900">Training Plan</h1>
		{#if !loading}
			<button
				class="text-sm text-blue-600 hover:text-blue-800 transition-colors"
				on:click={() => loadPlan($activeProfile)}
				aria-label="Refresh training plan"
			>
				↻ Refresh
			</button>
		{/if}
	</div>

	<!-- Loading state -->
	{#if loading}
		<div class="flex items-center justify-center py-20" role="status" aria-live="polite">
			<div class="flex flex-col items-center gap-3 text-gray-500">
				<div
					class="h-8 w-8 animate-spin rounded-full border-4 border-gray-200 border-t-blue-600"
					aria-hidden="true"
				></div>
				<span class="text-sm">Loading your training plan…</span>
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

	<!-- No plan state -->
	{:else if !activePlan}
		<div
			class="rounded-xl border-2 border-dashed border-gray-300 bg-white p-10 text-center"
			role="region"
			aria-label="No training plan"
		>
			<div class="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-blue-50">
				<span class="text-3xl" aria-hidden="true">📅</span>
			</div>
			<h2 class="mb-2 text-lg font-semibold text-gray-900">No training plan yet</h2>
			<p class="mb-5 text-sm text-gray-500">
				Create a training plan to see your weekly schedule here.
			</p>
			<a
				href="/onboarding"
				class="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-medium text-white
				       hover:bg-blue-700 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
			>
				<span aria-hidden="true">✨</span>
				Create your first plan
			</a>
		</div>

	<!-- Calendar view -->
	{:else}
		<!-- Plan summary bar -->
		<div class="rounded-xl border border-gray-200 bg-white px-5 py-4 shadow-sm">
			<div class="flex flex-wrap items-center justify-between gap-3">
				<div>
					<p class="text-xs font-medium uppercase tracking-wide text-gray-400">Active Plan</p>
					<p class="mt-0.5 text-sm font-semibold text-gray-900">
						{new Date(activePlan.start_date).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })}
						–
						{new Date(activePlan.end_date).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })}
					</p>
				</div>
				<div class="flex items-center gap-2 flex-wrap">
					<span
						class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium
						       {activePlan.status === 'active' ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-600'}"
					>
						{activePlan.status}
					</span>
					<span class="text-xs text-gray-400">{activePlan.blocks.length} blocks</span>
					<button
						on:click={regeneratePlan}
						disabled={regenerating || resetting}
						class="inline-flex items-center gap-1.5 rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-1.5 text-xs font-medium text-indigo-700
						       hover:bg-indigo-100 hover:border-indigo-300 transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2
						       disabled:opacity-50 disabled:cursor-not-allowed"
						aria-label="Regenerate training plan"
					>
						{#if regenerating}
							<span class="h-3 w-3 animate-spin rounded-full border-2 border-indigo-300 border-t-indigo-700" aria-hidden="true"></span>
							Regenerating…
						{:else}
							<span aria-hidden="true">✨</span>
							Regenerate Plan
						{/if}
					</button>
					<button
						on:click={openResetDialog}
						disabled={regenerating || resetting}
						class="inline-flex items-center gap-1.5 rounded-lg border border-red-200 bg-red-50 px-3 py-1.5 text-xs font-medium text-red-700
						       hover:bg-red-100 hover:border-red-300 transition-colors focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2
						       disabled:opacity-50 disabled:cursor-not-allowed"
						aria-label="Reset training plan"
					>
						<span aria-hidden="true">🗑️</span>
						Reset Plan
					</button>
				</div>
				{#if regenerateError}
					<p class="w-full text-xs text-red-600 mt-1" role="alert">{regenerateError}</p>
				{/if}
			</div>
		</div>

		<!-- Colour legend -->
		<div
			class="flex flex-wrap gap-2"
			role="list"
			aria-label="Workout type colour legend"
		>
			{#each Object.entries(WORKOUT_TYPE_LABELS) as [type, label] (type)}
				<span
					role="listitem"
					class="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium {workoutTypeColor(type)}"
				>
					{label}
				</span>
			{/each}
		</div>

		<!-- Day-name header row (sticky) -->
		<div class="sticky top-0 z-10 hidden sm:grid sm:grid-cols-7 gap-1 bg-gray-50 pb-1 pt-0.5" aria-hidden="true">
			{#each DAY_NAMES as name (name)}
				<div class="text-center text-xs font-semibold uppercase tracking-wide text-gray-400 py-1">
					{name}
				</div>
			{/each}
		</div>

		<!-- Weekly rows -->
		<div class="space-y-4" role="list" aria-label="Training plan calendar">
			{#each weeks as week, wi (wi)}
				<section
					role="listitem"
					aria-label={week.weekLabel}
					class="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden"
				>
					<!-- Week header -->
					<div class="flex items-center justify-between gap-2 border-b border-gray-100 bg-gray-50 px-4 py-2.5">
						<div class="flex items-center gap-2 min-w-0">
							<span class="text-xs font-semibold text-gray-700 truncate">{week.weekLabel}</span>
							{#if week.blockName}
								<span class="shrink-0 rounded-full bg-indigo-100 px-2 py-0.5 text-xs font-medium text-indigo-700">
									{week.blockName}
								</span>
							{/if}
						</div>
					</div>

					<!-- Day cells grid -->
					<div class="grid grid-cols-2 sm:grid-cols-7 gap-px bg-gray-100">
						{#each week.days as cell (cell.dateStr)}
							<div
								class="relative flex flex-col gap-1 p-2.5 min-h-[90px]
								       {cell.isToday ? 'bg-blue-50' : 'bg-white'}
								       {cell.isPast && !cell.isToday ? 'opacity-60' : ''}"
								aria-label="{DAY_NAMES[(cell.date.getDay() + 6) % 7]} {cell.date.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })}{cell.isToday ? ' (today)' : ''}"
							>
								<!-- Date number -->
								<div class="flex items-center justify-between">
									<span
										class="flex h-6 w-6 items-center justify-center rounded-full text-xs font-semibold
										       {cell.isToday
											? 'bg-blue-600 text-white'
											: 'text-gray-500'}"
									>
										{cell.date.getDate()}
									</span>
									<!-- Day name on mobile (hidden on sm+) -->
									<span class="text-xs text-gray-400 sm:hidden">
										{DAY_NAMES[(cell.date.getDay() + 6) % 7]}
									</span>
								</div>

								{#if cell.workout}
									{@const w = cell.workout}
									{@const weather = weatherMap.get(w.id)}

									<!-- Workout type chip -->
									<span
										class="inline-block rounded-full border px-1.5 py-0.5 text-xs font-semibold leading-tight {workoutTypeColor(w.workout_type)}"
										title={workoutTypeLabel(w.workout_type)}
									>
										{workoutTypeLabel(w.workout_type)}
									</span>

									<!-- Distance -->
									{#if w.target_distance_metres}
										<span class="text-xs font-medium text-gray-800">
											{formatDistanceKm(w.target_distance_metres)}
										</span>
									{/if}

									<!-- Pace zone -->
									{#if w.target_pace_zone}
										<span class="text-xs text-gray-500">
											{formatPaceZone(w.target_pace_zone)}
										</span>
									{/if}

									<!-- Status dot -->
									{#if w.status !== 'scheduled'}
										<div class="flex items-center gap-1 mt-auto">
											<span
												class="h-1.5 w-1.5 rounded-full {statusDotColor(w.status)}"
												aria-hidden="true"
											></span>
											<span class="text-xs text-gray-400">{statusLabel(w.status)}</span>
										</div>
									{/if}

									<!-- Weather badge (upcoming workouts within 7 days) -->
									{#if weather}
										<div
											class="mt-auto flex items-center gap-1 rounded-md bg-sky-50 border border-sky-100 px-1.5 py-0.5"
											aria-label="Weather: {weather.conditions}, {Math.round(weather.temperature_c)}°C"
											title="{weather.conditions} · {Math.round(weather.temperature_c)}°C · {weather.wind_kmh} km/h wind"
										>
											<span class="text-sm leading-none" aria-hidden="true">
												{weatherConditionIcon(weather.conditions)}
											</span>
											<span class="text-xs font-medium text-sky-700">
												{Math.round(weather.temperature_c)}°
											</span>
											{#if weather.advisories.length > 0}
												<span class="text-xs text-amber-600" aria-label="Weather advisory">⚠️</span>
											{/if}
										</div>
									{/if}
								{:else}
									<!-- Empty day -->
									<span class="text-xs text-gray-300 mt-auto">—</span>
								{/if}
							</div>
						{/each}
					</div>
				</section>
			{/each}
		</div>

		{#if weeks.length === 0}
			<p class="text-center text-sm text-gray-400 py-8">No weeks to display.</p>
		{/if}
	{/if}
</div>

<!-- Reset Plan confirmation dialog -->
{#if showResetDialog}
	<!-- Backdrop -->
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
		role="dialog"
		aria-modal="true"
		aria-labelledby="reset-dialog-title"
		on:click|self={closeResetDialog}
		on:keydown={(e) => e.key === 'Escape' && closeResetDialog()}
	>
		<div class="w-full max-w-md rounded-xl bg-white shadow-xl">
			<!-- Dialog header -->
			<div class="px-6 pt-6 pb-4">
				<h2 id="reset-dialog-title" class="text-lg font-semibold text-gray-900">Reset Training Plan</h2>
			</div>

			<!-- Dialog body -->
			<div class="px-6 pb-4">
				<p class="text-sm text-gray-700">
					This will permanently delete your current training plan and all scheduled workouts. This cannot be undone. Are you sure?
				</p>

				{#if resetError}
					<p class="mt-3 text-sm text-red-600" role="alert">{resetError}</p>
				{/if}
			</div>

			<!-- Dialog footer -->
			<div class="flex justify-end gap-3 border-t border-gray-100 px-6 py-4">
				<button
					on:click={closeResetDialog}
					disabled={resetting}
					class="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700
					       hover:bg-gray-50 transition-colors focus:outline-none focus:ring-2 focus:ring-gray-400 focus:ring-offset-2
					       disabled:opacity-50 disabled:cursor-not-allowed"
				>
					Cancel
				</button>
				<button
					on:click={confirmReset}
					disabled={resetting}
					class="inline-flex items-center gap-2 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white
					       hover:bg-red-700 transition-colors focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2
					       disabled:opacity-50 disabled:cursor-not-allowed"
				>
					{#if resetting}
						<span class="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" aria-hidden="true"></span>
						Resetting…
					{:else}
						Reset Plan
					{/if}
				</button>
			</div>
		</div>
	</div>
{/if}
