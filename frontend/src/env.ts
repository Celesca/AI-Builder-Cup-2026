import { defineEnvVars } from '@sveltejs/kit/env';

export const variables = defineEnvVars({
	DATABASE_URL: {
		description: 'The database connection string (optional: only the Drizzle module needs it).',
		schema: (value) => value
	},
	AI_BACKEND_URL: {
		description:
			'Base URL of the ai_backend FastAPI service. The /api/* server routes proxy to it (server-side only).',
		schema: (value) => (value || 'http://localhost:8000').replace(/\/+$/, '')
	},
	ALLOW_BACKEND_OVERRIDE: {
		description:
			'Let the UI point the /api proxy at another ai_backend (x-backend-url header). Set to "false" on a public deployment.',
		schema: (value) => value !== 'false'
	}
});
