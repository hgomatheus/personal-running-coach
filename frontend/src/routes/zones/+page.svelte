<script lang="ts">
	import { onMount } from 'svelte';
	import { activeProfile } from '$lib/stores';
	import { zonesApi, type PaceZones, type HRZones } from '$lib/api';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let loading = true;
	let error: string | null = null;

	let paceZones: PaceZones | null = null;
	let hrZones: HRZones | null = null;

	// Recalculate form
	const PRESET_DISTANCES = [
		{ label: '1 km', metres: 1000 },
		{ label: '5 km', metres: 5000 },
		{ label: '10 km', metres: 10000 },
		{ label: 'Half Marathon', metres: 21097 },
		{ label: 'Marathon', metres: 42195 }
	];

	let raceDistancePreset: number | 'custom' = 5000;
	let raceDistanceCustomKm = '';
	let raceTimeInput = ''; // hh:mm:ss or mm:ss
	let formErrors: Record<string, string> = {};
	let recalculating = false;
	let recalcError: string | null = null;
	let recalcSuccess: { vdot: number } | null = null;

	// ---------------------------------------------------------------------------
	// Derived
	// ---------------------------------------------------------------------------

	$: raceDistanceMetres = (() => {
		if (raceDistancePreset === 'custom') {
			const km = parseFloat(raceDistanceCustomKm);
			return isNaN(km) || km <= 0 ? null : Math.round(km * 1000);
		}
		return raceDistancePreset as number;
	})();

	// ---------------------------------------------------------------------------
	// Helpers
	// ---------------------------------------------------------------------------

	/** Format seconds-per-km as "M:SS /km" */
	function formatPace(secPerKm: number | null): string {
		if (secPerKm === null) return '—';
		const mins = Math.floor(secPerKm / 60);
		const secs = Math.round(secPerKm % 60);
		return `${mins}:${secs.toString().padStart(2, '0')} /km`;
	}

	/** Format a pace range as "M:SS – M:SS /km" */
	function formatPaceRange(minSec: number | null, maxSec: number | null): string {
		if (minSec === null && maxSec === null) return '—';
		if (minSec === null) return `< ${formatPace(maxSec)}`;
		if (maxSec === null) return `> ${formatPace(minSec)}`;
		return `${formatPace(minSec)} – ${formatPace(maxSec)}`;
	}

	/** Parse "hh:mm:ss" or "mm:ss" into total seconds, or null on failure */
	function parseTimeInput(raw: string): number | null {
		const trimmed = raw.trim();
		const parts = trimmed.split(':');
		if (parts.length === 2) {
			const [mm, ss] = parts.map(Number);
			if (isNaN(mm) || isNaN(ss) || ss < 0 || ss >= 60 || mm < 0) return null;
			return mm * 60 + ss;
		}
		if (parts.length === 3) {
			const [hh, mm, ss] = parts.map(Number);
			if (isNaN(hh) || isNaN(mm) || isNaN(ss) || ss < 0 || ss >= 60 || mm < 0 || mm >= 60 || hh < 0) return null;
			return hh * 3600 + mm * 60 + ss;
		}
		return null;
	}

	/** HR zone bpm range string */
	function hrZoneRange(zoneNum: number, zones: HRZones): string {
		const maxHr = zones.max_hr;
		const boundaries = [
			Math.round(maxHr * 0.5),  // zone 1 min
			zones.zone1_max,           // zone 1 max / zone 2 min
			zones.zone2_max,           // zone 2 max / zone 3 min
			zones.zone3_max,           // zone 3 max / zone 4 min
			zones.zone4_max,           // zone 4 max / zone 5 min
			zones.zone5_max            // zone 5 max
		];
		const low = boundaries[zoneNum - 1];
		const high = boundaries[zoneNum];
		return `${low}–${high} bpm`;
	}

	// ---------------------------------------------------------------------------
	// Pace zone definitions
	// ---------------------------------------------------------------------------

	interface PaceZoneDef {
		key: string;
		label: string;
		intensity: string;
		description: string;
		color: string;
		badgeColor: string;
		getRange: (z: PaceZones) => string;
	}

	const PACE_ZONE_DEFS: PaceZoneDef[] = [
		{
			key: 'easy',
			label: 'Easy',
			intensity: '62–70% VDOT',
			description: 'Conversational pace. You should be able to hold a full conversation. Used for recovery and base building.',
			color: 'border-green-200 bg-green-50',
			badgeColor: 'bg-green-100 text-green-800',
			getRange: (z) => formatPaceRange(z.easy_min_sec_per_km, z.easy_max_sec_per_km)
		},
		{
			key: 'moderate',
			label: 'Moderate',
			intensity: '75–84% VDOT',
			description: 'Comfortable but purposeful. Marathon race pace for most runners. Builds aerobic base.',
			color: 'border-blue-200 bg-blue-50',
			badgeColor: 'bg-blue-100 text-blue-800',
			getRange: (z) => formatPaceRange(z.moderate_min_sec_per_km, z.moderate_max_sec_per_km)
		},
		{
			key: 'threshold',
			label: 'Threshold',
			intensity: '86–88% VDOT',
			description: 'Comfortably hard. Sustainable for 20–60 minutes. Improves lactate threshold.',
			color: 'border-orange-200 bg-orange-50',
			badgeColor: 'bg-orange-100 text-orange-800',
			getRange: (z) => formatPaceRange(z.threshold_min_sec_per_km, z.threshold_max_sec_per_km)
		},
		{
			key: 'vo2max',
			label: 'VO₂ Max',
			intensity: '95–100% VDOT',
			description: 'Hard effort. Sustainable for 3–8 minutes. Improves maximal oxygen uptake.',
			color: 'border-red-200 bg-red-50',
			badgeColor: 'bg-red-100 text-red-800',
			getRange: (z) => formatPaceRange(z.vo2max_min_sec_per_km, z.vo2max_max_sec_per_km)
		},
		{
			key: 'anaerobic',
			label: 'Anaerobic',
			intensity: '>105% VDOT',
			description: 'Very hard, near-maximal effort. Short bursts only. Builds speed and power.',
			color: 'border-purple-200 bg-purple-50',
			badgeColor: 'bg-purple-100 text-purple-800',
			getRange: (z) => formatPaceRange(z.anaerobic_min_sec_per_km, z.anaerobic_max_sec_per_km)
		}
	];

	// ---------------------------------------------------------------------------
	// HR zone definitions
	// ---------------------------------------------------------------------------

	interface HRZoneDef {
		num: number;
		label: string;
		pctRange: string;
		description: string;
		color: string;
		badgeColor: string;
	}

	const HR_ZONE_DEFS: HRZoneDef[] = [
		{
			num: 1,
			label: 'Zone 1',
			pctRange: '50–60% max HR',
			description: 'Very easy. Active recovery and warm-up.',
			color: 'border-teal-200 bg-teal-50',
			badgeColor: 'bg-teal-100 text-teal-800'
		},
		{
			num: 2,
			label: 'Zone 2',
			pctRange: '60–70% max HR',
			description: 'Easy aerobic. Fat burning, base building.',
			color: 'border-green-200 bg-green-50',
			badgeColor: 'bg-green-100 text-green-800'
		},
		{
			num: 3,
			label: 'Zone 3',
			pctRange: '70–80% max HR',
			description: 'Aerobic. Improves cardiovascular efficiency.',
			color: 'border-yellow-200 bg-yellow-50',
			badgeColor: 'bg-yellow-100 text-yellow-800'
		},
		{
			num: 4,
			label: 'Zone 4',
			pctRange: '80–90% max HR',
			description: 'Threshold. Improves lactate threshold and race pace.',
			color: 'border-orange-200 bg-orange-50',
			badgeColor: 'bg-orange-100 text-orange-800'
		},
		{
			num: 5,
			label: 'Zone 5',
			pctRange: '90–100% max HR',
			description: 'Maximum effort. Improves VO₂ max and speed.',
			color: 'border-red-200 bg-red-50',
			badgeColor: 'bg-red-100 text-red-800'
		}
	];

	// ---------------------------------------------------------------------------
	// Data loading
	// ---------------------------------------------------------------------------

	async function loadZones(profileId: number) {
		loading = true;
		error = null;
		paceZones = null;
		hrZones = null;

		try {
			const data = await zonesApi.get(profileId);
			paceZones = data.pace_zones;
			hrZones = data.hr_zones;
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load zones. Please try again.';
		} finally {
			loading = false;
		}
	}

	// ---------------------------------------------------------------------------
	// Recalculate form
	// ---------------------------------------------------------------------------

	function validateForm(): boolean {
		const errs: Record<string, string> = {};

		if (raceDistancePreset === 'custom') {
			const km = parseFloat(raceDistanceCustomKm);
			if (!raceDistanceCustomKm || isNaN(km) || km <= 0) {
				errs.distance = 'Please enter a valid race distance greater than 0 km.';
			}
		}

		if (!raceTimeInput.trim()) {
			errs.time = 'Race time is required.';
		} else {
			const secs = parseTimeInput(raceTimeInput);
			if (secs === null || secs <= 0) {
				errs.time = 'Please enter a valid time in mm:ss or hh:mm:ss format.';
			}
		}

		formErrors = errs;
		return Object.keys(errs).length === 0;
	}

	async function handleRecalculate() {
		if (!validateForm()) return;

		const distMetres = raceDistanceMetres;
		const durationSecs = parseTimeInput(raceTimeInput);

		if (!distMetres || durationSecs === null) return;

		recalculating = true;
		recalcError = null;
		recalcSuccess = null;

		try {
			const result = await zonesApi.recalculate(
				{ distance_metres: distMetres, duration_seconds: durationSecs },
				$activeProfile
			);
			paceZones = result.pace_zones;
			hrZones = result.hr_zones;
			recalcSuccess = { vdot: result.vdot };
		} catch (e) {
			recalcError = e instanceof Error ? e.message : 'Recalculation failed. Please try again.';
		} finally {
			recalculating = false;
		}
	}

	// ---------------------------------------------------------------------------
	// Lifecycle
	// ---------------------------------------------------------------------------

	let mounted = false;

	onMount(() => {
		mounted = true;
		loadZones($activeProfile);
	});

	$: if (mounted) {
		loadZones($activeProfile);
	}
</script>

<div class="p-4 sm:p-6 max-w-4xl mx-auto space-y-8">

	<!-- Page header -->
	<div class="flex items-center justify-between">
		<div>
			<h1 class="text-2xl font-bold text-gray-900">Training Zones</h1>
			<p class="mt-1 text-sm text-gray-500">
				Your personalised pace and heart rate zones based on your fitness level.
			</p>
		</div>
		{#if !loading}
			<button
				class="text-sm text-blue-600 hover:text-blue-800 transition-colors"
				on:click={() => loadZones($activeProfile)}
				aria-label="Refresh zones"
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
				<span class="text-sm">Loading your zones…</span>
			</div>
		</div>

	<!-- Error state -->
	{:else if error}
		<div class="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700" role="alert">
			{error}
		</div>

	{:else}

		<!-- ================================================================== -->
		<!-- VDOT badge (if available)                                           -->
		<!-- ================================================================== -->
		{#if paceZones?.vdot != null}
			<div
				class="flex items-center gap-4 rounded-xl border border-blue-200 bg-gradient-to-r from-blue-50 to-indigo-50 p-4"
				role="region"
				aria-label="VDOT score"
			>
				<div
					class="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-blue-600 text-white"
					aria-hidden="true"
				>
					<span class="text-lg font-bold">{paceZones.vdot.toFixed(1)}</span>
				</div>
				<div>
					<p class="text-xs font-medium uppercase tracking-wide text-blue-500">VDOT Score</p>
					<p class="text-base font-semibold text-blue-900">
						Your current fitness score is <strong>{paceZones.vdot.toFixed(1)}</strong>
					</p>
					<p class="text-sm text-blue-700">
						Higher is better. Use the form below to update it from a recent race result.
					</p>
				</div>
			</div>
		{/if}

		<!-- ================================================================== -->
		<!-- Pace Zones                                                          -->
		<!-- ================================================================== -->
		<section aria-labelledby="pace-zones-heading">
			<h2 id="pace-zones-heading" class="mb-4 text-lg font-semibold text-gray-900 flex items-center gap-2">
				<span aria-hidden="true">⚡</span> Pace Zones
			</h2>

			{#if !paceZones}
				<div
					class="rounded-xl border-2 border-dashed border-gray-200 bg-white p-8 text-center text-sm text-gray-500"
					role="region"
					aria-label="No pace zones"
				>
					<span class="text-3xl block mb-2" aria-hidden="true">📏</span>
					No pace zones calculated yet. Use the form below to calculate them from a race result.
				</div>
			{:else}
				<div class="space-y-3" role="list" aria-label="Pace zones">
					{#each PACE_ZONE_DEFS as zone (zone.key)}
						<div
							class="rounded-xl border p-4 {zone.color}"
							role="listitem"
							aria-label="{zone.label} pace zone"
						>
							<div class="flex flex-wrap items-start justify-between gap-3">
								<div class="flex items-center gap-3 min-w-0">
									<span
										class="shrink-0 rounded-full px-2.5 py-0.5 text-xs font-semibold {zone.badgeColor}"
									>
										{zone.label}
									</span>
									<span class="text-xs text-gray-500">{zone.intensity}</span>
								</div>
								<div class="shrink-0 text-right">
									<span class="text-base font-bold text-gray-900 font-mono">
										{zone.getRange(paceZones)}
									</span>
								</div>
							</div>
							<p class="mt-2 text-sm text-gray-600">{zone.description}</p>
						</div>
					{/each}
				</div>
			{/if}
		</section>

		<!-- ================================================================== -->
		<!-- Heart Rate Zones                                                    -->
		<!-- ================================================================== -->
		<section aria-labelledby="hr-zones-heading">
			<h2 id="hr-zones-heading" class="mb-4 text-lg font-semibold text-gray-900 flex items-center gap-2">
				<span aria-hidden="true">❤️</span> Heart Rate Zones
			</h2>

			{#if !hrZones}
				<div
					class="rounded-xl border-2 border-dashed border-gray-200 bg-white p-8 text-center text-sm text-gray-500"
					role="region"
					aria-label="No heart rate zones"
				>
					<span class="text-3xl block mb-2" aria-hidden="true">💓</span>
					No heart rate zones available. HR zones are calculated when a max HR is known.
				</div>
			{:else}
				<div class="mb-3 flex items-center gap-2 text-sm text-gray-500">
					<span aria-hidden="true">📊</span>
					Based on max HR of <strong class="text-gray-800">{hrZones.max_hr} bpm</strong>
				</div>
				<div class="space-y-3" role="list" aria-label="Heart rate zones">
					{#each HR_ZONE_DEFS as zone (zone.num)}
						<div
							class="rounded-xl border p-4 {zone.color}"
							role="listitem"
							aria-label="{zone.label} heart rate zone"
						>
							<div class="flex flex-wrap items-start justify-between gap-3">
								<div class="flex items-center gap-3 min-w-0">
									<span
										class="shrink-0 rounded-full px-2.5 py-0.5 text-xs font-semibold {zone.badgeColor}"
									>
										{zone.label}
									</span>
									<span class="text-xs text-gray-500">{zone.pctRange}</span>
								</div>
								<div class="shrink-0 text-right">
									<span class="text-base font-bold text-gray-900 font-mono">
										{hrZoneRange(zone.num, hrZones)}
									</span>
								</div>
							</div>
							<p class="mt-2 text-sm text-gray-600">{zone.description}</p>
						</div>
					{/each}
				</div>
			{/if}
		</section>

		<!-- ================================================================== -->
		<!-- Recalculate from Race Result                                        -->
		<!-- ================================================================== -->
		<section aria-labelledby="recalculate-heading">
			<div class="rounded-2xl border border-gray-200 bg-white shadow-sm">
				<div class="border-b border-gray-100 px-6 py-4">
					<h2 id="recalculate-heading" class="text-lg font-semibold text-gray-900 flex items-center gap-2">
						<span aria-hidden="true">🏁</span> Recalculate from Race Result
					</h2>
					<p class="mt-1 text-sm text-gray-500">
						Enter a recent race result to update your VDOT score and recalculate all training zones.
					</p>
				</div>

				<form
					class="p-6 space-y-5"
					on:submit|preventDefault={handleRecalculate}
					aria-label="Recalculate zones form"
					novalidate
				>
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
							       {formErrors.distance ? 'border-red-400 bg-red-50' : 'border-gray-300 bg-white'}"
							aria-required="true"
							aria-describedby={formErrors.distance ? 'distance-error' : undefined}
							aria-invalid={!!formErrors.distance}
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
									       {formErrors.distance ? 'border-red-400 bg-red-50' : 'border-gray-300 bg-white'}"
									aria-label="Custom race distance in kilometres"
									aria-required="true"
								/>
								<span class="shrink-0 text-sm text-gray-500">km</span>
							</div>
						{/if}

						{#if formErrors.distance}
							<p id="distance-error" class="mt-1 text-xs text-red-600" role="alert">
								{formErrors.distance}
							</p>
						{/if}
					</div>

					<!-- Race time -->
					<div>
						<label for="race-time" class="block text-sm font-medium text-gray-700">
							Race time <span class="text-red-500" aria-hidden="true">*</span>
						</label>
						<input
							id="race-time"
							type="text"
							bind:value={raceTimeInput}
							placeholder="e.g. 25:30 or 1:45:00"
							autocomplete="off"
							class="mt-1 block w-full rounded-lg border px-3 py-2 text-sm shadow-sm transition-colors
							       focus:outline-none focus:ring-2 focus:ring-blue-500
							       {formErrors.time ? 'border-red-400 bg-red-50' : 'border-gray-300 bg-white'}"
							aria-required="true"
							aria-describedby="race-time-hint {formErrors.time ? 'time-error' : ''}"
							aria-invalid={!!formErrors.time}
						/>
						<p id="race-time-hint" class="mt-1 text-xs text-gray-400">
							Format: mm:ss (e.g. 25:30) or hh:mm:ss (e.g. 1:45:00)
						</p>
						{#if formErrors.time}
							<p id="time-error" class="mt-1 text-xs text-red-600" role="alert">
								{formErrors.time}
							</p>
						{/if}
					</div>

					<!-- API error -->
					{#if recalcError}
						<div
							class="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
							role="alert"
						>
							{recalcError}
						</div>
					{/if}

					<!-- Success message -->
					{#if recalcSuccess}
						<div
							class="rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-800"
							role="status"
							aria-live="polite"
						>
							<p class="font-semibold text-green-900">✅ Zones updated!</p>
							<p class="mt-0.5">
								Your new VDOT score is <strong>{recalcSuccess.vdot.toFixed(1)}</strong>.
								All training zones have been recalculated.
							</p>
						</div>
					{/if}

					<!-- Submit -->
					<div class="flex justify-end">
						<button
							type="submit"
							disabled={recalculating}
							class="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-medium text-white
							       hover:bg-blue-700 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500
							       disabled:opacity-60 disabled:cursor-not-allowed"
							aria-busy={recalculating}
						>
							{#if recalculating}
								<span
									class="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white"
									aria-hidden="true"
								></span>
								Recalculating…
							{:else}
								🔄 Recalculate Zones
							{/if}
						</button>
					</div>
				</form>
			</div>
		</section>

	{/if}
</div>
