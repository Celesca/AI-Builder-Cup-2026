<script lang="ts">
	import { fmt, fmtRange } from '#lib/analysis.ts';
	import { playback } from '#lib/playback.svelte.ts';

	let { start, end, label }: { start: number; end?: number; label?: string } = $props();
	let text = $derived(end !== undefined && end > start ? fmtRange(start, end) : fmt(start));
</script>

<button
	class="chip"
	type="button"
	onclick={() => playback.seek(start)}
	aria-label={label ?? `Play the video from ${fmt(start)}`}
>
	{text}
</button>
