<script lang="ts">
	import AnnotatePanel from '#lib/components/AnnotatePanel.svelte';
	import BackendUrl from '#lib/components/BackendUrl.svelte';
	import { onMount } from 'svelte';
	import { fmt, fmtRange } from '#lib/analysis.ts';
	import Icon from '#lib/components/Icon.svelte';
	import Player from '#lib/components/Player.svelte';
	import Slash from '#lib/components/Slash.svelte';
	import { playback } from '#lib/playback.svelte.ts';
	import { session } from '#lib/session.svelte.ts';

	type Tab = 'upload' | 'demo' | 'live';
	let tab = $state<Tab>('demo');
	let dragging = $state(false);
	let fileError = $state('');
	let live = $state(false);

	const MAX_MB = 500;

	onMount(() => {
		if (session.source?.kind === 'upload') tab = 'upload';
	});

	function accept(file: File | undefined) {
		fileError = '';
		if (!file) return;
		const isVideo =
			file.type.startsWith('video/') || /\.(mp4|mov|avi|mkv|webm|flv|wmv)$/i.test(file.name);
		if (!isVideo) return void (fileError = `"${file.name}" is not a video file.`);
		if (file.size > MAX_MB * 1024 * 1024)
			return void (fileError = `"${file.name}" is larger than ${MAX_MB} MB.`);
		live = false;
		session.selectUpload(file);
	}

	function drop(event: DragEvent) {
		event.preventDefault();
		dragging = false;
		accept(event.dataTransfer?.files?.[0]);
	}

	async function openDemo(clip: (typeof session.clips)[number]) {
		live = false;
		await session.selectDemo(clip);
	}

	async function startLive() {
		const clip = session.clips[0];
		if (!clip) return;
		live = true;
		await session.selectDemo(clip);
		playback.seek(0, true);
	}

	let feed = $derived(session.incidents.filter((i) => i.start <= playback.time));
	let cannotRun = $derived.by(() => {
		if (!session.source) return 'Choose a video first.';
		if (session.source.kind === 'demo') return 'Demo clips use a cached analysis.';
		if (!session.source.file) return 'Choose the video file again.';
		if (session.backend.state === 'offline') return 'The AI backend is not reachable.';
		if (session.backend.state === 'online' && !session.backend.keyConfigured)
			return 'The backend has no OpenRouter key.';
		if (!session.rules.some((r) => r.enabled)) return 'Turn on at least one safety rule.';
		return '';
	});
	let uploadBlock = $derived(
		session.backend.state === 'offline'
			? 'The AI backend is not reachable: you can choose a file, but it cannot be analysed until the backend runs.'
			: session.backend.state === 'online' && !session.backend.keyConfigured
				? 'The backend has no OpenRouter key, so an uploaded video cannot be analysed yet. Demo clips work without it.'
				: ''
	);
	let enabledCount = $derived(session.rules.filter((r) => r.enabled).length);
</script>

<svelte:head><title>Video · VALZ</title></svelte:head>

<main class="page">
	<div class="page-head">
		<div>
			<h1>Video</h1>
			<p>
				Load a workstation clip, then run the Safety Agent and the Gemba Kaizen Agent on it. Everything you
				see afterwards jumps back to a moment in this video.
			</p>
		</div>
	</div>

	<div class="layout">
		<div class="main-col">
			<section class="panel" aria-label="Video source">
				<div class="panel-head">
					<div class="segmented" role="group" aria-label="Source">
						<button type="button" aria-pressed={tab === 'demo'} onclick={() => (tab = 'demo')}
							>Demo clips</button
						>
						<button type="button" aria-pressed={tab === 'upload'} onclick={() => (tab = 'upload')}
							>Upload</button
						>
						<button type="button" aria-pressed={tab === 'live'} onclick={() => (tab = 'live')}
							>Live</button
						>
					</div>
					{#if session.source}
						<span class="meta"
							>{session.source.name}{session.source.synthetic ? ' · synthetic' : ''}</span
						>
					{/if}
				</div>

				{#if tab === 'demo'}
					<div class="panel-body">
						{#if session.clips.length === 0}
							<div class="empty">
								<h2>No demo clips found</h2>
								<p>
									Demo clips are listed in <code>frontend/static/demo/manifest.json</code>. Add one
									with <code>pnpm demo:add path/to/clip.mp4</code> while the backend is running; it saves
									the analysis next to the video.
								</p>
							</div>
						{:else}
							<ul class="clips">
								{#each session.clips as clip (clip.id)}
									<li class:current={session.source?.id === clip.id}>
										<div>
											<strong>{clip.title}</strong>
											<span class="muted"
												>{fmt(clip.duration)}<span class="note"
													>{clip.note ? ` · ${clip.note}` : ''}</span
												></span
											>
										</div>
										{#if clip.synthetic}<span class="tag note">Synthetic</span>{/if}
										<button
											class="btn small"
											class:primary={session.source?.id !== clip.id}
											type="button"
											onclick={() => openDemo(clip)}
										>
											{session.source?.id === clip.id ? 'Loaded' : 'Open'}
										</button>
									</li>
								{/each}
							</ul>
							<p class="hint">
								Demo clips carry a cached analysis, so they open instantly and need no API key. Add
								your own with <code>pnpm demo:add</code>.
							</p>
						{/if}
					</div>
				{:else if tab === 'upload'}
					<div class="panel-body">
						<label
							class="drop"
							class:dragging
							for="file"
							ondragover={(e) => {
								e.preventDefault();
								dragging = true;
							}}
							ondragleave={() => (dragging = false)}
							ondrop={drop}
						>
							<Icon name="upload" size={28} />
							<strong>Drop a video here, or choose a file</strong>
							<span class="muted"
								>mp4, mov, avi, mkv or webm, up to {MAX_MB} MB. The analysis takes about a minute for
								a short clip.</span
							>
						</label>
						<input
							id="file"
							class="sr-only"
							type="file"
							accept="video/*"
							onchange={(e) => {
								accept(e.currentTarget.files?.[0]);
								// so choosing the same file again still counts as a new upload
								e.currentTarget.value = '';
							}}
						/>
						{#if uploadBlock}<p class="notice warn" role="status">
								<Icon name="warn" />
								{uploadBlock}
							</p>{/if}
						{#if fileError}<p class="notice warn" role="alert">{fileError}</p>{/if}
					</div>
				{:else}
					<div class="panel-body live">
						<div class="notice info">
							<Icon name="live" />
							<p>
								<strong>Live ingest is not built yet.</strong> The backend analyses files, not streams.
								Planned: RTSP ingest, one keyframe per second, rolling analysis windows. Until then you
								can replay a demo clip as if its findings were arriving live.
							</p>
						</div>
						<div class="field">
							<label for="rtsp">Stream address</label>
							<div class="inline">
								<input
									id="rtsp"
									type="url"
									placeholder="rtsp://camera-3.plant.local/stream1"
									disabled
								/>
								<button class="btn" type="button" disabled>Connect</button>
							</div>
						</div>
						<div>
							<button
								class="btn primary"
								type="button"
								onclick={startLive}
								disabled={session.clips.length === 0}
							>
								<Icon name="live" /> Replay a demo clip as live <Slash />
							</button>
						</div>
					</div>
				{/if}

				{#if session.source}
					<div class="stage">
						{#if live}<div class="livebar">
								<i class="dot warn"></i>Live replay · simulated: findings are replayed from a cached
								analysis
							</div>{/if}
						{#if session.annotation.showing === 'annotated' && session.annotation.url}<div
								class="livebar"
							>
								<i class="dot on"></i>Annotated by the server · person boxes and rule names
							</div>{/if}
						<Player src={session.playUrl} label="Video of {session.source.name}" loop={live} />
					</div>
				{/if}

				<div class="runbar" aria-live="polite">
					{#if session.status === 'running'}
						<div class="progress" role="progressbar" aria-label="Analysis in progress"><i></i></div>
						<p>
							The Safety Agent is checking {enabledCount} rules on about one frame per second, then the
							Gemba Kaizen Agent writes the report. {session.elapsed} s
						</p>
						<button class="btn" type="button" onclick={() => session.cancel()}>Cancel</button>
					{:else if session.status === 'error'}
						<div class="notice warn" role="alert">
							<Icon name="warn" />
							<div>
								<strong>The analysis did not run.</strong>
								<p>{session.error}</p>
								{#if session.source?.kind === 'upload'}<p class="muted">
										You can still explore the product with a demo clip.
									</p>{/if}
							</div>
						</div>
						{#if session.source?.kind === 'upload'}
							<button
								class="btn primary"
								type="button"
								onclick={() => session.analyze()}
								disabled={Boolean(cannotRun)}>Try again</button
							>
						{/if}
					{:else if session.result && session.source}
						<p>
							{#if session.isDemo}Cached analysis loaded. No model was called.{:else}Analysed with {session
									.result.safety.model}{#if session.result.safety.vlm_usage?.cost != null}, vision
									cost ${session.result.safety.vlm_usage.cost.toFixed(4)}{/if}.{/if}
							{session.result.safety.stats.frames_analyzed} frames · {session.incidents.length} incidents.
						</p>
						<div class="go">
							<a class="btn" href="/safety">Safety Agent</a>
							<a class="btn" href="/dashboard">Dashboard</a>
							<a class="btn primary" href="/lss">Gemba Kaizen <Slash /></a>
						</div>
						{#if session.source.kind === 'upload'}
							<button
								class="btn"
								type="button"
								onclick={() => session.analyze()}
								disabled={Boolean(cannotRun)}><Icon name="reset" /> Analyse again</button
							>
						{/if}
					{:else if session.source}
						<button
							class="btn primary"
							type="button"
							onclick={() => session.analyze()}
							disabled={Boolean(cannotRun)}
						>
							Analyse video <Slash />
						</button>
						<p class="muted">
							{cannotRun ||
								`Runs ${enabledCount} safety rules, then the Gemba Kaizen report in ${session.language === 'en' ? 'English' : session.language === 'th' ? 'Thai' : 'Japanese'}.`}
						</p>
					{:else}
						<p class="muted">Choose a demo clip or upload a video to begin.</p>
					{/if}
				</div>
			</section>

			{#if session.source && !live}<AnnotatePanel />{/if}

			{#if live && session.result}
				<section class="panel" aria-label="Incidents so far">
					<div class="panel-head">
						<h2>Incidents so far</h2>
						<span class="meta"
							>{fmt(playback.time)} · {feed.length} of {session.incidents.length}</span
						>
					</div>
					{#if feed.length === 0}
						<p class="panel-body muted">
							Nothing yet. Findings appear here as the replay reaches them.
						</p>
					{:else}
						<ul class="feed">
							{#each feed as incident (incident.key)}
								<li>
									<span class="tag {incident.severity}">{incident.severity}</span>
									<strong>{incident.label}</strong>
									<span class="muted"
										>{fmtRange(incident.start, incident.end)} · {Math.round(
											incident.peak * 100
										)}%</span
									>
								</li>
							{/each}
						</ul>
					{/if}
				</section>
			{/if}
		</div>

		<aside class="side" aria-label="Analysis settings">
			<section class="panel">
				<div class="panel-head">
					<h2>Station</h2>
					<span class="meta">optional, for ROI</span>
				</div>
				<div class="panel-body form">
					<div class="field">
						<label for="station">Name</label>
						<input
							id="station"
							type="text"
							placeholder="WS10"
							bind:value={session.station.name}
							oninput={() => session.savePrefs()}
							disabled={session.isDemo}
						/>
					</div>
					<div class="two">
						<div class="field">
							<label for="cycle">Cycle time (s)</label>
							<input
								id="cycle"
								type="number"
								min="0"
								step="0.1"
								placeholder="72"
								bind:value={session.station.cycleTime}
								oninput={() => session.savePrefs()}
								disabled={session.isDemo}
							/>
						</div>
						<div class="field">
							<label for="takt">Takt time (s)</label>
							<input
								id="takt"
								type="number"
								min="0"
								step="0.1"
								placeholder="60"
								bind:value={session.station.taktTime}
								oninput={() => session.savePrefs()}
								disabled={session.isDemo}
							/>
						</div>
					</div>
					<p class="field-hint">
						{session.isDemo
							? 'The demo clip was analysed with a nominal cycle of 240 s (no takt time).'
							: 'With a cycle time the Gemba Kaizen Agent can turn saved seconds into hours per shift.'}
					</p>
				</div>
			</section>

			<section class="panel">
				<div class="panel-head">
					<h2>Safety rules</h2>
					<a class="meta" href="/safety">Edit</a>
				</div>
				<div class="panel-body">
					<p><strong>{enabledCount}</strong> of {session.rules.length} rules on</p>
					<ul class="rulelist">
						{#each session.rules.filter((r) => r.enabled) as rule (rule.id)}
							<li><span class="tag p-{rule.severity}">{rule.severity}</span> {rule.label}</li>
						{/each}
					</ul>
				</div>
			</section>

			<section class="panel flat">
				<div class="panel-head">
					<h2>AI backend</h2>
					<button class="btn small" type="button" onclick={() => session.refreshBackend()}
						>Check</button
					>
				</div>
				<div class="panel-body status">
					<p>
						<i
							class="dot"
							class:on={session.backend.state === 'online' && session.backend.keyConfigured}
							class:warn={session.backend.state === 'offline' ||
								(session.backend.state === 'online' && !session.backend.keyConfigured)}
						></i>
						<strong
							>{session.backend.state === 'checking'
								? 'Checking'
								: session.backend.state === 'offline'
									? 'Offline'
									: session.backend.keyConfigured
										? 'Online'
										: 'Online, no API key'}</strong
						>
					</p>
					<p class="muted">{session.backend.detail}</p>
					<BackendUrl />
					{#if session.backend.state === 'online'}
						<dl>
							<dt>Vision model</dt>
							<dd>{session.backend.vlmModel ?? '–'}</dd>
							<dt>Gemba Kaizen LLM</dt>
							<dd>{session.backend.llmModel ?? '–'}</dd>
						</dl>
					{/if}
				</div>
			</section>
		</aside>
	</div>
</main>

<style>
	.layout {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 22rem;
		gap: 1.5rem;
		align-items: start;
	}
	.main-col,
	.side {
		display: grid;
		gap: 1.5rem;
		min-width: 0;
	}
	code {
		padding: 0.0625rem 0.3125rem;
		background: var(--surface);
		border: 1px solid var(--grid);
		font:
			500 var(--t-sm) ui-monospace,
			'SF Mono',
			Menlo,
			monospace;
	}
	.clips {
		display: grid;
		gap: 0;
		border-top: 1px solid var(--ink);
	}
	.clips li {
		display: grid;
		grid-template-columns: 1fr auto auto;
		gap: 0.75rem;
		align-items: center;
		padding: 0.75rem 0.25rem;
		border-bottom: 1px solid var(--ink);
	}
	.clips li.current {
		background: var(--blue-tint);
	}
	.clips li div {
		display: grid;
		min-width: 0;
	}
	.hint {
		margin-top: 0.75rem;
		color: var(--muted);
		font-size: var(--t-sm);
	}
	.drop {
		display: grid;
		justify-items: center;
		gap: 0.5rem;
		padding: 2.5rem 1rem;
		margin: 0;
		background: var(--surface);
		border: 1px dashed var(--ink);
		text-align: center;
		text-transform: none;
		letter-spacing: 0;
		font: 400 var(--t-md) / 1.5 var(--body);
		color: var(--ink);
		cursor: pointer;
	}
	.drop strong {
		font: 600 var(--t-lg) var(--display);
		letter-spacing: 0.04em;
		text-transform: uppercase;
	}
	.drop:hover,
	.drop.dragging,
	.drop:has(+ input:focus-visible) {
		background: var(--blue-tint);
		border-color: var(--blue);
	}
	.live {
		display: grid;
		gap: 1rem;
	}
	.inline {
		display: flex;
		gap: 0.5rem;
	}
	.stage {
		position: relative;
		border-top: 1px solid var(--ink);
	}
	.livebar {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.5rem 1rem;
		background: var(--paper);
		border-bottom: 1px solid var(--ink);
		font: 600 var(--t-xs) var(--display);
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}
	.runbar {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.75rem 1rem;
		padding: 0.875rem 1rem;
		border-top: 1px solid var(--ink);
	}
	.runbar p {
		flex: 1 1 18rem;
		min-width: 0;
	}
	.runbar .notice {
		flex: 1 1 100%;
	}
	.go {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem;
	}
	.progress {
		flex: 1 1 100%;
		height: 6px;
		background: var(--grid);
		overflow: hidden;
	}
	.progress i {
		display: block;
		width: 30%;
		height: 100%;
		background: var(--blue);
		animation: slide 1.4s ease-in-out infinite;
	}
	@keyframes slide {
		from {
			transform: translateX(-100%);
		}
		to {
			transform: translateX(340%);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.progress i {
			animation: none;
			width: 100%;
		}
	}
	.feed li {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.5rem 0.75rem;
		padding: 0.625rem 1rem;
		border-bottom: 1px solid var(--grid);
	}
	.form {
		display: grid;
		gap: 0.875rem;
	}
	.two {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 0.75rem;
	}
	.rulelist {
		display: grid;
		gap: 0.375rem;
		margin-top: 0.5rem;
		font-size: var(--t-sm);
	}
	.status p {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}
	.status dl {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: 0.25rem 0.75rem;
		margin-top: 0.75rem;
		font-size: var(--t-sm);
	}
	.status dt {
		color: var(--muted);
	}
	.status dd {
		margin: 0;
		overflow-wrap: anywhere;
	}
	@media (max-width: 700px) {
		.clips .note {
			display: none;
		}
	}
	@container (max-width: 1000px) {
		.layout {
			grid-template-columns: minmax(0, 1fr);
		}
	}
</style>
