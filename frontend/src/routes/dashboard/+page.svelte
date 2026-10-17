<script lang="ts">
	import { CATEGORY_LABEL, fmt, hoursLabel, isWaste, severityRank } from '#lib/analysis.ts';
	import FrameGrid from '#lib/components/FrameGrid.svelte';
	import Legend from '#lib/components/Legend.svelte';
	import Player from '#lib/components/Player.svelte';
	import Slash from '#lib/components/Slash.svelte';
	import TimeChip from '#lib/components/TimeChip.svelte';
	import { playback } from '#lib/playback.svelte.ts';
	import { session } from '#lib/session.svelte.ts';
	import type { Category } from '#lib/types.ts';

	let result = $derived(session.result);
	let metrics = $derived(result?.lss.metrics);
	let summary = $derived(result?.safety.activity.summary);
	let step = $derived(session.sampleFps > 0 ? 1 / session.sampleFps : 1);
	let va = $derived(metrics ? Math.round(metrics.va_percent) : 0);
	let waste = $derived(
		metrics?.waste_by_category.filter((w) => isWaste(w.category) || w.category === 'NNVA') ?? []
	);
	let wasteSeconds = $derived(waste.reduce((sum, w) => sum + w.seconds, 0));
	let top = $derived(
		session.incidents
			.filter((i) => !session.isReviewed(i.key))
			.sort((a, b) => severityRank(b.severity) - severityRank(a.severity) || b.peak - a.peak)[0]
	);
	let cards = $derived(
		[...(result?.lss.lss_cards ?? [])]
			.sort((a, b) => severityRank(b.priority) - severityRank(a.priority))
			.slice(0, 3)
	);
	let people = $derived(result?.person_count?.statistics.max_persons ?? null);
	let overTakt = $derived(session.takt && session.cycle ? session.cycle - session.takt : null);
	let high = $derived(session.incidents.filter((i) => i.severity === 'high').length);
	let hoursSaved = $derived(
		(result?.lss.lss_cards ?? [])
			.filter((c) => session.decisionFor(c.id) === 'approved')
			.reduce((s, c) => s + (c.roi?.hours_saved_per_shift ?? 0), 0)
	);
	let vaSeconds = $derived(summary?.by_category_seconds.VA ?? 0);
	let unclearSeconds = $derived(summary?.by_category_seconds.UNCERTAIN ?? 0);
	let maxSeconds = $derived(Math.max(1, vaSeconds, unclearSeconds, ...waste.map((w) => w.seconds)));
	const width = (seconds: number) => `${(seconds / maxSeconds) * 100}%`;
</script>

<svelte:head><title>Dashboard · VALZ</title></svelte:head>

<main class="page">
	{#if !result || !metrics || !summary}
		<div class="page-head">
			<div>
				<h1>Dashboard</h1>
				<p>
					The shift in one screen: how much of the time was value-adding, where the rest went, and
					which rules were broken.
				</p>
			</div>
		</div>
		<div class="empty">
			<h2>No analysis to summarise</h2>
			<p>
				Open the cached demo clip to see this page filled in, or upload a video and run the agents
				on it.
			</p>
			<a class="btn primary" href="/video">Go to Video <Slash /></a>
		</div>
	{:else}
		<div class="hero">
			<div class="col">
				<section class="panel big" aria-label="Value-adding share">
					<div class="figure">
						<span class="num" aria-label="{metrics.va_percent} percent value-adding">{va}</span
						><span class="unit">%</span>
					</div>
					<p class="sentence">
						of the time a person was visible at
						<strong>{result.lss.context.station_name || session.source?.name}</strong> was
						value-adding work.
						{#if metrics.nva_percent > 0}{Math.round(metrics.nva_percent)}% was waste: at this rate
							{hoursLabel(metrics.projected_nva_hours_per_shift)} of every {result.lss.context
								.shift_hours} h shift.{/if}
					</p>
					<p class="run muted">
						{fmt(session.duration)} · {session.frames.length} frames at {session.sampleFps} fps ·
						{session.isDemo ? 'cached demo result' : `analysed with ${result.safety.model}`}
						{#if result.demo?.synthetic}· synthetic clip{/if}
					</p>
				</section>

				<section class="panel readout" aria-label="Readout">
					<dl>
						<div>
							<dt>Waste per shift</dt>
							<dd>{hoursLabel(metrics.projected_nva_hours_per_shift)}</dd>
						</div>
						<div>
							<dt>Safety incidents</dt>
							<dd>{session.incidents.length}<small>{high} high</small></dd>
						</div>
						<div>
							<dt>People on camera</dt>
							<dd>{people ?? '–'}<small>at most</small></dd>
						</div>
						<div>
							<dt>Cycle vs takt</dt>
							<dd>
								{#if session.cycle && session.takt}{session.cycle} s<small
										>takt {session.takt} s</small
									>{:else}–<small>not set</small>{/if}
							</dd>
						</div>
					</dl>
					{#if overTakt !== null && overTakt > 0}
						<p class="over">
							<strong>{overTakt} s over takt.</strong> Waste adds up to {fmt(wasteSeconds)} of this cycle;
							removing it is what brings the station back to takt.
						</p>
					{/if}
				</section>
			</div>

			<div class="col">
				<section class="panel video" aria-label="Video">
					<Player src={session.playUrl} label="Video of {session.source?.name}" />
				</section>

				{#if top}
					<section class="alert" aria-label="Incident to review">
						<div>
							<span class="tag high">{top.severity}</span>
							<strong>{top.label}</strong>
							<span
								>at <TimeChip start={top.start} end={top.end} /> · {Math.round(
									top.peak * 100
								)}%</span
							>
							<p>{top.description || top.prompt}</p>
						</div>
						<div class="acts">
							<button
								class="btn"
								type="button"
								onclick={() => playback.seek(Math.max(0, top.start - 1))}>Play</button
							>
							<a class="btn" href="/safety">Review all <Slash /></a>
						</div>
					</section>
				{:else}
					<section class="panel flat">
						<p class="panel-body">
							<strong>Nothing to review.</strong>
							{session.incidents.length
								? 'Every incident is marked reviewed.'
								: 'No rule reached its threshold.'}
						</p>
					</section>
				{/if}
			</div>
		</div>

		<section class="panel" aria-label="Shift timeline">
			<div class="panel-head">
				<h2>Shift</h2>
				<span class="meta"
					>one cell per sampled second, numbers are seconds · select a cell to play from there</span
				>
			</div>
			<div class="panel-body stack">
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

		<div class="two">
			<section class="panel" aria-label="Where the time went">
				<div class="panel-head">
					<h2>Where the time went</h2>
					<span class="meta">{fmt(summary.person_visible_seconds)} with a person visible</span>
				</div>
				<table>
					<thead
						><tr
							><th scope="col">Category</th><th scope="col">Time</th><th scope="col">Share</th><th
								scope="col">Per shift</th
							></tr
						></thead
					>
					<tbody>
						<tr>
							<th scope="row"><i class="swatch k-VA"></i> Value-adding</th>
							<td>{fmt(vaSeconds)}</td>
							<td
								><span class="bar" aria-hidden="true"><i style:width={width(vaSeconds)}></i></span
								>{metrics.va_percent}%</td
							>
							<td class="muted">n/a</td>
						</tr>
						{#each waste as w (w.category)}
							<tr>
								<th scope="row"
									><i class="swatch k-{w.category as Category}"></i>
									{CATEGORY_LABEL[w.category as Category] ?? w.label}</th
								>
								<td>{fmt(w.seconds)}</td>
								<td
									><span class="bar" aria-hidden="true"><i style:width={width(w.seconds)}></i></span
									>{w.percent_of_person_time}%</td
								>
								<td>{hoursLabel(w.projected_hours_per_shift)}</td>
							</tr>
						{/each}
						{#if unclearSeconds > 0}
							<tr>
								<th scope="row"><i class="swatch k-UNCERTAIN"></i> Unclear</th>
								<td>{fmt(unclearSeconds)}</td>
								<td
									><span class="bar" aria-hidden="true"
										><i style:width={width(unclearSeconds)}></i></span
									>{metrics.uncertain_percent}%</td
								>
								<td class="muted">n/a</td>
							</tr>
						{/if}
					</tbody>
				</table>
			</section>

			<section class="panel" aria-label="Gemba Kaizen actions">
				<div class="panel-head">
					<h2>Actions</h2>
					<a class="meta" href="/lss">All {result.lss.lss_cards.length}</a>
				</div>
				<p class="summary">{result.lss.summary}</p>
				{#if cards.length === 0}
					<p class="panel-body muted">The Agent found no waste worth acting on.</p>
				{:else}
					<ol class="actions">
						{#each cards as card (card.id)}
							{@const decision = session.decisionFor(card.id)}
							<li>
								<span class="tag p-{card.priority}">{card.priority}</span>
								<div>
									<strong>{card.title}</strong>
									<span class="muted">
										{card.roi ? `≈ ${card.roi.hours_saved_per_shift} h per shift` : 'no estimate'}
										{#if card.evidence[0]}
											· <TimeChip
												start={card.evidence[0].start_time}
												end={card.evidence[0].end_time}
											/>{/if}
									</span>
								</div>
								<span class="tag {decision === 'approved' ? 'blue' : 'low'}"
									>{decision ?? 'open'}</span
								>
							</li>
						{/each}
					</ol>
				{/if}
				{#if hoursSaved > 0}<p class="panel-body">
						<strong>{hoursLabel(hoursSaved)} per shift approved so far.</strong>
					</p>{/if}
			</section>
		</div>
	{/if}
</main>

<style>
	.hero {
		display: grid;
		grid-template-columns: minmax(0, 1.05fr) minmax(0, 1fr);
		gap: 1.5rem;
		align-items: start;
	}
	.col {
		display: grid;
		gap: 1.5rem;
		min-width: 0;
	}
	.big {
		display: grid;
		gap: 0.75rem;
		padding: 1.5rem;
	}
	.figure {
		display: flex;
		align-items: baseline;
		gap: 0.25rem;
		line-height: 0.85;
	}
	.num {
		font: 700 6rem / 0.85 var(--display);
		letter-spacing: -0.02em;
	}
	.unit {
		font: 700 2.25rem / 1 var(--display);
		color: var(--blue);
	}
	.sentence {
		max-width: 52ch;
		font-size: var(--t-lg);
		line-height: 1.4;
	}
	.run {
		font-size: var(--t-sm);
	}
	.video {
		border-color: var(--ink);
	}
	.readout dl {
		margin: 0;
	}
	.readout dl div {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 1rem;
		padding: 0.625rem 1rem;
		border-bottom: 1px solid var(--grid);
	}
	dt {
		font: 500 var(--t-xs) var(--display);
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--muted);
	}
	dd {
		margin: 0;
		font: 700 var(--t-xl) / 1.1 var(--display);
	}
	dd small {
		margin-left: 0.5rem;
		font: 400 var(--t-sm) var(--body);
		color: var(--muted);
	}
	.over {
		padding: 0.75rem 1rem;
		background: var(--blue-tint);
		font-size: var(--t-sm);
	}
	.alert {
		display: flex;
		flex-wrap: wrap;
		justify-content: space-between;
		gap: 0.75rem 1rem;
		padding: 1rem;
		background: var(--hot);
		border: 1px solid var(--ink);
		color: var(--ink);
	}
	.alert p {
		margin-top: 0.375rem;
		max-width: 46ch;
	}
	.alert strong {
		font: 700 var(--t-lg) var(--display);
		letter-spacing: 0.04em;
		text-transform: uppercase;
	}
	.alert .acts {
		display: flex;
		gap: 0.5rem;
		align-items: start;
	}
	.stack {
		display: grid;
		gap: 0.875rem;
	}
	.two {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 1.5rem;
		align-items: start;
	}
	table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--t-sm);
	}
	th,
	td {
		padding: 0.625rem 1rem;
		text-align: left;
		border-bottom: 1px solid var(--grid);
	}
	thead th {
		font: 500 var(--t-xs) var(--display);
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--muted);
		border-bottom: 1px solid var(--ink);
	}
	tbody th {
		font-weight: 600;
	}
	.bar {
		display: inline-block;
		width: 4rem;
		height: 0.5rem;
		margin-right: 0.5rem;
		background: var(--grid);
		vertical-align: middle;
	}
	.bar i {
		display: block;
		height: 100%;
		background: var(--blue);
	}
	.summary {
		padding: 1rem;
		border-bottom: 1px solid var(--grid);
		color: var(--ink-2);
	}
	.actions li {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr) auto;
		gap: 0.75rem;
		align-items: center;
		padding: 0.75rem 1rem;
		border-bottom: 1px solid var(--grid);
	}
	.actions li div {
		display: grid;
		gap: 0.125rem;
		min-width: 0;
	}
	@container (max-width: 1100px) {
		.hero,
		.two {
			grid-template-columns: minmax(0, 1fr);
		}
	}
	@media (max-width: 700px) {
		.num {
			font-size: 4rem;
		}
	}
</style>
