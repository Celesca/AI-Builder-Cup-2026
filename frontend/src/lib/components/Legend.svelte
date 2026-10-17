<script lang="ts">
	import { CATEGORY_LABEL, CATEGORY_ORDER } from '#lib/analysis.ts';
	import type { Category } from '#lib/types.ts';

	let {
		present,
		takt = false,
		violations = false
	}: { present?: Set<string>; takt?: boolean; violations?: boolean } = $props();
	let shown = $derived(CATEGORY_ORDER.filter((c) => !present || present.has(c)));
</script>

<div class="legend" aria-label="Legend">
	{#each shown as category (category)}
		<span><i class="swatch k-{category as Category}"></i>{CATEGORY_LABEL[category]}</span>
	{/each}
	{#if violations}<span
			><i class="swatch" style="background:linear-gradient(to top,var(--hot) 5px,var(--paper) 5px)"
			></i>Rule broken</span
		>{/if}
	{#if takt}<span
			><i
				class="swatch"
				style="background:linear-gradient(to top right,transparent calc(50% - 1px),var(--blue) calc(50% - 1px),var(--blue) calc(50% + 1px),transparent calc(50% + 1px))"
			></i>Takt time</span
		>{/if}
</div>
