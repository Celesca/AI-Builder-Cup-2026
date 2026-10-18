# VALZ recording runbook

Exact steps to reproduce the demo in [DEMO_STORYBOARD.md](DEMO_STORYBOARD.md). Steps 1–4 and 6–9 need no backend and no API key:
the demo clip carries its cached Gemini analysis. Step 5 is only for re-analysing or for the optional live upload shot.

## 1. Machine setup

```bash
cd frontend
corepack enable          # or: npx -y pnpm@10 ...
pnpm install
pnpm run dev             # http://localhost:5173
```

- Record from `http://localhost:5173`, or from the deployed URL once it serves this build. The public `gemba.limitlesstech-co.com`
  returned 502 on 18 Oct 2026.
- Browser: Chrome, a **fresh profile** with no extensions (the app restores the last opened clip, so an old profile can open the wrong
  one), bookmarks bar hidden, window **1920×1080** full screen (macOS: View → Enter Full Screen; ⌘⇧F hides the toolbar). Page zoom
  **125 %** (⌘+ twice from 100 %), which lays the app out at 1536×864. This layout was checked on the Video, Safety, Gemba Kaizen and
  Dashboard pages.
- macOS: Do Not Disturb on, Dock hidden, cursor one size larger (Accessibility → Display → Pointer).
- Capture: OBS or ScreenFlow at 1920×1080, 60 fps, constant frame rate, cursor visible, click highlight off (add emphasis in the edit).

## 2. Demo data

The clip and its analysis are in `frontend/static/demo/`:

| File | What it is |
|---|---|
| `ws10-car-door-2024-04-23.mp4` | CarDA WS10, camera SN22106779, 23 Apr 2024 13:53, L view, 49.7 s, re-encoded to H.264 (CRF 23, no audio) from `WS10-SN22106779-HD720dt__23_04_2024_13_53_19_4.0m_cropped_L_view_RAW.mp4` |
| `ws10-car-door-2024-04-23.analysis.json` | Gemini analysis, 18 Oct 2026: `gemini-3.1-flash-lite` for both agents, 0.5 fps, 4 default rules, station WS10, nominal cycle 240 s |
| `manifest.json` | The clip is listed first |

Before recording, **remove the old clip from `manifest.json`**: the entry with `"id": "xsens-004-ws10-in-l"`. Its MP4 has burned-in
"VIOLATION: no_helmet" boxes and its analysis was made by Qwen. Removing the entry is enough; delete its two files only if the team agrees.
The raw `WS10-…_RAW.mp4` (41 MB, MPEG-4 Part 2, which browsers play poorly) is not used by the app and should not be committed.

## 3. Reset the app state before every take

Threshold changes, review marks and approvals persist in the browser. In DevTools → Console on the app:

```js
localStorage.removeItem('valz-rules-v1'); localStorage.removeItem('valz-marks-v1'); location.reload();
```

Expected after reset, with the clip open: Safety Incidents panel "No rule reached its threshold in this video…", Gemba Kaizen
"0 approved · 0 deferred · 0 rejected · 2 open". Top-bar **Report** on **Report: English**.

## 4. Pre-set states for the hook (scene 1)

Record the hook last, from its own takes:

- Shot 1.1: `/video` → **Demo clips** → **Open** on *WS10 car door assembly (CarDA, 23 Apr 2024, L view)*. Seek the main player to 00:02,
  pause. Start recording, press play.
- Shot 1.2: `/dashboard`, top of the page (headline and *Where the time went*). Do this before any threshold change, so the
  near-miss card does not show.
- Shot 1.3: `/lss`, scrolled so card K01 is centred.

## 5. Re-analysing or a live upload (optional)

Verified on 18 Oct 2026 on this Mac, outside Docker, with the Gemini API key:

```bash
# ai_backend/.env (git-ignored): already set
#   OPENROUTER_URL=https://generativelanguage.googleapis.com/v1beta/openai/chat/completions
#   OPENROUTER_API_KEY=<the AI Studio key>      VLM_MODEL=gemini-3.1-flash-lite      LSS_LLM_MODEL=gemini-3.1-flash-lite
#   LLM_MIN_INTERVAL_S=4.5                       (spaces requests: 15 per minute on the free tier)
cd ai_backend
uv venv --python 3.13 .venv && uv pip install -r requirements.txt
.venv/bin/python server.py --port 8010          # 8000 was taken on this Mac by another program

cd ../frontend
pnpm demo:add <clip.mp4> --title "WS10 car door assembly (CarDA, 23 Apr 2024, L view)" --id ws10-car-door-2024-04-23 \
  --station WS10 --cycle-time 240 --sample-fps 0.5 --backend http://127.0.0.1:8010
```

- At 0.5 fps the run makes about 31 model calls and took **2:18**. The dashboard's own **Upload → Analyse video** always uses 1 fps
  (about 62 calls, roughly 5 minutes with the spacer).
- Model output changes from run to run. After any re-analysis, re-check every number in the storyboard and the script: 25 frames,
  0 incidents at 60 %, 4 near misses at 40 % (strongest 00:18–00:22, 50 %), transport 26 s / 52 %, K01 text, 0.67 h, +9.1 %, the 00:30 question.
- `gemini-3.7-flash` and `gemini-3.8-flash` were not usable on this key (5 requests per minute; 3.8 has no quota). 3.7 also needs
  a client change for its thinking output.
- For the live upload shot, point the dashboard at the backend: Video page → **AI backend** → *Backend address* `http://127.0.0.1:8010` → **Use**
  (only while `ALLOW_BACKEND_OVERRIDE=true`), or start the frontend with `AI_BACKEND_URL=http://127.0.0.1:8010`.

## 6. Recording order

Record the app in long continuous takes, one per page, and cut later. Run step 3 between takes.

| Take | Covers shots | Page | Notes |
|---|---|---|---|
| A | 3.1 | `/video` | Fresh tab after reset, nothing loaded. Hover the first row's note, click **Open** |
| B | 3.2, 3.3, 4.1–4.3 | `/safety` | One take: hover the awkward-posture prompt → hold on "No rule reached…" → drag that rule's **Threshold** to 40 % → hover the matrix row → scroll → **Play** on 00:18–00:22 (press play on the mini player if it opens paused) → **Mark reviewed** |
| C | 5.1–5.5 | `/lss` | Click **Gemba Kaizen** → K01 evidence chips **00:02–00:18**, **00:30–00:40** → hold on the ROI line → **Ask the operator** → **Approve** K01, **Approve** K02 |
| D | 1.1–1.3 | all | Hook shots from step 4 |
| E | 7.1 still | `/dashboard` | One clean screenshot after take C |
| F | backups | all | Repeat A–C at a slower pace; 10 s of each page with no cursor for cutaways |

## 7. Mouse and pacing

- Move the cursor in one straight, unhurried line to each control, rest 0.5 s, then click.
- After each click, keep the cursor still for at least 1 s.
- Drag the threshold slider in one smooth motion; it moves in 5 % steps.
- Scroll with a trackpad in one smooth stroke. Leave 2 s of still frame at the start and end of every take.

## 8. Edit guidance

- **Keep the real UI visible** for every claim: the clip note naming `gemini-3.1-flash-lite`, "Cached analysis loaded. No model was called.",
  "No rule reached its threshold…", the incidents count changing to 4, the mini player, K01, the ROI line, the Approve counter.
- Zoom with a 0.4 s ease, maximum 170 %. Never zoom while the cursor moves.
- Highlights: a 2 px rounded outline in the app's blue with the rest dimmed by 30 %, on for 1.5–2 s. One callout at a time, lower third.
- Motion graphics only in scenes 2 and 6 and the end card. Flat 2D on the app's grid background.
- Never speed up a wait without saying so on screen.
- Music low and steady, ducked 12 dB under the voice; final mix −14 LUFS.
- Credit "Video: CarDA dataset (CC BY 4.0)" in shot 1.1, on the end card and in the video description.
- Do not show: the old Qwen clip, the Voice Agent page, the synthetic clip, the **Live** tab, the "4.5 h of every 8 h shift" line, or
  the full Google Cloud target diagram as the current system.

## 9. Final checks before export

- [ ] Only the Gemini clip appears in the Demo clips list (or the old one is out of frame).
- [ ] Every number read aloud is on screen in the same shot: fifty seconds, "more than half" (52 % transport), forty percent, four near misses, twenty-six seconds.
- [ ] "cached" is spoken and visible in scene 3.
- [ ] Near misses are never called violations.
- [ ] The scene 6 hosting line matches what is actually deployed.
- [ ] Length between 3:00 and 4:00; target 3:35.
- [ ] Watched once at phone size: callouts readable.
- [ ] The prototype linked in the submission opens and serves the same clip.
- [ ] Captions (.srt) from the final narration, checked for "VALZ", "Gemba Kaizen", "Gemini".
