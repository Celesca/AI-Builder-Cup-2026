// Proxies /api/<path> to the ai_backend service (AI_BACKEND_URL), so the browser only talks to this app.
// Video uploads are streamed through, not buffered.
import { json } from '@sveltejs/kit';
import { AI_BACKEND_URL, ALLOW_BACKEND_OVERRIDE } from '$app/env/private';
import { normalizeBackendUrl } from '#lib/backend-url.ts';
import type { RequestHandler } from './$types';

// Only the ai_backend endpoints the dashboard uses (and their status / health routes) are exposed
const ALLOWED_PREFIXES = [
	'health',
	'analysis/',
	'safety/',
	'lss/',
	'vlm_action/',
	'person_count/',
	'voice/',
	'video/'
];
const FORWARDED_HEADERS = ['content-type', 'content-length', 'accept'];
// Sent back to the browser: the annotated video's counts, and its size so the download can show progress
const RETURNED_HEADERS = ['content-disposition', 'x-safety-events', 'x-annotated-frames'];

const proxy: RequestHandler = async ({ params, request, url }) => {
	const path = params.path;
	if (!ALLOWED_PREFIXES.some((prefix) => path === prefix || path.startsWith(prefix))) {
		return json({ detail: `Not an ai_backend route: /api/${path}` }, { status: 404 });
	}

	const headers = new Headers();
	for (const name of FORWARDED_HEADERS) {
		const value = request.headers.get(name);
		if (value) headers.set(name, value);
	}

	// A backend chosen in the UI (x-backend-url) replaces the server's default, unless the deployment forbids it
	let backend = AI_BACKEND_URL;
	const chosen = request.headers.get('x-backend-url');
	if (chosen) {
		if (!ALLOW_BACKEND_OVERRIDE)
			return json(
				{ detail: 'This deployment does not allow changing the backend.' },
				{ status: 403 }
			);
		const normalized = normalizeBackendUrl(chosen);
		if (!normalized) return json({ detail: `Not a valid backend URL: ${chosen}` }, { status: 400 });
		backend = normalized;
	}

	const hasBody = request.method !== 'GET' && request.method !== 'HEAD';
	try {
		const response = await fetch(`${backend}/${path}${url.search}`, {
			method: request.method,
			headers,
			body: hasBody ? request.body : undefined,
			// Required by Node's fetch to stream a request body
			duplex: hasBody ? 'half' : undefined
		} as RequestInit);
		const out = new Headers({
			'content-type': response.headers.get('content-type') ?? 'application/json'
		});
		for (const name of RETURNED_HEADERS) {
			const value = response.headers.get(name);
			if (value) out.set(name, value);
		}
		// fetch decodes a compressed body, so its length is only right for an uncompressed one
		const length = response.headers.get('content-length');
		if (length && !response.headers.get('content-encoding')) out.set('content-length', length);
		return new Response(response.body, { status: response.status, headers: out });
	} catch (error) {
		const reason = error instanceof Error ? error.message : String(error);
		return json({ detail: `AI backend unreachable at ${backend}: ${reason}` }, { status: 502 });
	}
};

export const GET = proxy;
export const POST = proxy;
