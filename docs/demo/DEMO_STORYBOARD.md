# VALZ demo storyboard

Shot-by-shot plan for the 3:35 AI Builder Cup video. Voiceover lines come from [NARRATION_SCRIPT.md](NARRATION_SCRIPT.md); how to
prepare the app and record each take is in [RECORDING_RUNBOOK.md](RECORDING_RUNBOOK.md); feature status is in [DEMO_AUDIT.md](DEMO_AUDIT.md).

## The golden path

One clip, followed through the whole product:

**Clip *WS10 car door assembly (CarDA, 23 Apr 2024, L view)* → Gemini scored 4 plain-English rules on 25 frames: none crossed 60 % →
lower *Awkward arm or wrist posture* to 40 % → 4 near misses during door fitting (00:18–00:22, 50 %) → play that moment →
Gemba Kaizen card K01: 26 s of moving the cart → water spider or flow rack (KC-TRN-01), 0.67 h/shift computed in code →
operator question at 00:30 → Approve.**

Every application shot uses the cached analysis made on 18 Oct 2026 by `gemini-3.1-flash-lite` through the Gemini API, at 0.5 fps
(Safety Agent 30 calls, Kaizen 1 call, run time 2:18 on a 15-requests-per-minute quota). The app labels it "Cached demo" and the
clip list shows "Analysed 2026-10-18 with gemini-3.1-flash-lite, 0.5 fps".

The story is waste first, safety second, because that is what Gemini found in this clip. Do not present the near misses as violations.

## Footage types

- **APP**: genuine screen recording of the running dashboard. Zooms and crops are applied in the edit, never mock-ups.
- **MG**: explanatory motion graphic. Never shows UI that does not exist.
- **CARD**: static title or text card.

## Shot list

Browser at 1920×1080, page zoom 125 % (layout 1536×864), as in the runbook.

### Scene 1: Hook (00:00–00:21)

| Shot | Time | Dur | Objective | Page / element | Actions | On-screen result | Voiceover | Text / callout | Camera | Transition | Evidence | Risks |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1.1 | 00:00–00:08 | 8 s | Real workstation, product first | `/video`, main player | Before the take: clip opened, seeked to 00:02. Press play | Operator pushes the cart with the door along the line | "This is a real car door assembly station. VALZ watched fifty seconds of ordinary camera footage." | Lower-left, small: "WS10 · CarDA dataset (CC BY 4.0)" | APP, crop to the player, slow push-in 100 → 115 % | Cut in from black | Analysed clip | None |
| 1.2 | 00:08–00:14 | 6 s | The finding | `/dashboard`, headline | None | "44 % of the time a person was visible at WS10 was value-adding work." and *Where the time went*: Transport 00:26, 52 % | "More than half of the operator's time went into moving the cart and materials, not assembling." | Highlight the Transport row | APP, crop to the headline and the table at 140 % | Hard cut | Cached summary | Do not show "4.5 h of every 8 h shift" in the crop: it extrapolates a 50 s clip |
| 1.3 | 00:14–00:21 | 7 s | The fix | `/lss`, card K01 | None | Recommendation "Introduce a water spider or flow rack system…" | "So it proposed a fix: bring the parts to the operator, with a water spider or a flow rack." | Highlight the Recommendation line | APP, crop to K01 at 140 % | Hard cut, then dip to MG | Gemini-written K01 | None |

### Scene 2: Problem (00:21–00:39)

| Shot | Time | Dur | Objective | Page / element | Actions | On-screen result | Voiceover | Text / callout | Camera | Transition | Evidence | Risks |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2.1 | 00:21–00:32 | 11 s | Why this matters | — | — | Grid of 6 muted camera tiles (the clip, desaturated, different offsets); a "reviewed" tick appears on one tile only after a red incident flash | "Most factories already have cameras. But the footage is usually reviewed only after something goes wrong. Wasted motion and strain are rarely written down, because no one has time to watch every cycle." | "Reviewed after incidents" · "Waste and strain: unrecorded" | MG | Cross-dissolve 8 frames | Narrative, no numbers | No invented statistics |
| 2.2 | 00:32–00:39 | 7 s | Proposition | — | — | VALZ wordmark, tagline, then "Observe → Understand → Improve" | "VALZ is built for that gap. Existing cameras. Actionable intelligence." | "Existing cameras. Actionable intelligence." | CARD, cover-slide style | Cut to app | — | — |

### Scene 3: Input and rules (00:39–01:23)

| Shot | Time | Dur | Objective | Page / element | Actions | On-screen result | Voiceover | Text / callout | Camera | Transition | Evidence | Risks |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 3.1 | 00:39–00:52 | 13 s | Load the input; be honest it is cached and that Gemini made it | `/video` → **Demo clips** | Hover the first row's note, then click **Open** on *WS10 car door assembly (CarDA, 23 Apr 2024, L view)* | Row shows **Loaded**; note "Analysed 2026-10-18 with gemini-3.1-flash-lite, 0.5 fps"; status "Cached analysis loaded. No model was called. 25 frames · 0 incidents." | "We start with a fifty-second clip from a public car door assembly dataset. We analysed it earlier with Gemini, and the app says so: cached, no model called now." | Highlight "gemini-3.1-flash-lite", then the status line | APP, full window, then 140 % on the note and status | Hard cut | Verified in browser | Fresh browser profile, or the last opened clip is restored |
| 3.2 | 00:52–01:08 | 16 s | Plain-English rules, honest "nothing found" | `/safety` | Click **Safety Agent** under the player → hover the *Awkward arm or wrist posture* prompt → move to the Incidents panel | Rules panel; Incidents panel says "No rule reached its threshold in this video. Lower a threshold above to see near misses." | "Safety rules are written in plain English. For every sampled frame, Gemini scores each rule from zero to one hundred. Here, no rule crossed its threshold, and VALZ says that plainly." | Show the full prompt as a callout | APP, 140 % on Rules, then on the message | Hard cut | Verified | None |
| 3.3 | 01:08–01:23 | 15 s | Tune the policy | `/safety` → *Awkward arm or wrist posture* → **Threshold** slider | Drag the slider from 60 % to **40 %** in one smooth move. Pause 1 s | Rule shows "4 incidents · strongest frame 50%"; header "4 found · 0 high · 4 to review"; matrix row turns orange at 18–22, 24–28, 30–32, 42–44 s | "A safety lead can tune the policy. Lower awkward posture to forty percent, and four near misses appear, straight from the scores already stored." | "re-derived in the browser from stored scores" | APP, split zoom: rule card left, Incidents header right | Hard cut | Verified: 4 found at 0.4 | The slider steps by 5 %; check the label reads 40 % before releasing |

### Scene 4: Near misses (01:23–01:54)

| Shot | Time | Dur | Objective | Page / element | Actions | On-screen result | Voiceover | Text / callout | Camera | Transition | Evidence | Risks |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 4.1 | 01:23–01:32 | 9 s | Where in time | **Rules over time** | Hover along the *Awkward arm or wrist posture* row | Orange cells at the door-fitting seconds | "The timeline shows every rule against every sampled second. The near misses sit where the operator fits parts into the door." | Bracket labelled "door fitting" | APP, 160 % on the matrix | Hard cut | Activity "working" at 18–28 s, 40–48 s | None |
| 4.2 | 01:32–01:41 | 9 s | Jump to the moment | **Incidents** → row 00:18–00:22 → **Play** | Click **Play** | Mini player docks top-right at 00:17: operator at the door; from 00:18 the amber "NEAR MISS: awkward_posture 0.50" box (the clip opens with **Boxes** on) | "One click plays that exact moment." | — | APP, 2-up: row left, mini player right | Hard cut | Verified | It may open paused; press play on the mini player. Let 3 s of video play without voice |
| 4.3 | 01:41–01:54 | 13 s | Human review | Same row | Hover thumbnail → hover "50% · 2 frames" → click **Mark reviewed** | Header "4 found · 0 high · 3 to review" (verified) | "Each one keeps a snapshot and the model's score. These are near misses, not violations, so a person reviews them. VALZ does not close anything on its own." | ① snapshot ② score | APP, 150 % on the row | Dip | Mark stored in the browser | No suggested action on these rows (they are below the 60 % the analysis used); do not mention one |

### Scene 5: Gemba Kaizen (01:54–02:44)

| Shot | Time | Dur | Objective | Page / element | Actions | On-screen result | Voiceover | Text / callout | Camera | Transition | Evidence | Risks |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 5.1 | 01:54–01:58 | 4 s | Hand-off to the second agent | Top bar → **Gemba Kaizen** | Click | Summary "…significant transportation waste, accounting for 52% of the observed time… No safety violations were observed."; "0 approved · 2 open" | "The Gemba Kaizen agent turns the measurements into improvement proposals." | — | APP, full window | Hard cut | Gemini summary | — |
| 5.2 | 01:58–02:16 | 18 s | The transport card | Card K01 *Implement material delivery system* | Hover Observed → click evidence chip **00:02–00:18** (mini player) → click **00:30–00:40** → hover Recommendation → hover **KC-TRN-01** | Mini player shows the cart being pushed | "The top card is transport: twenty-six seconds of moving the cart, with both moments in the video as evidence. It recommends a water spider or a flow rack, and cites the lean practice behind it." | Callout on KC-TRN-01: "Ohno, Toyota Production System · Liker, The Toyota Way" | APP, 140 % on K01 | Hard cut | Cached K01 | Evidence chips seek the video but may leave it paused; press play on the mini player |
| 5.3 | 02:16–02:26 | 10 s | Who computes what | K01 ROI line | Hold | "0.67 h per shift · +9.1% throughput · 20 s/cycle x 120 cycles/shift (computed from the measured times, not by the LLM)" | "Gemini estimates how many seconds that can remove. The hours per shift and the throughput gain are plain arithmetic in code." | Two labels: "20 s: Gemini's estimate" · "0.67 h, +9.1 %: code" | APP, 170 % on the ROI line | Hard cut | `lss_agent.py` step 4; `est_seconds_saved_per_cycle` = 20 | 120 cycles/shift comes from the nominal 240 s cycle the team entered; do not read the numbers aloud |
| 5.4 | 02:26–02:35 | 9 s | Uncertainty becomes a question | **Ask the operator** | Hover the 00:30 question | "I noticed you moving the mobile workstation at 00:30. Is this movement required for every assembly, or could the parts be staged closer?" | "And where the agent is unsure, it asks the operator instead of guessing: is this move needed every cycle?" | — | APP, 150 % | Hard cut | Cached question | Text only; nothing is sent to anyone |
| 5.5 | 02:35–02:44 | 9 s | Human decision | K01 → **Approve**, K02 → **Approve** | Click both | "2 approved · 0 deferred · 0 rejected · 0 open · 0.7 h per shift approved" | "The manager approves, defers, or rejects each card." | — | APP, full window, then 130 % on the counter | Dip to MG | Verified; stored in the browser | Do not call it saved or sent |

### Scene 6: How it works (02:44–03:15)

| Shot | Time | Dur | Objective | Page / element | Actions | On-screen result | Voiceover | Text / callout | Camera | Transition | Evidence | Risks |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 6.1 | 02:44–02:54 | 10 s | Serving layer | — | — | Browser → SvelteKit dashboard → FastAPI service → "1 frame / 2 s" | "Under the hood, a SvelteKit dashboard talks to a FastAPI service. It samples one frame every two seconds." | Box labels only | MG, dark grid in the app's style | Builds per sentence | `server.py`; `sample_fps` 0.5 | Do not draw Cloud Run unless it is deployed |
| 6.2 | 02:54–03:05 | 11 s | Perception | — | — | Frame → **Gemini 3.1 Flash-Lite** (rule scores + activity) and **YOLOv8n** (people count) → Python engine | "Gemini 3.1 Flash-Lite checks every rule on every frame and labels what the worker is doing, and a small YOLO model counts people. Plain code then measures the waste." | Small: "Gemini API" under the Gemini box | MG | — | `vlm_action_model.py`, `person_count_model.py`, `lss_agent.py` §1 | — |
| 6.3 | 03:05–03:15 | 10 s | Reasoning | — | — | Measurements + "19 knowledge cards" → **Gemini** → JSON card (observation, root_cause, recommendation, evidence, kb_card_ids) | "Finally, Gemini writes the Kaizen cards as structured data, grounded in nineteen curated lean and ergonomics cards." | — | MG | Dip to card | `lss_agent.py`, `knowledge/lss_cards.json` | Do not show Vertex AI, RAG Engine, Firestore, BigQuery as current |

### Scene 7: Limits and close (03:15–03:35)

| Shot | Time | Dur | Objective | Page / element | Actions | On-screen result | Voiceover | Text / callout | Camera | Transition | Evidence | Risks |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 7.1 | 03:15–03:27 | 12 s | Honest limits | `/dashboard` still, dimmed 30 % | — | Two lines appear one by one | "This is a prototype. It analyses recorded clips, not live streams yet. Gemini can mislabel what it sees, so every finding links back to the video for a person to check." | "Recorded clips, not live streams yet" · "Labels can be wrong → human review" | CARD over APP still | Cross-dissolve | Audit | — |
| 7.2 | 03:27–03:35 | 8 s | Close | — | — | VALZ wordmark, "Observe → Understand → Improve", Team TuiDui: Ratchanon Buachum, Sawit Koseeyaumporn, Wayu Tharai. Footer "Video: CarDA dataset, CC BY 4.0" | "VALZ. Observe. Understand. Improve." | As described | CARD, cover-slide style | Fade to black | — | Keep the CarDA credit |

## The boxed video

The clip ships with a pre-made copy that has person boxes drawn by the backend (`ws10-car-door-2024-04-23.annotated.mp4`, from
`POST /safety/annotate` with `gemini-3.1-flash-lite`, the 4 default rules, 0.5 fps, near-miss margin 0.15). Opening the clip shows it
by default; the Video page's **Annotated video** panel has **Original / Boxes** and says "cached with the demo clip, drawn with the default rules".
YOLO boxes the operator on almost every frame (1,437 of 1,492). Without a rule hit, the box carries Gemini's activity label:
blue "carrying - transport waste" while the cart is pushed, green "working - value-adding" at the door, blue "walking - motion waste".
At 00:18–00:20 the amber "NEAR MISS: awkward_posture 0.50" box and banner take over. No red boxes. The hook (shot 1.1) on **Boxes**
shows the transport-waste label live, which supports the first sentence. A few frames have no box where the door hides the operator.
After the threshold change in shot 3.3 the panel warns that the boxes were drawn with other rules; that is expected.

## Shots that must not be recorded as working

| Interaction | Why |
|---|---|
| **Upload** + **Analyse video** | Works locally with the Gemini key (verified through `pnpm demo:add`, same endpoint), but the dashboard uploads at 1 fps: about 62 model calls, roughly 5 minutes on the free-tier quota. Record only per the optional swap below |
| **Voice Agent** page | UNVERIFIED — DO NOT RECORD AS FUNCTIONAL. Speech is ElevenLabs, not Google, and the chat was not tested |
| **Draw boxes on the video** (a new run) | Verified once from the dashboard against the local backend (4:00 at 1 fps, same 00:18 near miss), but the result is lost on page reload. Show the cached boxed copy instead |
| **Live** tab | Simulation by design; the app says so |
| The older clip *WS10 car door assembly (in camera, L view)* | Analysed by Qwen, and its MP4 has burned-in "VIOLATION: no_helmet" boxes. Remove it from the list before recording (runbook §2) |
| *Assembly cell 3 (synthetic sample)* | Authored cards, not model output |

## Optional swap: a real upload

Only after runbook §5 passes on the recording machine. Replace shot 3.1 with: **Upload** → choose `ws10-car-door-2024-04-23.mp4` →
*Cycle time (s)* `240` → **Analyse video** → the top-bar chip "Analysing … Ns" counts up. Show the first and last 3 s with an on-screen
"≈ 5 min on a free-tier quota, shortened" label, then the status line "Analysed with gemini-3.1-flash-lite … ". Use the alternate scene 3 line.
A fresh run gives different scores, so re-check every number in scenes 3–5 against what the run shows.
