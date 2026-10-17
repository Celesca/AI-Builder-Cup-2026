<script lang="ts">
	import { captureFrame } from '#lib/frames.ts';
	import { fmt } from '#lib/analysis.ts';

	let {
		snapshot,
		url,
		time,
		width = 160
	}: { snapshot?: string | null; url?: string | null; time: number; width?: number } = $props();
	let captured = $state<string | null>(null);
	let failed = $state(false);

	$effect(() => {
		captured = null;
		failed = false;
		if (snapshot || !url) return;
		let live = true;
		captureFrame(url, time).then((data) => {
			if (!live) return;
			if (data) captured = data;
			else failed = true;
		});
		return () => (live = false);
	});

	let image = $derived(snapshot ?? captured);
</script>

<div class="thumb" style:width="{width}px">
	{#if image}
		<img src={image} alt="Frame at {fmt(time)}" />
	{:else}
		<div class="ph" class:skeleton={!failed && !!url}>{failed || !url ? 'No frame' : ''}</div>
	{/if}
</div>

<style>
	.thumb {
		flex: none;
		aspect-ratio: 16 / 9;
		background: var(--ink);
		border: 1px solid var(--ink);
		overflow: hidden;
	}
	img {
		display: block;
		width: 100%;
		height: 100%;
		object-fit: cover;
	}
	.ph {
		display: grid;
		place-items: center;
		height: 100%;
		color: var(--muted);
		font: 500 0.6875rem var(--display);
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}
</style>
