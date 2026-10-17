import { describe, expect, it, vi } from 'vitest';
import {
	analyzeUpload,
	annotateUpload,
	BackendError,
	fetchBackendStatus,
	loadDemoClips,
	type TransferProgress,
	type Transport
} from './backend';
import { DEFAULT_RULES } from './rules';

const file = new File(['x'], 'clip.mp4', { type: 'video/mp4' });
const json = (body: unknown, status = 200) =>
	new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
const station = { name: ' WS10 ', cycleTime: '240', taktTime: '' };

describe('analyzeUpload', () => {
	it('sends only the enabled rules, the language and the station fields that are set', async () => {
		const fetcher = vi.fn(async () => json({ ok: true }));
		const rules = DEFAULT_RULES.map((r) => ({ ...r, enabled: r.id !== 'overhead' }));

		await analyzeUpload({
			file,
			rules,
			language: 'th',
			station,
			fetcher: fetcher as unknown as typeof fetch
		});

		const [url, init] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
		expect(url).toBe('/api/analysis/analyze/upload');
		const form = init.body as FormData;
		const sent = JSON.parse(form.get('rules') as string);
		expect(sent.map((r: { id: string }) => r.id)).toEqual([
			'lifting',
			'bending',
			'awkward_posture'
		]);
		expect(sent[0]).toEqual({
			id: 'lifting',
			prompt: DEFAULT_RULES[0].prompt,
			severity: 'medium',
			threshold: 0.6
		});
		expect(form.get('language')).toBe('th');
		expect(form.get('station_name')).toBe('WS10');
		expect(form.get('cycle_time_s')).toBe('240');
		expect(form.has('takt_time_s')).toBe(false);
	});

	it('refuses to run with every rule off', async () => {
		const rules = DEFAULT_RULES.map((r) => ({ ...r, enabled: false }));
		await expect(analyzeUpload({ file, rules, language: 'en', station })).rejects.toThrow(
			'at least one safety rule'
		);
	});

	it('surfaces the backend detail, and says so when it is unreachable', async () => {
		const down = vi.fn(async () =>
			json({ detail: 'VLM action detection is not available: OPENROUTER_API_KEY is not set' }, 503)
		);
		await expect(
			analyzeUpload({
				file,
				rules: DEFAULT_RULES,
				language: 'en',
				station,
				fetcher: down as unknown as typeof fetch
			})
		).rejects.toThrow('OPENROUTER_API_KEY is not set');

		const refused = vi.fn(async () => {
			throw new TypeError('fetch failed');
		});
		await expect(
			analyzeUpload({
				file,
				rules: DEFAULT_RULES,
				language: 'en',
				station,
				fetcher: refused as unknown as typeof fetch
			})
		).rejects.toBeInstanceOf(BackendError);
	});
});

describe('fetchBackendStatus', () => {
	it('reports a missing key', async () => {
		const fetcher = vi.fn(async (url: string) =>
			url.includes('lss')
				? json({ llm_configured: false, model: 'google/x' })
				: json({ api_key_configured: false, model: 'qwen/y' })
		);
		const status = await fetchBackendStatus(fetcher as unknown as typeof fetch);
		expect(status).toMatchObject({
			state: 'online',
			keyConfigured: false,
			vlmModel: 'qwen/y',
			llmModel: 'google/x'
		});
		expect(status.detail).toMatch(/only demo clips/);
	});

	it('reports offline when the proxy cannot reach the backend', async () => {
		const bad = vi.fn(async () =>
			json({ detail: 'AI backend unreachable at http://localhost:8000: fetch failed' }, 502)
		);
		expect((await fetchBackendStatus(bad as unknown as typeof fetch)).state).toBe('offline');
		const thrown = vi.fn(async () => {
			throw new TypeError('network');
		});
		expect((await fetchBackendStatus(thrown as unknown as typeof fetch)).state).toBe('offline');
	});
});

describe('loadDemoClips', () => {
	it('returns an empty list when the manifest is missing', async () => {
		expect(
			await loadDemoClips(
				vi.fn(async () => new Response('', { status: 404 })) as unknown as typeof fetch
			)
		).toEqual([]);
	});
});

describe('annotateUpload', () => {
	const reply = (status: number, body: Blob, headers: Record<string, string> = {}) =>
		({
			status,
			statusText: '',
			header: (name: string) => headers[name.toLowerCase()] ?? null,
			body
		}) as Awaited<ReturnType<Transport>>;

	it('sends the enabled rules, skips the extras, and reports each phase', async () => {
		const seen: TransferProgress['phase'][] = [];
		const transport = vi.fn<Transport>(async (_url, _form, { onProgress }) => {
			onProgress?.({ phase: 'uploading', loaded: 1, total: 1 });
			onProgress?.({ phase: 'processing', loaded: 0, total: null });
			onProgress?.({ phase: 'downloading', loaded: 3, total: 3 });
			return reply(200, new Blob(['mp4'], { type: 'video/mp4' }), {
				'x-safety-events': '2',
				'x-annotated-frames': '40'
			});
		});
		const result = await annotateUpload({
			file,
			rules: DEFAULT_RULES.map((r) => ({ ...r, enabled: r.id === 'bending' })),
			nearMissMargin: 0.1,
			transport,
			onProgress: (p) => seen.push(p.phase)
		});

		const [url, form] = transport.mock.calls[0];
		expect(url).toBe('/api/safety/annotate/upload?near_miss_margin=0.1');
		expect(JSON.parse(form.get('rules') as string).map((r: { id: string }) => r.id)).toEqual([
			'bending'
		]);
		expect(form.get('count_people')).toBe('false');
		expect(seen).toEqual(['uploading', 'processing', 'downloading']);
		expect(result).toMatchObject({ safetyEvents: 2, annotatedFrames: 40 });
		expect(result.video.type).toBe('video/mp4');
	});

	it('surfaces the backend detail and a dropped connection', async () => {
		const failing = vi.fn<Transport>(async () =>
			reply(
				503,
				new Blob([JSON.stringify({ detail: 'OPENROUTER_API_KEY is not set' })], {
					type: 'application/json'
				})
			)
		);
		await expect(
			annotateUpload({ file, rules: DEFAULT_RULES, transport: failing })
		).rejects.toThrow('OPENROUTER_API_KEY is not set');

		const dropped = vi.fn<Transport>(async () => {
			throw new TypeError('Network request failed');
		});
		await expect(
			annotateUpload({ file, rules: DEFAULT_RULES, transport: dropped })
		).rejects.toBeInstanceOf(BackendError);
	});
});
