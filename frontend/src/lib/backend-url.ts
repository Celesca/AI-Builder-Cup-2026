// Pure helper shared by the UI and the server-side proxy.

const SCHEME = /^(https?):\/\//i;

/**
 * Checks what the user typed and only adds what is missing:
 * - `https://host` and `http://host` are kept exactly as typed (a pasted double prefix is collapsed to one)
 * - `host:8000` or `host` gets `http://`, since a self-hosted backend is usually plain http
 * - empty means "use the server's default"; any other scheme, or text that is not an address, is rejected (null)
 */
export function normalizeBackendUrl(input: string): string | null {
	let text = input.trim();
	if (!text) return '';
	while (SCHEME.test(text.replace(SCHEME, ''))) text = text.replace(SCHEME, '');
	if (!SCHEME.test(text)) {
		if (/^[a-z][a-z0-9+.-]*:\/\//i.test(text)) return null; // ftp://, file://, ...
		text = `http://${text}`;
	}
	try {
		const url = new URL(text);
		return `${url.origin}${url.pathname.replace(/\/+$/, '')}`;
	} catch {
		return null;
	}
}

export type UploadTarget = { url: string } | { error: string };

/**
 * Where a video upload should go. The /api proxy is fine locally and in Docker, but a serverless host (Vercel) refuses
 * request bodies over 4.5 MB, so when the manager has chosen a backend address the browser sends the file straight to it.
 * An https page cannot send to an http address (mixed content), which is explained instead of failing silently.
 */
export function uploadTarget(path: string, backend: string, pageProtocol: string): UploadTarget {
	if (!backend) return { url: `/api/${path}` };
	if (pageProtocol === 'https:' && backend.startsWith('http:')) {
		return {
			error: `This page is on https, and browsers block uploads from it to ${backend} (plain http). Give the backend an https address, or run the dashboard locally.`
		};
	}
	return { url: `${backend}/${path}` };
}
