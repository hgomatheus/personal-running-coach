<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import {
		Chart,
		BarController,
		BarElement,
		CategoryScale,
		LinearScale,
		Tooltip,
		Legend
	} from 'chart.js';
	import { statsApi, type WeeklyStats, type MonthlyStats, type PersonalRecord } from '$lib/api';
	import { activeProfile } from '$lib/stores';

	// Register Chart.js components
	Chart.register(BarController, BarElement, CategoryScale, LinearScale, Tooltip, Legend);

	// ---------------------------------------------------------------------------
	// Extended PRs response type (includes streak fields from the API)
	// ---------------------------------------------------------------------------

	interface PRsResponseExtended {
		records: PersonalRecord[];
		current_streak: number;
		longest_streak: number;
	}

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let loading = true;
	let error: string | null = null;

	let weeklyStats: WeeklyStats[] = [];
	let monthlyStats: MonthlyStats[] = [];
	let prsData: PRsResponseExtended | null = null;

	// Chart
	let canvasEl: HTMLCanvasElement;
	let chartInstance: Chart | null = null;

	// ---------------------------------------------------------------------------
	// Helpers
	// ---------------------------------------------------------------------------

	/** Format seconds as "M:SS /km" */
	function formatPace(secPerKm: number | null): string {
		if (secPerKm === null || secPerKm === undefined) return '—';
		const mins = Math.floor(secPerKm / 60);
		const secs = Math.round(secPerKm % 60);
		return `${mins}:${secs.toString().padStart(2, '0')} /km`;
	}

	/** Format total seconds as "Xh Ym" */
	function formatDuration(totalSeconds: number): string {
		const h = Math.floor(totalSeconds / 3600);
		const m = Math.floor((totalSeconds % 3600) / 60);
		if (h === 0) return `${m}m`;
		return `${h}h ${m}m`;
	}

	/** Format a week_start ISO date string as "DD MMM" */
	function formatWeekLabel(isoDate: string): string {
		const d = new Date(isoDate);
		return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
	}

	/** Format a month number (1-12) and year as "Jan 2025" */
	function formatMonthLabel(year: number, month: number): string {
		const d = new Date(year, month - 1, 1);
		return d.toLocaleDateString('en-GB', { month: 'short', year: 'numeric' });
	}

	/** Format a date string as "DD MMM YYYY" */
	function formatDate(isoDate: string | null): string {
		if (!isoDate) return '—';
		const d = new Date(isoDate);
		return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
	}

	// ---------------------------------------------------------------------------
	// PR distance label ordering
	// ---------------------------------------------------------------------------

	const PR_ORDER = ['1k', '5k', '10k', 'Half Marathon', 'Marathon'];

	function sortedPRs(records: PersonalRecord[]): PersonalRecord[] {
		return [...records].sort((a, b) => {
			const ai = PR_ORDER.findIndex((l) => l.toLowerCase() === a.distance_label.toLowerCase());
			const bi = PR_ORDER.findIndex((l) => l.toLowerCase() === b.distance_label.toLowerCase());
			const aIdx = ai === -1 ? 999 : ai;
			const bIdx = bi === -1 ? 999 : bi;
			return aIdx - bIdx;
		});
	}

	// ---------------------------------------------------------------------------
	// Chart rendering
	// ---------------------------------------------------------------------------

	function buildChart(data: WeeklyStats[]) {
		if (!canvasEl) return;

		// Take last 12 weeks
		const slice = data.slice(-12);
		const labels = slice.map((w) => formatWeekLabel(w.week_start));
		const values = slice.map((w) => w.total_km);

		if (chartInstance) {
			chartInstance.destroy();
			chartInstance = null;
		}

		chartInstance = new Chart(canvasEl, {
			type: 'bar',
			data: {
				labels,
				datasets: [
					{
						label: 'Weekly km',
						data: values,
						backgroundColor: 'rgba(59, 130, 246, 0.7)',
						borderColor: 'rgba(59, 130, 246, 1)',
						borderWidth: 1,
						borderRadius: 4
					}
				]
			},
			options: {
				responsive: true,
				maintainAspectRatio: false,
				plugins: {
					legend: { display: false },
					tooltip: {
						callbacks: {
							label: (ctx) => `${(ctx.raw as number).toFixed(1)} km`
						}
					}
				},
				scales: {
					x: {
						grid: { display: false },
						ticks: { font: { size: 11 } }
					},
					y: {
						beginAtZero: true,
						ticks: {
							font: { size: 11 },
							callback: (val) => `${val} km`
						},
						grid: { color: 'rgba(0,0,0,0.05)' }
					}
				}
			}
		});
	}

	// ---------------------------------------------------------------------------
	// Data loading
	// ---------------------------------------------------------------------------

	async function loadData() {
		loading = true;
		error = null;
		try {
			const profileId = $activeProfile;
			const [weekly, monthly, prs] = await Promise.all([
				statsApi.weekly(profileId),
				statsApi.monthly(profileId),
				// Cast to extended type since the API returns streak fields
				statsApi.prs(profileId) as unknown as PRsResponseExtended
			]);
			weeklyStats = weekly;
			monthlyStats = monthly;
			prsData = prs;
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load statistics.';
		} finally {
			loading = false;
		}
	}

	// ---------------------------------------------------------------------------
	// Lifecycle
	// ---------------------------------------------------------------------------

	onMount(async () => {
		await loadData();
		// Build chart after data is loaded and DOM is updated
		if (weeklyStats.length > 0) {
			// Use a microtask to ensure canvas is in the DOM
			await Promise.resolve();
			buildChart(weeklyStats);
		}
	});

	onDestroy(() => {
		if (chartInstance) {
			chartInstance.destroy();
			chartInstance = null;
		}
	});

	// Rebuild chart when weeklyStats changes (e.g. profile switch)
	$: if (!loading && weeklyStats.length > 0 && canvasEl) {
		buildChart(weeklyStats);
	}

	// Reload when active profile changes
	$: $activeProfile, loadData();
</script>

<!-- =========================================================================
     Template
     ========================================================================= -->

<div class="min-h-screen bg-gray-50 px-4 py-8">
	<div class="mx-auto max-w-5xl space-y-8">

		<!-- ------------------------------------------------------------------ -->
		<!-- Page header                                                          -->
		<!-- ------------------------------------------------------------------ -->
		<div>
			<h1 class="text-2xl font-bold text-gray-900">Statistics</h1>
			<p class="mt-1 text-sm text-gray-500">Your running performance at a glance.</p>
		</div>

		<!-- ------------------------------------------------------------------ -->
		<!-- Loading state                                                        -->
		<!-- ------------------------------------------------------------------ -->
		{#if loading}
			<div class="flex items-center justify-center py-20" role="status" aria-live="polite">
				<div
					class="h-10 w-10 animate-spin rounded-full border-4 border-blue-200 border-t-blue-600"
					aria-hidden="true"
				></div>
				<span class="ml-3 text-sm text-gray-500">Loading statistics…</span>
			</div>

		<!-- ------------------------------------------------------------------ -->
		<!-- Error state                                                          -->
		<!-- ------------------------------------------------------------------ -->
		{:else if error}
			<div
				class="rounded-xl border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700"
				role="alert"
			>
				<p class="font-semibold">Failed to load statistics</p>
				<p class="mt-1">{error}</p>
				<button
					type="button"
					on:click={loadData}
					class="mt-3 inline-flex items-center gap-1.5 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white
					       hover:bg-red-700 transition-colors focus:outline-none focus:ring-2 focus:ring-red-500"
				>
					↻ Retry
				</button>
			</div>

		{:else}

			<!-- -------------------------------------------------------------- -->
			<!-- Streak display                                                   -->
			<!-- -------------------------------------------------------------- -->
			{#if prsData}
				<div class="grid grid-cols-2 gap-4 sm:grid-cols-2">
					<!-- Current streak -->
					<div class="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm text-center">
						<div class="text-4xl font-bold text-blue-600">
							{prsData.current_streak}
						</div>
						<div class="mt-1 text-sm font-medium text-gray-700">Current Streak</div>
						<div class="mt-0.5 text-xs text-gray-400">consecutive weeks with a run</div>
					</div>

					<!-- All-time longest streak -->
					<div class="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm text-center">
						<div class="text-4xl font-bold text-emerald-600">
							{prsData.longest_streak}
						</div>
						<div class="mt-1 text-sm font-medium text-gray-700">All-Time Best Streak</div>
						<div class="mt-0.5 text-xs text-gray-400">consecutive weeks with a run</div>
					</div>
				</div>
			{/if}

			<!-- -------------------------------------------------------------- -->
			<!-- Weekly mileage bar chart                                         -->
			<!-- -------------------------------------------------------------- -->
			<div class="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
				<h2 class="mb-4 text-base font-semibold text-gray-900">Weekly Mileage</h2>
				{#if weeklyStats.length === 0}
					<p class="py-8 text-center text-sm text-gray-400">No weekly data available yet.</p>
				{:else}
					<div class="relative h-56">
						<canvas bind:this={canvasEl} aria-label="Weekly mileage bar chart" role="img"></canvas>
					</div>
				{/if}
			</div>

			<!-- -------------------------------------------------------------- -->
			<!-- Monthly summary cards                                            -->
			<!-- -------------------------------------------------------------- -->
			<div>
				<h2 class="mb-3 text-base font-semibold text-gray-900">Monthly Summary</h2>
				{#if monthlyStats.length === 0}
					<p class="rounded-2xl border border-gray-200 bg-white py-8 text-center text-sm text-gray-400 shadow-sm">
						No monthly data available yet.
					</p>
				{:else}
					<!-- Show last 6 months, most recent first -->
					<div class="grid grid-cols-2 gap-3 sm:grid-cols-3">
						{#each monthlyStats.slice(-6).reverse() as month (month.year + '-' + month.month)}
							<div class="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
								<div class="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">
									{formatMonthLabel(month.year, month.month)}
								</div>
								<div class="space-y-1.5">
									<div class="flex items-baseline justify-between">
										<span class="text-xs text-gray-500">Distance</span>
										<span class="text-sm font-semibold text-gray-900">
											{month.total_km.toFixed(1)} km
										</span>
									</div>
									<div class="flex items-baseline justify-between">
										<span class="text-xs text-gray-500">Time</span>
										<span class="text-sm font-medium text-gray-700">
											{formatDuration(month.total_duration_seconds)}
										</span>
									</div>
									<div class="flex items-baseline justify-between">
										<span class="text-xs text-gray-500">Runs</span>
										<span class="text-sm font-medium text-gray-700">{month.run_count}</span>
									</div>
								</div>
							</div>
						{/each}
					</div>
				{/if}
			</div>

			<!-- -------------------------------------------------------------- -->
			<!-- Personal records table                                           -->
			<!-- -------------------------------------------------------------- -->
			<div class="rounded-2xl border border-gray-200 bg-white shadow-sm">
				<div class="border-b border-gray-100 px-5 py-4">
					<h2 class="text-base font-semibold text-gray-900">Personal Records</h2>
				</div>

				{#if !prsData || prsData.records.length === 0}
					<p class="py-10 text-center text-sm text-gray-400">
						No personal records yet. Keep running!
					</p>
				{:else}
					<div class="overflow-x-auto">
						<table class="w-full text-sm" aria-label="Personal records">
							<thead>
								<tr class="border-b border-gray-100 bg-gray-50 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">
									<th class="px-5 py-3">Distance</th>
									<th class="px-5 py-3">Best Pace</th>
									<th class="px-5 py-3 hidden sm:table-cell">Date</th>
									<th class="px-5 py-3 hidden md:table-cell">Distance Run</th>
								</tr>
							</thead>
							<tbody class="divide-y divide-gray-100">
								{#each sortedPRs(prsData.records) as pr (pr.distance_label)}
									<tr class="hover:bg-gray-50 transition-colors">
										<td class="px-5 py-3.5 font-medium text-gray-900">
											{pr.distance_label}
										</td>
										<td class="px-5 py-3.5">
											{#if pr.avg_pace_sec_per_km !== null}
												<span class="font-semibold text-blue-600">
													{formatPace(pr.avg_pace_sec_per_km)}
												</span>
											{:else}
												<span class="text-gray-400">—</span>
											{/if}
										</td>
										<td class="px-5 py-3.5 text-gray-500 hidden sm:table-cell">
											{formatDate(pr.run_date)}
										</td>
										<td class="px-5 py-3.5 text-gray-500 hidden md:table-cell">
											{#if pr.distance_metres !== null}
												{(pr.distance_metres / 1000).toFixed(2)} km
											{:else}
												—
											{/if}
										</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{/if}
			</div>

		{/if}
		<!-- /else -->

	</div>
</div>
