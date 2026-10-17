<script lang="ts">
	// One authored icon set: 24px grid, 1.5px stroke, square caps, no fills except the play triangle.
	type Name =
		| 'upload'
		| 'download'
		| 'film'
		| 'live'
		| 'play'
		| 'check'
		| 'x'
		| 'plus'
		| 'trash'
		| 'reset'
		| 'warn'
		| 'link'
		| 'mic'
		| 'stop'
		| 'speaker'
		| 'send';
	let { name, size = 16 }: { name: Name; size?: number } = $props();
</script>

<svg
	width={size}
	height={size}
	viewBox="0 0 24 24"
	fill="none"
	stroke="currentColor"
	stroke-width="1.5"
	stroke-linecap="square"
	stroke-linejoin="miter"
	aria-hidden="true"
	focusable="false"
>
	{#if name === 'upload'}
		<path d="M12 16V4M7 9l5-5 5 5M4 20h16" />
	{:else if name === 'download'}
		<path d="M12 4v12M7 11l5 5 5-5M4 20h16" />
	{:else if name === 'film'}
		<path d="M3 5h18v14H3zM7 5v14M17 5v14M3 10h4M3 14h4M17 10h4M17 14h4" />
	{:else if name === 'live'}
		<circle cx="12" cy="12" r="2.5" fill="currentColor" stroke="none" />
		<path d="M7 7a7 7 0 0 0 0 10M17 7a7 7 0 0 1 0 10M4 4a11 11 0 0 0 0 16M20 4a11 11 0 0 1 0 16" />
	{:else if name === 'play'}
		<path d="M7 4l13 8-13 8z" fill="currentColor" />
	{:else if name === 'check'}
		<path d="M4 12.5l5 5L20 6.5" />
	{:else if name === 'x'}
		<path d="M5 5l14 14M19 5L5 19" />
	{:else if name === 'plus'}
		<path d="M12 4v16M4 12h16" />
	{:else if name === 'trash'}
		<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6" />
	{:else if name === 'reset'}
		<path d="M4 12a8 8 0 1 0 3-6.2M4 4v5h5" />
	{:else if name === 'warn'}
		<path d="M12 3L2 20h20zM12 10v5M12 17.5v1" />
	{:else if name === 'link'}
		<path
			d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"
		/>
	{:else if name === 'mic'}
		<path d="M9 4h6v9a3 3 0 0 1-6 0zM5 11a7 7 0 0 0 14 0M12 18v3" />
	{:else if name === 'stop'}
		<path d="M6 6h12v12H6z" fill="currentColor" />
	{:else if name === 'speaker'}
		<path d="M4 9h4l5-4v14l-5-4H4zM16 9a4 4 0 0 1 0 6M18.5 6.5a8 8 0 0 1 0 11" />
	{:else if name === 'send'}
		<path d="M3 12h15M12 5l7 7-7 7" />
	{/if}
</svg>
