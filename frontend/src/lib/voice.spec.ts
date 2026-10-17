import { describe, expect, it, vi } from 'vitest';
import type { AnalysisResponse } from './types';
import { askVoice, fetchSpeech, splitTimestamps, trimAnalysis } from './voice';

describe('splitTimestamps', () => {
	it('turns mm:ss into seek pieces and keeps the text around them', () => {
		expect(splitTimestamps('It starts at 0:42 and ends 01:05.')).toEqual([
			{ text: 'It starts at ' },
			{ time: 42, label: '0:42' },
			{ text: ' and ends ' },
			{ time: 65, label: '01:05' },
			{ text: '.' }
		]);
	});

	it('leaves clock-like and numeric text alone', () => {
		expect(splitTimestamps('Saves 12:75 or 1:2:3 or 3.5 hours')).toEqual([
			{ text: 'Saves 12:75 or 1:2:3 or 3.5 hours' }
		]);
	});
});

describe('trimAnalysis', () => {
	it('drops snapshots and the per-frame timeline', () => {
		const result = {
			lss: { summary: 's' },
			person_count: null,
			safety: {
				safety_events: [{ rule_id: 'r', snapshot: 'data:image/jpeg;base64,AAA' }],
				activity: {
					summary: {},
					segments: [{ activity: 'a', snapshot: 'data:image/jpeg;base64,BBB' }],
					timeline: [{ timestamp: 0 }]
				}
			}
		} as unknown as AnalysisResponse;
		const text = JSON.stringify(trimAnalysis(result));
		expect(text).not.toContain('base64');
		expect(text).not.toContain('timeline');
		expect(trimAnalysis(null)).toEqual({});
	});
});

describe('backend calls', () => {
	it('sends the last turns and the language to /voice/chat', async () => {
		const fetcher = vi.fn(async () =>
			Response.json({ reply: 'ok', sources: [], source: 'retrieval', model: null })
		);
		const history = Array.from({ length: 9 }, (_, i) => ({
			role: i % 2 ? ('assistant' as const) : ('user' as const),
			text: `m${i}`
		}));
		await askVoice({ message: 'hi', history, analysis: {}, language: 'th', fetcher });
		const [url, init] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
		const body = JSON.parse(init.body as string);
		expect(url).toBe('/api/voice/chat');
		expect(body.language).toBe('th');
		expect(body.history).toHaveLength(6);
	});

	it('reports whether the speech came from the voice database', async () => {
		const fetcher = vi.fn(async () => new Response('mp3', { headers: { 'x-voice-cache': 'hit' } }));
		expect((await fetchSpeech('hello', fetcher)).engine).toBe('database');
	});

	it('surfaces the backend detail when speech fails', async () => {
		const fetcher = vi.fn(async () =>
			Response.json({ detail: 'ELEVENLABS_API_KEY is not set' }, { status: 503 })
		);
		await expect(fetchSpeech('hello', fetcher)).rejects.toThrow('ELEVENLABS_API_KEY is not set');
	});
});
