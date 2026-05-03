import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [sveltekit()],

	test: {
		// Vitest configuration for unit tests
		include: ['src/**/*.{test,spec}.{js,ts}'],
		environment: 'jsdom',
		globals: true,
		setupFiles: []
	},

	server: {
		// Development server proxy — forwards API calls to the backend
		proxy: {
			'/api': {
				target: 'http://localhost:8000',
				changeOrigin: true
			},
			'/health': {
				target: 'http://localhost:8000',
				changeOrigin: true
			}
		}
	}
});
