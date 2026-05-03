<script lang="ts">
	import '../app.css';
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { activeProfile } from '$lib/stores';
	import { profilesApi } from '$lib/api';
	import { registerServiceWorker, requestNotificationPermission } from '$lib/notifications';
	import type { Profile } from '$lib/api';

	// Navigation links
	const navLinks = [
		{ href: '/', label: 'Dashboard', icon: '🏠' },
		{ href: '/plan', label: 'Plan', icon: '📅' },
		{ href: '/runs', label: 'Runs', icon: '🏃' },
		{ href: '/stats', label: 'Stats', icon: '📊' },
		{ href: '/zones', label: 'Zones', icon: '⚡' },
		{ href: '/settings', label: 'Settings', icon: '⚙️' }
	];

	let profiles: Profile[] = [];
	let notificationPermission: NotificationPermission = 'default';
	let sidebarOpen = false;

	onMount(async () => {
		// Register service worker
		await registerServiceWorker();

		// Check notification permission state
		if ('Notification' in window) {
			notificationPermission = Notification.permission;
		}

		// Load both profiles for the switcher
		try {
			profiles = await profilesApi.list();
		} catch {
			// Fallback: show placeholder names if API is unavailable
			profiles = [
				{ id: 1, display_name: 'Profile 1', date_of_birth: null, biological_sex: null, current_weekly_km: null, longest_recent_run_km: null, injury_notes: null, created_at: null, updated_at: null },
				{ id: 2, display_name: 'Profile 2', date_of_birth: null, biological_sex: null, current_weekly_km: null, longest_recent_run_km: null, injury_notes: null, created_at: null, updated_at: null }
			];
		}
	});

	function switchProfile(id: number) {
		activeProfile.set(id);
	}

	async function grantNotifications() {
		const result = await requestNotificationPermission();
		notificationPermission = result;
	}

	function isActive(href: string): boolean {
		if (href === '/') return $page.url.pathname === '/';
		return $page.url.pathname.startsWith(href);
	}
</script>

<div class="flex h-screen overflow-hidden bg-gray-50 text-gray-900">
	<!-- Mobile overlay -->
	{#if sidebarOpen}
		<button
			class="fixed inset-0 z-20 bg-black/40 lg:hidden"
			aria-label="Close sidebar"
			on:click={() => (sidebarOpen = false)}
		></button>
	{/if}

	<!-- Sidebar -->
	<aside
		class="fixed inset-y-0 left-0 z-30 flex w-64 flex-col bg-white shadow-lg transition-transform duration-200
		       {sidebarOpen ? 'translate-x-0' : '-translate-x-full'} lg:relative lg:translate-x-0"
	>
		<!-- App title -->
		<div class="flex items-center gap-2 border-b border-gray-200 px-5 py-4">
			<span class="text-xl" aria-hidden="true">🏃</span>
			<span class="text-base font-semibold leading-tight">Personal Running Coach</span>
		</div>

		<!-- Profile switcher -->
		<div class="border-b border-gray-200 px-4 py-3">
			<p class="mb-2 text-xs font-medium uppercase tracking-wide text-gray-500">Profile</p>
			<div class="flex flex-col gap-1">
				{#each profiles as profile (profile.id)}
					<button
						class="flex items-center gap-2 rounded-lg px-3 py-2 text-sm transition-colors
						       {$activeProfile === profile.id
							? 'bg-blue-600 text-white font-medium'
							: 'text-gray-700 hover:bg-gray-100'}"
						on:click={() => switchProfile(profile.id)}
						aria-pressed={$activeProfile === profile.id}
					>
						<span
							class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold
							       {$activeProfile === profile.id ? 'bg-white/20 text-white' : 'bg-gray-200 text-gray-600'}"
						>
							{profile.id}
						</span>
						<span class="truncate">{profile.display_name}</span>
						{#if $activeProfile === profile.id}
							<span class="ml-auto text-xs opacity-75">Active</span>
						{/if}
					</button>
				{/each}
			</div>
		</div>

		<!-- Navigation -->
		<nav class="flex-1 overflow-y-auto px-3 py-3" aria-label="Main navigation">
			<ul class="space-y-0.5">
				{#each navLinks as link (link.href)}
					<li>
						<a
							href={link.href}
							class="flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-colors
							       {isActive(link.href)
								? 'bg-blue-50 text-blue-700 font-medium'
								: 'text-gray-700 hover:bg-gray-100'}"
							aria-current={isActive(link.href) ? 'page' : undefined}
							on:click={() => (sidebarOpen = false)}
						>
							<span class="text-base" aria-hidden="true">{link.icon}</span>
							{link.label}
						</a>
					</li>
				{/each}
			</ul>
		</nav>
	</aside>

	<!-- Main content area -->
	<div class="flex flex-1 flex-col overflow-hidden">
		<!-- Top bar (mobile) -->
		<header class="flex items-center gap-3 border-b border-gray-200 bg-white px-4 py-3 lg:hidden">
			<button
				class="rounded-md p-1.5 text-gray-600 hover:bg-gray-100"
				aria-label="Open sidebar"
				on:click={() => (sidebarOpen = true)}
			>
				<svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16" />
				</svg>
			</button>
			<span class="text-sm font-semibold">Personal Running Coach</span>
		</header>

		<!-- Notification permission banner -->
		{#if notificationPermission === 'default'}
			<div
				class="flex items-center justify-between gap-4 bg-amber-50 px-4 py-3 text-sm text-amber-800 border-b border-amber-200"
				role="alert"
			>
				<div class="flex items-center gap-2">
					<span aria-hidden="true">🔔</span>
					<span>Enable notifications to get workout reminders.</span>
				</div>
				<div class="flex shrink-0 gap-2">
					<button
						class="rounded-md bg-amber-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-amber-700 transition-colors"
						on:click={grantNotifications}
					>
						Enable
					</button>
					<button
						class="rounded-md px-3 py-1.5 text-xs font-medium text-amber-700 hover:bg-amber-100 transition-colors"
						on:click={() => (notificationPermission = 'denied')}
					>
						Dismiss
					</button>
				</div>
			</div>
		{/if}

		<!-- Page content -->
		<main class="flex-1 overflow-y-auto">
			<slot />
		</main>
	</div>
</div>
