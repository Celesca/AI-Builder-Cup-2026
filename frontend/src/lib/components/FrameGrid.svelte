<script lang="ts">
	import { activityLabel, fmt } from '#lib/analysis.ts';
	import { playback } from '#lib/playback.svelte.ts';
	import type { Incident, TimelineFrame } from '#lib/types.ts';

	let {
		frames,
		incidents = [],
		step = 1,
		takt = null,
		label = 'Shift timeline, one cell per sampled second. Select a cell to play the video from there.'
	}: {
		frames: TimelineFrame[];
		incidents?: Incident[];
		step?: number;
		takt?: number | null;
		label?: string;
	} = $props();

	let violated = $derived(
		new Set(
			frames
				.filter((f) => incidents.some((i) => f.timestamp >= i.start && f.timestamp < i.end))
				.map((f) => f.timestamp)
		)
	);
	let narrow = $state(false);
	$effect(() => {
		const query = matchMedia('(max-width: 700px)');
		narrow = query.matches;
		const change = (event: MediaQueryListEvent) => (narrow = event.matches);
		query.addEventListener('change', change);
		return () => query.removeEventListener('change', change);
	});
	// One row per minute (a cell is one sampled second), so the cell at takt time opens the second row
	let perRow = $derived(narrow ? 15 : Math.max(1, Math.min(60, Math.round(60 / step))));
	// Numbers are seconds from the start of the video
	const tick = (i: number, t: number) =>
		i % perRow === 0 || Math.round(t) % 10 === 0 ? String(Math.round(t)) : undefined;
	let nowIndex = $derived(Math.floor(playback.time / step));
	let taktIndex = $derived(takt && takt > 0 ? Math.floor(takt / step) : -1);
</script>

<div class="cells" style:--cols={perRow} role="group" aria-label={label}>
	{#each frames as frame, i (frame.timestamp)}
		<button
			type="button"
			class="cell k-{frame.category}"
			class:now={i === nowIndex}
			class:takt={i === taktIndex}
			data-tick={tick(i, frame.timestamp)}
			aria-label="{fmt(frame.timestamp)} {activityLabel(frame.activity)}{violated.has(
				frame.timestamp
			)
				? ', a rule was broken'
				: ''}{i === taktIndex ? ', takt time reached' : ''}"
			onclick={() => playback.seek(frame.timestamp)}
		>
			{#if violated.has(frame.timestamp)}<span class="hit"></span>{/if}
		</button>
	{/each}
</div>
