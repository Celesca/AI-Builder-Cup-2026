# VALZ

**From factory-floor video to an approved Gemba Kaizen action.**

VALZ watches a short workstation clip, finds the waste (*Muda*) in each work cycle, and turns it into
Gemba Kaizen Action Cards with an ROI estimate. When it is not sure what it saw, it does not guess. A bilingual voice agent
asks the operator on the line, in Thai and hands-free, and the plant manager reviews and approves the result in Japanese or English.

> *The system says what it doesn't know, then asks the person who does.*

Built for the U-Hackathon AI track.

## System architecture

![VALZ system architecture](images/system_architecture.png)

The full architecture, with team delegation, shared data contracts and the 24-hour build plan, is in
[docs/system_architecture.html](docs/system_architecture.html).

Data flows left to right through three layers:

| Layer | Nodes | What happens |
|---|---|---|
| **Perception** | 01 Pre-processing · 02 BLIP Captioner · 03 VLM Reasoner · 04 SOP + Muda Prompts | The clip is sampled at 1–2 fps with motion-based keyframes. BLIP captions each keyframe, and a VLM (Gemini / GPT-4o), guided by the SOP and the 7 Muda definitions, labels time segments as value-adding or a type of waste, with a confidence score. |
| **Gemba Kaizen Core** | 05 Gemba Kaizen Orchestrator · 06 Gemba Kaizen Engine · 07 State Store | A FastAPI service runs the pipeline and keeps state. The engine computes cycle time and VA% vs NVA%, and produces Gemba Kaizen Action Cards with ROI. |
| **Interface** | 08 ElevenLabs Agent · 09 Dashboard | The voice agent (STT · LLM · TTS, TH / JP / EN personas) talks to the operator and the manager. The dashboard shows the video, a timeline synced to playback, and the cards, with live updates over SSE. |

### The uncertainty loop

1. **03** The VLM labels any segment with confidence below 0.75 as `UNCERTAIN` (a grey bar on the timeline).
2. **05** The orchestrator queues a question tied to that segment's id and timestamp.
3. **08** The voice agent asks the operator in Thai, hands-free, while they keep working:
   *"I saw a 4-second pause at 00:16. Did a part jam?"*
4. **05** The answer and its root cause are posted back, and the segment becomes `verified`.
5. **06** The Gemba Kaizen Engine recalculates ROI, and the dashboard updates live over SSE (**09**).

### Example Gemba Kaizen Action Card

| Field | Value |
|---|---|
| Observation | Reach to Bin B in 100% of cycles (avg 2.4 s) |
| Recommendation | Move Bin B 25 cm closer to the fixture |
| Seconds saved per cycle | 1.6 |
| Cycles per shift | 1,346 (8 h × 3600 / 21.4 s cycle) |
| Hours saved per shift | 0.60 (1.6 × 1,346 / 3600) |
| Throughput gain | 8.1% (21.4 / 19.8 − 1) |

Segment classes are `VA`, `NVA_MOTION`, `NVA_WAITING`, `NVA_SEARCH`, `SAFETY_ERGO`, `SOP_DEVIATION` and `UNCERTAIN`.
A segment's status moves from `auto` to `needs_verification` to `verified`.

## Project status

| Node | Component | Owner | Location | Status |
|---|---|---|---|---|
| 00 | Workstation clips (before / after) | P5 | — | Planned |
| 01 · 02 | Frame sampling, BLIP captioning, prompt-to-frame action matching | P1 | [ai_backend/](ai_backend) | **Built** |
| 01 | YOLOv8 person counting (runs in parallel with BLIP) | P1 | [ai_backend/](ai_backend) | **Built** |
| 02 | VLM per-frame action / safety detection on OpenRouter, Qwen3 flash by default (`/vlm_action`, alternative to BLIP) | P1 | [ai_backend/](ai_backend) | **Built** |
| 01 · 03 | Safety Agent: prompt safety rules + per-frame activity / Muda timeline (OpenRouter VLM) | P1 | [ai_backend/](ai_backend) | **PoC** |
| 04 · 06 | Gemba Kaizen Agent: Gemba Kaizen Engine metrics + knowledge cards + OpenRouter LLM → Gemba Kaizen cards with ROI | P1 | [ai_backend/](ai_backend) | **PoC** |
| 01 | Motion-based keyframes (FFmpeg + OpenCV frame diff) | P1 | — | Planned |
| 03 · 04 | VLM reasoner, SOP + Muda prompt pack | P2 | — | Planned |
| 05 · 06 · 07 | Gemba Kaizen Orchestrator, Gemba Kaizen Engine, State Store | P3 | — | Planned |
| 08 | ElevenLabs voice agent | P4 | — | Planned |
| 09 | Dashboard: Video, Safety Agent, Dashboard and Gemba Kaizen pages wired to ai_backend, with a mock mode | P5 | [frontend/](frontend) | **Integrated** |

The architecture diagram names Next.js for the dashboard. The repository's dashboard is SvelteKit.

## Repository layout

```
.
├── ai_backend/        Perception service: FastAPI + BLIP action detection + YOLO person counting
│   ├── server.py              API (Swagger at /docs, spec in openapi.json)
│   ├── video_action_model.py  BLIP captioning + MiniLM prompt matching → action segments
│   ├── vlm_action_model.py    OpenRouter VLM (Qwen3 flash) Yes/No per frame → action segments
│   ├── safety_agent.py        Safety Agent: safety rules + activity (Muda) timeline on the OpenRouter VLM
│   ├── lss_agent.py        Gemba Kaizen Agent: metrics + knowledge cards + OpenRouter LLM → Gemba Kaizen cards
│   ├── knowledge/             Countermeasure knowledge cards (RAG source)
│   ├── static/demo.html       Upload page for the VALZ pipeline (served at /demo)
│   ├── person_count_model.py  YOLOv8n person counting
│   ├── schemas/               JSON Schemas of the model outputs
│   └── tests/                 pytest (fake models, no downloads)
├── frontend/          Dashboard: SvelteKit (adapter-node); /api/* proxies to ai_backend; demo clips in static/demo
├── PRODUCT.md         Product record (users, purpose, constraints) for design work
├── DESIGN.md          The dashboard's design system
├── deploy/nginx.conf  nginx for the full system (docker-compose.yml at the root)
├── docker-compose.yml Full system: nginx → frontend → ai_backend
├── docs/              Architecture, delegation and data contracts
├── images/            Architecture diagram
└── .github/workflows/ CI: lint, type-check, tests and build for both apps
```

## Run the whole system

```
browser ──► nginx :80 ──► frontend (SvelteKit, :3000) ──► /api/* proxy ──► ai_backend (FastAPI, :8000) ──► OpenRouter
                 └─ /docs, /redoc, /openapi.json ─────────────────────────► ai_backend
```

```bash
cp ai_backend/.env.example ai_backend/.env      # set OPENROUTER_API_KEY
docker compose up --build                       # http://localhost  (API docs: http://localhost/docs)
```

The browser only talks to the frontend. Its server route [`/api/[...path]`](frontend/src/routes/api/[...path]/+server.ts)
streams requests (including video uploads) to `AI_BACKEND_URL` (`http://api:8000` in Compose), so ai_backend needs no CORS
setup and is not exposed except for its API docs. Uploads up to 550 MB and 15-minute analyses are allowed end to end.
It fits a 4 GB CPU-only VM: the vision model and the Gemba Kaizen LLM run on OpenRouter (ai_backend idles under 1 GB, the frontend at about 25 MB).

## AI backend

The perception service that exists today. Given a video and a prompt such as `person running`, it returns:

- **When the action happens.** It samples frames, captions them with BLIP (`Salesforce/blip-image-captioning-large`), splits the prompt and each caption into person, action and context words, and scores them with `all-MiniLM-L6-v2` embeddings. Matching frames are merged into time segments.
- **How many people are in frame.** YOLOv8 nano counts people per sampled frame and reports the max, min and average. It runs in a second thread at the same time as BLIP.

```bash
cd ai_backend
uv venv --python 3.13 .venv && uv pip install -r requirements.txt
.venv/bin/python -m spacy download en_core_web_sm
.venv/bin/python server.py --port 8000          # Swagger UI: http://localhost:8000/docs

# or with Docker (CPU)
docker compose up --build
```

```bash
curl -X POST http://localhost:8000/video_action/detect/upload \
     -F "file=@clip.mp4" -F "prompt=person reaching for a bin"
```

The first start downloads about 2 GB of model weights. See [ai_backend/README.md](ai_backend/README.md) for every
endpoint, parameter, environment variable and response schema.

## Frontend

The dashboard has five pages: **Video** (upload a clip, pick a bundled demo clip, or replay one as a simulated live feed),
**Safety Agent** (review incidents and edit the safety rules' prompts, severity and thresholds), **Dashboard** (the shift in one
screen), **Gemba Kaizen** (the agent's suggestions with ROI, evidence and cited sources; approve, defer or reject each) and **Voice Agent** (ask questions about the shift by voice or text; answers are read aloud with
ElevenLabs, from the analysis and the knowledge cards). Demo clips
carry a cached analysis, so everything works with no backend and no API key; `pnpm demo:add` analyses your own clip once and
adds it to the list. See [frontend/README.md](frontend/README.md).

```bash
cd frontend
corepack enable                 # provides pnpm
pnpm install
cp .env.example .env            # AI_BACKEND_URL (default http://localhost:8000); DATABASE_URL is optional
pnpm run dev                    # http://localhost:5173 (start ai_backend on :8000 first)
```

| Command | What it does |
|---|---|
| `pnpm run check` | Type-check with `svelte-check` |
| `pnpm run lint` | Prettier check |
| `pnpm run test:unit --run` | Vitest (component tests run in headless Chromium) |
| `pnpm exec playwright test` | End-to-end tests |
| `pnpm run build` | Production build |

## CI

GitHub Actions runs on pull requests and on pushes to `main`. Each workflow runs only when its folder changes, and can also be started by hand from the Actions tab. It tests and builds, but does not deploy.

| Workflow | Runs when | Does |
|---|---|---|
| [Frontend](.github/workflows/frontend.yml) | `frontend/` changes | pnpm install, Prettier, svelte-check, Vitest, build, Playwright e2e |
| [AI Backend](.github/workflows/backend.yml) | `ai_backend/` changes | pytest with CPU-only torch; includes a check that `openapi.json` is up to date |

## Team

| Owner | Role | Nodes |
|---|---|---|
| P1 | Vision pipeline engineer | 01 Pre-processing · 02 BLIP Captioner |
| P2 | VLM & Muda reasoning | 03 VLM Reasoner · 04 SOP + Muda Prompts |
| P3 | Backend & Gemba Kaizen engine | 05 Orchestrator · 06 Gemba Kaizen Engine · 07 State Store |
| P4 | Voice agent engineer | 08 ElevenLabs Agent |
| P5 | Dashboard, demo & pitch | 00 Clips · 09 Dashboard |