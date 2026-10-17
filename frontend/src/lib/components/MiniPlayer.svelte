<script lang="ts">
	import { fmt } from '#lib/analysis.ts';
	import { playback } from '#lib/playback.svelte.ts';
	import { session } from '#lib/session.svelte.ts';
	import Icon from './Icon.svelte';
	import Player from './Player.svelte';
</script>

<aside class="dock" aria-label="Video">
	<header>
		<span class="name">{session.source?.name}</span>
		<span class="time">{fmt(playback.time)}</span>
		<a class="btn small" href="/video" aria-label="Open the Video page"
			><Icon name="film" size={14} /></a
		>
		<button class="btn small" type="button" onclick={() => (playback.dockCollapsed = true)}
			>Hide</button
		>
	</header>
	<Player src={session.playUrl} label="Video of {session.source?.name}" />
</aside>

<style>
	/* Wide screens: a column beside the page (the page makes room for it). Narrow: a sheet at the bottom. */
	.dock {
		position: fixed;
		z-index: 40;
		top: 4.5rem;
		right: 1rem;
		width: 24rem;
		background: var(--paper);
		border: 1px solid var(--ink);
	}
	header {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.375rem 0.5rem 0.375rem 0.75rem;
		border-bottom: 1px solid var(--ink);
	}
	.name {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font: 500 var(--t-xs) var(--display);
		letter-spacing: 0.06em;
		text-transform: uppercase;
	}
	.time {
		font: 600 var(--t-sm) var(--display);
		color: var(--blue-dark);
	}
	@media (max-width: 1199px) {
		.dock {
			top: auto;
			bottom: 1rem;
			width: min(24rem, calc(100vw - 2rem));
		}
	}
	@media (max-width: 700px) {
		.dock {
			right: 0;
			bottom: 0;
			left: 0;
			width: auto;
			border-width: 1px 0 0;
		}
	}
</style>
