<script lang="ts">
	import { fmt, pct } from '#lib/analysis.ts';
	import { playback } from '#lib/playback.svelte.ts';
	import { session } from '#lib/session.svelte.ts';
	import type { TimelineFrame } from '#lib/types.ts';

	let { frames, step = 1 }: { frames: TimelineFrame[]; step?: number } = $props();

	let rules = $derived(session.rules.filter((r) => r.enabled));
	let hover = $state<{ rule: string; t: number; v: number } | null>(null);
	let span = $derived(Math.max(frames.length * step, 1));
	let playhead = $derived(Math.min(100, (playback.time / span) * 100));

	const hasData = (id: string) => frames.some((f) => f.rule_confidences[id] !== undefined);
	const countFor = (id: string) => session.incidents.filter((i) => i.ruleId === id).length;

	function cellStyle(v: number, threshold: number): string {
		if (v >= threshold) return `background:var(--hot)`;
		// near misses stay faintly visible so a threshold change is never a surprise
		return `background:rgba(255,77,26,${(Math.min(v / threshold, 1) * 0.28).toFixed(3)})`;
	}

	function frameAt(event: MouseEvent, ruleId: string) {
		const box = (event.currentTarget as HTMLElement).getBoundingClientRect();
		const index = Math.min(
			frames.length - 1,
			Math.max(0, Math.floor(((event.clientX - box.left) / box.width) * frames.length))
		);
		return frames[index] ? { frame: frames[index], ruleId } : null;
	}

	function show(ruleId: string, frame: TimelineFrame) {
		hover = { rule: ruleId, t: frame.timestamp, v: frame.rule_confidences[ruleId] ?? 0 };
	}

	function onmove(event: PointerEvent, ruleId: string) {
		const at = frameAt(event, ruleId);
		if (at) show(ruleId, at.frame);
	}

	// A tap or click scrubs the video and keeps the readout for that second
	function onclick(event: MouseEvent, ruleId: string) {
		const at = frameAt(event, ruleId);
		if (!at) return;
		show(ruleId, at.frame);
		playback.seek(at.frame.timestamp);
	}

	// Keyboard: arrows step one second, Home and End jump to the ends; the video seeks without playing
	function onkeydown(event: KeyboardEvent, ruleId: string) {
		const current = Math.min(frames.length - 1, Math.max(0, Math.round(playback.time / step)));
		const target =
			event.key === 'ArrowRight' || event.key === 'ArrowUp'
				? current + 1
				: event.key === 'ArrowLeft' || event.key === 'ArrowDown'
					? current - 1
					: event.key === 'Home'
						? 0
						: event.key === 'End'
							? frames.length - 1
							: null;
		if (target === null) return;
		event.preventDefault();
		const frame = frames[Math.min(frames.length - 1, Math.max(0, target))];
		show(ruleId, frame);
		playback.seek(frame.timestamp, false);
	}
</script>

<div class="matrix">
	<p class="readout" aria-live="polite">
		{#if hover}
			{fmt(hover.t)} · {session.rules.find((r) => r.id === hover!.rule)?.label} · {pct(hover.v)}%
		{:else}
			Each row is a rule, each column one sampled second. Orange means the rule's threshold was
			reached; faint orange is a near miss.
		{/if}
	</p>
	<div class="rows" style:--p={playhead / 100}>
		{#each rules as rule (rule.id)}
			<div class="row">
				<div class="name" title={rule.prompt}>{rule.label}</div>
				{#if hasData(rule.id)}
					<div
						class="track"
						role="slider"
						tabindex="0"
						aria-label="{rule.label} over time: arrow keys step one second"
						aria-valuemin={0}
						aria-valuemax={Math.max(0, frames.length - 1)}
						aria-valuenow={Math.min(frames.length - 1, Math.round(playback.time / step))}
						aria-valuetext="{fmt(playback.time)}, {pct(
							frames[Math.min(frames.length - 1, Math.round(playback.time / step))]
								?.rule_confidences[rule.id] ?? 0
						)}%"
						style:grid-template-columns="repeat({frames.length}, 1fr)"
						onpointermove={(e) => e.pointerType === 'mouse' && onmove(e, rule.id)}
						onpointerleave={(e) => e.pointerType === 'mouse' && (hover = null)}
						onclick={(e) => onclick(e, rule.id)}
						onkeydown={(e) => onkeydown(e, rule.id)}
					>
						{#each frames as frame (frame.timestamp)}
							<i style={cellStyle(frame.rule_confidences[rule.id] ?? 0, rule.threshold)}></i>
						{/each}
					</div>
					<div class="count" class:zero={countFor(rule.id) === 0}>{countFor(rule.id)}</div>
				{:else}
					<div class="nodata">Not analysed yet. Re-run the analysis to check this rule.</div>
					<div class="count zero">–</div>
				{/if}
			</div>
		{/each}
		<div class="playhead"></div>
	</div>
</div>

<style>
	.matrix {
		display: grid;
		gap: 0.5rem;
	}
	.readout {
		min-height: 1.4em;
		color: var(--ink-2);
		font-size: var(--t-sm);
	}
	.rows {
		--lead: 10rem;
		--tail: 3rem;
		position: relative;
		display: grid;
		gap: 0;
		border-top: 1px solid var(--ink);
	}
	.row {
		display: grid;
		grid-template-columns: var(--lead) 1fr var(--tail);
		align-items: stretch;
		min-height: 2rem;
		border-bottom: 1px solid var(--ink);
	}
	.name {
		display: flex;
		align-items: center;
		padding: 0 0.5rem;
		overflow: hidden;
		border-right: 1px solid var(--ink);
		font: 500 var(--t-xs) var(--display);
		letter-spacing: 0.06em;
		text-transform: uppercase;
		line-height: 1.15;
		overflow-wrap: anywhere;
	}
	.track:focus-visible {
		outline: 2px solid var(--blue);
		outline-offset: -2px;
	}
	.track {
		display: grid;
		cursor: crosshair;
		background: var(--paper);
	}
	.track i {
		display: block;
		min-width: 0;
	}
	.count {
		display: grid;
		place-items: center;
		border-left: 1px solid var(--ink);
		font: 700 var(--t-md) var(--display);
	}
	.count.zero {
		color: var(--muted);
		font-weight: 500;
	}
	.nodata {
		display: flex;
		align-items: center;
		padding: 0 0.75rem;
		background: repeating-linear-gradient(135deg, var(--surface) 0 6px, var(--paper) 6px 12px);
		color: var(--muted);
		font-size: var(--t-xs);
	}
	.playhead {
		position: absolute;
		top: 0;
		bottom: 0;
		left: calc(var(--lead) + (100% - var(--lead) - var(--tail)) * var(--p, 0));
		width: 2px;
		margin-left: -1px;
		background: var(--blue);
		pointer-events: none;
	}
	@media (max-width: 700px) {
		.rows {
			--lead: 6rem;
			--tail: 2.25rem;
		}
	}
</style>
