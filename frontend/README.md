# VALZ dashboard (frontend)

SvelteKit 3 app (adapter-node, runes, plain CSS) for VALZ. It runs the pipeline on a workstation video and
shows what the agents found. Design context: [../PRODUCT.md](../PRODUCT.md) and [../DESIGN.md](../DESIGN.md).

| Page                       | What the manager does there                                                                                                                                                                                                                                                                                                                                                                                               |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Video** `/video`         | Loads a clip: bundled **demo clips** (cached analysis, no API key), **upload** (analysed by the backend), or **live** (an explained simulation: the demo clip replayed as if findings arrived live; real stream ingest is not built in the backend yet). Sets the station's cycle and takt time, and runs the analysis.                                                                                                   |
| **Safety Agent** `/safety` | Reviews incidents (thumbnail, moment, confidence, suggested action, mark reviewed) and **edits the rules**: prompt, severity, threshold, on/off, add or remove. Thresholds, severity and on/off re-derive the incidents instantly from the per-frame confidences; a changed prompt needs a re-run (live backend only). The _Rules over time_ matrix shows each rule against each sampled second, with keyboard scrubbing. |
| **Dashboard** `/dashboard` | The shift in one screen: value-adding share, waste per shift, incidents, people, cycle vs takt, the shift grid (one cell per second, one row per minute, takt cell marked), where the time went, and the top Gemba Kaizen actions.                                                                                                                                                                                      |
| **Gemba Kaizen** `/lss`  | The Gemba Kaizen Agent's cards: observation, root cause, recommendation, ROI computed from the measured times, evidence moments, the knowledge cards each suggestion is based on. Approve, defer or reject each; questions to ask the operator; safety actions.                                                                                                                                                         |
| **Voice Agent** `/voice`   | A chatbot over the analysis: type or speak a question, the answer is read aloud (ElevenLabs, with the browser's voice as a fallback). Answers come from the analysis and the lean knowledge cards (RAG in the backend); times in answers jump the video. Speech is saved in a database so a repeated sentence is not paid for twice. The chat lasts for the browser tab.                                                  |

If the browser cannot play an uploaded file (H.265, MPEG-4, AVI ...), the player offers **Make a preview I can play**: the backend re-encodes it to H.264 with ffmpeg (`POST /video/preview`). The analysis always uses the original.

Every timestamp in the app plays the video from that moment (a Video toggle in the top bar opens the player beside the page).
Rules, review marks and decisions are kept on this device (localStorage); the last upload's results survive a reload in the tab.

## Mock mode and your own clips

`static/demo/manifest.json` lists the demo clips. Each is a video plus a cached analysis in the exact shape of
`ai_backend`'s `POST /analysis/analyze/upload` response, so it opens instantly with no backend and no key.

- Bundled: **`xsens-004-ws10-in-l`**, a 50 s crop of a real car door assembly (CarDA dataset, workstation WS10, `in` camera, left view,
  recording `xsens_004_WS10_2023_10_03`). It was analysed once on the live backend (4 ergonomic rules from `default-rules.json`,
  station WS10, nominal cycle 240 s, no takt time) and is cached. Only the video is used; the dataset's Xsens motion capture and depth data are not.
  The full dataset recordings are `.svo` (ZED); the clip was converted to H.264 mp4.
  CarDA (Car Door Assembly dataset) is licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); credit the CarDA authors when sharing.
- Also bundled: a **synthetic** animated workstation clip (`cell3-synthetic`), clearly labelled in the video and the UI. Regenerate it with
  `ai_backend/.venv/bin/python frontend/scripts/make-synthetic-demo.py`. The scenario is scripted; segments, incidents, metrics, ROI
  and knowledge-card retrieval are computed with the backend's own functions, and the Gemba Kaizen texts are authored.
- **Add your own clip** (needs the backend running with its OpenRouter key, once):

  ```bash
  pnpm demo:add path/to/clip.mp4 --title "Line 2, station 5" --cycle-time 21.4 --takt-time 20
  ```

  It copies the video into `static/demo/`, analyses it with the default rules, saves `<id>.analysis.json` and registers the clip.
  Options: `--station`, `--language en|th|ja`, `--rules rules.json`, `--backend http://localhost:8000`, `--id`.
  Browsers play H.264 `.mp4` or `.webm` best (`ffmpeg -i in.mov -c:v libx264 -pix_fmt yuv420p out.mp4`).

## How it talks to ai_backend

**Choosing the backend in the UI.** The _Backend address_ box (Video page, AI backend panel; Voice page, side column) points the app at
any ai_backend, e.g. `gemba.limitlesstech-co.com`, without restarting. It is saved in the browser and sent to the proxy as an
`x-backend-url` header; _Default_ goes back to `AI_BACKEND_URL`. Because that makes the proxy forward to whatever address is
typed, set `ALLOW_BACKEND_OVERRIDE=false` on a public deployment.

```
browser ── /api/analysis/analyze/upload ──► src/routes/api/[...path]/+server.ts ── stream ──► AI_BACKEND_URL/analysis/analyze/upload
```

- [src/routes/api/[...path]/+server.ts](src/routes/api/[...path]/+server.ts): server-side proxy for the routes the dashboard uses
  (`health`, `gemba/`, `safety/`, `lss/`, `vlm_action/`, `person_count/`); uploads are streamed.
- [src/lib/backend.ts](src/lib/backend.ts): status check, `analyzeUpload` (sends only the enabled rules, language and station fields), demo loading.
- [src/lib/analysis.ts](src/lib/analysis.ts): incidents re-derived from the per-frame confidences (same grouping as the backend), labels, formatting.
- [src/lib/session.svelte.ts](src/lib/session.svelte.ts): the working session; [src/lib/rules.ts](src/lib/rules.ts) with [src/lib/default-rules.json](src/lib/default-rules.json) (shared by the demo and `pnpm demo:add`).

Environment (declared in [src/env.ts](src/env.ts)): `AI_BACKEND_URL` (default `http://localhost:8000`, server-side only), `DATABASE_URL` (optional, unused so far).
In production adapter-node also needs `BODY_SIZE_LIMIT=600M` (video uploads) and, behind nginx, `PROTOCOL_HEADER=x-forwarded-proto` and `HOST_HEADER=x-forwarded-host`; the [Dockerfile](Dockerfile) sets them.

## Develop

```bash
corepack enable && pnpm install
cp .env.example .env
pnpm run dev                       # http://localhost:5173 (run ai_backend on :8000 for uploads)
```

| Command                             | What it does                                                                                       |
| ----------------------------------- | -------------------------------------------------------------------------------------------------- |
| `pnpm run check`                    | Type-check with `svelte-check`                                                                     |
| `pnpm run lint` / `pnpm run format` | Prettier                                                                                           |
| `pnpm run test:unit --run`          | Vitest: incident derivation (checked against the backend's own incidents), backend client, session |
| `pnpm exec playwright test`         | End-to-end: the whole demo flow with the cached clip (no backend, no key)                          |
| `pnpm run build`                    | Production build (`build/`, run with `node build`)                                                 |

SvelteKit 3 notes: import from `#lib/...` with the file extension (for example `#lib/analysis.ts`), since `$lib` was removed;
environment variables come from `$app/env/private` / `$app/env/public`; `browser` is in `$app/env`.

## Docker

```bash
docker build -t valz-frontend .
docker run -p 3000:3000 -e AI_BACKEND_URL=http://host.docker.internal:8000 valz-frontend
```

Use the root [docker-compose.yml](../docker-compose.yml) to run nginx, this app and ai_backend together.
