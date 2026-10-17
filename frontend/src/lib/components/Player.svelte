<script lang="ts">
	import { playback } from '#lib/playback.svelte.ts';
	import { session } from '#lib/session.svelte.ts';
	import Icon from './Icon.svelte';

	let {
		src,
		label = 'Workstation video',
		loop = false,
		muted = true
	}: { src: string | null; label?: string; loop?: boolean; muted?: boolean } = $props();

	let video: HTMLVideoElement | undefined = $state();
	/** The browser cannot decode this file (the server can still analyse it) */
	let unplayable = $state(false);

	$effect(() => {
		void src;
		unplayable = false;
	});
	let applied = playback.request?.n ?? 0;

	// Obey seek requests made anywhere in the app
	$effect(() => {
		const request = playback.request;
		if (!video || !request || request.n === applied) return;
		applied = request.n;
		const el = video;
		const go = () => {
			el.currentTime = request.t;
			if (request.play) void el.play().catch(() => {});
		};
		if (el.readyState >= 1) go();
		else el.addEventListener('loadedmetadata', go, { once: true });
	});

	function loaded() {
		if (!video) return;
		playback.duration = video.duration;
		// Pick up where another page's player left off
		if (playback.time > 0 && Math.abs(video.currentTime - playback.time) > 0.5)
			video.currentTime = playback.time;
	}
</script>

{#if src && unplayable}
	<div class="missing" role="alert">
		<p>
			<strong>This browser cannot play this video file.</strong> Its codec is not supported here, often
			H.265 (HEVC) from a camera or phone, or an older MPEG-4 or AVI file. The analysis does not need
			the preview and still works.
		</p>
		{#if session.source?.file}
			<button
				class="btn primary"
				type="button"
				onclick={() => session.convertPreview()}
				disabled={session.preview.state === 'converting'}
			>
				{session.preview.state === 'converting'
					? 'Converting on the server…'
					: 'Make a preview I can play'}
			</button>
			{#if session.preview.state === 'converting'}
				<p class="muted" role="status">
					The backend is re-encoding the video to H.264. This takes about as long as the clip is.
				</p>
			{:else if session.preview.state === 'error'}
				<p role="alert">
					<strong>Could not convert:</strong>
					{session.preview.error}
				</p>
			{/if}
		{/if}
		<p class="muted">
			Or convert it yourself (same timing, so timestamps still match):
			<code>ffmpeg -i input.mov -c:v libx264 -pix_fmt yuv420p -c:a aac output.mp4</code>
		</p>
	</div>
{:else if src}
	<video
		bind:this={video}
		{src}
		{loop}
		{muted}
		controls
		playsinline
		preload="metadata"
		aria-label={label}
		onloadedmetadata={loaded}
		onerror={() => (unplayable = video?.error?.code === 4 || !video?.videoWidth)}
		ontimeupdate={() => video && (playback.time = video.currentTime)}
	>
		<track kind="captions" />
	</video>
{:else}
	<div class="missing">
		<p>
			<strong>The video file is not loaded.</strong> The results survived the reload; the file did not.
			Choose it again to play the moments.
		</p>
		<label class="btn" for="reattach"><Icon name="upload" /> Choose the file</label>
		<input
			id="reattach"
			class="sr-only"
			type="file"
			accept="video/*"
			onchange={(e) => {
				const f = e.currentTarget.files?.[0];
				if (f) session.reattachFile(f);
				e.currentTarget.value = '';
			}}
		/>
	</div>
{/if}

<style>
	video {
		display: block;
		width: 100%;
		aspect-ratio: 16 / 9;
		background: var(--ink);
		object-fit: contain;
	}
	.missing {
		display: grid;
		gap: 0.75rem;
		justify-items: start;
		align-content: center;
		min-height: 12rem;
		padding: 1.5rem;
		background: var(--surface);
		border: 1px dashed var(--ink);
	}
	.missing code {
		max-width: 100%;
		padding: 0.375rem 0.5rem;
		background: var(--paper);
		border: 1px solid var(--ink);
		font: 400 var(--t-xs) / 1.4 var(--mono, monospace);
		overflow-wrap: anywhere;
	}
	.missing label {
		margin: 0;
		cursor: pointer;
	}
</style>
