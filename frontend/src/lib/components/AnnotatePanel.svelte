<script lang="ts">
	// The annotated video: asks the backend to draw person boxes and rule names on the loaded clip, and shows, step by
	// step, that the server is working on it (the request itself stays silent until the MP4 is ready).
	import { fmt } from '#lib/analysis.ts';
	import { session } from '#lib/session.svelte.ts';
	import Icon from './Icon.svelte';

	const a = session.annotation;

	const STEPS = [
		{ key: 'uploading', label: 'Upload' },
		{ key: 'processing', label: 'Server at work' },
		{ key: 'downloading', label: 'Download' }
	] as const;
	const ORDER = ['preparing', 'uploading', 'processing', 'downloading', 'done'];

	let enabled = $derived(session.rules.filter((r) => r.enabled).length);
	let cannot = $derived.by(() => {
		if (!session.source) return 'Choose a video first.';
		if (!session.source.file && session.source.kind === 'upload')
			return 'Choose the video file again.';
		if (session.backend.state === 'offline') return 'The AI backend is not reachable.';
		if (session.backend.state === 'online' && !session.backend.keyConfigured)
			return 'The backend has no OpenRouter key, so it cannot check the rules.';
		if (enabled === 0) return 'Turn on at least one safety rule.';
		return '';
	});

	function stepState(key: string): 'done' | 'now' | 'todo' {
		const at = ORDER.indexOf(a.state);
		const index = ORDER.indexOf(key);
		if (at > index) return 'done';
		return at === index ? 'now' : 'todo';
	}

	function mb(bytes: number) {
		return `${(bytes / 1024 / 1024).toFixed(bytes < 10 * 1024 * 1024 ? 1 : 0)} MB`;
	}

	/** What the server is most likely doing, from how long it has been at it */
	let serverLine = $derived.by(() => {
		const t = a.phaseElapsed;
		if (t < 15)
			return `The Safety Agent is checking ${enabled} rules on about one frame per second.`;
		if (t < 60)
			return 'Still checking frames with the vision model. A one-minute clip usually takes about a minute.';
		if (t < 150)
			return 'Then YOLO finds each person, the boxes are drawn and the video is encoded to MP4.';
		return 'Long clips take a few minutes. It is still running: the backend answers every check.';
	});

	let summary = $derived(
		[
			a.annotatedFrames !== null && `${a.annotatedFrames} frames marked`,
			a.safetyEvents !== null && `${a.safetyEvents} ${a.safetyEvents === 1 ? 'event' : 'events'}`,
			a.cached
				? 'cached with the demo clip, drawn with the default rules'
				: `made in ${fmt(a.elapsed)}`
		]
			.filter(Boolean)
			.join(' · ')
	);

	let stamp = $derived(
		session.source
			? session.source.name.replace(/\.[^.]+$/, '') + '.annotated.mp4'
			: 'annotated.mp4'
	);
</script>

<section class="panel annotate" aria-label="Annotated video">
	<div class="panel-head">
		<h2>Annotated video</h2>
		{#if a.state === 'done' && a.url}
			<div class="segmented" role="group" aria-label="Video shown">
				<button
					type="button"
					aria-pressed={a.showing === 'original'}
					onclick={() => (a.showing = 'original')}>Original</button
				>
				<button
					type="button"
					aria-pressed={a.showing === 'annotated'}
					onclick={() => (a.showing = 'annotated')}>Boxes</button
				>
			</div>
		{:else}
			<span class="meta">boxes + rule names, drawn by the server</span>
		{/if}
	</div>

	<div class="panel-body" aria-live="polite">
		{#if a.busy}
			<ol class="steps" aria-label="Progress">
				{#each STEPS as step, i (step.key)}
					{@const s = stepState(step.key)}
					<li class={s} aria-current={s === 'now' ? 'step' : undefined}>
						<span class="num"
							>{#if s === 'done'}<Icon name="check" size={12} />{:else}{i + 1}{/if}</span
						>
						<span class="lbl">{step.label}</span>
						<span class="t mono"
							>{#if s === 'now'}{a.phaseElapsed} s{:else if s === 'done' && a.durations[step.key] != null}{a
									.durations[step.key]} s{/if}</span
						>
					</li>
				{/each}
			</ol>

			{#if a.fraction !== null}
				<div
					class="bar"
					role="progressbar"
					aria-label={a.state === 'uploading' ? 'Upload' : 'Download'}
					aria-valuemin="0"
					aria-valuemax="100"
					aria-valuenow={Math.round(a.fraction * 100)}
				>
					<i style:width="{a.fraction * 100}%"></i>
				</div>
			{:else}
				<div class="bar busy" role="progressbar" aria-label="The server is working"><i></i></div>
			{/if}

			<div class="lines">
				{#if a.state === 'preparing'}
					<p>Reading the video…</p>
				{:else if a.state === 'uploading'}
					<p>
						Sending the video to the backend{#if a.total}: {mb(a.loaded)} of {mb(a.total)} ({Math.round(
								(a.fraction ?? 0) * 100
							)}%){/if}.
					</p>
				{:else if a.state === 'processing'}
					<p>{serverLine}</p>
					<p class="pulse" class:lost={a.heartbeat.ok === false}>
						<i class="beat" class:ok={a.heartbeat.ok === true}></i>
						{#if a.heartbeat.ok === null}
							Checking the backend…
						{:else if a.heartbeat.ok}
							Backend is alive · answered {a.sinceHeartbeat ?? 0} s ago
						{:else}
							No answer from the backend for {a.sinceHeartbeat ?? '?'} s · retrying
						{/if}
					</p>
				{:else if a.state === 'downloading'}
					<p>
						The video is ready. Receiving it{#if a.total}: {mb(a.loaded)} of {mb(a.total)}{:else}: {mb(
								a.loaded
							)}{/if}.
					</p>
				{/if}
			</div>

			{#if a.backendSilent}
				<p class="notice warn" role="alert">
					<Icon name="warn" />
					The backend has stopped answering. It may have restarted or run out of memory; the job is probably
					lost. Cancel and try again, or use a shorter clip.
				</p>
			{/if}

			<div class="row">
				<span class="muted mono">Total {fmt(a.elapsed)}</span>
				<button class="btn" type="button" onclick={() => a.cancel()}>Cancel</button>
			</div>
		{:else if a.state === 'done' && a.url}
			<p>
				Red boxes are violations, amber are near misses (within 0.15 of the threshold). Otherwise
				each person shows what they are doing: green is value-adding work, blue is waste.
				{summary}.
			</p>
			{#if session.annotationStale}
				<p class="notice warn" role="status">
					<Icon name="warn" />
					The rules changed since these boxes were drawn. Draw again to match them.
				</p>
			{/if}
			<div class="row">
				<a class="btn" href={a.url} download={stamp}><Icon name="download" /> Download MP4</a>
				<button
					class="btn"
					type="button"
					onclick={() => session.annotate()}
					disabled={Boolean(cannot)}><Icon name="reset" /> Draw again</button
				>
				{#if a.size}<span class="muted">{mb(a.size)}</span>{/if}
			</div>
		{:else}
			{#if a.state === 'error'}
				<div class="notice warn" role="alert">
					<Icon name="warn" />
					<div>
						<strong>The annotated video was not made.</strong>
						<p>{a.error}</p>
					</div>
				</div>
			{:else if a.state === 'cancelled'}
				<p class="muted">Cancelled. The backend may finish the job on its own; nothing is kept.</p>
			{/if}
			<p>
				The backend runs the Safety Agent on the whole clip, finds each person with YOLO and draws a
				box with the rule name on every violation and near miss. It takes about as long as the
				analysis
				{#if session.isDemo}and calls the vision model, even for a demo clip{/if}.
			</p>
			<div class="row">
				<button
					class="btn primary"
					type="button"
					onclick={() => session.annotate()}
					disabled={Boolean(cannot)}
				>
					<Icon name="film" />
					{a.state === 'error' ? 'Try again' : 'Draw boxes on the video'}
				</button>
				<span class="muted">{cannot || `${enabled} rules on`}</span>
			</div>
		{/if}
	</div>
</section>

<style>
	.panel-body {
		display: grid;
		gap: 0.875rem;
	}
	.row {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: 0.5rem 1rem;
	}
	.row .btn:first-child {
		margin-right: auto;
	}
	.steps {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		border: 1px solid var(--ink);
	}
	.steps li {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		min-width: 0;
		padding: 0.5rem 0.75rem;
		border-right: 1px solid var(--ink);
		color: var(--muted);
		font: 500 var(--t-xs) / 1.2 var(--display);
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}
	.steps li:last-child {
		border-right: 0;
	}
	.steps li.now {
		background: var(--blue-tint);
		color: var(--blue-dark);
	}
	.steps li.done {
		color: var(--ink);
	}
	.num {
		display: inline-grid;
		place-items: center;
		flex: none;
		width: 1.25rem;
		height: 1.25rem;
		border: 1px solid currentColor;
		font-weight: 600;
	}
	li.now .num {
		background: var(--blue);
		border-color: var(--blue);
		color: #fff;
	}
	.lbl {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.t {
		flex: none;
	}
	.bar {
		height: 6px;
		background: var(--grid);
		overflow: hidden;
	}
	.bar i {
		display: block;
		height: 100%;
		background: var(--blue);
		transition: width 0.2s linear;
	}
	.bar.busy i {
		width: 30%;
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
	.lines {
		display: grid;
		gap: 0.375rem;
	}
	.pulse {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		color: var(--muted);
		font-size: var(--t-sm);
	}
	.pulse.lost {
		color: var(--hot-ink);
	}
	.beat {
		flex: none;
		width: 8px;
		height: 8px;
		background: var(--muted);
	}
	.beat.ok {
		background: var(--blue);
		animation: beat 1.6s ease-out infinite;
	}
	@keyframes beat {
		0% {
			box-shadow: 0 0 0 0 var(--blue-line);
		}
		70% {
			box-shadow: 0 0 0 7px transparent;
		}
		100% {
			box-shadow: 0 0 0 0 transparent;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.bar.busy i {
			animation: none;
			width: 100%;
		}
		.beat.ok {
			animation: none;
		}
	}
	@media (max-width: 520px) {
		.steps {
			grid-template-columns: 1fr;
		}
		.steps li {
			border-right: 0;
			border-bottom: 1px solid var(--ink);
		}
		.steps li:last-child {
			border-bottom: 0;
		}
	}
</style>
