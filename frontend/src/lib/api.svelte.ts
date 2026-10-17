// Which ai_backend the app talks to. Empty means the server's own AI_BACKEND_URL. A URL chosen in the UI is sent
// with every /api request as the x-backend-url header, and the server-side proxy forwards to it.
import { browser } from '$app/env';
import { normalizeBackendUrl, uploadTarget } from './backend-url';

export { normalizeBackendUrl };

const KEY = 'valz-backend-url-v1';

class Api {
	url = $state('');
	/** The server's own backend when it is public https: uploads go there directly (see /config) */
	publicBackend = $state('');
	/** Settles once /config has been read, so an early upload does not pick the proxy by mistake */
	configReady: Promise<void> = Promise.resolve();

	/** Where uploads are sent directly, or '' to use the /api proxy */
	get uploadBase() {
		return this.url || this.publicBackend;
	}

	hydrate() {
		if (!browser) return;
		try {
			this.url = localStorage.getItem(KEY) ?? '';
		} catch {
			// private mode: the default backend is used
		}
		this.configReady = fetch('/config')
			.then((response) => (response.ok ? response.json() : null))
			.then((config) => (this.publicBackend = config?.uploadBackend ?? ''))
			.catch(() => {})
			.then(() => {});
	}

	set(url: string) {
		this.url = url;
		try {
			if (url) localStorage.setItem(KEY, url);
			else localStorage.removeItem(KEY);
		} catch {
			// the choice stays in memory
		}
	}
}

export const api = new Api();

/**
 * fetch for ai_backend calls: straight to the backend when it has a public address (the chosen one, or the server's
 * https AI_BACKEND_URL), otherwise through the /api proxy, with the chosen backend URL (if any) as a header.
 */
export const apiFetch: typeof fetch = async (input, init) => {
	await api.configReady;
	if (typeof input === 'string' && input.startsWith('/api/')) {
		const target = uploadTarget(
			input.replace(/^\/api\//, ''),
			api.uploadBase,
			browser ? location.protocol : 'http:'
		);
		if ('url' in target && api.uploadBase) return fetch(target.url, init);
	}
	if (!api.url) return fetch(input, init);
	const headers = new Headers(init?.headers);
	headers.set('x-backend-url', api.url);
	return fetch(input, { ...init, headers });
};

/**
 * fetch for video uploads, which can be hundreds of MB: straight to the chosen backend when there is one (the /api proxy
 * on a serverless host rejects bodies over 4.5 MB), otherwise through the /api proxy.
 */
export const apiUpload: typeof fetch = async (input, init) => {
	const target = await uploadUrl(String(input).replace(/^\/api\//, ''));
	if ('error' in target) throw new TypeError(target.error);
	return fetch(target.url, init);
};

/** The address an upload to ai_backend's `path` goes to (see apiUpload), for callers that cannot use fetch. */
export async function uploadUrl(path: string) {
	await api.configReady;
	return uploadTarget(path, api.uploadBase, browser ? location.protocol : 'http:');
}

export function uploadBlocked(): string | null {
	const target = uploadTarget('x', api.uploadBase, browser ? location.protocol : 'http:');
	return 'error' in target ? target.error : null;
}
