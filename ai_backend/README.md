# Video Action Detection API (OpenRouter VLM + Gemba Kaizen agent + YOLO; BLIP optional)

FastAPI service that finds when an action happens in a video, given a text prompt such as `person running`,
and counts the people in it.
There are two action detection lines that return the same kind of segments: BLIP + MiniLM (`/video_action/*`)
and a vision language model on OpenRouter, Qwen3 flash by default (`/vlm_action/*`).
Ported from the BLIP pipeline and the YOLO person counter in [Celesca/valz](https://github.com/Celesca/valz) (`cmkl-backend`), same as [Celesca/DAMZ](https://github.com/Celesca/DAMZ).

## How it works

Action detection ([video_action_model.py](video_action_model.py)):

1. Sample frames at `sample_fps` (default 1 per second)
2. Caption each frame with BLIP (`Salesforce/blip-image-captioning-large`), in batches
3. Split the prompt and each caption into person / action / context words (spaCy `en_core_web_sm`, keyword fallback)
4. Compare each part with `all-MiniLM-L6-v2` embeddings and combine with the weights
5. A frame passes when `weighted >= similarity_threshold` and `action >= action_threshold`
6. Passed frames less than `segment_gap` seconds apart are merged into segments

VLM action detection ([vlm_action_model.py](vlm_action_model.py)), a vision model on OpenRouter (`VLM_MODEL`, default `qwen/qwen3.7-flash`):

1. Sample frames at `sample_fps` (default 1 per second), downscaled to `VLM_MAX_IMAGE_SIDE` (default 640 px) and sent as JPEG
2. Ask the model per frame (`VLM_CONCURRENCY` requests in parallel): *Is this happening in the image: "<prompt>"?* It answers Yes / No
   with a 0-100 confidence, and (with `describe=true`) a one-sentence description of the frame
3. `confidence` is the probability of Yes: the reported confidence, or one minus it for a No
4. A frame passes when `confidence >= confidence_threshold`; passed frames are merged into segments as above

The VLM judges the prompt directly instead of comparing captions with it, so prompts can describe a condition or
a safety rule (`worker not wearing a helmet`, `hand inside the machine guard`), which BLIP + MiniLM cannot do.
There are no model weights to load, so it runs on any small VM. Confidences are what the model reports, so they are coarser
than token probabilities: tune `confidence_threshold` on your own footage.

Person counting ([person_count_model.py](person_count_model.py)):

1. Sample frames at `person_sample_fps` (default 2 per second)
2. Run YOLOv8 nano on batches of frames, keeping only the COCO `person` class above `person_confidence`
3. Report the count and boxes per frame, plus max / min / average over the video

When a video goes to `/video_action/detect*` or `/vlm_action/detect*`, YOLO runs in a second thread at the same time as the action model (turn off with `count_people=false`).
YOLO runs on CUDA when available, otherwise on CPU. It never uses Apple MPS, because two threads using MPS at once crash the process (BLIP may use it).
If counting fails, the action result is still returned, with `person_count: null` and the reason in `person_count_error`.

## VALZ pipeline (proof of concept): Safety Agent → Gemba Kaizen Agent

Upload a workstation / CCTV clip at **http://localhost:8000/demo**, or call `/analysis/analyze/upload`.

```
video ──► Safety Agent (VLM on OpenRouter) ───────────────┐
      │     per frame: Yes/No per safety rule              │
      │              + "what is the worker doing?" (A-H)   ├──► Gemba Kaizen Engine ──► Gemba Kaizen Agent ──► Gemba Kaizen cards
      │     key frames: one-sentence description + JPEG    │    (VA/NVA time,     (OpenRouter LLM +       + ROI
      └──► YOLO person count (parallel) ───────────────────┘     waste/shift,      knowledge cards,       + safety actions
                                                                  ROI math)         cites ids + times)     + operator questions
```

**Safety Agent** ([safety_agent.py](safety_agent.py)), on the same OpenRouter vision model as `/vlm_action`:

- **Safety rules** are prompts you choose, e.g. `high: a person who is not wearing a safety helmet`, `running`.
  Each rule gets a 0-100 confidence per frame; confidence ≥ `threshold` (0.6) flags the frame, and flagged frames
  closer than `segment_gap` seconds form one event. Built-in rules: no helmet, running, phone use, person down.
- **Activity**: one multiple-choice question per frame (the chosen letter and its confidence), mapped to a Muda category:

  | Activity | Category |
  |---|---|
  | working (assembling, machining) | `VA` |
  | inspecting | `NNVA` (necessary, non-value-adding) |
  | walking, reaching | `NVA_MOTION` |
  | carrying | `NVA_TRANSPORT` |
  | searching | `NVA_SEARCH` |
  | waiting / idle | `NVA_WAITING` |
  | no person visible | `NO_PERSON` (not counted in VA / NVA %) |
  | top choice below `activity_min_confidence` (0.4) | `UNCERTAIN` |

- On the `openrouter` backend the same agent runs with one request per frame (see "Vision model backend").
- **Time comes from frame timestamps, never from the VLM** (VLMs are poor at timing): each sampled frame counts
  for `1 / sample_fps` seconds. Videos longer than `max_frames / sample_fps` are sampled more sparsely.
- Evidence: the key frame of every safety event and of the longest activity segments gets a one-sentence
  description (up to `max_descriptions`) and a small JPEG snapshot (`include_snapshots`).
- **One request per frame** answers the activity question and all rules at once (about 600 input and 40 output tokens),
  so cost grows with the number of frames, not with the number of rules. Requests run `VLM_CONCURRENCY` at a time.
  The response has `safety.vlm_usage` (requests, tokens, and the cost in USD that OpenRouter reports for that run).

**Gemba Kaizen Agent** ([lss_agent.py](lss_agent.py)):

1. **Gemba Kaizen Engine** (plain Python): VA / NNVA / NVA %, seconds and projected hours per shift for each waste
   category, longest waste segments, safety counts, people on camera.
2. **Knowledge retrieval** from [knowledge/lss_cards.json](knowledge/lss_cards.json): countermeasure
   cards for the observed waste categories, the triggered safety rules (matched by tags) and general method
   (ECRS, 5 Whys, standard work). Each card is our own summary of a named source (Ohno, Barnes, Shingo,
   Hirano, Lean Lexicon, OSHA, NIOSH); add plant SOPs and past Gemba Kaizen cards to the same file.
3. **LLM** through [OpenRouter](https://openrouter.ai) with a strict JSON schema: 2-5 Gemba Kaizen cards
   (observation, root cause, recommendation, video evidence times, cited card ids, estimated saving),
   one safety action per triggered rule, and questions for the operator about unclear moments
   (for the voice agent). Output language: `en`, `th` or `ja`. The metrics, not the LLM, are the source of numbers.
4. **ROI** (plain Python): `est_seconds_saved_per_cycle × cycles per shift` when `cycle_time_s` is known
   (plus throughput gain), else `waste_share_removed × projected waste hours per shift`.

Without `OPENROUTER_API_KEY` (or with `use_llm=false`, or if the LLM call fails) the cards are built by rules
from the same metrics and knowledge cards; the response says `source: "rules"` and why in `llm_error`.
One Gemba Kaizen call sends about 5-10k tokens, so it costs well under a cent with `google/gemini-3.1-flash-lite`.

```bash
cp .env.example .env    # then set OPENROUTER_API_KEY=sk-or-...

# Full pipeline
curl -X POST http://localhost:8000/analysis/analyze/upload \
     -F "file=@station.mp4" \
     -F $'rules=high: a person who is not wearing a safety helmet\nmedium: a person running' \
     -F "station_name=Assembly cell 3" -F "cycle_time_s=21.4" -F "language=th"

# Or step by step: Safety Agent, then send its result to the Gemba Kaizen Agent
curl -X POST http://localhost:8000/safety/detect/upload -F "file=@station.mp4" -o safety.json
jq '{safety: (del(.success, .person_count, .person_count_error)), person_count, context: {cycle_time_s: 21.4}}' \
   safety.json | curl -X POST http://localhost:8000/lss/suggest -H "Content-Type: application/json" -d @-
```

| Parameter | Default | Description |
|---|---|---|
| `rules` | built-in 4 | Upload: one rule per line (`high: ...`) or a JSON list; URL: list of `{id, prompt, severity, threshold}` |
| `sample_fps` / `max_frames` | 1.0 / 240 | Frames analyzed per second, and the cap for long videos |
| `segment_gap` | 2.0 | Seconds between flagged frames in one safety event |
| `activity_min_confidence` | 0.4 | Below this the activity is `UNCERTAIN` |
| `max_descriptions` / `include_snapshots` | 12 / true | Key-frame evidence |
| `station_name`, `process_description`, `notes` | | Context for the Gemba Kaizen Agent |
| `cycle_time_s`, `takt_time_s`, `cycles_per_shift`, `shift_hours`, `operators` | –, –, –, 8, 1 | For ROI |
| `language` | `en` | `en`, `th`, `ja` |
| `use_llm` / `count_people` | true / true | |

### Models: everything runs on OpenRouter

Both agents use hosted models, so the service needs no GPU and no model weights (about 1 GB of RAM in Docker,
tested with a 4 GB limit). Set `OPENROUTER_API_KEY` and, if you like, pick other models:

| Agent | Variable | Default |
|---|---|---|
| Safety Agent / `/vlm_action` (vision) | `VLM_MODEL` | `qwen/qwen3.7-flash` |
| Gemba Kaizen Agent (text) | `LSS_LLM_MODEL` | `google/gemini-3.1-flash-lite` |

The vision model must accept images: check its input modalities in `curl -s https://openrouter.ai/api/v1/models`,
and compare two or three on your own footage (events found, `vlm_usage.cost`) before you pick one.
Without a key `/safety/*`, `/vlm_action/*` and `/analysis/*` return 503 and `/lss/suggest` falls back to rule-based cards.
Only the older `/video_action` endpoints use local weights (BLIP, about 2 GB), so avoid them on a 4 GB VM.

## Setup

```bash
cd ai_backend
uv venv --python 3.13 .venv            # or: python -m venv .venv
uv pip install -r requirements.txt     # or: .venv/bin/pip install -r requirements.txt
.venv/bin/python -m spacy download en_core_web_sm
```

## Run

```bash
.venv/bin/python server.py --port 8000
```

Nothing is downloaded at startup except the 6 MB `yolov8n.pt` (saved in the working directory, on the first person count).
The `/video_action` endpoints download about 2 GB of BLIP / MiniLM weights on first use; BLIP picks CUDA, then Apple MPS, then CPU.
Swagger UI is at http://localhost:8000/docs.

| Env var | Default | Meaning |
|---|---|---|
| `PRELOAD_MODEL` | `1` | Preload BLIP and YOLO at startup (`0` = load on first use; docker-compose sets `0`) |
| `BLIP_BATCH_SIZE` | `8` | Frames per BLIP batch |
| `VLM_MODEL` | `qwen/qwen3.7-flash` | OpenRouter vision model of the Safety Agent and `/vlm_action` |
| `VLM_CONCURRENCY` | `4` | Parallel VLM requests |
| `VLM_MAX_IMAGE_SIDE` | `640` | Frames are downscaled to this longest side (fewer vision tokens, faster) |
| `YOLO_MODEL` | `yolov8n.pt` | YOLO weights name or path (e.g. `yolo11n.pt`, `yolov8s.pt`) |
| `YOLO_DEVICE` | auto | YOLO device: `cuda`, `cpu`, ... (auto = CUDA if available, else CPU) |
| `YOLO_BATCH_SIZE` | `16` | Frames per YOLO batch |
| `MAX_VIDEO_MB` | `500` | Max upload or download size |
| `VLM_CONCURRENCY` | `4` | Parallel requests per frame batch (`openrouter` backend) |
| `OPENROUTER_API_KEY` | – | OpenRouter key for the vision model and the Gemba Kaizen Agent (also read from `.env`) |
| `LSS_LLM_MODEL` | `google/gemini-3.1-flash-lite` | Any OpenRouter chat model with JSON output |
| `OPENROUTER_URL` | OpenRouter chat completions URL | Override to use a proxy |

## Docker

```bash
cp .env.example .env             # set OPENROUTER_API_KEY (docker compose reads .env next to the compose file)
docker compose up --build        # api + nginx on http://localhost (demo at /demo, Swagger at /docs)
```

The image is CPU only and needs no GPU: the vision model and the Gemba Kaizen LLM run on OpenRouter, nothing is preloaded
(`PRELOAD_MODEL=0`), and the YOLO weights (6 MB) are included. Idle memory is under 1 GB, so a 4 GB VM is enough.
The `hf-cache` volume only matters if you call the `/video_action` (BLIP) endpoints, which download about 2 GB on first use.
Without `OPENROUTER_API_KEY` the container still starts; `/health` says `degraded` and `/analysis/*` returns 503 until a key is set.
nginx allows 550 MB uploads and 15-minute requests, because `/analysis/analyze` stays open until the analysis finishes.
For an NVIDIA GPU (only useful for YOLO and BLIP), build with `--build-arg TORCH_INDEX_URL=https://download.pytorch.org/whl/cu124`
and uncomment the `deploy` block in `docker-compose.yml`.

## Voice Agent (chatbot with ElevenLabs speech)

`voice_agent.py` answers questions about an analysis, by text or voice.

- **RAG:** the analysis the client sends (Gemba Kaizen summary, time breakdown, waste, incidents, Gemba Kaizen cards, activity segments)
  and the knowledge cards are cut into passages; the best matches for the question (BM25 keyword scoring, character bigrams
  for Thai and Japanese) go to the LLM (`VOICE_LLM_MODEL`, default `LSS_LLM_MODEL`). Answers are plain sentences meant to
  be read aloud, with times as `m:ss`. Without `OPENROUTER_API_KEY` the best passages are returned as they are.
- **Voice out:** `POST /voice/speak` calls ElevenLabs text-to-speech (`ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`,
  `ELEVENLABS_TTS_MODEL`). Each clip is stored in SQLite (`VOICE_DB_PATH`, default `data/voice.db`, a Docker volume) keyed by
  voice, model and text, so a repeated sentence costs nothing and still plays if ElevenLabs is unreachable.
  `X-Voice-Cache: hit|miss` says which.
- **Voice in:** `POST /voice/transcribe` uses ElevenLabs Scribe, which detects the language.

## HTTPS (needed when the frontend is on Vercel)

A page on `https://` cannot send files to an `http://` backend, and Vercel refuses request bodies over 4.5 MB, so a video
upload from the hosted dashboard must go from the browser straight to an **https** backend. `docker-compose.https.yml` swaps
nginx for Caddy, which gets and renews a Let's Encrypt certificate by itself (DNS for the domain must point at the server,
ports 80 and 443 open):

```bash
DOMAIN=gemba.limitlesstech-co.com docker compose -f docker-compose.yml -f docker-compose.https.yml up -d --build
```

Then set `AI_BACKEND_URL=https://gemba.limitlesstech-co.com` on the frontend host and redeploy it: the app sends uploads to
that address directly (`/config`) and everything else through its `/api` proxy. To lock the API to your dashboard, set
`ALLOWED_ORIGINS=https://your-app.vercel.app`.

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/voice/status` | Voice Agent: ElevenLabs and LLM configured, voice, audio database size |
| POST | `/voice/chat` | Answer a question about an analysis (RAG + LLM), JSON |
| POST | `/voice/speak` | Text to speech (MP3), cached in the voice database |
| POST | `/video/preview` | H.264 MP4 preview (max 1280 px, no audio, same timing) of an uploaded video the browser cannot play; needs `ffmpeg` (in the Docker image) |
| POST | `/voice/transcribe` | Speech to text (multipart audio) |
| GET | `/video_action/status` | Detector status, device and models |
| POST | `/video_action/detect` | Action detection + person count, video from a direct URL (JSON body; YouTube URLs are not supported) |
| POST | `/video_action/detect/upload` | Action detection + person count, uploaded video (multipart form) |
| GET | `/vlm_action/status` | VLM status: key configured, model, concurrency |
| POST | `/vlm_action/detect` | VLM action detection + person count, video from a direct URL (JSON body) |
| POST | `/vlm_action/detect/upload` | VLM action detection + person count, uploaded video (multipart form) |
| GET | `/person_count/status` | YOLO counter status, model and device |
| POST | `/safety/detect` · `/safety/detect/upload` | Safety Agent: safety events + activity timeline |
| GET | `/lss/status` | Gemba Kaizen Agent: LLM configured, model, knowledge cards, default rules |
| POST | `/lss/suggest` | Gemba Kaizen Agent on a Safety Agent result (JSON) |
| POST | `/analysis/analyze` · `/analysis/analyze/upload` | Full pipeline: Safety Agent → Gemba Kaizen Agent |
| GET | `/demo` | Browser upload page for the full pipeline |
| POST | `/person_count/detect` | Person count only, video from a direct URL (JSON body) |
| POST | `/person_count/detect/upload` | Person count only, uploaded video (multipart form) |

```bash
curl -X POST http://localhost:8000/video_action/detect/upload \
     -F "file=@video.mp4" -F "prompt=person running"

curl -X POST http://localhost:8000/video_action/detect \
     -H "Content-Type: application/json" \
     -d '{"video_url": "https://example.com/video.mp4", "prompt": "person running"}'

curl -X POST http://localhost:8000/vlm_action/detect/upload \
     -F "file=@video.mp4" -F "prompt=worker not wearing a helmet" -F "describe=false"

curl -X POST http://localhost:8000/person_count/detect/upload -F "file=@video.mp4"
```

Optional parameters (JSON fields or form fields):

| Parameter | Default | Endpoints | Description |
|---|---|---|---|
| `person_weight` | 0.2 | video_action | Weight of the person component |
| `action_weight` | 0.7 | video_action | Weight of the action component |
| `context_weight` | 0.1 | video_action | Weight of the context component |
| `similarity_threshold` | 0.5 | video_action | Minimum weighted score |
| `action_threshold` | 0.4 | video_action | Minimum action score |
| `sample_fps` | 1.0 | video_action, vlm_action | Frames analyzed per second of video |
| `segment_gap` | 3.0 | video_action, vlm_action | Max gap in seconds inside one segment |
| `confidence_threshold` | 0.5 | vlm_action | Minimum P(Yes) for a frame to pass |
| `describe` | true | vlm_action | Also return a one-sentence `vlm_description` per frame (slower) |
| `return_timeline` | true | video_action, vlm_action | Include `timeline_visualization` data |
| `count_people` | true | video_action, vlm_action | Also count people with YOLO, in parallel |
| `person_confidence` | 0.5 | both | YOLO confidence threshold |
| `person_sample_fps` | 2.0 | both | Frames counted per second of video |

## OpenAPI / Swagger

- Swagger UI: http://localhost:8000/docs (ReDoc: `/redoc`), with examples for the JSON endpoints and a file picker for uploads
- **Annotated video:** `POST /safety/annotate` (URL) and `POST /safety/annotate/upload` take the same fields as
  `/safety/detect*` and return an MP4: person boxes (YOLO) labelled with the rule name, red `VIOLATION: no_helmet 0.82`
  when a rule passed its threshold, amber `NEAR MISS` within `near_miss_margin` (query, default 0.15). The VLM scores whole frames,
  so a hit is drawn on every person in that frame. Code: `annotate_video.py`.
- Live spec: http://localhost:8000/openapi.json
- Committed copy: [openapi.json](openapi.json). A test fails when it is out of date; regenerate it with:

```bash
.venv/bin/python server.py --export-openapi openapi.json
```

Every endpoint has a typed response model and documented errors (400 / 413 / 422 / 500 / 503).
The operationIds are the Python function names (e.g. `detect_video_action_from_upload`), so generated clients get readable names.
To generate TypeScript types for the frontend:

```bash
npx openapi-typescript ../ai_backend/openapi.json -o src/lib/api-types.ts
```

## Response schemas

- [schemas/video_action_result.schema.json](schemas/video_action_result.schema.json): output of `ActionDetector.process_video()`.
  The `/video_action/detect*` response is the same data with `passed_detections_only` renamed to `passed_detections`,
  `timeline_data` renamed to `timeline_visualization`, and `success`, `person_count`, `person_count_error`, `error` added.
- `/vlm_action/detect*` returns `VLMActionResponse` (see [openapi.json](openapi.json)): the same layout as
  `/video_action/detect*`, with `model` instead of `action_verb`, and each detection has `confidence`, `answer`
  (`Yes` / `No`) and `vlm_description` instead of `blip_description` and `similarity_scores`.
  `action_label` and the timeline's `action_verb` are the prompt.
- [schemas/person_count_result.schema.json](schemas/person_count_result.schema.json): output of `PersonCounter.process_video()`.
  It is `person_count` in the `/video_action/detect*` response, and the body of `/person_count/detect*` (plus `success`).

`person_id` is the box index within one frame, not a tracked identity, so `max_persons` is the most people
visible at once, not the number of different people in the whole video.

## CLI and tests

```bash
.venv/bin/python video_action_model.py video.mp4 "person walking"
.venv/bin/python vlm_action_model.py video.mp4 "worker not wearing a helmet"
.venv/bin/python person_count_model.py video.mp4
.venv/bin/python safety_agent.py video.mp4 --rules $'high: not wearing a helmet\nrunning' > safety.json
.venv/bin/python lss_agent.py safety.json --cycle-time 21.4 --language th
.venv/bin/python -m pytest -q     # tests use fake models, so no model download is needed
```
