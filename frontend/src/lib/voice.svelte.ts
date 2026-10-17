// The Voice Agent's conversation: messages, speaking (ElevenLabs, with the browser's voice as a fallback)
// and the microphone. One instance is shared so the chat survives moving between pages.
import { browser } from '$app/env';
import { session } from './session.svelte';
import type { ChatMessage, VoiceEngine, VoiceStatus } from './types';
import {
	askVoice,
	BROWSER_LANG,
	fetchSpeech,
	fetchVoiceStatus,
	GREETING,
	transcribe,
	trimAnalysis
} from './voice';

const CHAT_KEY = 'valz-voice-chat-v1';
const PREF_KEY = 'valz-voice-prefs-v1';

// Voice activity detection for the recorder: stop after the user has spoken and then gone quiet
const VAD_POLL_MS = 100;
const VAD_CALIBRATE_MS = 300; // measure the room's noise level before judging speech
const VAD_MIN_LEVEL = 0.05; // RMS floor for "speech", whatever the room noise
const VAD_SILENCE_MS = 1200; // quiet after speech that ends the recording
const VAD_NO_SPEECH_MS = 5000; // give up when nobody starts talking
const VAD_MAX_MS = 30000;
const RESUME_DELAY_MS = 400; // let the speaker's tail fade so the mic does not hear the agent
const MAX_EMPTY_ROUNDS = 3; // hands-free stops after this many rounds without speech

type SpeechRecognitionLike = {
	lang: string;
	interimResults: boolean;
	onresult: ((event: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
	onerror: ((event: { error: string }) => void) | null;
	onend: (() => void) | null;
	start(): void;
	stop(): void;
};

function recognitionCtor(): (new () => SpeechRecognitionLike) | null {
	if (!browser) return null;
	const w = window as unknown as Record<string, new () => SpeechRecognitionLike>;
	return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

function readJson<T>(key: string, fallback: T): T {
	try {
		const raw = sessionStorage.getItem(key);
		return raw ? (JSON.parse(raw) as T) : fallback;
	} catch {
		return fallback;
	}
}

class VoiceChat {
	messages = $state<ChatMessage[]>([]);
	status = $state.raw<VoiceStatus | null>(null);
	statusChecked = $state(false);
	busy = $state(false);
	error = $state('');
	/** Why the last spoken clip came from the browser's voice, if it did */
	speechNote = $state('');
	speakReplies = $state(true);
	/** Message being spoken, and message whose audio is still being fetched */
	playing = $state<string | null>(null);
	loading = $state<string | null>(null);
	recording = $state(false);
	transcribing = $state(false);
	/** Hands-free preference: once you speak, keep listening again after every answer (on by default) */
	handsFree = $state(true);

	/** Whether the hands-free loop is running right now. It starts when you speak and pauses when you
	 * stop the agent, nobody talks for a few rounds, or something fails. */
	engaged = $state(false);
	private emptyRounds = 0;
	private manualStop = false;
	private heardSpeech = false;
	private resumeTimer: ReturnType<typeof setTimeout> | null = null;
	private audio: HTMLAudioElement | null = null;
	private clips = new Map<string, { url: string; engine: VoiceEngine }>();
	private recorder: MediaRecorder | null = null;
	private recognition: SpeechRecognitionLike | null = null;
	private abort: AbortController | null = null;
	private hydrated = false;

	/** Mic input is possible with ElevenLabs transcription, or the browser's own recogniser */
	canListen = $derived(
		browser &&
			(Boolean(this.status?.elevenlabs_configured) && Boolean(navigator.mediaDevices?.getUserMedia)
				? true
				: recognitionCtor() !== null)
	);

	hydrate() {
		if (!browser || this.hydrated) return;
		this.hydrated = true;
		this.messages = readJson<ChatMessage[]>(CHAT_KEY, []);
		const prefs = readJson(PREF_KEY, { speakReplies: true, handsFree: true });
		this.speakReplies = prefs.speakReplies ?? true;
		this.handsFree = prefs.handsFree ?? true;
		void this.refreshStatus();
	}

	private savePrefs() {
		try {
			sessionStorage.setItem(
				PREF_KEY,
				JSON.stringify({ speakReplies: this.speakReplies, handsFree: this.handsFree })
			);
		} catch {
			// the choice stays in memory
		}
	}

	/** Turning hands-free on from the checkbox is a click, so the mic may start right away. */
	setHandsFree(on: boolean) {
		this.handsFree = on;
		this.savePrefs();
		this.emptyRounds = 0;
		this.clearResume();
		this.engaged = on && this.messages.length > 0;
		if (this.engaged && !this.playing && !this.loading) void this.startListening();
	}

	/** Stop the hands-free loop without changing the preference; pressing Speak starts it again. */
	private pause() {
		this.engaged = false;
		this.clearResume();
	}

	private clearResume() {
		if (this.resumeTimer) clearTimeout(this.resumeTimer);
		this.resumeTimer = null;
	}

	/** In hands-free mode, listen again once the agent has finished (or if there is nothing to say). */
	private resume() {
		this.clearResume();
		if (!this.handsFree || !this.engaged) return;
		this.resumeTimer = setTimeout(() => {
			this.resumeTimer = null;
			if (this.handsFree && this.engaged && !this.playing && !this.loading)
				void this.startListening();
		}, RESUME_DELAY_MS);
	}

	/** A listening round that produced no speech. Too many in a row switches hands-free off. */
	private emptyRound() {
		this.emptyRounds++;
		if (this.handsFree && this.engaged && this.emptyRounds >= MAX_EMPTY_ROUNDS) {
			this.pause();
			this.speechNote = 'Listening paused because no speech was heard. Press Speak to continue.';
			return;
		}
		this.resume();
	}

	async refreshStatus() {
		this.status = await fetchVoiceStatus();
		this.statusChecked = true;
	}

	setSpeakReplies(on: boolean) {
		this.speakReplies = on;
		if (!on) this.stop();
		this.savePrefs();
	}

	newChat() {
		this.pause();
		this.stop();
		this.abort?.abort();
		this.messages = [];
		this.error = '';
		this.speechNote = '';
		this.save();
	}

	private save() {
		try {
			sessionStorage.setItem(CHAT_KEY, JSON.stringify($state.snapshot(this.messages).slice(-60)));
		} catch {
			// the chat stays in memory
		}
	}

	private add(message: Omit<ChatMessage, 'id'>): ChatMessage {
		this.messages.push({ id: crypto.randomUUID(), ...message });
		this.save();
		return this.messages[this.messages.length - 1];
	}

	// ---- asking ---------------------------------------------------------------------------------------------

	/**
	 * Open the conversation with the agent's greeting (no question from the user, no model call).
	 * In hands-free mode the mic opens straight away: the Start click is the gesture browsers require.
	 */
	start() {
		if (this.messages.length) return;
		const text = GREETING[session.language];
		this.add({
			role: 'assistant',
			text: session.result ? text.withAnalysis : text.withoutAnalysis,
			answeredBy: 'greeting'
		});
		if (this.handsFree && this.statusChecked && this.canListen) {
			this.emptyRounds = 0;
			this.engaged = true;
			void this.startListening();
		}
	}

	async send(text: string) {
		text = text.trim();
		if (!text || this.busy) return;
		this.error = '';
		const history = this.messages.map((m) => ({ role: m.role, text: m.text }));
		this.add({ role: 'user', text });
		this.busy = true;
		this.abort = new AbortController();
		try {
			const answer = await askVoice({
				message: text,
				history,
				analysis: trimAnalysis(session.result),
				language: session.language,
				signal: this.abort.signal
			});
			const reply = this.add({
				role: 'assistant',
				text: answer.reply,
				sources: answer.sources,
				answeredBy: answer.source,
				model: answer.model
			});
			if (this.speakReplies) void this.play(reply);
			else this.resume();
		} catch (error) {
			if (error instanceof DOMException && error.name === 'AbortError') return;
			this.error = error instanceof Error ? error.message : String(error);
			this.pause(); // do not keep looping on a backend that is failing
		} finally {
			this.busy = false;
		}
	}

	// ---- speaking -------------------------------------------------------------------------------------------

	stop() {
		this.audio?.pause();
		this.audio = null;
		if (browser) window.speechSynthesis?.cancel();
		this.playing = null;
		this.loading = null;
	}

	/**
	 * Speak a message; pressing it again while it plays stops it. Stopping on purpose also pauses
	 * hands-free, so the mic does not open the moment the agent is cut off.
	 */
	async play(message: ChatMessage) {
		if (this.playing === message.id || this.loading === message.id) {
			this.pause();
			this.stop();
			return;
		}
		this.clearResume();
		this.stop();
		this.loading = message.id;
		this.speechNote = '';

		let clip = this.clips.get(message.text);
		if (!clip) {
			try {
				const { blob, engine } = await fetchSpeech(message.text);
				clip = { url: URL.createObjectURL(blob), engine };
				this.clips.set(message.text, clip);
				void this.refreshStatus(); // the voice database grew
			} catch (error) {
				this.speechNote = `${error instanceof Error ? error.message : String(error)} Using the browser voice instead.`;
			}
		}
		if (this.loading !== message.id) return; // stopped while loading

		this.loading = null;
		if (clip) {
			const audio = new Audio(clip.url);
			this.audio = audio;
			audio.onended = () => {
				if (this.audio === audio) {
					this.stop();
					this.resume();
				}
			};
			try {
				await audio.play();
				message.engine = clip.engine;
				this.playing = message.id;
			} catch (error) {
				if (this.audio !== audio) return; // stopped or replaced on purpose, which rejects play()
				this.stop();
				if (error instanceof DOMException && error.name === 'NotAllowedError')
					this.speechNote = 'The browser blocked playback. Press the speaker button.';
				else this.speechNote = 'The audio could not be played. Press the speaker button to retry.';
				this.resume();
			}
		} else if (browser && window.speechSynthesis) {
			const utterance = new SpeechSynthesisUtterance(message.text);
			utterance.lang = BROWSER_LANG[session.language];
			utterance.onend = utterance.onerror = () => {
				// cancel() (Stop, or another message) also fires this: only resume after a natural end
				if (this.playing !== message.id) return;
				this.playing = null;
				this.resume();
			};
			message.engine = 'browser';
			this.playing = message.id;
			window.speechSynthesis.speak(utterance);
		} else {
			this.speechNote = 'This browser cannot speak.';
			this.resume();
		}
		this.save();
	}

	// ---- listening ------------------------------------------------------------------------------------------

	async toggleRecording() {
		if (this.recording) return this.finishRecording();
		this.emptyRounds = 0;
		this.engaged = this.handsFree; // speaking (re)starts the hands-free loop
		this.speechNote = '';
		await this.startListening();
	}

	private async startListening() {
		if (this.recording || this.transcribing || this.busy) return;
		this.clearResume();
		this.stop();
		this.error = '';
		this.manualStop = false;
		this.heardSpeech = false;

		// Without ElevenLabs, the browser's own recogniser turns speech into text (and ends itself on silence)
		if (!this.status?.elevenlabs_configured) {
			const Recognition = recognitionCtor();
			if (!Recognition) return;
			const recognition = new Recognition();
			recognition.lang = BROWSER_LANG[session.language];
			recognition.interimResults = false;
			recognition.onresult = (event) => {
				const heard = event.results[0]?.[0]?.transcript ?? '';
				if (!heard) return;
				this.heardSpeech = true;
				this.emptyRounds = 0;
				void this.send(heard);
			};
			recognition.onerror = (event) => {
				if (event.error !== 'no-speech' && event.error !== 'aborted') {
					this.error = `Speech recognition failed (${event.error}).`;
					this.pause();
				}
			};
			recognition.onend = () => {
				this.recording = false;
				this.recognition = null;
				if (!this.heardSpeech && this.engaged) this.emptyRound();
			};
			this.recognition = recognition;
			this.recording = true;
			recognition.start();
			return;
		}

		try {
			const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
			const chunks: Blob[] = [];
			const recorder = new MediaRecorder(stream);
			const stopDetecting = this.detectSpeech(stream, () => this.recorder?.stop());
			recorder.ondataavailable = (event) => chunks.push(event.data);
			recorder.onstop = () => {
				stopDetecting();
				stream.getTracks().forEach((track) => track.stop());
				this.recording = false;
				this.recorder = null;
				// Stopped on its own with no speech: skip the transcription call (and its cost)
				if (!this.manualStop && !this.heardSpeech) {
					if (!this.engaged) this.error = 'No speech was heard. Press Speak and try again.';
					this.emptyRound();
					return;
				}
				void this.transcribeAndSend(new Blob(chunks, { type: recorder.mimeType }));
			};
			this.recorder = recorder;
			recorder.start();
			this.recording = true;
		} catch {
			this.pause();
			this.error =
				'The microphone is blocked or missing. Allow it in the address bar, or type instead.';
		}
	}

	/**
	 * Watch the microphone level and call `onSilence` once the user has spoken and then gone quiet
	 * (or nobody spoke for a while). Returns a function that stops the watching.
	 */
	private detectSpeech(stream: MediaStream, onSilence: () => void): () => void {
		const context = new AudioContext();
		void context.resume();
		const analyser = context.createAnalyser();
		analyser.fftSize = 1024;
		context.createMediaStreamSource(stream).connect(analyser);
		const samples = new Float32Array(analyser.fftSize);

		const startedAt = performance.now();
		let lastVoiceAt = startedAt;
		let noiseSum = 0;
		let noiseCount = 0;
		let threshold = VAD_MIN_LEVEL;

		const timer = setInterval(() => {
			analyser.getFloatTimeDomainData(samples);
			let sum = 0;
			for (const sample of samples) sum += sample * sample;
			const level = Math.sqrt(sum / samples.length);
			const now = performance.now();
			const elapsed = now - startedAt;

			if (elapsed < VAD_CALIBRATE_MS) {
				noiseSum += level;
				noiseCount++;
				threshold = Math.max(VAD_MIN_LEVEL, (noiseSum / noiseCount) * 2.5);
				return;
			}
			if (level > threshold) {
				this.heardSpeech = true;
				lastVoiceAt = now;
			}
			const quietFor = now - lastVoiceAt;
			if (
				(this.heardSpeech && quietFor > VAD_SILENCE_MS) ||
				(!this.heardSpeech && elapsed > VAD_NO_SPEECH_MS) ||
				elapsed > VAD_MAX_MS
			)
				onSilence();
		}, VAD_POLL_MS);

		return () => {
			clearInterval(timer);
			void context.close();
		};
	}

	/** The user pressed Stop: send what was heard so far. */
	finishRecording() {
		this.manualStop = true;
		this.recorder?.stop();
		this.recognition?.stop();
	}

	private async transcribeAndSend(audio: Blob) {
		if (audio.size < 1000) {
			if (!this.engaged) this.error = 'Nothing was recorded. Speak a little longer.';
			this.emptyRound();
			return;
		}
		this.transcribing = true;
		try {
			const { text } = await transcribe(audio);
			if (text) {
				this.emptyRounds = 0;
				await this.send(text);
			} else {
				if (!this.engaged)
					this.error = 'No speech was recognised. Try again closer to the microphone.';
				this.emptyRound();
			}
		} catch (error) {
			this.error = error instanceof Error ? error.message : String(error);
			this.pause();
		} finally {
			this.transcribing = false;
		}
	}
}

export const voice = new VoiceChat();
