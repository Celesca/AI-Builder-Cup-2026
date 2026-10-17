<script lang="ts">
	import BackendUrl from '#lib/components/BackendUrl.svelte';
	import { onMount, tick } from 'svelte';
	import Icon from '#lib/components/Icon.svelte';
	import Slash from '#lib/components/Slash.svelte';
	import TimeChip from '#lib/components/TimeChip.svelte';
	import { session } from '#lib/session.svelte.ts';
	import type { ChatMessage, VoiceEngine } from '#lib/types.ts';
	import { voice } from '#lib/voice.svelte.ts';
	import { splitTimestamps } from '#lib/voice.ts';

	let draft = $state('');
	let log: HTMLElement | undefined = $state();

	onMount(() => voice.hydrate());

	// Keep the newest message in view
	$effect(() => {
		void voice.messages.length;
		void voice.busy;
		void tick().then(() => log?.scrollTo({ top: log.scrollHeight }));
	});

	const ENGINE_LABEL: Record<VoiceEngine, string> = {
		elevenlabs: 'ElevenLabs voice',
		database: 'ElevenLabs · from the voice database',
		browser: 'Browser voice'
	};

	let status = $derived(voice.status);
	let context = $derived(
		session.result && session.source
			? `${session.source.name} · ${session.result.lss.lss_cards.length} Gemba Kaizen cards · ${session.result.safety.safety_events.length} incidents`
			: ''
	);
	let started = $derived(voice.messages.length > 0);
	let ready = $derived(voice.statusChecked && status !== null);

	function submit() {
		const text = draft;
		draft = '';
		void voice.send(text);
	}

	function onkeydown(event: KeyboardEvent) {
		if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
			event.preventDefault();
			submit();
		}
	}

	function speakerLabel(message: ChatMessage) {
		if (voice.loading === message.id) return 'Loading the voice…';
		return voice.playing === message.id ? 'Stop' : 'Listen';
	}
</script>

<svelte:head><title>Voice Agent · VALZ</title></svelte:head>

<main class="page">
	<div class="page-head">
		<div>
			<h1>Voice Agent</h1>
			<p>
				Ask about the shift you analysed, by voice or by typing. Answers come from the analysis and
				the lean knowledge cards, and can be read aloud.
			</p>
		</div>
		<button
			class="btn"
			type="button"
			onclick={() => voice.newChat()}
			disabled={!voice.messages.length}
		>
			<Icon name="reset" /> New chat
		</button>
	</div>

	{#if voice.statusChecked && !status}
		<div class="notice warn" role="status">
			<Icon name="warn" />
			<p>
				<strong>The AI backend is not reachable.</strong> Chat and ElevenLabs voice need it. Start
				it with <span class="mono">docker compose up</span>.
			</p>
		</div>
	{:else if ready && !status?.llm_configured}
		<div class="notice info" role="status">
			<p>
				<strong>No OpenRouter key on the backend:</strong> answers are the best matching passages from
				the analysis, not written by a model.
			</p>
		</div>
	{/if}

	<div class="layout">
		<section class="panel chat" aria-label="Conversation">
			<div class="log" bind:this={log} role="log" aria-live="polite" aria-label="Messages">
				{#if voice.messages.length === 0}
					<div class="start">
						<h2>Voice Agent</h2>
						<p class="muted">
							{context ? `Ready to answer from ${context}.` : 'No video is analysed yet.'}
						</p>
						<button class="btn primary" type="button" onclick={() => voice.start()}>
							Start chatting <Slash />
						</button>
					</div>
				{/if}

				{#each voice.messages as message (message.id)}
					<article class="msg {message.role}">
						<header>
							<span class="who">{message.role === 'user' ? 'You' : 'Agent'}</span>
							{#if message.engine}<span class="tag note">{ENGINE_LABEL[message.engine]}</span>{/if}
						</header>
						<p lang={session.language}>
							{#each splitTimestamps(message.text) as piece, i (i)}
								{#if 'time' in piece}<TimeChip start={piece.time} />{:else}{piece.text}{/if}
							{/each}
						</p>
						<footer>
							<button
								class="btn small"
								type="button"
								aria-pressed={voice.playing === message.id}
								onclick={() => voice.play(message)}
							>
								<Icon name={voice.playing === message.id ? 'stop' : 'speaker'} size={14} />
								{speakerLabel(message)}
							</button>
							{#if message.role === 'assistant'}
								{#if message.answeredBy !== 'greeting'}
									<span class="muted by">
										{message.answeredBy === 'llm'
											? `Written by ${message.model}`
											: 'Matching passages, no model'}
									</span>
								{/if}
								{#each (message.sources ?? []).slice(0, 4) as source (source.id)}
									<span class="tag {source.source === 'knowledge' ? 'blue' : 'note'}"
										>{source.title}</span
									>
								{/each}
								{#if (message.sources?.length ?? 0) > 4}
									<span class="muted by">+{message.sources!.length - 4} more passages</span>
								{/if}
							{/if}
						</footer>
					</article>
				{/each}

				{#if voice.busy}
					<p class="muted thinking" role="status">The agent is reading the analysis…</p>
				{/if}
			</div>

			{#if voice.error}
				<div class="notice warn" role="alert">
					<Icon name="warn" />
					<p>{voice.error}</p>
				</div>
			{/if}
			{#if voice.speechNote}
				<div class="notice" role="status"><p>{voice.speechNote}</p></div>
			{/if}

			<form
				class="composer"
				onsubmit={(event) => {
					event.preventDefault();
					submit();
				}}
			>
				<label class="sr-only" for="ask">Your question</label>
				<textarea
					id="ask"
					rows="2"
					bind:value={draft}
					{onkeydown}
					disabled={!started}
					placeholder={!started
						? 'Press Start chatting first'
						: voice.recording
							? 'Listening…'
							: 'Type a question, or press the microphone'}
					lang={session.language}></textarea>
				<div class="buttons">
					<button
						class="btn"
						type="button"
						aria-pressed={voice.recording}
						onclick={() => voice.toggleRecording()}
						disabled={!started || !voice.canListen || voice.transcribing || voice.busy}
						title={voice.canListen
							? ''
							: 'This browser has no speech input and ElevenLabs is not configured'}
					>
						<Icon name={voice.recording ? 'stop' : 'mic'} />
						{voice.recording ? 'Stop' : voice.transcribing ? 'Transcribing…' : 'Speak'}
					</button>
					<button
						class="btn primary"
						type="submit"
						disabled={!started || !draft.trim() || voice.busy}
					>
						Send <Icon name="send" size={14} />
					</button>
				</div>
			</form>
		</section>

		<aside class="side" aria-label="Voice settings">
			<section class="panel">
				<div class="panel-head"><h2>Voice</h2></div>
				<div class="panel-body rows">
					<label class="check">
						<input
							type="checkbox"
							checked={voice.speakReplies}
							onchange={(event) => voice.setSpeakReplies(event.currentTarget.checked)}
						/>
						Read answers aloud
					</label>
					<label class="check">
						<input
							type="checkbox"
							checked={voice.handsFree}
							disabled={!voice.canListen}
							onchange={(event) => voice.setHandsFree(event.currentTarget.checked)}
						/>
						Hands-free (listen again after each answer){#if voice.handsFree && started && !voice.engaged}
							· paused{/if}
					</label>
					<dl>
						<div>
							<dt>Speech</dt>
							<dd>
								{#if !ready}Checking…{:else if status?.elevenlabs_configured}ElevenLabs · {status.tts_model}{:else}Browser
									voice (no ElevenLabs key){/if}
							</dd>
						</div>
						<div>
							<dt>Microphone</dt>
							<dd>
								{#if !ready}Checking…{:else if status?.elevenlabs_configured}ElevenLabs Scribe{:else if voice.canListen}Browser
									recognition{:else}Not available{/if}
							</dd>
						</div>
						<div>
							<dt>Answers</dt>
							<dd>{status?.llm_configured ? status.llm_model : 'Matching passages'}</dd>
						</div>
						<div>
							<dt>Language</dt>
							<dd>{{ en: 'English', th: 'ไทย', ja: '日本語' }[session.language]} · top bar</dd>
						</div>
					</dl>
				</div>
			</section>

			<section class="panel">
				<div class="panel-head"><h2>Backend</h2></div>
				<div class="panel-body"><BackendUrl /></div>
			</section>

			<section class="panel">
				<div class="panel-head"><h2>Voice database</h2></div>
				<div class="panel-body rows">
					<p class="figure">{status?.audio_cache.clips ?? 0}<small> clips stored</small></p>
					<p class="muted">
						Every sentence ElevenLabs speaks is saved once, so replaying it is free and works
						offline.
						{#if status}{status.audio_cache.replays} replays served so far.{/if}
					</p>
				</div>
			</section>

			<section class="panel">
				<div class="panel-head"><h2>Context</h2></div>
				<div class="panel-body rows">
					{#if context}
						<p>{context}</p>
						<p class="muted">Time stamps in answers jump the video.</p>
					{:else}
						<p class="muted">No analysis loaded.</p>
						<a class="btn small primary" href="/video">Go to Video <Slash /></a>
					{/if}
				</div>
			</section>
		</aside>
	</div>
</main>

<style>
	.layout {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 20rem;
		gap: 1.5rem;
		align-items: start;
	}
	.chat {
		display: grid;
		grid-template-rows: minmax(0, 1fr) auto;
		min-height: 32rem;
	}
	.log {
		display: grid;
		align-content: start;
		gap: 1rem;
		height: min(60vh, 40rem);
		overflow-y: auto;
		padding: 1rem;
	}
	.start {
		display: grid;
		gap: 0.75rem;
		justify-items: center;
		align-content: center;
		min-height: min(52vh, 36rem);
		text-align: center;
	}
	.start h2 {
		font: 600 var(--t-lg) var(--display);
		letter-spacing: 0.04em;
		text-transform: uppercase;
	}
	.msg {
		display: grid;
		gap: 0.5rem;
		max-width: 46rem;
		padding: 0.75rem 1rem;
		border: 1px solid var(--ink);
		background: var(--paper);
	}
	.msg.user {
		justify-self: end;
		background: var(--surface);
	}
	.msg header,
	.msg footer {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.5rem 0.75rem;
	}
	.who {
		font: 600 var(--t-xs) var(--display);
		letter-spacing: 0.1em;
		text-transform: uppercase;
	}
	.msg p {
		line-height: 1.6;
		overflow-wrap: anywhere;
	}
	.by {
		font-size: var(--t-xs);
	}
	.thinking {
		font-size: var(--t-sm);
	}
	.chat > .notice {
		margin: 0 1rem 0.75rem;
	}
	.composer {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		gap: 0.75rem;
		padding: 0.75rem 1rem;
		border-top: 1px solid var(--ink);
		align-items: stretch;
	}
	.buttons {
		display: grid;
		gap: 0.5rem;
	}
	.side {
		display: grid;
		gap: 1.5rem;
	}
	.rows {
		display: grid;
		gap: 0.75rem;
	}
	.check {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		font-weight: 600;
	}
	dl {
		display: grid;
		margin: 0;
	}
	dl div {
		display: flex;
		justify-content: space-between;
		gap: 1rem;
		padding: 0.4375rem 0;
		border-top: 1px solid var(--grid);
		font-size: var(--t-sm);
	}
	dt {
		color: var(--muted);
	}
	dd {
		margin: 0;
		text-align: right;
	}
	.figure {
		font: 700 var(--t-2xl) / 1 var(--display);
	}
	.figure small {
		font: 400 var(--t-sm) var(--body);
		color: var(--muted);
	}
	@container (max-width: 960px) {
		.layout {
			grid-template-columns: minmax(0, 1fr);
		}
		.side {
			grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr));
		}
	}
	@media (max-width: 700px) {
		.composer {
			grid-template-columns: minmax(0, 1fr);
		}
		.buttons {
			grid-auto-flow: column;
		}
		.log {
			height: 50vh;
		}
	}
</style>
