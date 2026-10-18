# VALZ narration script

English voiceover for the 3:35 AI Builder Cup video. Every sentence matches a shot in [DEMO_STORYBOARD.md](DEMO_STORYBOARD.md) and
a feature marked verified in [DEMO_AUDIT.md](DEMO_AUDIT.md). Written to be spoken by a person at a calm pace (about 145 words a minute);
the ElevenLabs track is a guide for timing only.

Source of every fact: the cached analysis `frontend/static/demo/ws10-car-door-2024-04-23.analysis.json`, made on 18 Oct 2026 by
`gemini-3.1-flash-lite` through the Gemini API (Google AI Studio key) for both the Safety Agent and the Gemba Kaizen Agent.
If the clip is re-analysed, re-check every number below.

**Hosting line (scene 6):** the default says nothing about where it is hosted. Use the Cloud Run alternate only once the deployment exists.

## 1. Clean narration (paste into ElevenLabs)

---

This is a real car door assembly station. VALZ watched fifty seconds of ordinary camera footage. More than half of the operator's time went into moving the cart and materials, not assembling. So it proposed a fix: bring the parts to the operator, with a water spider or a flow rack.

Most factories already have cameras. But the footage is usually reviewed only after something goes wrong. Wasted motion and strain are rarely written down, because no one has time to watch every cycle. VALZ is built for that gap. Existing cameras. Actionable intelligence.

We start with a fifty-second clip from a public car door assembly dataset. We analysed it earlier with Gemini, and the app says so: cached, no model called now. Safety rules are written in plain English. For every sampled frame, Gemini scores each rule from zero to one hundred. Here, no rule crossed its threshold, and VALZ says that plainly. A safety lead can tune the policy. Lower awkward posture to forty percent, and four near misses appear, straight from the scores already stored.

The timeline shows every rule against every sampled second. The near misses sit where the operator fits parts into the door. One click plays that exact moment. Each one keeps a snapshot and the model's score. These are near misses, not violations, so a person reviews them. VALZ does not close anything on its own.

The Gemba Kaizen agent turns the measurements into improvement proposals. The top card is transport: twenty-six seconds of moving the cart, with both moments in the video as evidence. It recommends a water spider or a flow rack, and cites the lean practice behind it. Gemini estimates how many seconds that can remove. The hours per shift and the throughput gain are plain arithmetic in code. And where the agent is unsure, it asks the operator instead of guessing: is this move needed every cycle? The manager approves, defers, or rejects each card.

Under the hood, a SvelteKit dashboard talks to a FastAPI service. It samples one frame every two seconds. Gemini 3.1 Flash-Lite checks every rule on every frame and labels what the worker is doing, and a small YOLO model counts people. Plain code then measures the waste. Finally, Gemini writes the Kaizen cards as structured data, grounded in nineteen curated lean and ergonomics cards.

This is a prototype. It analyses recorded clips, not live streams yet. Gemini can mislabel what it sees, so every finding links back to the video for a person to check. VALZ. Observe. Understand. Improve.

---

## 2. Scene by scene

Speech time at about 145 words a minute; the slot adds room for clicks and pauses.

| # | Scene | Slot | Words | Speech | Spare |
|---|---|---|---|---|---|
| 1 | Hook | 00:00–00:21 (21 s) | 51 | 21.1 s | −0.1 s, start the voice at 00:00.3 |
| 2 | Problem | 00:21–00:39 (18 s) | 43 | 17.8 s | 0.2 s |
| 3 | Input and rules | 00:39–01:23 (44 s) | 84 | 34.8 s | 9.2 s |
| 4 | Near misses | 01:23–01:54 (31 s) | 55 | 22.8 s | 8.2 s |
| 5 | Gemba Kaizen | 01:54–02:44 (50 s) | 93 | 38.5 s | 11.5 s |
| 6 | How it works | 02:44–03:15 (31 s) | 64 | 26.5 s | 4.5 s |
| 7 | Limits and close | 03:15–03:35 (20 s) | 35 | 14.5 s | 5.5 s |
| | **Total** | **3:35** | **425** | **≈ 2:56** | **≈ 39 s** |

Re-count after any edit: words ÷ 2.42 = seconds at 145 words a minute.

### Scene 1 — Hook (00:00–00:21)

> This is a real car door assembly station. VALZ watched fifty seconds of ordinary camera footage. More than half of the operator's time went into moving the cart and materials, not assembling. So it proposed a fix: bring the parts to the operator, with a water spider or a flow rack.

Facts: Dashboard "44 % … value-adding", transport 26 s of 50 s (52 %), walking 2 s; card K01 recommendation "Introduce a water spider or flow rack system…".

### Scene 2 — Problem (00:21–00:39)

> Most factories already have cameras. But the footage is usually reviewed only after something goes wrong. Wasted motion and strain are rarely written down, because no one has time to watch every cycle. VALZ is built for that gap. Existing cameras. Actionable intelligence.

No statistics on purpose: the repository has no sourced industry number.

### Scene 3 — Input and rules (00:39–01:23)

> We start with a fifty-second clip from a public car door assembly dataset. We analysed it earlier with Gemini, and the app says so: cached, no model called now. Safety rules are written in plain English. For every sampled frame, Gemini scores each rule from zero to one hundred. Here, no rule crossed its threshold, and VALZ says that plainly. A safety lead can tune the policy. Lower awkward posture to forty percent, and four near misses appear, straight from the scores already stored.

Facts: clip list note "Analysed 2026-10-18 with gemini-3.1-flash-lite, 0.5 fps"; status "Cached analysis loaded. No model was called.";
Incidents panel "No rule reached its threshold in this video. Lower a threshold above to see near misses."; threshold 40 % → "4 found".

Alternate, **only if a fresh upload is recorded** (runbook §5): replace the second sentence with
"We upload it, and Gemini analyses it on the server. That takes about two minutes on our free-tier quota; we've shortened the wait."

### Scene 4 — Near misses (01:23–01:54)

> The timeline shows every rule against every sampled second. The near misses sit where the operator fits parts into the door. One click plays that exact moment. Each one keeps a snapshot and the model's score. These are near misses, not violations, so a person reviews them. VALZ does not close anything on its own.

Facts: incidents 00:18–00:22 (50 %, 2 frames), 00:24–00:28, 00:30–00:32, 00:42–00:44 (40 %); activity "working" at 18–28 s and 40–48 s.

### Scene 5 — Gemba Kaizen (01:54–02:44)

> The Gemba Kaizen agent turns the measurements into improvement proposals. The top card is transport: twenty-six seconds of moving the cart, with both moments in the video as evidence. It recommends a water spider or a flow rack, and cites the lean practice behind it. Gemini estimates how many seconds that can remove. The hours per shift and the throughput gain are plain arithmetic in code. And where the agent is unsure, it asks the operator instead of guessing: is this move needed every cycle? The manager approves, defers, or rejects each card.

Facts: K01 evidence 00:02–00:18 and 00:30–00:40, KC-TRN-01 (Ohno; Liker); ROI line "0.67 h per shift · +9.1% throughput · 20 s/cycle x 120 cycles/shift
(computed from the measured times, not by the LLM)". The 20 s is Gemini's estimate (`est_seconds_saved_per_cycle`); 120 cycles comes from the nominal
240 s cycle the team entered. The narration does not read these numbers aloud.

### Scene 6 — How it works (02:44–03:15)

> Under the hood, a SvelteKit dashboard talks to a FastAPI service. It samples one frame every two seconds. Gemini 3.1 Flash-Lite checks every rule on every frame and labels what the worker is doing, and a small YOLO model counts people. Plain code then measures the waste. Finally, Gemini writes the Kaizen cards as structured data, grounded in nineteen curated lean and ergonomics cards.

| Condition | Replace | With |
|---|---|---|
| Frontend and API are deployed on Cloud Run and the video shows that deployment | "a SvelteKit dashboard talks to a FastAPI service." | "a SvelteKit dashboard and a FastAPI service run on Cloud Run." |

### Scene 7 — Limits and close (03:15–03:35)

> This is a prototype. It analyses recorded clips, not live streams yet. Gemini can mislabel what it sees, so every finding links back to the video for a person to check. VALZ. Observe. Understand. Improve.

## 3. Pronunciation

Confirm the first two with the team; nothing in the repository says how they are pronounced.

| Term | Say | Note |
|---|---|---|
| VALZ | **VALZ**, one syllable, rhymes with "pals" | Team to confirm |
| TuiDui | **TOO-ee DOO-ee** | Team to confirm. Not spoken in the script |
| Gemba | **GEM-bah** | Hard G |
| Kaizen | **KYE-zen** | |
| Gemini | **JEM-in-eye** | |
| Flash-Lite | **flash light** | |
| water spider | as written | Lean term: a person who delivers material to the line |
| YOLO | **YO-low** | |
| SvelteKit | **SVELT-kit** | |
| FastAPI | **fast A-P-I** | |
| Takt, Muda, DMAIC | — | Not in the script. DMAIC is not implemented, so do not say it |

## 4. Pauses and emphasis (human read only)

`/` short pause · `//` long pause · **bold** stress · `[click]` the action the line waits for.

1. This is a **real** car door assembly station. / VALZ watched **fifty seconds** of ordinary camera footage. // **More than half** of the operator's time / went into moving the cart and materials, / **not** assembling. // So it proposed a fix: / bring the **parts** to the **operator**, / with a water spider / or a flow rack.
2. Most factories **already** have cameras. / But the footage is usually reviewed only **after** something goes wrong. // Wasted motion and strain are rarely written down, / because no one has time to watch **every** cycle. // VALZ is built for that gap. // *Existing cameras.* / *Actionable intelligence.*
3. We start with a fifty-second clip / from a public car door assembly dataset. / We analysed it earlier with **Gemini**, / and the app **says so**: / cached, / no model called now. // Safety rules are written in **plain English**. / For every sampled frame, / Gemini scores each rule / from zero to one hundred. // Here, **no** rule crossed its threshold, / and VALZ says that **plainly**. // A safety lead can tune the policy. / Lower awkward posture to **forty** percent, `[click]` / and **four** near misses appear, / straight from the scores already stored.
4. The timeline shows every rule / against every sampled second. / The near misses sit where the operator **fits parts** into the door. // One click `[click]` / plays that **exact** moment. // Each one keeps a **snapshot** / and the model's score. // These are near misses, / **not** violations, / so a **person** reviews them. `[click]` / VALZ does not close anything on its own.
5. The Gemba Kaizen agent turns the measurements into **improvement proposals**. // The top card is **transport**: / twenty-six seconds of moving the cart, / with **both** moments in the video as evidence. / It recommends a water spider or a flow rack, / and **cites** the lean practice behind it. // Gemini **estimates** how many seconds that can remove. / The hours per shift and the throughput gain / are **plain arithmetic** in code. // And where the agent is **unsure**, / it **asks** the operator / instead of guessing: / is this move needed every cycle? // The manager approves, `[click]` / defers, / or rejects each card.
6. Under the hood, / a SvelteKit dashboard talks to a FastAPI service. / It samples one frame every **two seconds**. / **Gemini** 3.1 Flash-Lite checks every rule on every frame / and labels what the worker is doing, / and a small YOLO model counts people. // **Plain code** then measures the waste. // Finally, / Gemini writes the Kaizen cards as structured data, / grounded in nineteen curated lean and ergonomics cards.
7. This is a **prototype**. / It analyses recorded clips, / not live streams yet. / Gemini can **mislabel** what it sees, / so every finding links back to the video / for a person to check. // VALZ. // Observe. / Understand. / Improve.

## 5. Timing reconciliation

| Slot | Speech | UI or graphic time the line waits on | Fits? |
|---|---|---|---|
| 00:00–00:21 | 21.1 s | Video 00:02–00:12 (cart push) → Dashboard 44 % → K01; no clicks | Yes, tight |
| 00:21–00:39 | 17.8 s | Motion graphic, tagline card | Yes |
| 00:39–01:23 | 34.8 s | Open clip (2 s), cut to Safety (1 s), hold on "No rule reached…" (2 s), drag slider (2 s), count change (1 s) | Yes, 9 s spare |
| 01:23–01:54 | 22.8 s | Matrix zoom (3 s), Play (1 s) + 3 s of video, Mark reviewed (1 s) | Yes, 8 s spare |
| 01:54–02:44 | 38.5 s | Tab click (1 s), two evidence chips (2 s), ROI line zoom (2 s), question (2 s), Approve ×2 (2 s) | Yes, 11 s spare |
| 02:44–03:15 | 26.5 s | Diagram builds per sentence | Yes |
| 03:15–03:35 | 14.5 s | End card, 4 s silent hold | Yes |
| **Total** | **≈ 2:56** | **≈ 39 s non-speech** | **3:35** |

If the human read runs long, cut in this order: scene 2 "VALZ is built for that gap." (−1.5 s); scene 4 "One click plays that exact
moment." (−2 s, keep the click); scene 6 ", and a small YOLO model counts people" (−2 s).
