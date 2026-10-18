// The working session: the loaded source, the pipeline result, the manager's rules and their marks
// (incidents reviewed, Gemba Kaizen decisions). Rules, marks and preferences survive reloads on this device.
import { browser } from '$app/env';
import { api } from './api.svelte';
import { Annotation, rulesSignature } from './annotation.svelte';
import { deriveIncidents } from './analysis';
import {
	analyzeUpload,
	BackendError,
	convertPreview,
	fetchBackendStatus,
	loadDemoAnalysis,
	loadDemoClips
} from './backend';
import { releaseVideo } from './frames';
import { DEFAULT_RULES, loadRules, saveRules } from './rules';
import type {
	BackendStatus,
	DemoClip,
	Decision,
	AnalysisResponse,
	Language,
	Rule,
	SourceInfo
} from './types';

interface Marks {
	reviewed: Record<string, boolean>;
	decisions: Record<string, Decision>;
}

const PREFS_KEY = 'valz-prefs-v1';
const MARKS_KEY = 'valz-marks-v1';
const RUN_KEY = 'valz-run-v1';

function read<T>(storage: Storage, key: string, fallback: T): T {
	try {
		const raw = storage.getItem(key);
		return raw ? (JSON.parse(raw) as T) : fallback;
	} catch {
		return fallback;
	}
}

function write(storage: Storage, key: string, value: unknown) {
	try {
		storage.setItem(key, JSON.stringify(value));
	} catch {
		// quota or private mode: the value stays in memory
	}
}

export type RuleState = 'ready' | 'new' | 'changed';

class Session {
	clips = $state.raw<DemoClip[]>([]);
	backend = $state.raw<BackendStatus>({
		state: 'checking',
		keyConfigured: false,
		vlmModel: null,
		llmModel: null,
		detail: 'Checking the AI backend'
	});
	source = $state.raw<SourceInfo | null>(null);
	result = $state.raw<AnalysisResponse | null>(null);
	status = $state<'idle' | 'running' | 'done' | 'error'>('idle');
	error = $state('');
	elapsed = $state(0);
	rules = $state<Rule[]>(structuredClone(DEFAULT_RULES));
	language = $state<Language>('en');
	station = $state({ name: '', cycleTime: '', taktTime: '' });
	marks = $state<Record<string, Marks>>({});
	hydrated = $state(false);

	/** The annotated copy of the video (boxes + rule names), made on request by the backend */
	annotation = new Annotation();

	private abort: AbortController | null = null;
	private timer: ReturnType<typeof setInterval> | undefined;

	frames = $derived(this.result?.safety.activity.timeline ?? []);
	sampleFps = $derived(this.result?.safety.sample_fps ?? 1);
	duration = $derived(this.result?.safety.video_duration ?? 0);
	isDemo = $derived(this.source?.kind === 'demo');
	/** What the players show: the annotated video when there is one and it is chosen, otherwise the source */
	playUrl = $derived(
		this.annotation.showing === 'annotated' && this.annotation.url
			? this.annotation.url
			: (this.source?.url ?? null)
	);
	/** The annotated video was drawn with other rules than the ones on now */
	annotationStale = $derived(
		Boolean(this.annotation.url) && this.annotation.signature !== rulesSignature(this.rules)
	);
	incidents = $derived(
		this.result
			? deriveIncidents(this.frames, this.rules, this.sampleFps, this.result.safety.safety_events)
			: []
	);
	runKey = $derived(this.result?.lss.job_id ?? '');
	takt = $derived(this.result?.lss.context.takt_time_s ?? null);
	cycle = $derived(this.result?.lss.context.cycle_time_s ?? null);
	/** Enabled rules the current result cannot answer: new, or with an edited prompt. */
	staleRules = $derived(this.rules.filter((r) => r.enabled && this.ruleState(r) !== 'ready'));

	// ---- hydration ------------------------------------------------------------------------------------------

	async hydrate() {
		if (!browser || this.hydrated) return;
		api.hydrate();
		this.rules = loadRules();
		this.marks = read(localStorage, MARKS_KEY, {});
		const prefs = read<{
			language?: Language;
			station?: { name: string; cycleTime: string; taktTime: string };
		}>(localStorage, PREFS_KEY, {});
		if (prefs.language) this.language = prefs.language;
		if (prefs.station) this.station = prefs.station;
		this.clips = await loadDemoClips();
		this.hydrated = true;

		const saved = read<{
			source: Omit<SourceInfo, 'file' | 'url'>;
			result?: AnalysisResponse;
		} | null>(sessionStorage, RUN_KEY, null);
		if (saved?.source) {
			if (saved.source.kind === 'demo') {
				const clip = this.clips.find((c) => c.id === saved.source.id);
				if (clip) await this.selectDemo(clip);
			} else if (saved.result) {
				this.source = { ...saved.source, url: null, file: null };
				this.result = saved.result;
				this.status = 'done';
			}
		}
		void this.refreshBackend();
	}

	/** Point the app at another ai_backend ('' for the server's default) and re-check it. */
	async setBackendUrl(url: string) {
		api.set(url);
		this.backend = { ...this.backend, state: 'checking', detail: 'Checking the AI backend' };
		await this.refreshBackend();
	}

	async refreshBackend() {
		this.backend = await fetchBackendStatus();
	}

	savePrefs() {
		if (browser)
			write(localStorage, PREFS_KEY, {
				language: this.language,
				station: $state.snapshot(this.station)
			});
	}

	saveRulesNow() {
		if (browser) saveRules($state.snapshot(this.rules));
	}

	private persistRun() {
		if (!browser || !this.source) return;
		const { kind, id, name, synthetic, size } = this.source;
		const payload: { source: object; result?: AnalysisResponse } = {
			source: { kind, id, name, synthetic, size }
		};
		if (kind === 'upload' && this.result) payload.result = this.result;
		write(sessionStorage, RUN_KEY, payload);
	}

	// ---- source and run -----------------------------------------------------------------------------------------

	private clearRun() {
		this.cancel();
		this.annotation.reset();
		this.preview = { state: 'idle', error: '' };
		this.result = null;
		this.status = 'idle';
		this.error = '';
	}

	selectUpload(file: File) {
		this.dropSourceUrl();
		this.clearRun();
		this.source = {
			kind: 'upload',
			id: `upload-${Date.now()}`,
			name: file.name,
			url: URL.createObjectURL(file),
			file,
			synthetic: false,
			size: file.size
		};
		this.persistRun();
	}

	/** Give a restored upload its video back (its results survive a reload, the file does not). */
	reattachFile(file: File) {
		if (!this.source || this.source.kind !== 'upload') return;
		// Another video than the one analysed: its old results do not apply, start fresh
		const { name, size } = this.source;
		if (file.name !== name || (size !== undefined && file.size !== size))
			return this.selectUpload(file);
		this.dropSourceUrl();
		this.source = {
			...this.source,
			name: file.name,
			url: URL.createObjectURL(file),
			file,
			size: file.size
		};
	}

	async selectDemo(clip: DemoClip) {
		this.dropSourceUrl();
		this.clearRun();
		this.source = {
			kind: 'demo',
			id: clip.id,
			name: clip.title,
			url: clip.video,
			file: null,
			synthetic: Boolean(clip.synthetic)
		};
		if (clip.annotated) this.annotation.useCached(clip.annotated, rulesSignature(DEFAULT_RULES));
		await this.analyze();
	}

	clearSource() {
		this.dropSourceUrl();
		this.clearRun();
		this.source = null;
		if (browser) sessionStorage.removeItem(RUN_KEY);
	}

	/** Converting an upload the browser cannot play into a preview it can (the analysis itself never needs it). */
	preview = $state<{ state: 'idle' | 'converting' | 'error'; error: string }>({
		state: 'idle',
		error: ''
	});

	async convertPreview() {
		const source = this.source;
		if (!source?.file || this.preview.state === 'converting') return;
		this.preview = { state: 'converting', error: '' };
		try {
			const blob = await convertPreview(source.file);
			// The source may have changed while the backend worked
			if (this.source !== source) return;
			this.dropSourceUrl();
			this.source = { ...source, url: URL.createObjectURL(blob) };
			this.preview = { state: 'idle', error: '' };
		} catch (error) {
			this.preview = {
				state: 'error',
				error: error instanceof Error ? error.message : String(error)
			};
		}
	}

	private dropSourceUrl() {
		if (this.source?.kind === 'upload' && this.source.url) {
			releaseVideo(this.source.url);
			URL.revokeObjectURL(this.source.url);
		}
	}

	cancel() {
		this.abort?.abort();
		this.abort = null;
		clearInterval(this.timer);
	}

	async analyze() {
		const source = this.source;
		if (!source || this.status === 'running') return;
		this.error = '';
		this.status = 'running';
		this.elapsed = 0;
		const started = Date.now();
		this.timer = setInterval(() => (this.elapsed = Math.round((Date.now() - started) / 1000)), 500);
		try {
			let result: AnalysisResponse;
			if (source.kind === 'demo') {
				const clip = this.clips.find((c) => c.id === source.id);
				if (!clip) throw new BackendError('This demo clip is no longer in the manifest.');
				result = await loadDemoAnalysis(clip);
			} else {
				if (!source.file) throw new BackendError('The video file is not loaded: choose it again.');
				this.abort = new AbortController();
				result = await analyzeUpload({
					file: source.file,
					rules: this.rules,
					language: this.language,
					station: this.station,
					signal: this.abort.signal
				});
			}
			// Another video was loaded while this one ran (e.g. a demo still loading when a file is uploaded):
			// its result must not land on the new video
			if (this.source?.id !== source.id) return;
			this.result = result;
			this.status = 'done';
			this.persistRun();
		} catch (error) {
			if (this.source?.id !== source.id) return;
			if (error instanceof DOMException && error.name === 'AbortError') {
				this.status = 'idle';
			} else {
				this.status = 'error';
				this.error = error instanceof Error ? error.message : String(error);
			}
		} finally {
			if (this.source?.id === source.id) {
				clearInterval(this.timer);
				this.abort = null;
			}
		}
	}

	/** Ask the backend for the video with person boxes and rule names drawn on it. */
	async annotate() {
		const source = this.source;
		if (!source) return;
		await this.annotation.run(async () => {
			if (source.file) return source.file;
			if (source.kind === 'demo' && source.url) {
				const response = await fetch(source.url);
				if (!response.ok) throw new BackendError(`Could not read the demo video (${source.url}).`);
				const blob = await response.blob();
				return new File([blob], source.url.split('/').pop() || 'demo.mp4', {
					type: blob.type || 'video/mp4'
				});
			}
			throw new BackendError('The video file is not loaded: choose it again.');
		}, $state.snapshot(this.rules));
	}

	// ---- rules --------------------------------------------------------------------------------------------------

	ruleState(rule: Rule): RuleState {
		const used = this.result?.safety.rules.find((r) => r.id === rule.id);
		if (!used) return 'new';
		return used.prompt === rule.prompt ? 'ready' : 'changed';
	}

	updateRule(id: string, patch: Partial<Rule>) {
		const rule = this.rules.find((r) => r.id === id);
		if (rule) Object.assign(rule, patch);
		this.saveRulesNow();
	}

	addRule(rule: Rule) {
		this.rules.push(rule);
		this.saveRulesNow();
	}

	removeRule(id: string) {
		this.rules = this.rules.filter((r) => r.id !== id);
		this.saveRulesNow();
	}

	resetRules() {
		this.rules = structuredClone(DEFAULT_RULES);
		this.saveRulesNow();
	}

	// ---- marks --------------------------------------------------------------------------------------------------

	private marksFor(): Marks {
		return (this.marks[this.runKey] ??= { reviewed: {}, decisions: {} });
	}

	isReviewed(key: string): boolean {
		return Boolean(this.marks[this.runKey]?.reviewed[key]);
	}

	toggleReviewed(key: string) {
		const marks = this.marksFor();
		if (marks.reviewed[key]) delete marks.reviewed[key];
		else marks.reviewed[key] = true;
		this.saveMarks();
	}

	decisionFor(cardId: string): Decision | null {
		return this.marks[this.runKey]?.decisions[cardId] ?? null;
	}

	setDecision(cardId: string, decision: Decision | null) {
		const marks = this.marksFor();
		if (decision === null || marks.decisions[cardId] === decision) delete marks.decisions[cardId];
		else marks.decisions[cardId] = decision;
		this.saveMarks();
	}

	private saveMarks() {
		if (browser) write(localStorage, MARKS_KEY, $state.snapshot(this.marks));
	}
}

export const session = new Session();
