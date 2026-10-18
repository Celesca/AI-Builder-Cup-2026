// The annotated copy of the loaded video (POST /safety/annotate/upload): person boxes with the rule name on every
// violation and near miss. The backend sends nothing while it works, which can take minutes, so this also keeps a
// heartbeat on the backend and the time spent in each phase, for the page to show that the job is alive.
import { browser } from '$app/env';
import { apiFetch } from './api.svelte';
import { annotateUpload, BackendError, type TransferPhase, type Transport } from './backend';
import type { Rule } from './types';

export type AnnotationState = 'idle' | 'preparing' | TransferPhase | 'done' | 'error' | 'cancelled';

/** How often the backend is asked whether it is still up while it works on the video */
export const HEARTBEAT_MS = 8000;

/** The rules that shape the drawing: when any changes, the annotated video is out of date. */
export function rulesSignature(rules: Rule[]): string {
	return JSON.stringify(
		rules.filter((r) => r.enabled).map((r) => [r.id, r.prompt, r.severity, r.threshold])
	);
}

export class Annotation {
	state = $state<AnnotationState>('idle');
	error = $state('');
	/** Bytes of the current transfer (upload, then download) */
	loaded = $state(0);
	total = $state<number | null>(null);
	/** Object URL of the annotated MP4 */
	url = $state<string | null>(null);
	size = $state(0);
	safetyEvents = $state<number | null>(null);
	annotatedFrames = $state<number | null>(null);
	/** Rules the video was drawn with, see rulesSignature */
	signature = $state('');
	/** Which video the players show when an annotated one exists */
	showing = $state<'original' | 'annotated'>('original');
	/** The annotated video came with a demo clip, it was not drawn now */
	cached = $state(false);

	/** Clock, so the elapsed times tick */
	now = $state(Date.now());
	startedAt = $state(0);
	phaseStartedAt = $state(0);
	finishedAt = $state(0);
	/** Per phase, how long it took, in seconds */
	durations = $state<Partial<Record<TransferPhase, number>>>({});

	heartbeat = $state<{ ok: boolean | null; at: number; misses: number }>({
		ok: null,
		at: 0,
		misses: 0
	});

	private abort: AbortController | null = null;
	private ticker: ReturnType<typeof setInterval> | undefined;
	private beater: ReturnType<typeof setInterval> | undefined;

	busy = $derived(['preparing', 'uploading', 'processing', 'downloading'].includes(this.state));
	elapsed = $derived(
		this.startedAt
			? Math.max(0, Math.round(((this.finishedAt || this.now) - this.startedAt) / 1000))
			: 0
	);
	phaseElapsed = $derived(
		this.phaseStartedAt ? Math.max(0, Math.round((this.now - this.phaseStartedAt) / 1000)) : 0
	);
	/** 0-1 for the transfers, null while the backend works (it reports nothing) */
	fraction = $derived(
		(this.state === 'uploading' || this.state === 'downloading') && this.total
			? Math.min(1, this.loaded / this.total)
			: null
	);
	/** Seconds since the backend last answered a heartbeat */
	sinceHeartbeat = $derived(
		this.heartbeat.at ? Math.max(0, Math.round((this.now - this.heartbeat.at) / 1000)) : null
	);
	/** The backend stopped answering while it should be working */
	backendSilent = $derived(this.state === 'processing' && this.heartbeat.misses >= 2);

	async run(
		getFile: () => Promise<File>,
		rules: Rule[],
		options: { nearMissMargin?: number; transport?: Transport } = {}
	) {
		if (this.busy) return;
		this.discard();
		this.error = '';
		this.durations = {};
		this.startedAt = this.phaseStartedAt = this.now = Date.now();
		this.finishedAt = 0;
		this.loaded = 0;
		this.total = null;
		this.state = 'preparing';
		this.heartbeat = { ok: null, at: 0, misses: 0 };
		this.abort = new AbortController();
		const signal = this.abort.signal;
		const signature = rulesSignature(rules);
		if (browser) this.ticker = setInterval(() => (this.now = Date.now()), 500);

		try {
			const file = await getFile();
			if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
			const result = await annotateUpload({
				file,
				rules,
				nearMissMargin: options.nearMissMargin,
				signal,
				transport: options.transport,
				onProgress: (p) => {
					if (p.phase !== this.state) this.enter(p.phase);
					this.loaded = p.loaded;
					this.total = p.total;
				}
			});
			this.url = URL.createObjectURL(result.video);
			this.size = result.video.size;
			this.safetyEvents = result.safetyEvents;
			this.annotatedFrames = result.annotatedFrames;
			this.signature = signature;
			this.enter('done');
			this.showing = 'annotated';
		} catch (error) {
			if (error instanceof DOMException && error.name === 'AbortError') {
				this.enter('cancelled');
			} else {
				this.error =
					error instanceof BackendError || error instanceof Error ? error.message : String(error);
				this.enter('error');
			}
		} finally {
			this.abort = null;
			this.stopTimers();
			this.finishedAt = Date.now();
		}
	}

	cancel() {
		this.abort?.abort();
	}

	/** Show a demo clip's pre-made annotated video: no backend, no wait. */
	useCached(url: string, signature: string) {
		this.reset();
		this.url = url;
		this.signature = signature;
		this.cached = true;
		this.state = 'done';
		this.showing = 'annotated';
	}

	/** Forget the annotated video (another source was loaded). */
	reset() {
		this.cancel();
		this.stopTimers();
		this.discard();
		this.state = 'idle';
		this.error = '';
		this.startedAt = this.phaseStartedAt = this.finishedAt = 0;
		this.durations = {};
	}

	private discard() {
		if (this.url && !this.cached) URL.revokeObjectURL(this.url);
		this.cached = false;
		this.url = null;
		this.size = 0;
		this.safetyEvents = this.annotatedFrames = null;
		this.signature = '';
		this.showing = 'original';
	}

	private enter(state: AnnotationState) {
		const now = Date.now();
		const previous = this.state;
		if (previous === 'uploading' || previous === 'processing' || previous === 'downloading') {
			this.durations = {
				...this.durations,
				[previous]: Math.round((now - this.phaseStartedAt) / 1000)
			};
		}
		this.state = state;
		this.phaseStartedAt = this.now = now;
		clearInterval(this.beater);
		if (state === 'processing' && browser) {
			void this.beat();
			this.beater = setInterval(() => void this.beat(), HEARTBEAT_MS);
		}
	}

	/** Ask the backend whether it is up: the annotate request itself is silent until the video is ready. */
	private async beat() {
		let ok = false;
		try {
			const response = await apiFetch('/api/health', { signal: AbortSignal.timeout(5000) });
			ok = response.ok;
		} catch {
			ok = false;
		}
		if (this.state !== 'processing') return;
		this.heartbeat = ok
			? { ok: true, at: Date.now(), misses: 0 }
			: { ok: false, at: this.heartbeat.at, misses: this.heartbeat.misses + 1 };
	}

	private stopTimers() {
		clearInterval(this.ticker);
		clearInterval(this.beater);
	}
}
