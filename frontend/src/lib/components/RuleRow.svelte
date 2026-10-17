<script lang="ts">
	import { pct, peakConfidence } from '#lib/analysis.ts';
	import { MAX_PROMPT_LENGTH, SEVERITIES } from '#lib/rules.ts';
	import { session } from '#lib/session.svelte.ts';
	import type { Rule } from '#lib/types.ts';
	import Icon from './Icon.svelte';

	let { rule }: { rule: Rule } = $props();

	let state = $derived(session.ruleState(rule));
	let count = $derived(session.incidents.filter((i) => i.ruleId === rule.id).length);
	let peak = $derived(state === 'ready' ? peakConfidence(session.frames, rule.id) : null);
	const uid = $props.id();
</script>

<li class="rule" class:off={!rule.enabled}>
	<div class="top">
		<input
			type="checkbox"
			checked={rule.enabled}
			aria-label="Rule {rule.label} is on"
			onchange={(e) => session.updateRule(rule.id, { enabled: e.currentTarget.checked })}
		/>
		<input
			type="text"
			class="name"
			value={rule.label}
			aria-label="Rule name"
			maxlength="40"
			oninput={(e) => session.updateRule(rule.id, { label: e.currentTarget.value })}
		/>
		<button
			class="btn small"
			type="button"
			aria-label="Remove rule {rule.label}"
			onclick={() => session.removeRule(rule.id)}
		>
			<Icon name="trash" size={14} />
		</button>
	</div>

	<div class="body">
		<details class="prompt" open={state !== 'ready' || !rule.prompt.trim()}>
			<summary>
				<span class="field-label">Prompt</span>
				<span class="preview">{rule.prompt || 'Describe the violation'}</span>
			</summary>
			<div class="field">
				<label class="sr-only" for="{uid}-prompt">Prompt for {rule.label}</label>
				<textarea
					id="{uid}-prompt"
					rows="2"
					maxlength={MAX_PROMPT_LENGTH}
					value={rule.prompt}
					oninput={(e) => session.updateRule(rule.id, { prompt: e.currentTarget.value })}
				></textarea>
				<p class="field-hint">
					Describe the violation. For every frame the agent is asked whether this is happening.
				</p>
			</div>
		</details>

		<div class="ctl">
			<div class="field">
				<span class="field-label" id="{uid}-sev">Severity</span>
				<div class="segmented" role="group" aria-labelledby="{uid}-sev">
					{#each SEVERITIES as level (level)}
						<button
							type="button"
							aria-pressed={rule.severity === level}
							onclick={() => session.updateRule(rule.id, { severity: level })}>{level}</button
						>
					{/each}
				</div>
			</div>
			<div class="field grow">
				<label for="{uid}-th">Threshold <span class="val">{pct(rule.threshold)}%</span></label>
				<input
					id="{uid}-th"
					type="range"
					min="0.3"
					max="0.95"
					step="0.05"
					value={rule.threshold}
					oninput={(e) => session.updateRule(rule.id, { threshold: Number(e.currentTarget.value) })}
				/>
			</div>
		</div>

		<p class="state {state}">
			{#if !rule.enabled}
				Off: not checked and not sent on the next run.
			{:else if state === 'ready'}
				<strong>{count} {count === 1 ? 'incident' : 'incidents'}</strong>
				· strongest frame {peak === null ? '–' : `${pct(peak)}%`}
			{:else if state === 'changed'}
				<Icon name="warn" size={14} /> Prompt changed: re-run the analysis to apply it.
			{:else}
				<Icon name="warn" size={14} /> Not analysed yet: re-run the analysis to check it.
			{/if}
		</p>
	</div>
</li>

<style>
	.rule {
		display: grid;
		border-bottom: 1px solid var(--ink);
	}
	.rule.off .body {
		opacity: 0.55;
	}
	.top {
		display: grid;
		grid-template-columns: auto 1fr auto;
		gap: 0.625rem;
		align-items: center;
		padding: 0.625rem 1rem;
		background: var(--surface);
		border-bottom: 1px solid var(--grid);
	}
	.name {
		font: 600 var(--t-md) var(--display);
		letter-spacing: 0.04em;
		text-transform: uppercase;
		border-color: transparent;
		background: transparent;
	}
	.name:hover {
		border-color: var(--ink);
		background: var(--paper);
	}
	.body {
		display: grid;
		gap: 0.75rem;
		padding: 0.75rem 1rem 1rem;
	}
	.prompt summary {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr);
		gap: 0.75rem;
		align-items: baseline;
		cursor: pointer;
		list-style: none;
	}
	.prompt summary::-webkit-details-marker {
		display: none;
	}
	.prompt summary .field-label {
		margin: 0;
	}
	.prompt summary::after {
		content: none;
	}
	.preview {
		overflow: hidden;
		color: var(--ink-2);
		font-size: var(--t-sm);
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.prompt[open] summary {
		margin-bottom: 0.5rem;
	}
	.prompt[open] .preview {
		visibility: hidden;
	}
	.ctl {
		display: flex;
		flex-wrap: wrap;
		gap: 0.75rem 1.25rem;
		align-items: end;
	}
	.grow {
		flex: 1 1 8rem;
	}
	.val {
		margin-left: 0.5rem;
		color: var(--blue-dark);
		font-weight: 700;
	}
	.state {
		display: flex;
		align-items: center;
		gap: 0.375rem;
		font-size: var(--t-sm);
		color: var(--ink-2);
	}
	.state.changed,
	.state.new {
		color: var(--ink);
		font-weight: 600;
	}
</style>
