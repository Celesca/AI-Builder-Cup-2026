<script lang="ts">
	import '@fontsource/chakra-petch/500.css';
	import '@fontsource/chakra-petch/600.css';
	import '@fontsource/chakra-petch/700.css';
	import '@fontsource/noto-sans/400.css';
	import '@fontsource/noto-sans/600.css';
	import '@fontsource/noto-sans-thai/400.css';
	import '@fontsource/noto-sans-thai/600.css';
	import '../app.css';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import Icon from '#lib/components/Icon.svelte';
	import MiniPlayer from '#lib/components/MiniPlayer.svelte';
	import Slash from '#lib/components/Slash.svelte';
	import { fmt } from '#lib/analysis.ts';
	import { playback } from '#lib/playback.svelte.ts';
	import { session } from '#lib/session.svelte.ts';

	let { children } = $props();

	const tabs = [
		{ href: '/video', label: 'Video' },
		{ href: '/safety', label: 'Safety' },
		{ href: '/dashboard', label: 'Dashboard' },
		{ href: '/lss', label: 'Gemba Kaizen' },
		{ href: '/voice', label: 'Voice Agent' }
	];

	onMount(() => void session.hydrate());

	let path = $derived(page.url.pathname);
	let dock = $derived(Boolean(session.playUrl) && !['/video', '/dashboard'].includes(path));
	let chip = $derived.by(() => {
		if (session.status === 'running')
			return { dot: 'on', text: `Analysing ${session.source?.name ?? ''}… ${session.elapsed}s` };
		if (session.annotation.busy) {
			const a = session.annotation;
			const step =
				a.state === 'uploading'
					? `Uploading${a.fraction !== null ? ` ${Math.round(a.fraction * 100)}%` : ''}`
					: a.state === 'processing'
						? 'Server drawing boxes'
						: a.state === 'downloading'
							? 'Receiving video'
							: 'Preparing';
			return { dot: 'on', text: `${step}… ${a.elapsed}s` };
		}
		if (session.result && session.source) {
			return {
				dot: 'on',
				text: `${session.isDemo ? 'Cached demo' : 'Live run'} · ${session.source.name}`
			};
		}
		if (session.source) return { dot: '', text: `${session.source.name} · not analysed` };
		return { dot: '', text: 'No video loaded' };
	});
</script>

<header class="topbar">
	<a class="brand" href="/video">VALZ<span style="color:var(--blue)">∿</span>AI </a>
	<nav class="tabs" aria-label="Main">
		{#each tabs as tab (tab.href)}
			<a class="tab" href={tab.href} aria-current={path.startsWith(tab.href) ? 'page' : undefined}
				>{tab.label}</a
			>
		{/each}
	</nav>
	<div class="topbar-end">
		{#if dock}
			<button
				class="btn small"
				type="button"
				aria-pressed={!playback.dockCollapsed}
				onclick={() => (playback.dockCollapsed = !playback.dockCollapsed)}
			>
				<Icon name="play" size={12} /> Video <span class="mono">{fmt(playback.time)}</span>
			</button>
		{/if}
		<div class="runchip" role="status"><i class="dot {chip.dot}"></i><span>{chip.text}</span></div>
		<div class="field" style="min-width:8rem">
			<label class="sr-only" for="lang">Report language</label>
			<select id="lang" bind:value={session.language} onchange={() => session.savePrefs()}>
				<option value="en">Report: English</option>
				<option value="th">Report: ไทย</option>
				<option value="ja">Report: 日本語</option>
			</select>
		</div>
	</div>
</header>

<div class="content" class:docked-open={dock && !playback.dockCollapsed}>
	{@render children()}
</div>

{#if dock && !playback.dockCollapsed}<MiniPlayer />{/if}
