<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { activeProfile } from '$lib/stores';
	import { analysisApi, type PostRunAnalysis, ApiError } from '$lib/api';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let loading = true;
	let error: string | null = null;
	let notFound = false;
	let analysis: PostRunAnalysis | null = null;

	// ---------------------------------------------------------------------------
	// Formatting helpers
	// ---------------------------------------------------------------------------

	function formatPace(secPerKm: number | null): string {
		if (secPerKm === null) return '—';
		const mins = Math.floor(secPerKm / 60);
		const secs = Math.round(secPerKm % 60);
		return `${mins}:${secs.toString().padStart(2, '0')}`;
	}

	function formatDistanceKm(km: number): string {
		return km.toFixed(2);
	}

	function formatElevation(metres: number | null): string {
		if (metres === null) return '—';
		return `${Math.round(metres)} m`;
	}

	function formatHR(hr: number | null): string {
		if (hr === null) return '—';
		return `${hr} bpm`;
	}

	// ---------------------------------------------------------------------------
	// Pace comparison styling
	// ---------------------------------------------------------------------------

	function paceComparisonLabel(comparison: string | null): string {
		switch (comparison) {
			case 'on_target':
				return 'On Target';
			case 'faster':
				return 'Faster';
			case 'slower':
				return 'Slower';
			default:
				return '—';
		}
	}

	function paceComparisonClasses(comparison: string | null): string {
		switch (comparison) {
			case 'on_target':
				return 'bg-green-100 text-green-800 border-green-200';
			case 'faster':
				return 'bg-blue-100 text-blue-800 border-blue-200';
			case 'slower':
				return 'bg-orange-100 text-orange-800 border-orange-200';
			default:
				return 'bg-gray-100 text-gray-600 border-gray-200';
		}
	}

	function paceComparisonIcon(comparison: string | null): string {
		switch (comparison) {
			case 'on_target':
				return '✓';
			case 'faster':
				return '↑';
			case 'slower':
				return '↓';
			default:
				return '—';
		}
	}

	// ---------------------------------------------------------------------------
	// Distance comparison helpers
	// ---------------------------------------------------------------------------

	function distanceDiffKm(target: number, actual: number): string {
		const diff = actual - target;
		const sign = diff >= 0 ? '+' : '';
		return `${sign}${diff.toFixed(2)} km`;
	}

	function distanceDiffClasses(target: number, actual: number): string {
		const diff = actual - target;
		const tolerance = 0.1; // 100 m tolerance
		if (Math.abs(diff) <= tolerance) return 'text-green-700';
		if (diff > 0) return 'text-blue-700';
		return 'text-orange-700';
	}

	// ---------------------------------------------------------------------------
	// Data loading
	// ---------------------------------------------------------------------------

	async function loadAnalysis(runId: number, profileId: number) {
		loading = true;
		error = null;
		notFound = false;
		analysis = null;

		try {
			analysis = await analysisApi.get(runId, profileId);
		} catch (e) {
			if (e instanceof ApiError && e.status === 404) {
				notFound = true;
			} else {
				error = e instanceof Error ? e.message : 'Failed to load analysis.';
			}
		} finally {
			loading = false;
		}
	}

	// ---------------------------------------------------------------------------
	// Lifecycle
	// ---------------------------------------------------------------------------

	onMount(() => {
		const idParam = $page.params.id;
		const runId = parseInt(idParam, 10);
		if (isNaN(runId)) {
			error = 'Invalid run ID.';
			loading = false;
			return;
		}
		loadAnalysis(runId, $activeProfile);
	});

	$: runId = $page.params.id;
</script>

<div class="p-4 sm:p-6 max-w-3xl mx-auto space-y-6">

	<!-- Navigation breadcrumb -->
	<nav aria-label="Breadcrumb" class="flex items-center gap-2 text-sm text-gray-500">
		<a
			href="/runs"
			class="hover:text-gray-700 transition-colors focus:outline-none focus:underline"
		>
			Runs
		</a>
		<span aria-hidden="true">›</span>
		<a
			href="/runs/{runId}"
			class="hover:text-gray-700 transition-colors focus:outline-none focus:underline"
		>
			Run #{runId}
		</a>
		<span aria-hidden="true">›</span>
		<span class="text-gray-900 font-medium">Analysis</span>
	</nav>

	<!-- Loading state -->
	{#if loading}
		<div class="flex items-center justify-center py-20" role="status" aria-live="polite">
			<div class="flex flex-col items-center gap-3 text-gray-500">
				<div
					class="h-8 w-8 animate-spin rounded-full border-4 border-gray-200 border-t-blue-600"
					aria-hidden="true"
				></div>
				<span class="text-sm">Loading analysis…</span>
			</div>
		</div>

	<!-- 404 — run not matched to a workout -->
	{:else if notFound}
		<div
			class="rounded-xl border border-gray-200 bg-white shadow-sm p-8 text-center"
			role="alert"
		>
			<span class="text-4xl" aria-hidden="true">📊</span>
			<h1 class="mt-4 text-lg font-semibold text-gray-800">No Analysis Available</h1>
			<p class="mt-2 text-sm text-gray-500 max-w-sm mx-auto">
				This run hasn't been matched to a planned workout yet, so there's no target data to
				compare against. Analysis is available for runs that correspond to a scheduled workout.
			</p>
			<div class="mt-6 flex items-center justify-center gap-4">
				<a
					href="/runs/{runId}"
					class="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white
					       hover:bg-blue-700 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500"
				>
					Back to Run
				</a>
				<a
					href="/runs"
					class="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700
					       hover:bg-gray-50 transition-colors focus:outline-none focus:ring-2 focus:ring-gray-400"
				>
					All Runs
				</a>
			</div>
		</div>

	<!-- Error state -->
	{:else if error}
		<div
			class="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700"
			role="alert"
		>
			<p class="font-medium">Failed to load analysis</p>
			<p class="mt-1">{error}</p>
			<button
				type="button"
				on:click={() => loadAnalysis(parseInt(runId, 10), $activeProfile)}
				class="mt-3 rounded-lg bg-red-600 px-3 py-1.5 text-xs font-medium text-white
				       hover:bg-red-700 transition-colors focus:outline-none focus:ring-2 focus:ring-red-500"
			>
				Retry
			</button>
		</div>

	{:else if analysis}
		<!-- Page heading -->
		<div>
			<h1 class="text-xl font-semibold text-gray-900">Post-Run Analysis</h1>
			<p class="mt-0.5 text-sm text-gray-500">
				Comparing your run against the planned workout
			</p>
		</div>

		<!-- =====================================================================
		     1. Distance Comparison
		     ===================================================================== -->
		<section
			class="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden"
			aria-label="Distance comparison"
		>
			<div class="px-5 py-3 border-b border-gray-100 bg-gray-50">
				<h2 class="text-sm font-semibold text-gray-700 uppercase tracking-wide">Distance</h2>
			</div>
			<div class="grid grid-cols-2 divide-x divide-gray-100 px-0">
				<div class="px-5 py-4">
					<p class="text-xs font-medium text-gray-400 uppercase tracking-wide">Target</p>
					<p class="mt-1 text-2xl font-bold text-gray-900">
						{formatDistanceKm(analysis.target_distance_km)}
						<span class="text-base font-normal text-gray-500">km</span>
					</p>
				</div>
				<div class="px-5 py-4">
					<p class="text-xs font-medium text-gray-400 uppercase tracking-wide">Actual</p>
					<p class="mt-1 text-2xl font-bold text-gray-900">
						{formatDistanceKm(analysis.actual_distance_km)}
						<span class="text-base font-normal text-gray-500">km</span>
					</p>
					<p
						class="mt-0.5 text-xs font-medium {distanceDiffClasses(analysis.target_distance_km, analysis.actual_distance_km)}"
						aria-label="Difference from target: {distanceDiffKm(analysis.target_distance_km, analysis.actual_distance_km)}"
					>
						{distanceDiffKm(analysis.target_distance_km, analysis.actual_distance_km)}
					</p>
				</div>
			</div>
		</section>

		<!-- =====================================================================
		     2. Pace Comparison
		     ===================================================================== -->
		<section
			class="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden"
			aria-label="Pace comparison"
		>
			<div class="px-5 py-3 border-b border-gray-100 bg-gray-50">
				<h2 class="text-sm font-semibold text-gray-700 uppercase tracking-wide">Pace</h2>
			</div>
			<div class="px-5 py-4 space-y-4">
				<div class="grid grid-cols-2 gap-4">
					<div>
						<p class="text-xs font-medium text-gray-400 uppercase tracking-wide">Target Zone</p>
						<p class="mt-1 text-lg font-semibold text-gray-900 capitalize">
							{analysis.target_pace_zone || '—'}
						</p>
					</div>
					<div>
						<p class="text-xs font-medium text-gray-400 uppercase tracking-wide">Actual Avg Pace</p>
						<p class="mt-1 text-lg font-semibold text-gray-900">
							{formatPace(analysis.actual_avg_pace_sec_per_km)}
							{#if analysis.actual_avg_pace_sec_per_km !== null}
								<span class="text-sm font-normal text-gray-500">/km</span>
							{/if}
						</p>
					</div>
				</div>

				<!-- Pace comparison badge -->
				{#if analysis.pace_comparison !== null}
					<div class="flex items-center gap-3">
						<span
							class="inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm font-semibold {paceComparisonClasses(analysis.pace_comparison)}"
							aria-label="Pace result: {paceComparisonLabel(analysis.pace_comparison)}"
						>
							<span aria-hidden="true">{paceComparisonIcon(analysis.pace_comparison)}</span>
							{paceComparisonLabel(analysis.pace_comparison)}
						</span>
						{#if analysis.pace_comparison === 'on_target'}
							<span class="text-sm text-gray-500">Great pacing — you hit your target zone!</span>
						{:else if analysis.pace_comparison === 'faster'}
							<span class="text-sm text-gray-500">You ran faster than the target zone.</span>
						{:else if analysis.pace_comparison === 'slower'}
							<span class="text-sm text-gray-500">You ran slower than the target zone.</span>
						{/if}
					</div>
				{:else}
					<p class="text-sm text-gray-400 italic">Pace data not available for this run.</p>
				{/if}
			</div>
		</section>

		<!-- =====================================================================
		     3. Heart Rate Zone Comparison
		     ===================================================================== -->
		<section
			class="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden"
			aria-label="Heart rate comparison"
		>
			<div class="px-5 py-3 border-b border-gray-100 bg-gray-50">
				<h2 class="text-sm font-semibold text-gray-700 uppercase tracking-wide">Heart Rate</h2>
			</div>
			<div class="grid grid-cols-2 divide-x divide-gray-100">
				<div class="px-5 py-4">
					<p class="text-xs font-medium text-gray-400 uppercase tracking-wide">Target HR Zone</p>
					<p class="mt-1 text-2xl font-bold text-gray-900">
						{#if analysis.target_hr_zone !== null}
							Zone {analysis.target_hr_zone}
						{:else}
							<span class="text-gray-400">—</span>
						{/if}
					</p>
				</div>
				<div class="px-5 py-4">
					<p class="text-xs font-medium text-gray-400 uppercase tracking-wide">Actual Avg HR</p>
					<p class="mt-1 text-2xl font-bold text-gray-900">
						{#if analysis.actual_avg_hr !== null}
							{analysis.actual_avg_hr}
							<span class="text-base font-normal text-gray-500">bpm</span>
						{:else}
							<span class="text-gray-400">—</span>
						{/if}
					</p>
				</div>
			</div>
		</section>

		<!-- =====================================================================
		     4. Elevation
		     ===================================================================== -->
		<section
			class="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden"
			aria-label="Elevation"
		>
			<div class="px-5 py-3 border-b border-gray-100 bg-gray-50">
				<h2 class="text-sm font-semibold text-gray-700 uppercase tracking-wide">Elevation</h2>
			</div>
			<div class="px-5 py-4 flex items-center gap-3">
				<span class="text-2xl" aria-hidden="true">⛰️</span>
				<div>
					<p class="text-xs font-medium text-gray-400 uppercase tracking-wide">Total Gain</p>
					<p class="mt-0.5 text-2xl font-bold text-gray-900">
						{formatElevation(analysis.actual_elevation_gain_metres)}
					</p>
				</div>
			</div>
		</section>

		<!-- =====================================================================
		     5. Per-km Splits Table
		     ===================================================================== -->
		{#if analysis.km_splits && analysis.km_splits.length > 0}
			<section
				class="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden"
				aria-label="Per-kilometre splits"
			>
				<div class="px-5 py-3 border-b border-gray-100 bg-gray-50">
					<h2 class="text-sm font-semibold text-gray-700 uppercase tracking-wide">
						Splits
					</h2>
				</div>
				<div class="overflow-x-auto">
					<table class="min-w-full divide-y divide-gray-100" aria-label="Per-kilometre splits">
						<thead class="bg-gray-50">
							<tr>
								<th
									scope="col"
									class="px-5 py-2.5 text-left text-xs font-medium uppercase tracking-wide text-gray-500"
								>
									Km
								</th>
								<th
									scope="col"
									class="px-5 py-2.5 text-right text-xs font-medium uppercase tracking-wide text-gray-500"
								>
									Pace
								</th>
								<th
									scope="col"
									class="px-5 py-2.5 text-right text-xs font-medium uppercase tracking-wide text-gray-500"
								>
									Avg HR
								</th>
							</tr>
						</thead>
						<tbody class="divide-y divide-gray-50">
							{#each analysis.km_splits as split (split.km)}
								<tr class="hover:bg-gray-50 transition-colors">
									<td class="whitespace-nowrap px-5 py-2.5">
										<span class="text-sm font-medium text-gray-900">{split.km}</span>
									</td>
									<td class="whitespace-nowrap px-5 py-2.5 text-right">
										<span class="text-sm text-gray-700">{formatPace(split.pace_sec_per_km)}</span>
										{#if split.pace_sec_per_km !== null}
											<span class="text-xs text-gray-400"> /km</span>
										{/if}
									</td>
									<td class="whitespace-nowrap px-5 py-2.5 text-right">
										<span class="text-sm text-gray-700">{formatHR(split.avg_hr)}</span>
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</section>
		{/if}

		<!-- =====================================================================
		     6. AI Coaching Summary
		     ===================================================================== -->
		{#if analysis.coaching_summary}
			<section
				class="rounded-xl border border-amber-100 bg-amber-50 p-5"
				aria-label="AI coaching summary"
			>
				<div class="flex items-start gap-3">
					<span class="text-2xl shrink-0" aria-hidden="true">🤖</span>
					<div>
						<h2 class="text-sm font-semibold text-amber-900 mb-2">Coaching Summary</h2>
						<p class="text-sm text-amber-800 leading-relaxed whitespace-pre-line">
							{analysis.coaching_summary}
						</p>
					</div>
				</div>
			</section>
		{/if}

		<!-- Back links -->
		<div class="flex items-center gap-4 pt-2 pb-4">
			<a
				href="/runs/{runId}"
				class="inline-flex items-center gap-1.5 text-sm font-medium text-blue-600
				       hover:text-blue-700 transition-colors focus:outline-none focus:underline"
			>
				← Back to Run
			</a>
			<span class="text-gray-300" aria-hidden="true">·</span>
			<a
				href="/runs"
				class="inline-flex items-center gap-1.5 text-sm font-medium text-gray-500
				       hover:text-gray-700 transition-colors focus:outline-none focus:underline"
			>
				All Runs
			</a>
		</div>
	{/if}
</div>
