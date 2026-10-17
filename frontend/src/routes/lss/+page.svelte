<script lang="ts">
	import { fmt, hoursLabel, severityRank } from '#lib/analysis.ts';
	import Icon from '#lib/components/Icon.svelte';
	import Slash from '#lib/components/Slash.svelte';
	import TimeChip from '#lib/components/TimeChip.svelte';
	import { session } from '#lib/session.svelte.ts';
	import type { Decision } from '#lib/types.ts';

	let result = $derived(session.result);
	let lss = $derived(result?.lss);
	let cards = $derived(
		[...(lss?.lss_cards ?? [])].sort((a, b) => severityRank(b.priority) - severityRank(a.priority))
	);
	let sourceLabel = $derived(
		!lss
			? ''
			: session.isDemo
				? 'Cached demo result'
				: lss.source === 'llm'
					? `Written by ${lss.model}`
					: 'Rule-based: no LLM was used'
	);
	let cited = $derived(
		new Set([
			...(lss?.lss_cards ?? []).flatMap((c) => c.kb_card_ids),
			...(lss?.safety_actions ?? []).flatMap((a) => a.kb_card_ids)
		])
	);
	let citedCards = $derived((lss?.knowledge_cards_used ?? []).filter((k) => cited.has(k.id)));
	let otherCards = $derived((lss?.knowledge_cards_used ?? []).filter((k) => !cited.has(k.id)));
	let knowledge = $derived(new Map((lss?.knowledge_cards_used ?? []).map((k) => [k.id, k])));
	let tally = $derived.by(() => {
		const t = { approved: 0, deferred: 0, rejected: 0, open: 0, hours: 0 };
		for (const card of cards) {
			const d = session.decisionFor(card.id);
			if (d) t[d]++;
			else t.open++;
			if (d === 'approved') t.hours += card.roi?.hours_saved_per_shift ?? 0;
		}
		return t;
	});
	let copied = $state('');

	const DECISIONS: { value: Decision; label: string }[] = [
		{ value: 'approved', label: 'Approve' },
		{ value: 'deferred', label: 'Defer' },
		{ value: 'rejected', label: 'Reject' }
	];

	async function copy(text: string, what: string) {
		try {
			await navigator.clipboard.writeText(text);
			copied = what;
			setTimeout(() => (copied = ''), 1800);
		} catch {
			copied = '';
		}
	}

	function approvedText(): string {
		return cards
			.filter((c) => session.decisionFor(c.id) === 'approved')
			.map(
				(c) =>
					`- ${c.title}${c.roi ? ` (about ${c.roi.hours_saved_per_shift} h per shift)` : ''}: ${c.recommendation}`
			)
			.join('\n');
	}
</script>

<svelte:head><title>Gemba Kaizen · VALZ</title></svelte:head>

<main class="page">
	<div class="page-head">
		<div>
			<h1>Gemba Kaizen</h1>
			<p>
				What the agent suggests, from the waste and incidents measured in the video. Each suggestion
				names the moment it comes from and the lean practice it is based on. You decide.
			</p>
		</div>
		{#if lss}<span class="tag {session.isDemo || lss.source === 'rules' ? 'note' : 'blue'}"
				>{sourceLabel}</span
			>{/if}
	</div>

	{#if !lss}
		<div class="empty">
			<h2>No report yet</h2>
			<p>
				The Agent writes its report from an analysed video. Open the cached demo clip to read an
				example, or upload a video.
			</p>
			<a class="btn primary" href="/video">Go to Video <Slash /></a>
		</div>
	{:else}
		{#if lss.llm_error}
			<div class="notice warn" role="status">
				<Icon name="warn" />
				<p>
					<strong>The LLM was not used.</strong>
					{lss.llm_error} These cards come from rules and the knowledge base.
				</p>
			</div>
		{/if}

		<section class="summary panel" aria-label="Summary">
			<p class="text">{lss.summary}</p>
			<div class="tally" role="group" aria-label="Decisions">
				<div><strong>{tally.approved}</strong> approved</div>
				<div><strong>{tally.deferred}</strong> deferred</div>
				<div><strong>{tally.rejected}</strong> rejected</div>
				<div><strong>{tally.open}</strong> open</div>
				<div class="hours"><strong>{hoursLabel(tally.hours)}</strong> per shift approved</div>
				<button
					class="btn small"
					type="button"
					disabled={tally.approved === 0}
					onclick={() => copy(approvedText(), 'approved')}
				>
					<Icon name="link" size={14} />
					{copied === 'approved' ? 'Copied' : 'Copy approved'}
				</button>
			</div>
		</section>

		<div class="layout">
			<section class="cards" aria-label="Gemba Kaizen cards">
				{#if cards.length === 0}
					<div class="empty">
						<h2>No waste worth acting on</h2>
						<p>The agent found no waste category large enough for a card in this clip.</p>
					</div>
				{/if}
				{#each cards as card, index (card.id)}
					{@const decision = session.decisionFor(card.id)}
					<details class="panel card" open={cards.length <= 3 || index === 0}>
						<summary>
							<span class="tag p-{card.priority}">{card.priority}</span>
							<strong>{card.title}</strong>
							<span class="roi"
								>{card.roi ? `≈ ${card.roi.hours_saved_per_shift} h / shift` : 'no estimate'}</span
							>
							<span class="tag {decision === 'approved' ? 'blue' : 'low'}"
								>{decision ?? 'open'}</span
							>
						</summary>
						<div class="detail">
							<dl>
								<div>
									<dt>Observed</dt>
									<dd>{card.observation}</dd>
								</div>
								<div>
									<dt>Root cause</dt>
									<dd>{card.root_cause}</dd>
								</div>
								<div>
									<dt>Recommendation</dt>
									<dd>{card.recommendation}</dd>
								</div>
							</dl>

							{#if card.roi}
								<p class="calc">
									<strong>{card.roi.hours_saved_per_shift} h per shift</strong>
									{#if card.roi.throughput_gain_percent != null}· +{card.roi
											.throughput_gain_percent}% throughput{/if}
									<span class="muted"
										>· {card.roi.basis} (computed from the measured times, not by the LLM)</span
									>
								</p>
							{/if}

							<div class="refs">
								{#if card.evidence.length}
									<span class="field-label">Evidence</span>
									{#each card.evidence as e, i (i)}<TimeChip
											start={e.start_time}
											end={e.end_time}
										/>{/each}
								{/if}
								{#if card.kb_card_ids.length}
									<span class="field-label">Based on</span>
									{#each card.kb_card_ids as id (id)}
										<span class="chip" title={knowledge.get(id)?.source ?? ''}
											>{id}{knowledge.get(id) ? ` · ${knowledge.get(id)?.title}` : ''}</span
										>
									{/each}
								{/if}
								<span class="muted conf">confidence {Math.round(card.confidence * 100)}%</span>
							</div>

							<div class="decide">
								<div class="segmented" role="group" aria-label="Decision for {card.title}">
									{#each DECISIONS as d (d.value)}
										<button
											type="button"
											aria-pressed={decision === d.value}
											onclick={() => session.setDecision(card.id, d.value)}>{d.label}</button
										>
									{/each}
								</div>
								{#if decision}<button
										class="btn small"
										type="button"
										onclick={() => session.setDecision(card.id, null)}>Undo</button
									>{/if}
							</div>
						</div>
					</details>
				{/each}
			</section>

			<aside class="side" aria-label="Follow-ups">
				<section class="panel">
					<div class="panel-head">
						<h2>Ask the operator</h2>
						<span class="meta">{lss.operator_questions.length}</span>
					</div>
					{#if lss.operator_questions.length === 0}
						<p class="panel-body muted">
							The agent was sure of what it saw; there is nothing to ask.
						</p>
					{:else}
						<ul class="questions">
							{#each lss.operator_questions as q, i (i)}
								<li>
									<TimeChip start={q.timestamp} />
									<p>{q.question}</p>
									<button class="btn small" type="button" onclick={() => copy(q.question, `q${i}`)}
										>{copied === `q${i}` ? 'Copied' : 'Copy'}</button
									>
								</li>
							{/each}
						</ul>
					{/if}
				</section>

				<section class="panel">
					<div class="panel-head">
						<h2>Safety actions</h2>
						<a class="meta" href="/safety">Incidents</a>
					</div>
					{#if lss.safety_actions.length === 0}
						<p class="panel-body muted">No safety rule was broken.</p>
					{:else}
						<ul class="sa">
							{#each lss.safety_actions as action (action.rule_id)}
								<li>
									<span class="tag {action.severity}">{action.severity}</span>
									<div>
										<strong
											>{session.rules.find((r) => r.id === action.rule_id)?.label ??
												action.rule_id}</strong
										>
										<p>{action.action}</p>
										{#if action.kb_card_ids.length}<p class="muted mono">
												{action.kb_card_ids.join(', ')}
											</p>{/if}
									</div>
								</li>
							{/each}
						</ul>
					{/if}
				</section>
			</aside>
		</div>
		<section class="panel flat" aria-label="Knowledge used">
			<div class="panel-head">
				<h2>Knowledge used</h2>
				<span class="meta">{citedCards.length} cited</span>
			</div>
			<ul class="kb">
				{#each citedCards as k (k.id)}
					<li>
						<span class="chip">{k.id}</span> <span>{k.title}</span>
						<span class="muted">{k.source}</span>
					</li>
				{/each}
			</ul>
			{#if otherCards.length}
				<details class="more">
					<summary>{otherCards.length} more cards the agent read</summary>
					<ul class="kb">
						{#each otherCards as k (k.id)}
							<li>
								<span class="chip">{k.id}</span> <span>{k.title}</span>
								<span class="muted">{k.source}</span>
							</li>
						{/each}
					</ul>
				</details>
			{/if}
		</section>
		<p class="muted foot">
			Times come from frame timestamps and savings from arithmetic on them. The vision model only
			judges what is visible, and the activity labels can be wrong: unclear moments become questions
			above, not guesses. Video length {fmt(session.duration)}.
		</p>
	{/if}
</main>

<style>
	.summary {
		display: grid;
		gap: 0;
	}
	.text {
		padding: 1rem 1.25rem;
		font-size: var(--t-lg);
		line-height: 1.45;
		max-width: 80ch;
	}
	.tally {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.5rem 1.5rem;
		padding: 0.75rem 1.25rem;
		border-top: 1px solid var(--ink);
		font-size: var(--t-sm);
	}
	.tally strong {
		font: 700 var(--t-lg) var(--display);
		margin-right: 0.25rem;
	}
	.tally .hours {
		margin-left: auto;
	}
	.layout {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 24rem;
		gap: 1.5rem;
		align-items: start;
	}
	.cards,
	.side {
		display: grid;
		gap: 1rem;
		min-width: 0;
	}
	.card summary {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr) auto auto;
		gap: 0.75rem;
		align-items: center;
		padding: 0.875rem 1rem;
		cursor: pointer;
		list-style: none;
	}
	.card summary::-webkit-details-marker {
		display: none;
	}
	.card summary:hover {
		background: var(--blue-tint);
	}
	.card summary strong {
		font: 600 var(--t-md) / 1.3 var(--display);
		letter-spacing: 0.03em;
	}
	.roi {
		font: 600 var(--t-sm) var(--display);
		color: var(--blue-dark);
		white-space: nowrap;
	}
	.card[open] summary {
		border-bottom: 1px solid var(--ink);
	}
	.detail {
		display: grid;
		gap: 1rem;
		padding: 1rem;
	}
	.detail dl {
		display: grid;
		gap: 0.75rem;
		margin: 0;
	}
	.detail dl div {
		display: grid;
		grid-template-columns: 6.5rem minmax(0, 1fr);
		gap: 0.75rem;
	}
	dt {
		font: 500 var(--t-xs) var(--display);
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--muted);
		padding-top: 0.125rem;
	}
	dd {
		margin: 0;
		max-width: 68ch;
	}
	.calc {
		padding: 0.625rem 0.875rem;
		background: var(--blue-tint);
		border: 1px solid var(--blue-line);
		font-size: var(--t-sm);
	}
	.refs {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.5rem;
	}
	.refs .field-label {
		margin: 0 0.25rem 0 0.5rem;
	}
	.refs .field-label:first-child {
		margin-left: 0;
	}
	.conf {
		margin-left: auto;
		font-size: var(--t-sm);
	}
	.decide {
		display: flex;
		gap: 0.75rem;
		align-items: center;
		padding-top: 0.5rem;
		border-top: 1px solid var(--grid);
	}
	.questions li {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr) auto;
		gap: 0.625rem;
		align-items: start;
		padding: 0.75rem 1rem;
		border-bottom: 1px solid var(--grid);
	}
	.sa li {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr);
		gap: 0.75rem;
		padding: 0.75rem 1rem;
		border-bottom: 1px solid var(--grid);
		font-size: var(--t-sm);
	}
	.sa li .tag {
		align-self: start;
	}
	.more summary {
		padding: 0.625rem 1rem;
		border-bottom: 1px solid var(--grid);
		font: 500 var(--t-xs) var(--display);
		letter-spacing: 0.08em;
		text-transform: uppercase;
		cursor: pointer;
	}
	.sa strong {
		font: 600 var(--t-sm) var(--display);
		letter-spacing: 0.04em;
		text-transform: uppercase;
	}
	.kb {
		columns: 2 22rem;
		column-gap: 0;
	}
	.kb li {
		break-inside: avoid;
		display: flex;
		flex-wrap: wrap;
		gap: 0.25rem 0.5rem;
		align-items: baseline;
		padding: 0.5rem 1rem;
		border-bottom: 1px solid var(--grid);
		font-size: var(--t-sm);
	}
	.foot {
		max-width: 90ch;
		font-size: var(--t-sm);
	}
	@container (max-width: 1100px) {
		.layout {
			grid-template-columns: minmax(0, 1fr);
		}
	}
	@media (max-width: 700px) {
		.card summary {
			grid-template-columns: auto minmax(0, 1fr);
		}
		.detail dl div {
			grid-template-columns: minmax(0, 1fr);
			gap: 0.125rem;
		}
	}
</style>
