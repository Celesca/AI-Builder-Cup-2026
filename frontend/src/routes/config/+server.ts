// Tells the browser where it may send big uploads directly. A serverless host (Vercel) rejects request bodies over
// 4.5 MB, so the /api proxy cannot carry a video; when the server's backend has a public https address the browser
// uploads to it itself. A private address (http, or a Docker hostname) is never exposed: the proxy is used for it.
import { json } from '@sveltejs/kit';
import { AI_BACKEND_URL } from '$app/env/private';
import type { RequestHandler } from './$types';

export const GET: RequestHandler = () =>
	json({ uploadBackend: AI_BACKEND_URL.startsWith('https://') ? AI_BACKEND_URL : '' });
