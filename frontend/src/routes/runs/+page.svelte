<script lang="ts">
	import { onMount } from 'svelte';
	import { activeProfile } from '$lib/stores';
	import { runsApi, statsApi, type Run, type PersonalRecord, type RunFilters } from '$lib/api';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let runs: Run[] = [];
	let prs: PersonalRecord[] = [];
	let loading = true;
	let error: string | null = null;

	// Filters
	let dateFrom = '';
	let dateTo = '';
	let runType = '';
	let minDistanceKm = '';
	let maxDistanceKm = '';

	// PR lookup: run_id → array of distance labels that run set a PR for
	let prByRunId = new Map<number, string[]>();

	// Run types for the filter dropdown
	const RUN_TYPES = [
		{ value: '', label: 'All types' },
		{ value: 'easy', label: 'Easy' },
		{ value: 'tempo', label: 'Tempo' },
		{ value: 'interval', label: 'Interval' },
		{ value: 'hills', label: 'Hills' },
		{ value: 'long', label: 'Long' },
		{ value: 'race', label: 'Race' },
		{ value: 'recovery', label: 'Recovery' }
	];

	// ---------------------------------------------------------------------------
	// Data loading
	// ---------------------------------------------------------------------------

	async function loadData() {
		loading = true;
		error = null;
		try {
			const filters: RunFilters = {};
			if (dateFrom) filters.date_from = dateFrom;
			if (dateTo) filters.date_to = dateTo;
			if (runType) filters.run_type = runType;
			const minKm = parseFloat(minDistanceKm);
			if (!isNaN(minKm) && minKm > 0) filters.min_distance_km = minKm;
			const maxKm = parseFloat(maxDistanceKm);
			if (!isNaN(maxKm) && maxKm > 0) filters.max_distance_km = maxKm;

			const [runsResult, prsResult] = await Promise.all([
				runsApi.list(filters),
				statsApi.prs()
			]);

			// Sort chronologically descending (most recent first)
			runs = runsResult.sort(
				(a, b) => new Date(b.date).getTime() - new Date(a.date).getTime()
			);

			prs = prsResult.records;

			// Build PR lookup map: run_id → [distance labels]
			prByRunId = new Map();
			for (const pr of prs) {
				if (pr.run_id !== null) {
					const existing = prByRunId.get(pr.run_id) ?? [];
					existing.push(pr.distance_label);
					prByRunId.set(pr.run_id, existing);
				}
			}
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load runs.';
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		loadData();
	});

	// Reload when active profile changes
	$: $activeProfile, loadData();

	// ---------------------------------------------------------------------------
	// Filter submission
	// ---------------------------------------------------------------------------

	function applyFilters() {
		loadData();
	}

	function clearFilters() {
		dateFrom = '';
		dateTo = '';
		runType = '';
		minDistanceKm = '';
		maxDistanceKm = '';
		loadData();
	}

	$: hasActiveFilters =
		dateFrom !== '' ||
		dateTo !== '' ||
		runType !== '' ||
		minDistanceKm !== '' ||
		maxDistanceKm !== '';

	// ---------------------------------------------------------------------------
	// Formatting helpers
	// ---------------------------------------------------------------------------

	function formatDate(dateStr: string): string {
		const d = new Date(dateStr + 'T00:00:00');
		return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
	}

	function formatDistanceKm(metres: number): string {
		return (metres / 1000).toFixed(2);
	}

	function formatPace(secPerKm: number | null): string {
		if (secPerKm === null) return '—';
		const mins = Math.floor(secPerKm / 60);
		const secs = Math.round(secPerKm % 60);
		return `${mins}:${secs.toString().padStart(2, '0')}`;
	}

	function formatHR(hr: number | null): string {
		if (hr === null) return '—';
		return `${hr} bpm`;
	}

	function formatElevation(metres: number | null): string {
		if (metres === null) return '—';
		return `${Math.round(metres)} m`;
	}

	function formatDuration(seconds: number): string {
		const h = Math.floor(seconds / 3600);
		const m = Math.floor((seconds % 3600) / 60);
		const s = seconds % 60;
		if (h > 0) {
			return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
		}
		return `${m}:${s.toString().padStart(2, '0')}`;
	}

	function runTypeLabel(type: string | null): string {
		if (!type) return '';
		return type.charAt(0).toUpperCase() + type.slice(1);
	}

	function runTypeBadgeClass(type: string | null): string {
		switch (type) {
			case 'easy':
				return 'bg-green-100 text-green-800';
			case 'tempo':
				return 'bg-orange-100 text-orange-800';
			case 'interval':
				return 'bg-red-100 text-red-800';
			case 'hills':
				return 'bg-amber-100 text-amber-800';
			case 'long':
				return 'bg-blue-100 text-blue-800';
			case 'race':
				return 'bg-purple-100 text-purple-800';
			case 'recovery':
				return 'bg-teal-100 text-teal-800';
			default:
				return 'bg-gray-100 text-gray-700';
		}
	}
</script>

<div class="p-4 sm:p-6 lg:p-8">
	<!-- Page header -->
	<div class="mb-6 flex flex-wrap items-center justify-between gap-3">
		<div>
			<h1 class="text-xl font-semibold text-gray-900">Run History</h1>
			<p class="mt-0.5 text-sm text-gray-500">
				{#if !loading}
					{runs.length} run{runs.length !== 1 ? 's' : ''}
					{#if hasActiveFilters}<span class="text-blue-600"> (filtered)</span>{/if}
				{/if}
			</p>
		</div>
		<a
			href="/runs/new"
			class="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white
			       hover:bg-blue-700 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500"
		>
			<span aria-hidden="true">+</span> Log Run
		</a>
	</div>

	<!-- Filters panel -->
	<div class="mb-6 rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
		<h2 class="mb-3 text-sm font-medium text-gray-700">Filters</h2>
		<div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
			<!-- Date from -->
			<div>
				<label for="filter-date-from" class="block text-xs font-medium text-gray-600 mb-1">
					From date
				</label>
				<input
					id="filter-date-from"
					type="date"
					bind:value={dateFrom}
					max={dateTo || undefined}
					class="block w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm
					       focus:outline-none focus:ring-2 focus:ring-blue-500"
				/>
			</div>

			<!-- Date to -->
			<div>
				<label for="filter-date-to" class="block text-xs font-medium text-gray-600 mb-1">
					To date
				</label>
				<input
					id="filter-date-to"
					type="date"
					bind:value={dateTo}
					min={dateFrom || undefined}
					class="block w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm
					       focus:outline-none focus:ring-2 focus:ring-blue-500"
				/>
			</div>

			<!-- Run type -->
			<div>
				<label for="filter-run-type" class="block text-xs font-medium text-gray-600 mb-1">
					Run type
				</label>
				<select
					id="filter-run-type"
					bind:value={runType}
					class="block w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm
					       focus:outline-none focus:ring-2 focus:ring-blue-500"
				>
					{#each RUN_TYPES as rt (rt.value)}
						<option value={rt.value}>{rt.label}</option>
					{/each}
				</select>
			</div>

			<!-- Min distance -->
			<div>
				<label for="filter-min-dist" class="block text-xs font-medium text-gray-600 mb-1">
					Min distance (km)
				</label>
				<input
					id="filter-min-dist"
					type="number"
					bind:value={minDistanceKm}
					min="0"
					step="0.1"
					placeholder="e.g. 5"
					class="block w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm
					       focus:outline-none focus:ring-2 focus:ring-blue-500"
				/>
			</div>

			<!-- Max distance -->
			<div>
				<label for="filter-max-dist" class="block text-xs font-medium text-gray-600 mb-1">
					Max distance (km)
				</label>
				<input
					id="filter-max-dist"
					type="number"
					bind:value={maxDistanceKm}
					min="0"
					step="0.1"
					placeholder="e.g. 21"
					class="block w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm
					       focus:outline-none focus:ring-2 focus:ring-blue-500"
				/>
			</div>
		</div>

		<!-- Filter actions -->
		<div class="mt-3 flex items-center gap-2">
			<button
				type="button"
				on:click={applyFilters}
				class="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white
				       hover:bg-blue-700 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500"
			>
				Apply
			</button>
			{#if hasActiveFilters}
				<button
					type="button"
					on:click={clearFilters}
					class="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700
					       hover:bg-gray-50 transition-colors focus:outline-none focus:ring-2 focus:ring-gray-400"
				>
					Clear filters
				</button>
			{/if}
		</div>
	</div>

	<!-- Loading state -->
	{#if loading}
		<div class="flex items-center justify-center py-16" role="status" aria-live="polite">
			<div
				class="h-8 w-8 animate-spin rounded-full border-4 border-blue-200 border-t-blue-600"
				aria-hidden="true"
			></div>
			<span class="ml-3 text-sm text-gray-500">Loading runs…</span>
		</div>

	<!-- Error state -->
	{:else if error}
		<div
			class="rounded-xl border border-red-200 bg-red-50 px-4 py-4 text-sm text-red-700"
			role="alert"
		>
			<p class="font-medium">Failed to load runs</p>
			<p class="mt-1">{error}</p>
			<button
				type="button"
				on:click={loadData}
				class="mt-3 rounded-lg bg-red-600 px-3 py-1.5 text-xs font-medium text-white
				       hover:bg-red-700 transition-colors focus:outline-none focus:ring-2 focus:ring-red-500"
			>
				Retry
			</button>
		</div>

	<!-- Empty state -->
	{:else if runs.length === 0}
		<div class="rounded-xl border border-gray-200 bg-white py-16 text-center shadow-sm">
			<span class="text-4xl" aria-hidden="true">🏃</span>
			<p class="mt-3 text-sm font-medium text-gray-700">
				{hasActiveFilters ? 'No runs match your filters.' : 'No runs logged yet.'}
			</p>
			{#if hasActiveFilters}
				<button
					type="button"
					on:click={clearFilters}
					class="mt-3 text-sm text-blue-600 hover:underline focus:outline-none"
				>
					Clear filters
				</button>
			{:else}
				<a
					href="/runs/new"
					class="mt-3 inline-block text-sm text-blue-600 hover:underline focus:outline-none"
				>
					Log your first run →
				</a>
			{/if}
		</div>

	<!-- Run list — desktop table -->
	{:else}
		<!-- Desktop table (hidden on small screens) -->
		<div class="hidden overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm sm:block">
			<table class="min-w-full divide-y divide-gray-200" aria-label="Run history">
				<thead class="bg-gray-50">
					<tr>
						<th
							scope="col"
							class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-gray-500"
						>
							Date
						</th>
						<th
							scope="col"
							class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-gray-500"
						>
							Type
						</th>
						<th
							scope="col"
							class="px-4 py-3 text-right text-xs font-medium uppercase tracking-wide text-gray-500"
						>
							Distance
						</th>
						<th
							scope="col"
							class="px-4 py-3 text-right text-xs font-medium uppercase tracking-wide text-gray-500"
						>
							Duration
						</th>
						<th
							scope="col"
							class="px-4 py-3 text-right text-xs font-medium uppercase tracking-wide text-gray-500"
						>
							Pace
						</th>
						<th
							scope="col"
							class="px-4 py-3 text-right text-xs font-medium uppercase tracking-wide text-gray-500"
						>
							Avg HR
						</th>
						<th
							scope="col"
							class="px-4 py-3 text-right text-xs font-medium uppercase tracking-wide text-gray-500"
						>
							Elevation
						</th>
						<th scope="col" class="px-4 py-3">
							<span class="sr-only">Actions</span>
						</th>
					</tr>
				</thead>
				<tbody class="divide-y divide-gray-100">
					{#each runs as run (run.id)}
						{@const runPRs = prByRunId.get(run.id) ?? []}
						<tr class="group hover:bg-gray-50 transition-colors">
							<!-- Date -->
							<td class="whitespace-nowrap px-4 py-3">
								<div class="flex items-center gap-2">
									<span class="text-sm font-medium text-gray-900">{formatDate(run.date)}</span>
									{#if runPRs.length > 0}
										<span
											class="inline-flex items-center gap-0.5 rounded-full bg-yellow-100 px-2 py-0.5 text-xs font-semibold text-yellow-800"
											title="Personal record: {runPRs.join(', ')}"
											aria-label="Personal record for {runPRs.join(', ')}"
										>
											🏅 PR
										</span>
									{/if}
								</div>
							</td>

							<!-- Run type -->
							<td class="whitespace-nowrap px-4 py-3">
								{#if run.run_type}
									<span
										class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium {runTypeBadgeClass(run.run_type)}"
									>
										{runTypeLabel(run.run_type)}
									</span>
								{:else}
									<span class="text-xs text-gray-400">—</span>
								{/if}
							</td>

							<!-- Distance -->
							<td class="whitespace-nowrap px-4 py-3 text-right">
								<span class="text-sm text-gray-900">{formatDistanceKm(run.distance_metres)}</span>
								<span class="text-xs text-gray-400"> km</span>
							</td>

							<!-- Duration -->
							<td class="whitespace-nowrap px-4 py-3 text-right">
								<span class="text-sm text-gray-700">{formatDuration(run.duration_seconds)}</span>
							</td>

							<!-- Pace -->
							<td class="whitespace-nowrap px-4 py-3 text-right">
								<span class="text-sm text-gray-700">{formatPace(run.avg_pace_sec_per_km)}</span>
								{#if run.avg_pace_sec_per_km !== null}
									<span class="text-xs text-gray-400"> /km</span>
								{/if}
							</td>

							<!-- Avg HR -->
							<td class="whitespace-nowrap px-4 py-3 text-right">
								<span class="text-sm text-gray-700">{formatHR(run.avg_heart_rate)}</span>
							</td>

							<!-- Elevation -->
							<td class="whitespace-nowrap px-4 py-3 text-right">
								<span class="text-sm text-gray-700">{formatElevation(run.elevation_gain_metres)}</span>
							</td>

							<!-- Actions -->
							<td class="whitespace-nowrap px-4 py-3 text-right">
								<div class="flex items-center justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
									<a
										href="/runs/{run.id}"
										class="rounded-md px-2 py-1 text-xs font-medium text-blue-600 hover:bg-blue-50 transition-colors
										       focus:outline-none focus:ring-2 focus:ring-blue-500"
									>
										Detail
									</a>
									<a
										href="/runs/{run.id}/analysis"
										class="rounded-md px-2 py-1 text-xs font-medium text-purple-600 hover:bg-purple-50 transition-colors
										       focus:outline-none focus:ring-2 focus:ring-purple-500"
									>
										Analysis
									</a>
								</div>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>

		<!-- Mobile card list (visible on small screens only) -->
		<ul class="space-y-3 sm:hidden" aria-label="Run history">
			{#each runs as run (run.id)}
				{@const runPRs = prByRunId.get(run.id) ?? []}
				<li class="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
					<!-- Header row: date + PR badge + type -->
					<div class="flex items-start justify-between gap-2">
						<div class="flex items-center gap-2 flex-wrap">
							<span class="text-sm font-semibold text-gray-900">{formatDate(run.date)}</span>
							{#if runPRs.length > 0}
								<span
									class="inline-flex items-center gap-0.5 rounded-full bg-yellow-100 px-2 py-0.5 text-xs font-semibold text-yellow-800"
									aria-label="Personal record for {runPRs.join(', ')}"
								>
									🏅 PR
								</span>
							{/if}
						</div>
						{#if run.run_type}
							<span
								class="shrink-0 inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium {runTypeBadgeClass(run.run_type)}"
							>
								{runTypeLabel(run.run_type)}
							</span>
						{/if}
					</div>

					<!-- Stats grid -->
					<dl class="mt-3 grid grid-cols-2 gap-x-4 gap-y-2">
						<div>
							<dt class="text-xs text-gray-500">Distance</dt>
							<dd class="text-sm font-medium text-gray-900">
								{formatDistanceKm(run.distance_metres)} km
							</dd>
						</div>
						<div>
							<dt class="text-xs text-gray-500">Duration</dt>
							<dd class="text-sm font-medium text-gray-900">{formatDuration(run.duration_seconds)}</dd>
						</div>
						<div>
							<dt class="text-xs text-gray-500">Pace</dt>
							<dd class="text-sm font-medium text-gray-900">
								{formatPace(run.avg_pace_sec_per_km)}
								{#if run.avg_pace_sec_per_km !== null}
									<span class="text-xs font-normal text-gray-500">/km</span>
								{/if}
							</dd>
						</div>
						<div>
							<dt class="text-xs text-gray-500">Avg HR</dt>
							<dd class="text-sm font-medium text-gray-900">{formatHR(run.avg_heart_rate)}</dd>
						</div>
						<div>
							<dt class="text-xs text-gray-500">Elevation</dt>
							<dd class="text-sm font-medium text-gray-900">{formatElevation(run.elevation_gain_metres)}</dd>
						</div>
					</dl>

					<!-- Links -->
					<div class="mt-3 flex items-center gap-3 border-t border-gray-100 pt-3">
						<a
							href="/runs/{run.id}"
							class="text-sm font-medium text-blue-600 hover:underline focus:outline-none"
						>
							View detail
						</a>
						<span class="text-gray-300" aria-hidden="true">·</span>
						<a
							href="/runs/{run.id}/analysis"
							class="text-sm font-medium text-purple-600 hover:underline focus:outline-none"
						>
							Analysis
						</a>
					</div>
				</li>
			{/each}
		</ul>
	{/if}
</div>
