// Calls to the Voice Agent endpoints of ai_backend (through the /api proxy) and the pure helpers around them.
import { apiFetch } from './api.svelte';
import { BackendError, detailOf } from './backend';
import type {
	ChatMessage,
	AnalysisResponse,
	Language,
	VoiceEngine,
	VoiceSource,
	VoiceStatus
} from './types';

/** BCP-47 tags for the browser's own speech engines */
export const BROWSER_LANG: Record<Language, string> = { en: 'en-US', th: 'th-TH', ja: 'ja-JP' };

export async function fetchVoiceStatus(
	fetcher: typeof fetch = apiFetch
): Promise<VoiceStatus | null> {
	try {
		const response = await fetcher('/api/voice/status', { signal: AbortSignal.timeout(5000) });
		return response.ok ? ((await response.json()) as VoiceStatus) : null;
	} catch {
		return null;
	}
}

/** The analysis without what the chatbot cannot use: frame snapshots and the per-frame timeline. */
export function trimAnalysis(result: AnalysisResponse | null): Record<string, unknown> {
	if (!result) return {};
	const { safety, lss, person_count } = result;
	return {
		lss,
		person_count,
		safety: {
			safety_events: safety.safety_events.map((e) => ({ ...e, snapshot: null })),
			activity: {
				summary: safety.activity.summary,
				segments: safety.activity.segments.map((s) => ({ ...s, snapshot: null }))
			}
		}
	};
}

export interface AskInput {
	message: string;
	history: Pick<ChatMessage, 'role' | 'text'>[];
	analysis: Record<string, unknown>;
	language: Language;
	signal?: AbortSignal;
	fetcher?: typeof fetch;
}

export interface AskResult {
	reply: string;
	sources: VoiceSource[];
	source: 'llm' | 'retrieval';
	model: string | null;
}

export async function askVoice(input: AskInput): Promise<AskResult> {
	let response: Response;
	try {
		response = await (input.fetcher ?? apiFetch)('/api/voice/chat', {
			method: 'POST',
			headers: { 'content-type': 'application/json' },
			signal: input.signal,
			body: JSON.stringify({
				message: input.message,
				history: input.history.slice(-6).map((m) => ({ role: m.role, content: m.text })),
				analysis: input.analysis,
				language: input.language
			})
		});
	} catch (error) {
		if (error instanceof DOMException && error.name === 'AbortError') throw error;
		throw new BackendError('Could not reach the AI backend. Is it running?');
	}
	if (!response.ok) throw new BackendError(await detailOf(response));
	return (await response.json()) as AskResult;
}

/** MP3 from ElevenLabs (or the voice database). Throws BackendError when the backend cannot speak. */
export async function fetchSpeech(
	text: string,
	fetcher: typeof fetch = apiFetch
): Promise<{ blob: Blob; engine: VoiceEngine }> {
	let response: Response;
	try {
		response = await fetcher('/api/voice/speak', {
			method: 'POST',
			headers: { 'content-type': 'application/json' },
			body: JSON.stringify({ text })
		});
	} catch {
		throw new BackendError('Could not reach the AI backend.');
	}
	if (!response.ok) throw new BackendError(await detailOf(response));
	return {
		blob: await response.blob(),
		engine: response.headers.get('x-voice-cache') === 'hit' ? 'database' : 'elevenlabs'
	};
}

export async function transcribe(
	audio: Blob,
	fetcher: typeof fetch = apiFetch
): Promise<{ text: string; language: string | null }> {
	const form = new FormData();
	form.append('file', audio, audio.type.includes('mp4') ? 'speech.mp4' : 'speech.webm');
	let response: Response;
	try {
		response = await fetcher('/api/voice/transcribe', { method: 'POST', body: form });
	} catch {
		throw new BackendError('Could not reach the AI backend.');
	}
	if (!response.ok) throw new BackendError(await detailOf(response));
	return (await response.json()) as { text: string; language: string | null };
}

export type Piece = { text: string } | { time: number; label: string };

/** Split a reply so 0:42 / 12:05 / 00:42 become buttons that seek the video. */
export function splitTimestamps(text: string): Piece[] {
	const pieces: Piece[] = [];
	let last = 0;
	for (const match of text.matchAll(/(?<![\d:])(\d{1,2}):([0-5]\d)(?![\d:])/g)) {
		const at = match.index ?? 0;
		if (at > last) pieces.push({ text: text.slice(last, at) });
		pieces.push({ time: Number(match[1]) * 60 + Number(match[2]), label: match[0] });
		last = at + match[0].length;
	}
	if (last < text.length) pieces.push({ text: text.slice(last) });
	return pieces;
}

/** The agent's opening line, in the report language. Not a model answer: it costs nothing. */
export const GREETING: Record<Language, { withAnalysis: string; withoutAnalysis: string }> = {
	en: {
		withAnalysis:
			'Hello. I have read this shift. Ask me about the waste, the safety incidents or what to change first, by voice or by typing.',
		withoutAnalysis:
			'Hello. No video is analysed yet, so I can only answer from the lean knowledge cards. Open a demo clip to ask about a real shift.'
	},
	th: {
		withAnalysis:
			'สวัสดีครับ ผมอ่านข้อมูลกะนี้แล้ว ถามเรื่องความสูญเปล่า เหตุการณ์ความปลอดภัย หรือสิ่งที่ควรปรับปรุงก่อนได้เลย พิมพ์หรือพูดก็ได้',
		withoutAnalysis:
			'สวัสดีครับ ยังไม่มีวิดีโอที่วิเคราะห์ ผมจึงตอบได้จากการ์ดความรู้ลีนเท่านั้น เปิดคลิปตัวอย่างเพื่อถามเกี่ยวกับกะจริง'
	},
	ja: {
		withAnalysis:
			'こんにちは。このシフトのデータを読みました。ムダ、安全インシデント、最初に改善すべきことなどを、音声または入力でご質問ください。',
		withoutAnalysis:
			'こんにちは。まだ分析された動画がないため、リーン知識カードからのみお答えできます。デモクリップを開くと実際のシフトについて質問できます。'
	}
};
