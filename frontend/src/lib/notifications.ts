/**
 * Web Push notification helpers.
 *
 * - registerServiceWorker()         — registers /service-worker.js
 * - requestNotificationPermission() — asks the browser for notification permission
 * - subscribeToWebPush(profileId)   — creates a Push subscription and sends it to the backend
 */

import { settingsApi } from './api';

// ---------------------------------------------------------------------------
// Service Worker registration
// ---------------------------------------------------------------------------

/**
 * Registers the service worker at /service-worker.js.
 * Safe to call multiple times — returns the existing registration if already registered.
 */
export async function registerServiceWorker(): Promise<ServiceWorkerRegistration | null> {
	if (!('serviceWorker' in navigator)) {
		console.warn('[notifications] Service workers are not supported in this browser.');
		return null;
	}

	try {
		const registration = await navigator.serviceWorker.register('/service-worker.js', {
			scope: '/'
		});
		console.info('[notifications] Service worker registered:', registration.scope);
		return registration;
	} catch (err) {
		console.error('[notifications] Service worker registration failed:', err);
		return null;
	}
}

// ---------------------------------------------------------------------------
// Notification permission
// ---------------------------------------------------------------------------

/**
 * Requests browser notification permission.
 * Returns the resulting permission state: "granted" | "denied" | "default".
 */
export async function requestNotificationPermission(): Promise<NotificationPermission> {
	if (!('Notification' in window)) {
		console.warn('[notifications] Notifications are not supported in this browser.');
		return 'denied';
	}

	if (Notification.permission !== 'default') {
		return Notification.permission;
	}

	const result = await Notification.requestPermission();
	console.info('[notifications] Permission result:', result);
	return result;
}

// ---------------------------------------------------------------------------
// Web Push subscription
// ---------------------------------------------------------------------------

/**
 * VAPID public key — must match the backend VAPID_PUBLIC_KEY env var.
 * Falls back to an empty string if the env var is not set (dev mode).
 */
const VAPID_PUBLIC_KEY: string =
	(typeof import.meta !== 'undefined' &&
		(import.meta as Record<string, unknown>).env &&
		((import.meta as Record<string, unknown>).env as Record<string, string>)
			.VITE_VAPID_PUBLIC_KEY) ||
	'';

function urlBase64ToUint8Array(base64String: string): Uint8Array {
	const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
	const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
	const rawData = atob(base64);
	return Uint8Array.from([...rawData].map((char) => char.charCodeAt(0)));
}

/**
 * Creates a Web Push subscription for the given profile and sends it to the backend.
 * Requires notification permission to already be granted.
 *
 * @param profileId - The profile to associate the subscription with.
 * @returns The PushSubscription object, or null on failure.
 */
export async function subscribeToWebPush(profileId: number): Promise<PushSubscription | null> {
	if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
		console.warn('[notifications] Push messaging is not supported in this browser.');
		return null;
	}

	if (Notification.permission !== 'granted') {
		console.warn('[notifications] Notification permission not granted — cannot subscribe.');
		return null;
	}

	if (!VAPID_PUBLIC_KEY) {
		console.warn('[notifications] VITE_VAPID_PUBLIC_KEY is not set — skipping push subscription.');
		return null;
	}

	try {
		const registration = await navigator.serviceWorker.ready;

		const subscription = await registration.pushManager.subscribe({
			userVisibleOnly: true,
			applicationServerKey: urlBase64ToUint8Array(VAPID_PUBLIC_KEY)
		});

		// Persist the subscription to the backend
		const subscriptionJson = subscription.toJSON() as Record<string, unknown>;
		await settingsApi.updateProfile(
			{
				notification_enabled: true,
				push_subscription: subscriptionJson
			},
			profileId
		);

		console.info('[notifications] Push subscription created and saved for profile', profileId);
		return subscription;
	} catch (err) {
		console.error('[notifications] Failed to subscribe to push:', err);
		return null;
	}
}
