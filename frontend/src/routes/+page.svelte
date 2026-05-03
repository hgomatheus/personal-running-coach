<script lang="ts">
	import { onMount } from 'svelte';
	import { activeProfile } from '$lib/stores';
	import {
		plansApi,
		workoutsApi,
		runsApi,
		statsApi,
		raceGoalsApi,
		taperApi,
		type TrainingPlanDetail,
		type TrainingBlock,
		type WorkoutSummary,
		type Run,
		type WeeklyStats,
		type RaceGoal,
		type TaperStatus,
		type WeatherForecast
	} from '$lib/api';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let loading = true;
	let error: string | null = null;

	// Plan data
	let activePlan: TrainingPlanDetail | null = null;
	let currentBlock: TrainingBlock | null = null;
	let nextWorkout: WorkoutSummary | null = null;
	let nextWorkoutWeather: WeatherForecast | null = null;

	// Race goal
	let activeRaceGoal: RaceGoal | null = null;
	let raceCountdownDismissed = false; // session-only dismiss

	// Taper
	let taperStatus: TaperStatus | null = null;

	// Stats
	let weeklyStats: WeeklyStats[] = [];
	let recentRuns: Run[] = [];
	let currentStreak = 0;

	// ---------------------------------------------------------------------------
	// Derived values
	// ---------------------------------------------------------------------------

	$: daysUntilRace = activeRaceGoal
		? Math.ceil(
				(new Date(activeRaceGoal.target_date).getTime() - Date.now()) / (1000 * 60 * 60 * 24)
			)
		: null;

	$: motivationalMessage = (() => {
		if (daysUntilRace === null) return '';
		if (daysUntilRace > 90) return 'Building your base';
		if (daysUntilRace >= 30) return 'Getting stronger';
		if (daysUntilRace >= 14) return 'Race prep mode';
		if (daysUntilRace >= 7) return 'Taper time — trust your training';
		return 'Race week — you\'re ready';
	})();

	$: currentWeekStats = (() => {
		if (!weeklyStats.length) return null;
		// Find the most recent week (last entry)
		return weeklyStats[weeklyStats.length - 1] ?? null;
	})();

	$: plannedKmThisWeek = (() => {
		if (!activePlan || !currentBlock) return 0;
		const today = new Date();
		const weekStart = new Date(today);
		weekStart.setDate(today.getDate() - today.getDay()); // Sunday
		weekStart.setHours(0, 0, 0, 0);
		const weekEnd = new Date(weekStart);
		weekEnd.setDate(weekStart.getDate() + 7);

		let total = 0;
		for (const block of activePlan.blocks) {
			for (const w of block.workouts) {
				const d = new Date(w.scheduled_date);
				if (d >= weekStart && d < weekEnd && w.target_distance_metres) {
					total += w.target_distance_metres / 1000;
				}
			}
		}
		return total;
	})();

	$: completedKmThisWeek = currentWeekStats?.total_km ?? 0;

	$: weeklyProgressPct = plannedKmThisWeek > 0
		? Math.min(100, Math.round((completedKmThisWeek / plannedKmThisWeek) * 100))
		: 0;

	$: weeksUntilRace = (() => {
		if (!activeRaceGoal) return null;
		const days = daysUntilRace ?? 0;
		return Math.ceil(days / 7);
	})();

	// ---------------------------------------------------------------------------
	// Helpers
	// ---------------------------------------------------------------------------

	function formatPace(secPerKm: number | null): string {
		if (secPerKm === null) return '—';
		const mins = Math.floor(secPerKm / 60);
		const secs = Math.round(secPerKm % 60);
		return `${mins}:${secs.toString().padStart(2, '0')} /km`;
	}

	function formatDistance(metres: number | null): string {
		if (metres === null) return '—';
		return `${(metres / 1000).toFixed(1)} km`;
	}

	function formatDate(dateStr: string): string {
		return new Date(dateStr).toLocaleDateString(undefined, {
			weekday: 'short',
			month: 'short',
			day: 'numeric'
		});
	}

	function workoutTypeLabel(type: string): string {
		const labels: Record<string, string> = {
			easy: 'Easy Run',
			tempo: 'Tempo',
			interval: 'Intervals',
			hills: 'Hills',
			long: 'Long Run',
			race: 'Race',
			rest: 'Rest',
			recovery: 'Recovery'
		};
		return labels[type] ?? type;
	}

	function workoutTypeColor(type: string): string {
		const colors: Record<string, string> = {
			easy: 'bg-green-100 text-green-800',
			tempo: 'bg-orange-100 text-orange-800',
			interval: 'bg-red-100 text-red-800',
			hills: 'bg-purple-100 text-purple-800',
			long: 'bg-blue-100 text-blue-800',
			race: 'bg-yellow-100 text-yellow-800',
			rest: 'bg-gray-100 text-gray-500',
			recovery: 'bg-emerald-100 text-emerald-700'
		};
		return colors[type] ?? 'bg-gray-100 text-gray-700';
	}

	function weatherConditionIcon(conditions: string): string {
		const c = conditions.toLowerCase();
		if (c.includes('rain') || c.includes('drizzle')) return '🌧️';
		if (c.includes('snow')) return '❄️';
		if (c.includes('cloud')) return '☁️';
		if (c.includes('clear') || c.includes('sunny')) return '☀️';
		if (c.includes('wind')) return '💨';
		return '🌤️';
	}

	// ---------------------------------------------------------------------------
	// Data loading
	// ---------------------------------------------------------------------------

	async function loadDashboard(profileId: number) {
		loading = true;
		error = null;
		activePlan = null;
		currentBlock = null;
		nextWorkout = null;
		nextWorkoutWeather = null;
		activeRaceGoal = null;
		taperStatus = null;
		weeklyStats = [];
		recentRuns = [];
		currentStreak = 0;

		try {
			// Load all data in parallel
			const [plans, raceGoals, taper, weekly, runs] = await Promise.allSettled([
				plansApi.list(profileId),
				raceGoalsApi.list(profileId),
				taperApi.get(profileId),
				statsApi.weekly(profileId),
				runsApi.list({}, profileId)
			]);

			// Race goals
			if (raceGoals.status === 'fulfilled') {
				activeRaceGoal = raceGoals.value.find((g) => g.is_active) ?? null;
			}

			// Taper status
			if (taper.status === 'fulfilled') {
				taperStatus = taper.value;
			}

			// Weekly stats
			if (weekly.status === 'fulfilled') {
				weeklyStats = weekly.value;
			}

			// Recent runs (last 3)
			if (runs.status === 'fulfilled') {
				const sorted = [...runs.value].sort(
					(a, b) => new Date(b.date).getTime() - new Date(a.date).getTime()
				);
				recentRuns = sorted.slice(0, 3);

				// Calculate streak (consecutive weeks with at least one run)
				currentStreak = calculateStreak(runs.value);
			}

			// Active plan — look for active status first, then any plan
			if (plans.status === 'fulfilled' && plans.value.length > 0) {
				const active =
					plans.value.find((p) => p.status === 'active') ??
					plans.value.find((p) => p.status !== 'archived') ??
					plans.value[0];
				if (active) {
					try {
						activePlan = await plansApi.get(active.id, profileId);
						findCurrentBlockAndNextWorkout();

						// Try to fetch weather for next workout
						if (nextWorkout) {
							try {
								nextWorkoutWeather = await workoutsApi.getWeather(nextWorkout.id, profileId);
							} catch {
								// Weather is optional — ignore errors
							}
						}
					} catch {
						// Plan detail failed — treat as no plan
					}
				}
			}
		} catch (e) {
			error = 'Failed to load dashboard data. Please try again.';
		} finally {
			loading = false;
		}
	}

	function findCurrentBlockAndNextWorkout() {
		if (!activePlan) return;
		const today = new Date();
		today.setHours(0, 0, 0, 0);

		// Find next scheduled workout
		let earliest: WorkoutSummary | null = null;
		let earliestBlock: TrainingBlock | null = null;

		for (const block of activePlan.blocks) {
			for (const w of block.workouts) {
				if (w.status === 'scheduled') {
					const d = new Date(w.scheduled_date);
					if (d >= today) {
						if (!earliest || d < new Date(earliest.scheduled_date)) {
							earliest = w;
							earliestBlock = block;
						}
					}
				}
			}
		}

		nextWorkout = earliest;

		// Find current block (block whose date range contains today)
		currentBlock = null;
		for (const block of activePlan.blocks) {
			const start = new Date(block.start_date);
			const end = new Date(block.end_date);
			if (today >= start && today <= end) {
				currentBlock = block;
				break;
			}
		}

		// Fallback: use the block of the next workout
		if (!currentBlock && earliestBlock) {
			currentBlock = earliestBlock;
		}
	}

	function calculateStreak(runs: Run[]): number {
		if (!runs.length) return 0;

		// Group runs by ISO week
		const weekSet = new Set<string>();
		for (const run of runs) {
			const d = new Date(run.date);
			const year = d.getFullYear();
			// ISO week number
			const startOfYear = new Date(year, 0, 1);
			const week = Math.ceil(
				((d.getTime() - startOfYear.getTime()) / 86400000 + startOfYear.getDay() + 1) / 7
			);
			weekSet.add(`${year}-W${week}`);
		}

		// Count consecutive weeks ending at the current week
		const now = new Date();
		let streak = 0;
		let checkDate = new Date(now);

		for (let i = 0; i < 52; i++) {
			const year = checkDate.getFullYear();
			const startOfYear = new Date(year, 0, 1);
			const week = Math.ceil(
				((checkDate.getTime() - startOfYear.getTime()) / 86400000 + startOfYear.getDay() + 1) / 7
			);
			const key = `${year}-W${week}`;
			if (weekSet.has(key)) {
				streak++;
				checkDate.setDate(checkDate.getDate() - 7);
			} else {
				break;
			}
		}

		return streak;
	}

	// ---------------------------------------------------------------------------
	// Lifecycle
	// ---------------------------------------------------------------------------

	let mounted = false;

	onMount(() => {
		mounted = true;
		loadDashboard($activeProfile);
	});

	// Reload when profile switches (skip the initial reactive run before mount)
	$: if (mounted) {
		loadDashboard($activeProfile);
	}
</script>

<div class="p-4 sm:p-6 max-w-4xl mx-auto space-y-6">
	<!-- Page header -->
	<div class="flex items-center justify-between">
		<h1 class="text-2xl font-bold text-gray-900">Dashboard</h1>
		{#if !loading}
			<button
				class="text-sm text-blue-600 hover:text-blue-800 transition-colors"
				on:click={() => loadDashboard($activeProfile)}
				aria-label="Refresh dashboard"
			>
				↻ Refresh
			</button>
		{/if}
	</div>

	<!-- Loading state -->
	{#if loading}
		<div class="flex items-center justify-center py-16" role="status" aria-live="polite">
			<div class="flex flex-col items-center gap-3 text-gray-500">
				<div
					class="h-8 w-8 animate-spin rounded-full border-4 border-gray-200 border-t-blue-600"
					aria-hidden="true"
				></div>
				<span class="text-sm">Loading your dashboard…</span>
			</div>
		</div>

	<!-- Error state -->
	{:else if error}
		<div class="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700" role="alert">
			{error}
		</div>

	{:else}
		<!-- ------------------------------------------------------------------ -->
		<!-- Race countdown widget (task 16.2)                                   -->
		<!-- ------------------------------------------------------------------ -->
		{#if activeRaceGoal && daysUntilRace !== null && daysUntilRace >= 0 && !raceCountdownDismissed}
			<div
				class="relative rounded-xl border border-blue-200 bg-gradient-to-r from-blue-50 to-indigo-50 p-4"
				role="region"
				aria-label="Race countdown"
			>
				<button
					class="absolute right-3 top-3 rounded-full p-1 text-blue-400 hover:bg-blue-100 hover:text-blue-600 transition-colors"
					aria-label="Dismiss race countdown"
					on:click={() => (raceCountdownDismissed = true)}
				>
					<svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
					</svg>
				</button>

				<div class="flex items-center gap-4">
					<div class="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-blue-600 text-white">
						<span class="text-xl font-bold">{daysUntilRace}</span>
					</div>
					<div>
						<p class="text-xs font-medium uppercase tracking-wide text-blue-500">Race Countdown</p>
						<p class="text-lg font-semibold text-blue-900">
							{activeRaceGoal.label ?? `${(activeRaceGoal.distance_metres / 1000).toFixed(0)} km Race`}
						</p>
						<p class="text-sm text-blue-700">
							{daysUntilRace === 0
								? '🏁 Race day!'
								: daysUntilRace === 1
									? '1 day to go'
									: `${daysUntilRace} days to go`}
							— {motivationalMessage}
						</p>
					</div>
				</div>
			</div>
		{/if}

		<!-- ------------------------------------------------------------------ -->
		<!-- No active plan prompt (task 16.4)                                   -->
		<!-- ------------------------------------------------------------------ -->
		{#if !activePlan}
			<div
				class="rounded-xl border-2 border-dashed border-gray-300 bg-white p-8 text-center"
				role="region"
				aria-label="No training plan"
			>
				<div class="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-blue-50">
					<span class="text-3xl" aria-hidden="true">📋</span>
				</div>
				<h2 class="mb-2 text-lg font-semibold text-gray-900">No training plan yet</h2>
				<p class="mb-4 text-sm text-gray-500">
					Create your first plan to get personalised workouts, track your progress, and prepare for
					your race.
				</p>
				<a
					href="/onboarding"
					class="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-blue-700 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
				>
					<span aria-hidden="true">✨</span>
					Create your first plan
				</a>
			</div>

		{:else}
			<!-- -------------------------------------------------------------- -->
			<!-- Next workout card (task 16.1)                                   -->
			<!-- -------------------------------------------------------------- -->
			{#if nextWorkout}
				<section aria-labelledby="next-workout-heading">
					<h2 id="next-workout-heading" class="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500">
						Next Workout
					</h2>
					<a
						href="/workout/{nextWorkout.id}"
						class="block rounded-xl border border-gray-200 bg-white p-5 shadow-sm hover:shadow-md transition-shadow focus:outline-none focus:ring-2 focus:ring-blue-500"
						aria-label="View workout: {workoutTypeLabel(nextWorkout.workout_type)}"
					>
						<div class="flex items-start justify-between gap-3">
							<div class="flex-1 min-w-0">
								<!-- Type badge -->
								<span
									class="inline-block rounded-full px-2.5 py-0.5 text-xs font-semibold {workoutTypeColor(nextWorkout.workout_type)}"
								>
									{workoutTypeLabel(nextWorkout.workout_type)}
								</span>

								<p class="mt-2 text-sm text-gray-500">{formatDate(nextWorkout.scheduled_date)}</p>

								<div class="mt-3 flex flex-wrap items-center gap-4">
									{#if nextWorkout.target_distance_metres}
										<div>
											<p class="text-xs text-gray-400">Distance</p>
											<p class="text-lg font-bold text-gray-900">
												{formatDistance(nextWorkout.target_distance_metres)}
											</p>
										</div>
									{/if}
									{#if nextWorkout.target_pace_zone}
										<div>
											<p class="text-xs text-gray-400">Pace Zone</p>
											<p class="text-base font-semibold capitalize text-gray-800">
												{nextWorkout.target_pace_zone}
											</p>
										</div>
									{/if}
								</div>

								{#if nextWorkout.coaching_note}
									<p class="mt-2 text-sm text-gray-600 line-clamp-2">{nextWorkout.coaching_note}</p>
								{/if}
							</div>

							<!-- Weather badge -->
							{#if nextWorkoutWeather}
								<div
									class="shrink-0 rounded-lg border border-gray-100 bg-gray-50 px-3 py-2 text-center"
									aria-label="Weather: {nextWorkoutWeather.conditions}, {nextWorkoutWeather.temperature_c}°C"
								>
									<span class="text-xl" aria-hidden="true">
										{weatherConditionIcon(nextWorkoutWeather.conditions)}
									</span>
									<p class="mt-0.5 text-xs font-medium text-gray-700">
										{Math.round(nextWorkoutWeather.temperature_c)}°C
									</p>
									{#if nextWorkoutWeather.advisories.length > 0}
										<p class="mt-0.5 text-xs text-amber-600">⚠️ Advisory</p>
									{/if}
								</div>
							{/if}
						</div>
					</a>
				</section>
			{:else}
				<div class="rounded-xl border border-gray-200 bg-white p-5 text-center text-sm text-gray-500">
					No upcoming workouts scheduled.
					<a href="/plan" class="ml-1 text-blue-600 hover:underline">View plan →</a>
				</div>
			{/if}

			<!-- -------------------------------------------------------------- -->
			<!-- Training block + weeks to race (tasks 16.1, 16.3)              -->
			<!-- -------------------------------------------------------------- -->
			<section aria-labelledby="training-block-heading">
				<h2 id="training-block-heading" class="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500">
					Training Progress
				</h2>
				<div class="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
					<div class="flex flex-wrap items-start justify-between gap-4">
						<!-- Block name / taper mode indicator (task 16.3) -->
						<div>
							<p class="text-xs text-gray-400">Current Block</p>
							{#if taperStatus?.taper_active}
								<div class="mt-1 flex items-center gap-2">
									<span
										class="inline-flex items-center gap-1 rounded-full bg-amber-100 px-3 py-1 text-sm font-semibold text-amber-800"
										aria-label="Taper mode active"
									>
										🏁 Taper Mode
									</span>
								</div>
							{:else if currentBlock}
								<p class="mt-1 text-base font-semibold text-gray-900">{currentBlock.name}</p>
							{:else}
								<p class="mt-1 text-base font-semibold text-gray-400">—</p>
							{/if}
						</div>

						<!-- Weeks to race -->
						{#if weeksUntilRace !== null}
							<div class="text-right">
								<p class="text-xs text-gray-400">Weeks to Race</p>
								<p class="mt-1 text-2xl font-bold text-blue-600">{weeksUntilRace}</p>
							</div>
						{/if}
					</div>

					<!-- Taper guidance panel (task 16.3) -->
					{#if taperStatus?.taper_active && taperStatus.guidance}
						<div
							class="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-4 space-y-2"
							role="region"
							aria-label="Taper guidance"
						>
							<p class="text-sm font-semibold text-amber-800">Taper Guidance</p>
							{#if taperStatus.volume_reduction_pct}
								<p class="text-sm text-amber-700">
									🎯 Target mileage reduction: <strong>{taperStatus.volume_reduction_pct}%</strong>
								</p>
							{/if}
							<p class="text-sm text-amber-700">
								😴 {taperStatus.guidance.sleep_nutrition_reminder}
							</p>
							<p class="text-sm text-amber-700">
								💪 {taperStatus.guidance.sluggishness_note}
							</p>
						</div>
					{/if}
				</div>
			</section>

			<!-- -------------------------------------------------------------- -->
			<!-- Weekly mileage progress bar (task 16.1)                         -->
			<!-- -------------------------------------------------------------- -->
			<section aria-labelledby="weekly-mileage-heading">
				<h2 id="weekly-mileage-heading" class="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500">
					This Week's Mileage
				</h2>
				<div class="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
					<div class="flex items-end justify-between mb-2">
						<div>
							<span class="text-2xl font-bold text-gray-900">
								{completedKmThisWeek.toFixed(1)}
							</span>
							<span class="text-sm text-gray-500 ml-1">km completed</span>
						</div>
						{#if plannedKmThisWeek > 0}
							<span class="text-sm text-gray-500">
								of {plannedKmThisWeek.toFixed(1)} km planned
							</span>
						{/if}
					</div>

					{#if plannedKmThisWeek > 0}
						<div
							class="h-3 w-full overflow-hidden rounded-full bg-gray-100"
							role="progressbar"
							aria-valuenow={weeklyProgressPct}
							aria-valuemin={0}
							aria-valuemax={100}
							aria-label="Weekly mileage progress: {weeklyProgressPct}%"
						>
							<div
								class="h-full rounded-full transition-all duration-500
								       {weeklyProgressPct >= 100 ? 'bg-green-500' : 'bg-blue-500'}"
								style="width: {weeklyProgressPct}%"
							></div>
						</div>
						<p class="mt-1.5 text-xs text-gray-400 text-right">{weeklyProgressPct}% complete</p>
					{:else}
						<div class="h-3 w-full rounded-full bg-gray-100" aria-hidden="true"></div>
						<p class="mt-1.5 text-xs text-gray-400">No workouts planned this week</p>
					{/if}
				</div>
			</section>
		{/if}

		<!-- ------------------------------------------------------------------ -->
		<!-- Streak display (task 16.1)                                          -->
		<!-- ------------------------------------------------------------------ -->
		<section aria-labelledby="streak-heading">
			<h2 id="streak-heading" class="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500">
				Streak
			</h2>
			<div class="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
				<div class="flex items-center gap-4">
					<div
						class="flex h-14 w-14 shrink-0 items-center justify-center rounded-full
						       {currentStreak > 0 ? 'bg-orange-100' : 'bg-gray-100'}"
					>
						<span class="text-2xl" aria-hidden="true">{currentStreak > 0 ? '🔥' : '💤'}</span>
					</div>
					<div>
						<p class="text-3xl font-bold {currentStreak > 0 ? 'text-orange-600' : 'text-gray-400'}">
							{currentStreak}
						</p>
						<p class="text-sm text-gray-500">
							{currentStreak === 1 ? 'week streak' : 'week streak'}
							{currentStreak === 0 ? '— start running to build your streak!' : '— keep it up!'}
						</p>
					</div>
				</div>
			</div>
		</section>

		<!-- ------------------------------------------------------------------ -->
		<!-- 3 recent runs (task 16.1)                                           -->
		<!-- ------------------------------------------------------------------ -->
		<section aria-labelledby="recent-runs-heading">
			<div class="mb-3 flex items-center justify-between">
				<h2 id="recent-runs-heading" class="text-sm font-semibold uppercase tracking-wide text-gray-500">
					Recent Runs
				</h2>
				<a href="/runs" class="text-sm text-blue-600 hover:text-blue-800 transition-colors">
					View all →
				</a>
			</div>

			{#if recentRuns.length === 0}
				<div class="rounded-xl border border-gray-200 bg-white p-5 text-center text-sm text-gray-500">
					No runs logged yet.
					<a href="/runs" class="ml-1 text-blue-600 hover:underline">Log your first run →</a>
				</div>
			{:else}
				<div class="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
					<ul role="list" class="divide-y divide-gray-100">
						{#each recentRuns as run (run.id)}
							<li>
								<a
									href="/runs/{run.id}/analysis"
									class="flex items-center justify-between gap-3 px-5 py-4 hover:bg-gray-50 transition-colors focus:outline-none focus:bg-gray-50"
									aria-label="Run on {formatDate(run.date)}: {formatDistance(run.distance_metres)}"
								>
									<div class="flex items-center gap-3 min-w-0">
										<span class="text-xl shrink-0" aria-hidden="true">🏃</span>
										<div class="min-w-0">
											<p class="text-sm font-medium text-gray-900">{formatDate(run.date)}</p>
											{#if run.run_type}
												<p class="text-xs text-gray-400 capitalize">{run.run_type}</p>
											{/if}
										</div>
									</div>

									<div class="flex items-center gap-5 shrink-0 text-right">
										<div>
											<p class="text-sm font-semibold text-gray-900">
												{formatDistance(run.distance_metres)}
											</p>
											<p class="text-xs text-gray-400">distance</p>
										</div>
										{#if run.avg_pace_sec_per_km}
											<div>
												<p class="text-sm font-semibold text-gray-900">
													{formatPace(run.avg_pace_sec_per_km)}
												</p>
												<p class="text-xs text-gray-400">pace</p>
											</div>
										{/if}
									</div>
								</a>
							</li>
						{/each}
					</ul>
				</div>
			{/if}
		</section>
	{/if}
</div>
