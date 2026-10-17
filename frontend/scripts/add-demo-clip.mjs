#!/usr/bin/env node
// Add your own clip to the demo list: copies the video into static/demo, analyses it with the RUNNING ai_backend
// (it needs the backend and its OpenRouter key once), saves the result next to the video and registers both in
// static/demo/manifest.json. After that the clip opens instantly in the dashboard with no backend and no key.
//
//   pnpm demo:add path/to/clip.mp4 --title "Line 2, station 5" [--cycle-time 21.4] [--takt-time 20] [--station "Cell 5"]
//                                  [--language en|th|ja] [--rules rules.json] [--backend http://localhost:8000]
import { openAsBlob } from 'node:fs';
import { copyFile, mkdir, readFile, writeFile } from 'node:fs/promises';
import { basename, dirname, extname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const demoDir = join(root, 'static', 'demo');

const { values, positionals } = parseArgs({
	allowPositionals: true,
	options: {
		title: { type: 'string' },
		id: { type: 'string' },
		station: { type: 'string' },
		'cycle-time': { type: 'string' },
		'takt-time': { type: 'string' },
		language: { type: 'string', default: 'en' },
		rules: { type: 'string' },
		backend: { type: 'string', default: process.env.AI_BACKEND_URL ?? 'http://localhost:8000' }
	}
});

function fail(message) {
	console.error(`demo:add: ${message}`);
	process.exit(1);
}

const [videoPath] = positionals;
if (!videoPath) fail('give the path of a video: pnpm demo:add path/to/clip.mp4 --title "My clip"');
const extension = extname(videoPath).toLowerCase();
if (!['.mp4', '.webm', '.mov', '.m4v'].includes(extension))
	fail(`unsupported video type "${extension}"`);

const title = values.title ?? basename(videoPath, extension);
const id =
	values.id ??
	title
		.toLowerCase()
		.replace(/[^a-z0-9]+/g, '-')
		.replace(/^-+|-+$/g, '');
if (!id) fail('could not make an id from the title; pass --id');

const rulesFile = values.rules ?? join(root, 'src', 'lib', 'default-rules.json');
const rules = JSON.parse(await readFile(rulesFile, 'utf8'))
	.filter((rule) => rule.enabled !== false)
	.map(({ id, prompt, severity, threshold }) => ({ id, prompt, severity, threshold }));

const form = new FormData();
form.append('file', await openAsBlob(videoPath), basename(videoPath));
form.append('rules', JSON.stringify(rules));
form.append('language', values.language);
form.append('station_name', values.station ?? title);
if (values['cycle-time']) form.append('cycle_time_s', values['cycle-time']);
if (values['takt-time']) form.append('takt_time_s', values['takt-time']);

console.log(
	`Analysing ${videoPath} with ${rules.length} rules on ${values.backend} (about a minute per 30 s of video)...`
);
let response;
try {
	response = await fetch(`${values.backend}/analysis/analyze/upload`, {
		method: 'POST',
		body: form
	});
} catch {
	fail(
		`cannot reach the backend at ${values.backend}. Start it with: cd ../ai_backend && .venv/bin/python server.py`
	);
}
if (!response.ok) {
	const body = await response.json().catch(() => ({}));
	fail(`the backend answered ${response.status}: ${body.detail ?? response.statusText}`);
}
const result = await response.json();

await mkdir(demoDir, { recursive: true });
const videoName = `${id}${extension}`;
await copyFile(videoPath, join(demoDir, videoName));
await writeFile(join(demoDir, `${id}.analysis.json`), JSON.stringify(result));

const manifestPath = join(demoDir, 'manifest.json');
const manifest = JSON.parse(await readFile(manifestPath, 'utf8').catch(() => '{"clips":[]}'));
manifest.clips = [
	...manifest.clips.filter((clip) => clip.id !== id),
	{
		id,
		title,
		video: `/demo/${videoName}`,
		analysis: `/demo/${id}.analysis.json`,
		duration: Math.round(result.safety.video_duration),
		synthetic: false,
		note: `Analysed ${new Date().toISOString().slice(0, 10)} with ${result.safety.model}`
	}
];
await writeFile(manifestPath, JSON.stringify(manifest, null, 2) + '\n');

const { stats } = result.safety;
console.log(`Saved static/demo/${videoName} and ${id}.analysis.json.`);
console.log(
	`${stats.frames_analyzed} frames, ${stats.safety_events} incidents, ${result.lss.lss_cards.length} Gemba Kaizen cards (${result.lss.source}).`
);
if (extension === '.mov' || extension === '.m4v') {
	console.log(
		'Note: browsers play H.264 mp4 or webm best. If it does not play: ffmpeg -i in.mov -c:v libx264 -pix_fmt yuv420p out.mp4'
	);
}
