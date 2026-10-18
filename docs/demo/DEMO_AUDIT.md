# VALZ demo audit

What the AI Builder Cup video can honestly show, checked on 2026-10-18 against `main` at `0688f3b`, plus the local changes listed
in [Changes made on 18 Oct](#changes-made-on-18-oct).
The storyboard ([DEMO_STORYBOARD.md](DEMO_STORYBOARD.md)), narration ([NARRATION_SCRIPT.md](NARRATION_SCRIPT.md)) and
recording steps ([RECORDING_RUNBOOK.md](RECORDING_RUNBOOK.md)) only use what this audit marks as verified.

## Changes made on 18 Oct

The first pass of this audit found that the demo clip had burned-in "no_helmet" boxes and that the Safety Agent ran on Qwen. Later the same day:

| Change | Files | Why |
|---|---|---|
| Both agents switched to **Gemini 3.1 Flash-Lite through the Gemini API** (Google AI Studio key), using the client's existing `OPENROUTER_URL` override to point at Gemini's OpenAI-compatible endpoint | `ai_backend/.env` (git-ignored) | The competition requires Google AI models |
| Opt-in request spacing `LLM_MIN_INTERVAL_S` (4.5 s keeps under 15 requests/minute) and the OpenRouter-only `reasoning` field no longer sent to other endpoints (the Gemini API answered HTTP 400, doubling requests) | `ai_backend/openrouter_client.py`, test pinned to the OpenRouter URL in `tests/test_cloud_vlm.py` | Free-tier quota; without spacing, a 50-frame burst fails frames |
| Rule prompt clarified: "0 = not happening, including when you are sure it is not happening…" | `ai_backend/vlm_action_model.py` | Flash-Lite scored **every** rule 100 % on frames of a person walking or standing (repeatable, 3 of 3). After the change those frames score 0, and a real deep-bend frame still scores 0.85 |
| `--sample-fps` option | `frontend/scripts/add-demo-clip.mjs` | 0.5 fps halves model calls |
| New clean clip analysed live and added as the first demo clip | `frontend/static/demo/ws10-car-door-2024-04-23.*`, `manifest.json` | Replaces the clip with burned-in boxes |

Backend tests: 95 of 96 pass. The one failure, `test_openapi_json_is_up_to_date`, also fails on unchanged `main`.
Nothing is committed.

## How this was checked

| Check | Result |
|---|---|
| Frontend run locally (`pnpm run dev`, no backend, no API key) | Video, Safety, Dashboard and Gemba Kaizen pages driven in a browser at 1920×1080 and 1536×864 |
| Production site `https://gemba.limitlesstech-co.com` (`/` and `/health`) | **HTTP 502** on both, 18 Oct 2026. The deployed backend is down or the VM is stopped |
| Backend (`ai_backend/`) | Run locally on port 8010 (Python 3.13 venv, outside Docker) with the Gemini API key. One full analysis of the new clip through `POST /analysis/analyze/upload`, twice (before and after the prompt fix). Voice endpoints not exercised |
| Cached analysis files | Parsed `frontend/static/demo/*.analysis.json`; one incident snapshot decoded and viewed |
| Demo video | Frames extracted with ffmpeg at 0 s, 10 s and 35 s |
| Competition rules | [aibuildercup.com](https://aibuildercup.com/) and its Challenges page |

## Competition requirements that affect the video

From the Challenges page:

- Submissions **must leverage Google AI models (Gemini or Gemma)** or a Google agentic platform, and **must be deployed on Google Cloud via Cloud Run or Firebase**.
- Video: public YouTube, Vimeo or Drive link, about 3 minutes, showing the AI creation in action. Everything in English.
- Judging: Technical merit and Gen AI implementation 40 %, problem alignment and impact 25 %, innovation 25 %, user experience 10 %.
- Prototype submission deadline on the timeline: **18 Oct 2026**, which is today.

## Feature verification matrix

Statuses: VERIFIED LIVE (tested against a working backend), VERIFIED CACHED (working UI on stored results), IMPLEMENTED,
NOT TESTED, MOCK / HARDCODED, PARTIAL, NOT IMPLEMENTED.

The evidence column quotes the first check, on the old clip (`xsens-004-ws10-in-l`). The same controls were re-checked on the new
Gemini clip (Open, threshold re-derivation, Play, Mark reviewed, evidence chips, Approve counter); its exact on-screen values are in
the storyboard. The severity and threshold notes about the bending rule apply to the old clip only.

| Feature | UI route | Relevant code | Status | Evidence | Demo recommendation |
|---|---|---|---|---|---|
| Load a bundled demo clip | `/video` → **Demo clips** → **Open** | `frontend/src/lib/backend.ts` (demo loading), `static/demo/manifest.json` | VERIFIED CACHED | Clicking **Open** on *WS10 car door assembly* shows "Cached analysis loaded. No model was called. 50 frames · 11 incidents." The top-bar chip reads "Cached demo · WS10 car door assembly…" | **Use.** The label is honest on screen; keep it visible once |
| Upload and analyse a new clip | `/video` → **Upload** → **Analyse video** | `server.py` `POST /analysis/analyze/upload` → `run_analysis` (line 1121) | VERIFIED LIVE (endpoint, through `pnpm demo:add`); dashboard upload button not clicked | 50 s clip, 0.5 fps: 30 vision calls + 1 Kaizen call, **2:18** with the 4.5 s spacer. The dashboard sends 1 fps, so about 5 minutes | Cached path for the video. A live upload only per the storyboard's optional swap |
| Live camera feed | `/video` → **Live** | `routes/video/+page.svelte` | MOCK / HARDCODED (labelled) | UI: "Live ingest is not built yet… you can replay a demo clip as if its findings were arriving live." **Connect** button is disabled | **Exclude.** Mention "not live streams yet" in the limitations |
| Safety rules in plain English | `/safety` → **Rules** panel | `lib/rules.ts`, `lib/default-rules.json`, `safety_agent.py` | VERIFIED CACHED | Four rules shown with prompt, severity and threshold | **Use** |
| Change severity / threshold / on-off | `/safety` → **Low / Medium / High**, **Threshold** slider | `lib/analysis.ts` (re-derives incidents from stored per-frame confidences) | VERIFIED CACHED (client-side) | Deep bend set to **High** → header "11 found · 4 high". Threshold 0.9 → bending incidents 4 → 0, "7 found". Threshold 0.8 → bending incidents 4 → **5** (a long run splits), so do not show 0.8 | **Use severity → High.** If showing the slider, drag to 0.9 and back to 0.6, never 0.8 |
| Edit a rule's prompt / add a rule | `/safety` → prompt text, **+ Add rule**, **Re-run analysis** | `session.svelte.ts`, backend upload path | PARTIAL | Prompt edits and new rules need a re-run, which needs an uploaded video and an OpenRouter key. UI says so | Show the prompt text only. Do not add a rule on camera |
| Rules over time matrix | `/safety` → **Rules over time** | `components/RuleMatrix.svelte` | VERIFIED CACHED | Rule × second grid; counts 0 / 4 / 1 / 6 | **Use**, with a zoom on the Deep bend row |
| Incident list with evidence | `/safety` → **Incidents** | `routes/safety/+page.svelte` | VERIFIED CACHED | Each incident has a thumbnail, time chip, confidence, frame count, a one-sentence description and "Suggested action … (KC-ERG-01)" | **Use** the 00:32–00:47 bending incident (85 %, 13 frames) |
| Jump to the video moment | **Play** on an incident, any time chip, shift grid cell | `lib/playback.svelte.ts`, `components/MiniPlayer.svelte` | VERIFIED CACHED | **Play** on 00:32–00:47 docks a mini player top-right, playing from about 00:31 | **Use** |
| Mark reviewed | **Mark reviewed** | `localStorage` key `valz-marks-v1` | VERIFIED CACHED (browser only) | Stored per browser, not on a server | Use; do not call it "logged" or "saved to the system" |
| Annotated video (boxes drawn by server) | `/video` → **Annotated video** panel → **Draw boxes on the video**, **Original / Boxes** | `POST /safety/annotate/upload`, `annotate_video.py`, `AnnotatePanel.svelte` | VERIFIED LIVE (18 Oct, Gemini, 4:00 at 1 fps) + VERIFIED CACHED (boxed copy ships with the clip) | Every visible person is boxed with Gemini's activity label (green value-adding, blue waste); one amber near-miss box at 00:18–00:20; a fresh result is kept only in the tab and is lost on reload, so the clip now carries a cached copy | Use the cached copy; do not run it on camera |
| Activity / Muda timeline | `/safety` → **Whole shift**, `/dashboard` → **Shift** | `safety_agent.py` activity classes | VERIFIED CACHED | 39 s value-adding, 8 s walking (motion), 3 s carrying (transport) | Use briefly on the Dashboard |
| Dashboard | `/dashboard` | `routes/dashboard/+page.svelte` | VERIFIED CACHED | "78 % of the time a person was visible at WS10 was value-adding work… 1.8 h of every 8 h shift" | Use for 3–5 s in the hook or the Kaizen scene. Avoid dwelling on "1.8 h per shift": it extrapolates a 50 s clip to a whole shift |
| Gemba Kaizen cards | `/lss` | `lss_agent.py` | VERIFIED CACHED | Card K01 *Reduce bending and awkward postures with height adjustment* (high, evidence 00:32–00:47, KC-ERG-01, confidence 90 %). Card K02 *Optimize layout to eliminate walking waste* (≈ 0.13 h/shift, +1.7 % throughput) | **Use.** Strongest feature |
| ROI computed by code, not the LLM | `/lss` → K02 ROI line | `lss_agent.py` step 4 | VERIFIED CACHED | UI: "0.13 h per shift · +1.7% throughput · 4 s/cycle x 120 cycles/shift (computed from the measured times, not by the LLM)" | **Use.** Say the number is arithmetic on measured time, with a 240 s nominal cycle the team entered |
| Approve / defer / reject | `/lss` → **Approve**, **Defer**, **Reject**, **Undo** | `localStorage` `valz-marks-v1` | VERIFIED CACHED (browser only) | Approving both → "2 approved … 0.1 h per shift approved"; Dashboard shows both as Approved | Use. Do not claim it notifies anyone or writes to Firestore |
| Ask the operator | `/lss` → **Ask the operator** | `lss_agent.py` output `operator_questions` | VERIFIED CACHED | Two questions with time chips (00:13, 00:32) and **Copy** | Use. They are text; nothing is sent to an operator |
| Knowledge citations | `/lss` → **Knowledge used** | `ai_backend/knowledge/lss_cards.json` (19 cards), `retrieve_cards` | VERIFIED CACHED | "3 cited" with sources (Barnes; Ohno; NIOSH lifting equation, RULA) and "5 more cards the agent read" | Use. Describe retrieval as matching curated cards by waste category and rule, not as semantic or vector search |
| Voice Agent (chat, speech in/out) | `/voice` | `voice_agent.py`, `lib/voice.svelte.ts` | IMPLEMENTED, NOT TESTED | UI: "The AI backend is not reachable. Chat and ElevenLabs voice need it." Speech is ElevenLabs, chat is OpenRouter, retrieval is keyword (BM25-style) | **UNVERIFIED — DO NOT RECORD AS FUNCTIONAL.** Exclude unless the backend is up and tested |
| Semantic event search | — | — | NOT IMPLEMENTED | No search UI or endpoint | Exclude |
| Reports / analytics (BigQuery, Looker Studio) | — | — | NOT IMPLEMENTED | Only in `docs/DEPLOYMENT.md` and the architecture diagram | Exclude. **COPY APPROVED** (clipboard text) is the only export |
| Report language EN / TH / JA | Top bar **Report** select | `lss_agent.py` `LANGUAGES` | IMPLEMENTED, NOT TESTED | Language is sent with a new analysis; the cached English cards do not change | Exclude |
| Authentication | — | — | NOT IMPLEMENTED | No sign-in. `DEPLOYMENT_VM.md` recommends a Caddy password until Firebase Auth exists | Nothing to show |
| Synthetic clip *Assembly cell 3* | `/video` → second demo clip | `frontend/scripts/make-synthetic-demo.py` | MOCK / HARDCODED (labelled SYNTHETIC) | Scenario scripted; Gemba Kaizen texts "authored", model "cached demo (authored)" | **Exclude.** Its cards were not written by a model |

## What the AI actually does today (verified in code and one live run)

```
browser ─► SvelteKit (frontend, /api proxy) ─► FastAPI ai_backend
                                                 │
   OpenCV samples 1 frame/s ────────────────────┤
   YOLOv8n counts people (local) ───────────────┤
   Vision model (now Gemini 3.1 Flash-Lite via the Gemini API), one request per frame:
     • one Yes/No question per safety rule → P(Yes) is the confidence
     • one multiple-choice "what is the worker doing?" → Muda category
   Deterministic engine (Python): VA / waste seconds, per-shift projection, ROI
   Knowledge retrieval: 19 curated cards in lss_cards.json, matched by waste category and rule words
   LLM (now Gemini 3.1 Flash-Lite) writes Kaizen cards, safety actions, operator questions as strict JSON
```

Models recorded in the cached analyses:

| Clip | Step | Model | Provider path | Usage |
|---|---|---|---|---|
| **`ws10-car-door-2024-04-23`** (18 Oct, use this) | Safety Agent | `gemini-3.1-flash-lite` | Gemini API (AI Studio key) | 30 calls, 40,900 prompt tokens; cost not reported by the API |
| | Gemba Kaizen Agent | `gemini-3.1-flash-lite` | Gemini API | 1 call |
| | People count | YOLOv8n | local PyTorch | 100 frames, max 1 person |
| `xsens-004-ws10-in-l` (16 Oct, retire) | Safety Agent | `qwen/qwen3.7-flash` | OpenRouter | 62 calls, about $0.002 |
| | Gemba Kaizen Agent | `google/gemini-3.1-flash-lite` | OpenRouter | about $0.002 |

Frame check (all 25 sampled moments of the boxed video, 18 Oct): no rule violation anywhere, so no false red box. The one near miss
(awkward posture 0.50 at 00:18) is the operator reaching into the door frame, which is plausible. Activity labels: about 20 of 25 match
what is visible. Wrong type of waste at 00:34 (walking empty-handed, labelled carrying) and 00:36 (standing at the table, labelled
carrying); 00:16 is labelled carrying while the operator already works at the door; 00:30 (holding a part at the door) is borderline.
The 00:30–00:40 trip is real: he walks to a table and comes back with a blue parts bin, which is what K01's water spider suggestion is about.
The waste total is right; only the split between transport and motion waste is off by a few seconds.

What Gemini found on the new clip: no rule above 60 % (highest: awkward posture 50 % at 00:18). Activity 22 s value-adding,
26 s transport (pushing the cart), 2 s walking. Cards: K01 *Implement material delivery system* (water spider or flow rack, KC-TRN-01,
Gemini's estimate 20 s/cycle → 0.67 h/shift, +9.1 % in code), K02 *Optimize workstation layout* (0.03 h/shift). One operator question at 00:30.

## Architecture discrepancies

| Claim in diagrams / README | What the code does | Video consequence |
|---|---|---|
| Gemini on **Vertex AI** | Gemini 3.1 Flash-Lite through the **Gemini API** (AI Studio key, OpenAI-compatible endpoint). No Vertex AI and no `google-genai` SDK | Say "Gemini". Do not say "Vertex AI" |
| Gemini does the vision reasoning | True for the new clip: both agents ran on Gemini 3.1 Flash-Lite | Fine to say, for the new clip only |
| Cloud Run, Eventarc, Workflows, Transcoder, Cloud Run Jobs, Video Intelligence | Not in code. One FastAPI process does everything in-process | Do not show the full diagram as the current system |
| Vertex AI RAG Engine | Static JSON file, category and keyword matching | Say "curated knowledge cards" |
| Speech-to-Text, Text-to-Speech, Translation | ElevenLabs, and the browser's own voice. The Voice Agent's chat now also goes to Gemini (it defaults to `LSS_LLM_MODEL`), not tested | Exclude voice |
| Firestore, Pub/Sub, BigQuery, Looker Studio | Browser `localStorage`; SQLite for voice clips. Firestore rules exist in `deploy/firebase/` but nothing calls Firestore | Do not mention |
| Old deck: YOLO, BLIP, MiniLM, Qwen3-VL, ElevenLabs | YOLO, BLIP, MiniLM and ElevenLabs still exist in code. BLIP + MiniLM (`/video_action/*`) is **not** used by the dashboard pipeline | Do not mention BLIP or MiniLM |
| Deployed on Google Cloud | README describes one Compute Engine VM with Docker Compose. The public site returned **502** today | Hosting must move to Cloud Run or Firebase before it can be claimed (open decision) |
| README says the prototype was built for "U-Hackathon AI track" | Wording only | Not visible in the app |

## Deployment and data risks

1. *(Resolved by switching to the new clip; remove the old entry from `manifest.json`.)* **The old demo video has burned-in "VIOLATION: no_helmet 1.00" boxes on every frame checked** (0 s, 10 s, 35 s).
   `no_helmet` is not one of the four rules shown in the app, and the workers are not breaking a site rule by not wearing hard hats at
   a door assembly cart. Judges will see a red banner that contradicts the UI. The incident snapshots inside the analysis JSON are clean,
   so the analysis was run on an unannotated original (`car-door-assembly.mp4`) and the MP4 was swapped afterwards. **Fix: restore the clean
   50 s crop as `frontend/static/demo/xsens-004-ws10-in-l.mp4`** (same crop, same length, H.264). This is a data file, not a code change.
2. **Production is down (502).** The deadline requires a deployment on Cloud Run or Firebase. The current design is a VM.
3. **Free-tier quota.** 15 requests per minute for Flash-Lite. A dashboard upload (1 fps) takes about 5 minutes; without `LLM_MIN_INTERVAL_S` frames fail with 429.
   Gemini does not report cost, so a live run's status line shows "cost $0.0000".
4. **Gemini found no violation at 60 % on the new clip.** The demo shows near misses by lowering a threshold; never call them violations.
   Near-miss rows have no suggested action, because the analysis only wrote actions for rules that crossed 60 %.
5. **Flash-Lite needed a prompt fix** (see Changes). Before it, 12 of 16 incidents were false. Any other clip should be spot-checked the same way.
6. **Incident descriptions are generic.** They describe the scene ("A worker is assembling or inspecting a car door frame…"), not the
   violation. Narration must not say the AI "explains why it is unsafe". The rule name, confidence and snapshot are the evidence.
7. **Severity, thresholds, review marks and approvals live in `localStorage`.** Clear `valz-rules-v1` and `valz-marks-v1` before each take, or a
   previous take's state shows up.
8. **ROI inputs.** The seconds saved per cycle (20 s on K01) are Gemini's estimate; only the conversion to hours and throughput is code.
   The cycle time (240 s) is a nominal value the team entered, not measured. Narration says exactly this.
9. CarDA is CC BY 4.0: put a credit line in the video and the description.
