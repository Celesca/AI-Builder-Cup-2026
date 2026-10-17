<script lang="ts">
	import { fmt, severityRank } from '#lib/analysis.ts';
	import FrameGrid from '#lib/components/FrameGrid.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import Legend from '#lib/components/Legend.svelte';
	import RuleMatrix from '#lib/components/RuleMatrix.svelte';
	import RuleRow from '#lib/components/RuleRow.svelte';
	import Thumb from '#lib/components/Thumb.svelte';
	import TimeChip from '#lib/components/TimeChip.svelte';
	import Slash from '#lib/components/Slash.svelte';
	import { playback } from '#lib/playback.svelte.ts';
	import { newRuleId, PRESET_RULES } from '#lib/rules.ts';
	import { session } from '#lib/session.svelte.ts';
	import type { Rule } from '#lib/types.ts';

	let filter = $state<'all' | 'open' | 'high'>('all');
	let sort = $state<'severity' | 'time'>('severity');

	let step = $derived(session.sampleFps > 0 ? 1 / session.sampleFps : 1);
	let actions = $derived(
		new Map((session.result?.lss.safety_actions ?? []).map((a) => [a.rule_id, a]))
	);
	let unreviewed = $derived(session.incidents.filter((i) => !session.isReviewed(i.key)).length);
	let high = $derived(session.incidents.filter((i) => i.severity === 'high').length);
	let list = $derived(
		session.incidents
			.filter((i) =>
				filter === 'open'
					? !session.isReviewed(i.key)
					: filter === 'high'
						? i.severity === 'high'
						: true
			)
			.sort((a, b) =>
				sort === 'severity'
					? severityRank(b.severity) - severityRank(a.severity) || a.start - b.start
					: a.start - b.start
			)
	);
	let presets = $derived(PRESET_RULES.filter((p) => !session.rules.some((r) => r.id === p.id)));
	let rerunBlock = $derived.by(() => {
		const source = session.source;
		if (!source) return 'Load a video on the Video page first.';
		if (source.kind === 'demo')
			return session.backend.state === 'online' && session.backend.keyConfigured
				? 'Demo clips carry a cached analysis. Upload a video to run your own prompts.'
				: 'Demo clips carry a cached analysis. Running your own prompts needs an uploaded video and an OpenRouter key on the backend; none is configured.';
		if (!source.file) return 'Choose the video file again on the Video page.';
		if (session.backend.state === 'offline') return 'The AI backend is not reachable.';
		if (session.backend.state === 'online' && !session.backend.keyConfigured)
			return 'The backend has no OpenRouter key.';
		return '';
	});

	function addBlank() {
		const id = newRuleId(
			'new rule',
			session.rules.map((r) => r.id)
		);
		session.addRule({
			id,
			label: 'New rule',
			prompt: '',
			severity: 'medium',
			threshold: 0.6,
			enabled: true
		});
	}

	function addPreset(preset: Rule) {
		session.addRule({ ...preset });
	}
</script>

<svelte:head><title>Safety Agent · VALZ</title></svelte:head>

<main class="page">
	<div class="page-head">
		<div>
			<h1>Safety Agent</h1>
			<p>
				The agent asks a vision model, for every sampled frame, whether each rule is being broken.
				Edit the prompts here. Thresholds, severity and on/off update the incidents instantly; a
				changed prompt needs a re-run.
			</p>
		</div>
		<div class="rerun">
			<button
				class="btn primary"
				type="button"
				onclick={() => session.analyze()}
				disabled={Boolean(rerunBlock) || session.status === 'running'}
			>
				<Icon name="reset" /> Re-run analysis <Slash />
			</button>
			{#if rerunBlock}<p class="field-hint">{rerunBlock}</p>{/if}
		</div>
	</div>

	{#if session.staleRules.length > 0}
		<div class="notice warn" role="status">
			<Icon name="warn" />
			<p>
				<strong
					>{session.staleRules.length}
					{session.staleRules.length === 1 ? 'rule has' : 'rules have'} no results yet</strong
				>
				({session.staleRules.map((r) => r.label).join(', ')}).
				{rerunBlock || 'Re-run the analysis to check them.'}
			</p>
		</div>
	{/if}

	<div class="layout">
		<section class="panel" aria-label="Rules">
			<div class="panel-head">
				<h2>Rules</h2>
				<span class="meta">{session.rules.filter((r) => r.enabled).length} on</span>
			</div>
			<ul>
				{#each session.rules as rule (rule.id)}
					<RuleRow {rule} />
				{/each}
			</ul>
			<div class="panel-body adders">
				<button class="btn small" type="button" onclick={addBlank}
					><Icon name="plus" size={14} /> Add rule</button
				>
				{#each presets as preset (preset.id)}
					<button class="chip" type="button" onclick={() => addPreset(preset)}
						>+ {preset.label}</button
					>
				{/each}
				<button class="btn small" type="button" onclick={() => session.resetRules()}
					><Icon name="reset" size={14} /> Reset to defaults</button
				>
			</div>
		</section>

		<div class="evidence">
			{#if !session.result}
				<div class="empty">
					<h2>No analysis yet</h2>
					<p>
						Incidents appear here once a video has been analysed. Open the cached demo clip to
						explore this page now, or upload your own video.
					</p>
					<a class="btn primary" href="/video">Go to Video <Slash /></a>
				</div>
			{:else}
				<section class="panel" aria-label="Rules over time">
					<div class="panel-head">
						<h2>Rules over time</h2>
						<span class="meta"
							>{fmt(session.duration)} · {session.frames.length} frames at {session.sampleFps} fps</span
						>
					</div>
					<div class="panel-body">
						<RuleMatrix frames={session.frames} {step} />
					</div>
				</section>

				<section class="panel" aria-label="Incidents">
					<div class="panel-head">
						<h2>Incidents</h2>
						<span class="meta"
							>{session.incidents.length} found · {high} high · {unreviewed} to review</span
						>
					</div>
					<div class="toolbar">
						<div class="segmented" role="group" aria-label="Filter incidents">
							<button type="button" aria-pressed={filter === 'all'} onclick={() => (filter = 'all')}
								>All</button
							>
							<button
								type="button"
								aria-pressed={filter === 'open'}
								onclick={() => (filter = 'open')}>To review</button
							>
							<button
								type="button"
								aria-pressed={filter === 'high'}
								onclick={() => (filter = 'high')}>High</button
							>
						</div>
						<div class="segmented" role="group" aria-label="Sort incidents">
							<button
								type="button"
								aria-pressed={sort === 'severity'}
								onclick={() => (sort = 'severity')}>By severity</button
							>
							<button type="button" aria-pressed={sort === 'time'} onclick={() => (sort = 'time')}
								>By time</button
							>
						</div>
					</div>

					{#if list.length === 0}
						<div class="panel-body">
							<p class="muted">
								{session.incidents.length === 0
									? 'No rule reached its threshold in this video. Lower a threshold above to see near misses.'
									: 'No incident matches this filter.'}
							</p>
						</div>
					{:else}
						<ul class="incidents">
							{#each list as incident (incident.key)}
								{@const reviewed = session.isReviewed(incident.key)}
								{@const action = actions.get(incident.ruleId)}
								<li class="incident" class:reviewed>
									<Thumb
										snapshot={incident.snapshot}
										url={session.source?.url}
										time={incident.keyTime}
										width={176}
									/>
									<div class="info">
										<div class="line">
											<span class="tag {incident.severity}">{incident.severity}</span>
											<strong>{incident.label}</strong>
											<TimeChip start={incident.start} end={incident.end} />
											<span class="muted"
												>{Math.round(incident.peak * 100)}% · {incident.frames}
												{incident.frames === 1 ? 'frame' : 'frames'}</span
											>
										</div>
										<p>{incident.description || `Rule: ${incident.prompt}`}</p>
										{#if action}
											<p class="action">
												<strong>Suggested action:</strong>
												{action.action}
												{#if action.kb_card_ids.length}<span class="muted mono">
														({action.kb_card_ids.join(', ')})</span
													>{/if}
											</p>
										{/if}
									</div>
									<div class="acts">
										<button
											class="btn small primary"
											type="button"
											onclick={() => playback.seek(Math.max(0, incident.start - 1))}
										>
											<Icon name="play" size={12} /> Play
										</button>
										<button
											class="btn small"
											type="button"
											aria-pressed={reviewed}
											onclick={() => session.toggleReviewed(incident.key)}
										>
											<Icon name="check" size={14} />
											{reviewed ? 'Reviewed' : 'Mark reviewed'}
										</button>
									</div>
								</li>
							{/each}
						</ul>
					{/if}
				</section>

				<section class="panel flat" aria-label="Whole shift">
					<div class="panel-head">
						<h2>Whole shift</h2>
						<span class="meta"
							>numbers are seconds · orange edge = a rule was broken in that second</span
						>
					</div>
					<div class="panel-body grid">
						<FrameGrid
							frames={session.frames}
							incidents={session.incidents}
							{step}
							takt={session.takt}
						/>
						<Legend
							present={new Set(session.frames.map((f) => f.category))}
							violations
							takt={session.takt !== null}
						/>
					</div>
				</section>
			{/if}
		</div>
	</div>
</main>

<style>
	.layout {
		display: grid;
		grid-template-columns: 26rem minmax(0, 1fr);
		gap: 1.5rem;
		align-items: start;
	}
	.rerun {
		display: grid;
		gap: 0.375rem;
		justify-items: end;
		max-width: 26rem;
		text-align: right;
	}
	.evidence {
		display: grid;
		gap: 1.5rem;
		min-width: 0;
	}
	.adders {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem;
	}
	.toolbar {
		display: flex;
		flex-wrap: wrap;
		gap: 0.75rem;
		justify-content: space-between;
		padding: 0.625rem 1rem;
		border-bottom: 1px solid var(--grid);
	}
	.incident {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr) auto;
		gap: 1rem;
		padding: 1rem;
		border-bottom: 1px solid var(--ink);
	}
	.incident:last-child {
		border-bottom: 0;
	}
	.incident.reviewed {
		background: var(--surface);
	}
	.incident.reviewed .info {
		opacity: 0.7;
	}
	.info {
		display: grid;
		gap: 0.375rem;
		min-width: 0;
	}
	.line {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.5rem 0.75rem;
	}
	.line strong {
		font: 600 var(--t-md) var(--display);
		letter-spacing: 0.04em;
		text-transform: uppercase;
	}
	.action {
		font-size: var(--t-sm);
		color: var(--ink-2);
	}
	.acts {
		display: grid;
		gap: 0.5rem;
		align-content: start;
	}
	.grid {
		display: grid;
		gap: 0.875rem;
	}
	@container (max-width: 1100px) {
		.layout {
			grid-template-columns: minmax(0, 1fr);
		}
		.evidence {
			order: -1;
		}
	}
	@media (max-width: 700px) {
		.incident {
			grid-template-columns: minmax(0, 1fr);
		}
		.acts {
			grid-auto-flow: column;
			justify-content: start;
		}
	}
</style>
