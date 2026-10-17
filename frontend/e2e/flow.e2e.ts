import { expect, test, type Page } from '@playwright/test';
import { createServer } from 'node:http';
import type { AddressInfo } from 'node:net';

// The whole demo flow with the bundled cached clip: no backend and no API key involved.
const nav = (page: Page, name: string) =>
	page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name });

test('open the demo clip, review incidents, read the summary, decide on Gemba Kaizen actions', async ({
	page
}) => {
	await page.goto('/');
	await expect(page).toHaveURL(/\/video$/);

	await page.getByRole('button', { name: 'Open' }).first().click();
	await expect(page.getByText('Cached analysis loaded. No model was called.')).toBeVisible();

	// Safety Agent: incidents come from the rules; a raised threshold removes the one-frame false alarm
	await nav(page, 'Safety').click();
	await expect(page.getByRole('heading', { name: 'Incidents' })).toBeVisible();
	await expect(page.getByText('11 found')).toBeVisible();
	const overhead = page.getByLabel('Threshold', { exact: false }).nth(2);
	await overhead.focus();
	for (let i = 0; i < 6; i++) await page.keyboard.press('ArrowRight');
	await expect(page.getByText('10 found')).toBeVisible();

	await page.getByRole('button', { name: 'Mark reviewed' }).first().click();
	await expect(page.getByText('9 to review')).toBeVisible();

	// Dashboard
	await nav(page, 'Dashboard').click();
	await expect(page.getByLabel('78 percent value-adding')).toBeVisible();

	// Gemba Kaizen: approve the first card
	await nav(page, 'Gemba Kaizen').click();
	await page.getByRole('button', { name: 'Approve', exact: true }).first().click();
	await expect(page.getByText('1 approved')).toBeVisible();

	// Decisions and rules survive a reload
	await page.reload();
	await expect(page.getByText('1 approved')).toBeVisible();
});

test('pages explain what to do before anything is loaded', async ({ page }) => {
	for (const path of ['/safety', '/dashboard', '/lss']) {
		await page.goto(path);
		await expect(page.getByRole('link', { name: /Go to Video/ })).toBeVisible();
	}
});

test('voice agent: ask by typing, get a spoken answer from the backend, jump the video from a time stamp', async ({
	page
}) => {
	// The Voice Agent endpoints are stubbed: this checks the page, not ElevenLabs or a model
	await page.route('**/api/voice/status', (route) =>
		route.fulfill({
			json: {
				elevenlabs_configured: true,
				llm_configured: true,
				llm_model: 'test/model',
				tts_model: 'eleven_flash_v2_5',
				stt_model: 'scribe_v1',
				voice_id: 'v',
				audio_cache: { clips: 0, bytes: 0, replays: 0 }
			}
		})
	);
	await page.route('**/api/voice/chat', (route) =>
		route.fulfill({
			json: {
				reply: 'Walking to the rack is the biggest waste. It first happens at 0:12.',
				sources: [{ id: 'metrics', title: 'Time breakdown', source: 'analysis' }],
				source: 'llm',
				model: 'test/model'
			}
		})
	);
	let spoken = 0;
	await page.route('**/api/voice/speak', (route) => {
		spoken++;
		return route.fulfill({ status: 503, json: { detail: 'ELEVENLABS_API_KEY is not set' } });
	});

	await page.goto('/video');
	await page.getByRole('button', { name: 'Open' }).first().click();
	await expect(page.getByText('Cached analysis loaded. No model was called.')).toBeVisible();
	await nav(page, 'Voice Agent').click();

	// The chat opens with the agent's greeting, not with a question from the user
	await page.getByRole('button', { name: /^Start chatting/ }).click();
	await expect(page.getByText('I have read this shift.')).toBeVisible();
	await expect(page.locator('.msg.user')).toHaveCount(0);
	await page.getByLabel('Your question').fill('What is the biggest waste?');
	await page.getByRole('button', { name: /^Send/ }).click();
	await expect(page.getByText('Walking to the rack is the biggest waste.')).toBeVisible();
	await expect(page.getByText('Written by test/model')).toBeVisible();
	await expect.poll(() => spoken).toBeGreaterThan(0); // replies are read aloud by default

	// ElevenLabs failing is explained, and the chat keeps working with the browser voice
	await expect(page.getByText('ELEVENLABS_API_KEY is not set')).toBeVisible();

	// A time stamp in an answer opens the video at that moment
	await page.getByRole('button', { name: 'Play the video from 00:12' }).click();
	await expect(page.getByRole('button', { name: 'Hide' })).toBeVisible();

	// The chat survives a reload
	await page.reload();
	await expect(page.getByText('Walking to the rack is the biggest waste.')).toBeVisible();
});

test('annotated video: shows the server at work, then plays the boxes version', async ({
	page
}) => {
	// A real local stub backend (page.route hides XHR upload progress): online with a key, and the annotate call
	// answers only when released, so the "server at work" state can be checked
	let beats = 0;
	let release: () => void = () => {};
	const held = new Promise<void>((resolve) => (release = resolve));
	const cors = {
		'access-control-allow-origin': '*',
		'access-control-allow-headers': '*',
		'access-control-expose-headers': 'content-length, x-safety-events, x-annotated-frames'
	};
	const server = createServer((req, res) => {
		const send = (body: unknown) => {
			res.writeHead(200, { ...cors, 'content-type': 'application/json' });
			res.end(JSON.stringify(body));
		};
		if (req.method === 'OPTIONS') return void (res.writeHead(204, cors), res.end());
		if (req.url?.startsWith('/lss/status'))
			return send({ llm_configured: true, model: 'test/llm' });
		if (req.url?.startsWith('/vlm_action/status'))
			return send({ api_key_configured: true, model: 'test/vlm' });
		if (req.url?.startsWith('/health')) return (beats++, send({ status: 'healthy' }));
		if (req.url?.startsWith('/safety/annotate/upload')) {
			req.resume();
			req.on('end', async () => {
				await held;
				const body = Buffer.from('not really an mp4');
				res.writeHead(200, {
					...cors,
					'content-type': 'video/mp4',
					'content-length': String(body.length),
					'x-safety-events': '3',
					'x-annotated-frames': '42'
				});
				res.end(body);
			});
			return;
		}
		res.writeHead(404, cors);
		res.end('{}');
	});
	await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
	const { port } = server.address() as AddressInfo;
	await page.addInitScript(
		(url) => localStorage.setItem('valz-backend-url-v1', url),
		`http://127.0.0.1:${port}`
	);

	try {
		await page.goto('/video');
		await page.getByRole('button', { name: 'Open' }).first().click();
		await expect(page.getByText('Cached analysis loaded. No model was called.')).toBeVisible();
		await page.getByRole('button', { name: 'Draw boxes on the video' }).click();

		await expect(page.getByRole('progressbar', { name: 'The server is working' })).toBeVisible();
		await expect(page.getByText(/Backend is alive/)).toBeVisible();
		await expect(
			page.getByRole('status').filter({ hasText: 'Server drawing boxes' })
		).toBeVisible();
		expect(beats).toBeGreaterThan(0);
		await page.screenshot({ path: 'test-results/annotate-processing.png', fullPage: true });

		release();
		await expect(page.getByText('42 frames marked')).toBeVisible();
		await expect(page.getByRole('button', { name: 'Boxes', pressed: true })).toBeVisible();
		await expect(page.getByText('Annotated by the server')).toBeVisible();
		await expect(page.getByRole('link', { name: 'Download MP4' })).toBeVisible();
		await page.screenshot({ path: 'test-results/annotate-done.png', fullPage: true });

		await page.getByRole('button', { name: 'Original' }).click();
		await expect(page.getByText('Annotated by the server')).toHaveCount(0);
	} finally {
		release();
		server.close();
	}
});
