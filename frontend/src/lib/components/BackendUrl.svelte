<script lang="ts">
	import { api } from '#lib/api.svelte.ts';
	import { normalizeBackendUrl } from '#lib/backend-url.ts';
	import { session } from '#lib/session.svelte.ts';
	import { voice } from '#lib/voice.svelte.ts';

	let draft = $state('');
	let error = $state('');
	let editing = $state(false);

	// Show the saved URL until the manager starts typing
	let shown = $derived(editing ? draft : api.url);

	async function apply(value: string) {
		const url = normalizeBackendUrl(value);
		if (url === null) {
			error = 'Enter a web address such as http://localhost:8000 or https://valz.example.com';
			return;
		}
		error = '';
		editing = false;
		await session.setBackendUrl(url);
		await voice.refreshStatus();
	}
</script>

<form
	class="backend-url"
	onsubmit={(event) => {
		event.preventDefault();
		void apply(shown);
	}}
>
	<label class="field-label" for="backend-url">Backend address</label>
	<div class="row">
		<input
			id="backend-url"
			type="text"
			inputmode="url"
			autocomplete="off"
			spellcheck="false"
			placeholder="Server default"
			value={shown}
			oninput={(event) => {
				editing = true;
				draft = event.currentTarget.value;
				error = '';
			}}
			aria-describedby="backend-url-hint"
		/>
		<button class="btn small primary" type="submit" disabled={!editing}>Use</button>
		<button
			class="btn small"
			type="button"
			disabled={!api.url && !editing}
			onclick={() => {
				draft = '';
				void apply('');
			}}>Default</button
		>
	</div>
	<p class="field-hint" id="backend-url-hint">
		{#if error}{error}{:else if api.url}Using {api.url}. Saved in this browser.{:else}Using the
			address the server was started with. Type another ai_backend to try it.{/if}
	</p>
</form>

<style>
	.backend-url {
		display: grid;
		gap: 0.375rem;
	}
	.row {
		display: flex;
		gap: 0.5rem;
	}
	.row input {
		min-width: 0;
	}
</style>
