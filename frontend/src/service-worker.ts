/**
 * Service Worker for the Personal Running Coach app.
 *
 * Handles:
 *   - push events:             show a notification with title + body from push data
 *   - notificationclick events: focus or open the app window
 */

/// <reference lib="webworker" />
declare const self: ServiceWorkerGlobalScope;

// ---------------------------------------------------------------------------
// Push event handler
// ---------------------------------------------------------------------------

self.addEventListener('push', (event: PushEvent) => {
	let title = 'Personal Running Coach';
	let body = 'You have a new notification.';
	let icon = '/favicon.png';
	let data: Record<string, unknown> = {};

	if (event.data) {
		try {
			const payload = event.data.json() as {
				title?: string;
				body?: string;
				icon?: string;
				data?: Record<string, unknown>;
			};
			if (payload.title) title = payload.title;
			if (payload.body) body = payload.body;
			if (payload.icon) icon = payload.icon;
			if (payload.data) data = payload.data;
		} catch {
			// Fallback: treat the raw text as the body
			body = event.data.text();
		}
	}

	const options: NotificationOptions = {
		body,
		icon,
		badge: '/favicon.png',
		data,
		requireInteraction: false
	};

	event.waitUntil(self.registration.showNotification(title, options));
});

// ---------------------------------------------------------------------------
// Notification click handler
// ---------------------------------------------------------------------------

self.addEventListener('notificationclick', (event: NotificationEvent) => {
	event.notification.close();

	// Try to focus an existing app window; open a new one if none is found.
	event.waitUntil(
		(self.clients as Clients)
			.matchAll({ type: 'window', includeUncontrolled: true })
			.then((clientList) => {
				for (const client of clientList) {
					if ('focus' in client) {
						return (client as WindowClient).focus();
					}
				}
				if (self.clients.openWindow) {
					return self.clients.openWindow('/');
				}
			})
	);
});
