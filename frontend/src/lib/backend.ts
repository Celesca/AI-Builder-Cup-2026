// Calls to ai_backend through this app's /api proxy, and the bundled demo clips.
import { api, apiFetch, apiUpload, uploadBlocked, uploadUrl } from './api.svelte';
import type { BackendStatus, DemoClip, AnalysisResponse, Language, Rule } from './types';

export class BackendError extends Error {}

export async function detailOf(response: Response): Promise<string> {
	const body = await response.json().catch(() => null);
	const detail =
		body && typeof body === 'object' && 'detail' in body
			? (body as { detail: unknown }).detail
			: null;
	if (typeof detail === 'string') return detail;
	if (detail) return JSON.stringify(detail);
	return `${response.status} ${response.statusText}`.trim();
}

/** Error for a failed upload request: explains a hosting platform's body-size limit instead of printing "413". */
async function uploadFailure(response: Response): Promise<BackendError> {
	if (response.status === 413 && !api.uploadBase) {
		return new BackendError(
			'This hosting platform refuses uploads over 4.5 MB through the app. Give the backend an https address (set AI_BACKEND_URL to it) or enter it under Backend address, so the browser can send the file straight to it.'
		);
	}
	return new BackendError(await detailOf(response));
}

export async function fetchBackendStatus(fetcher: typeof fetch = apiFetch): Promise<BackendStatus> {
	try {
		const [lss, vlm] = await Promise.all([
			fetcher('/api/lss/status', { signal: AbortSignal.timeout(5000) }),
			fetcher('/api/vlm_action/status', { signal: AbortSignal.timeout(5000) })
		]);
		if (!lss.ok || !vlm.ok) {
			return {
				state: 'offline',
				keyConfigured: false,
				vlmModel: null,
				llmModel: null,
				detail: await detailOf(lss.ok ? vlm : lss)
			};
		}
		const k = await lss.json();
		const v = await vlm.json();
		const keyConfigured = Boolean(v.api_key_configured);
		return {
			state: 'online',
			keyConfigured,
			vlmModel: v.model ?? null,
			llmModel: k.model ?? null,
			detail: keyConfigured
				? 'Vision model and Gemba Kaizen LLM ready'
				: 'No OpenRouter key on the backend: only demo clips can be analysed'
		};
	} catch {
		return {
			state: 'offline',
			keyConfigured: false,
			vlmModel: null,
			llmModel: null,
			detail: 'The AI backend is not reachable'
		};
	}
}

export interface AnalyzeInput {
	file: File;
	rules: Rule[];
	language: Language;
	station: { name: string; cycleTime: string; taktTime: string };
	signal?: AbortSignal;
	fetcher?: typeof fetch;
}

/** The enabled rules as the backend's `rules` form field (a JSON list). */
function rulesField(rules: Rule[]): string {
	const enabled = rules
		.filter((r) => r.enabled)
		.map((r) => ({ id: r.id, prompt: r.prompt, severity: r.severity, threshold: r.threshold }));
	if (enabled.length === 0) throw new BackendError('Turn on at least one safety rule first.');
	return JSON.stringify(enabled);
}

/** Run the Safety Agent then the Gemba Kaizen Agent on an uploaded video. Takes about a minute for a short clip. */
export async function analyzeUpload(input: AnalyzeInput): Promise<AnalysisResponse> {
	const form = new FormData();
	form.append('file', input.file);
	form.append('rules', rulesField(input.rules));
	form.append('language', input.language);
	if (input.station.name.trim()) form.append('station_name', input.station.name.trim());
	for (const [field, value] of [
		['cycle_time_s', input.station.cycleTime],
		['takt_time_s', input.station.taktTime]
	] as const) {
		if (Number(value) > 0) form.append(field, String(Number(value)));
	}

	let response: Response;
	try {
		response = await (input.fetcher ?? apiFetch)('/api/analysis/analyze/upload', {
			method: 'POST',
			body: form,
			signal: input.signal
		});
	} catch (error) {
		if (error instanceof DOMException && error.name === 'AbortError') throw error;
		throw new BackendError(
			uploadBlocked() ?? 'Could not reach the AI backend. Is it running, or use a demo clip.'
		);
	}
	if (!response.ok) throw await uploadFailure(response);
	return (await response.json()) as AnalysisResponse;
}

export async function loadDemoClips(fetcher: typeof fetch = fetch): Promise<DemoClip[]> {
	try {
		const response = await fetcher('/demo/manifest.json');
		if (!response.ok) return [];
		const manifest = await response.json();
		return Array.isArray(manifest.clips) ? manifest.clips : [];
	} catch {
		return [];
	}
}

export async function loadDemoAnalysis(
	clip: DemoClip,
	fetcher: typeof fetch = fetch
): Promise<AnalysisResponse> {
	const response = await fetcher(clip.analysis);
	if (!response.ok)
		throw new BackendError(
			`The cached analysis for "${clip.title}" is missing (${clip.analysis}).`
		);
	return (await response.json()) as AnalysisResponse;
}

/** An H.264 MP4 copy of a video the browser cannot play, made by the backend (ffmpeg). Same timing as the original. */
export async function convertPreview(
	file: File,
	signal?: AbortSignal,
	fetcher: typeof fetch = apiUpload
): Promise<Blob> {
	const form = new FormData();
	form.append('file', file);
	let response: Response;
	try {
		response = await fetcher('/api/video/preview', { method: 'POST', body: form, signal });
	} catch (error) {
		if (error instanceof DOMException && error.name === 'AbortError') throw error;
		throw new BackendError(uploadBlocked() ?? 'Could not reach the AI backend.');
	}
	if (!response.ok) throw await uploadFailure(response);
	return response.blob();
}

// ---- annotated video ----------------------------------------------------------------------------------------------

/**
 * Where a long upload is in its life. Only `uploading` and `downloading` have real byte counts: while the backend works
 * (`processing`) it sends nothing back until the MP4 is ready.
 */
export type TransferPhase = 'uploading' | 'processing' | 'downloading';

export interface TransferProgress {
	phase: TransferPhase;
	loaded: number;
	/** null when the size is unknown (no content-length) */
	total: number | null;
}

export interface TransferResponse {
	status: number;
	statusText: string;
	header(name: string): string | null;
	body: Blob;
}

/** Sends a form and reports upload and download progress, which fetch cannot do for a request body. */
export type Transport = (
	url: string,
	form: FormData,
	options: { signal?: AbortSignal; onProgress?: (progress: TransferProgress) => void }
) => Promise<TransferResponse>;

export const xhrTransport: Transport = (url, form, { signal, onProgress }) =>
	new Promise((resolve, reject) => {
		const xhr = new XMLHttpRequest();
		xhr.open('POST', url);
		xhr.responseType = 'blob';
		const report = (phase: TransferPhase, loaded: number, total: number | null) =>
			onProgress?.({ phase, loaded, total });
		// Once the whole file is on the server and until the first byte comes back, the backend is working.
		// Some setups never fire upload.onload, so a complete progress event counts too.
		let sent = false;
		const uploaded = () => {
			if (sent) return;
			sent = true;
			report('processing', 0, null);
		};
		xhr.upload.onprogress = (e) => {
			if (sent) return;
			report('uploading', e.loaded, e.lengthComputable ? e.total : null);
			if (e.lengthComputable && e.total > 0 && e.loaded >= e.total) uploaded();
		};
		xhr.upload.onload = uploaded;
		xhr.onreadystatechange = () => {
			if (xhr.readyState !== XMLHttpRequest.HEADERS_RECEIVED) return;
			sent = true;
			const length = Number(xhr.getResponseHeader('content-length'));
			report('downloading', 0, length > 0 ? length : null);
		};
		xhr.onprogress = (e) => report('downloading', e.loaded, e.lengthComputable ? e.total : null);
		xhr.onload = () =>
			resolve({
				status: xhr.status,
				statusText: xhr.statusText,
				header: (name) => xhr.getResponseHeader(name),
				body: xhr.response as Blob
			});
		xhr.onerror = () => reject(new TypeError('Network request failed'));
		xhr.onabort = () => reject(new DOMException('Aborted', 'AbortError'));
		if (signal?.aborted) return reject(new DOMException('Aborted', 'AbortError'));
		signal?.addEventListener('abort', () => xhr.abort(), { once: true });
		report('uploading', 0, null);
		xhr.send(form);
	});

export interface AnnotateInput {
	file: File;
	rules: Rule[];
	/** Amber NEAR MISS boxes within this confidence below a rule's threshold (backend default 0.15) */
	nearMissMargin?: number;
	signal?: AbortSignal;
	onProgress?: (progress: TransferProgress) => void;
	transport?: Transport;
}

export interface AnnotatedVideo {
	video: Blob;
	safetyEvents: number | null;
	annotatedFrames: number | null;
}

/**
 * The uploaded video back from the backend with person boxes and the rule name drawn on every violation (red) and
 * near miss (amber). The backend runs the Safety Agent again, then draws and encodes, so this takes a little longer
 * than the analysis itself.
 */
export async function annotateUpload(input: AnnotateInput): Promise<AnnotatedVideo> {
	const form = new FormData();
	form.append('file', input.file);
	form.append('rules', rulesField(input.rules));
	// The boxes come from YOLO in the render step; the Safety Agent's own person count is not needed
	form.append('count_people', 'false');
	form.append('include_snapshots', 'false');
	form.append('max_descriptions', '0');

	const path = `safety/annotate/upload?near_miss_margin=${input.nearMissMargin ?? 0.15}`;
	const target = await uploadUrl(path);
	if ('error' in target) throw new BackendError(target.error);

	let response: TransferResponse;
	try {
		response = await (input.transport ?? xhrTransport)(target.url, form, {
			signal: input.signal,
			onProgress: input.onProgress
		});
	} catch (error) {
		if (error instanceof DOMException && error.name === 'AbortError') throw error;
		throw new BackendError(
			'Could not reach the AI backend, or the connection dropped while it worked.'
		);
	}
	if (response.status < 200 || response.status >= 300) {
		throw await uploadFailure(
			new Response(response.body, { status: response.status, statusText: response.statusText })
		);
	}
	const count = (name: string) => {
		const value = response.header(name);
		return value === null || value === '' || !Number.isFinite(Number(value)) ? null : Number(value);
	};
	return {
		video: response.body.type ? response.body : new Blob([response.body], { type: 'video/mp4' }),
		safetyEvents: count('x-safety-events'),
		annotatedFrames: count('x-annotated-frames')
	};
}
