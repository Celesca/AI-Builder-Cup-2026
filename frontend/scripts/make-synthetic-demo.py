"""
Build the bundled SYNTHETIC demo: an animated workstation clip plus a cached analysis in the exact shape of
ai_backend's POST /analysis/analyze/upload response, so the dashboard works with no API key.

  ai_backend/.venv/bin/python frontend/scripts/make-synthetic-demo.py

Outputs (frontend/static/demo/): cell3-synthetic.mp4, cell3-synthetic.analysis.json, manifest.json (merged).

Nothing here is real footage or a real model run. The scenario is scripted (see SCENARIO) and the analysis is
computed from it with the backend's own functions (segments, events, metrics, ROI, knowledge-card retrieval), so the
numbers are arithmetic on the scripted timeline, and the Gemba Kaizen texts are authored. The JSON carries
"demo": {"synthetic": true} and the UI labels it as a cached demo result.
"""

import base64
import json
import math
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ai_backend"))

from lss_agent import LssAgent, StationContext, compute_metrics, compute_roi  # noqa: E402
from safety_agent import (  # noqa: E402
    ACTIVITY_CLASSES, FrameObservation, SafetyRule, build_activity_segments, build_safety_events, smooth_labels,
    summarize_activity,
)

OUT = ROOT / "frontend" / "static" / "demo"

CLIP_ID = "cell3-synthetic"
W, H, VIDEO_FPS, DURATION = 640, 360, 10, 72

# ---- scripted scenario (seconds) -------------------------------------------------------------------------------
# activity per second; hard hat is off from 16 s to 21 s; running from 66 s to 69 s; the worker leaves at 71 s
def activity_at(t: int) -> str:
    if t >= 71:
        return "no_person"
    if 64 <= t < 71:
        return "walking"
    if 52 <= t < 64:
        return "working"
    if 34 <= t < 52:
        return "waiting"
    if 18 <= t < 34:
        return "working"
    if 14 <= t < 18:
        return "reaching"
    return "working"


HAT_OFF = (16, 21)
RUNNING = (66, 69)
# One source of truth with the dashboard and `pnpm demo:add`
RULES = [SafetyRule(r["id"], r["prompt"], r["severity"], r["threshold"])
         for r in json.loads((ROOT / "frontend" / "src" / "lib" / "default-rules.json").read_text()) if r["enabled"]]


def rule_confidences(t: int) -> dict:
    """Per-frame P(violation) as a vision model might report it: clear hits, a ramp either side, and one false alarm."""
    c = {r.id: 0.04 + 0.02 * ((t * 7) % 3) for r in RULES}
    hat = {15: 0.42, 16: 0.88, 17: 0.93, 18: 0.9, 19: 0.91, 20: 0.86, 21: 0.48}
    run = {65: 0.38, 66: 0.82, 67: 0.9, 68: 0.85, 69: 0.44}
    lift = {14: 0.41, 15: 0.66, 16: 0.71, 17: 0.52}
    c["helmet"] = hat.get(t, c["helmet"])
    c["running"] = run.get(t, c["running"])
    c["lifting"] = lift.get(t, c["lifting"])
    c["gloves"] = 0.64 if t == 27 else (0.31 + 0.03 * (t % 4) if 18 <= t < 34 else c["gloves"])  # one-frame false alarm
    return {k: round(v, 4) for k, v in c.items()}


def activity_confidence(t: int) -> float:
    return 0.35 if t in (13, 52) else round(0.82 + 0.02 * ((t * 5) % 7), 3)  # two unclear frames


# ---- drawing ---------------------------------------------------------------------------------------------------
def lerp(a, b, k):
    return a + (b - a) * k


def draw_frame(t10: int) -> np.ndarray:
    """Frame for time t10 / 10 seconds."""
    t = t10 / VIDEO_FPS
    img = np.full((H, W, 3), (232, 228, 222), np.uint8)
    cv2.rectangle(img, (0, 290), (W, H), (168, 164, 158), -1)          # floor
    cv2.rectangle(img, (0, 40), (W, 52), (200, 196, 190), -1)           # wall rail
    cv2.rectangle(img, (150, 232), (470, 252), (60, 66, 74), -1)        # bench top
    cv2.rectangle(img, (160, 252), (172, 292), (60, 66, 74), -1)
    cv2.rectangle(img, (448, 252), (460, 292), (60, 66, 74), -1)
    cv2.rectangle(img, (290, 212), (340, 232), (180, 120, 40), -1)      # fixture with the part
    cv2.rectangle(img, (170, 208), (214, 232), (110, 140, 90), -1)      # bin A (near)
    cv2.rectangle(img, (548, 208), (610, 292), (110, 140, 90), -1)      # bin B (far right, on a stand)
    cv2.putText(img, "BIN B", (556, 200), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (70, 90, 60), 1, cv2.LINE_AA)
    cv2.rectangle(img, (0, 262), (130, 282), (120, 124, 130), -1)       # upstream conveyor
    s = int(t)
    if activity_at(min(s, 70)) != "waiting":                             # parts only arrive when the line feeds
        for k in range(2):
            x = int((t * 40 + k * 60) % 120)
            cv2.rectangle(img, (x, 246), (x + 18, 262), (180, 120, 40), -1)

    act = activity_at(min(s, 70))
    x_base = 310
    if t >= 64:                                                          # walk to the right, run 66-69
        speed = 70 if RUNNING[0] <= t < RUNNING[1] else 28
        x_base = int(310 + (t - 64) * speed + (RUNNING[0] <= t) * 0)
    if t >= 71 or x_base > W + 40:
        pass
    else:
        stride = math.sin(t * (14 if RUNNING[0] <= t < RUNNING[1] else 7))
        walking = t >= 64
        lean = 0
        arm_r = (x_base + 28, 214)
        arm_l = (x_base - 28, 214)
        if act == "working":
            wob = math.sin(t * 6) * 6
            arm_r = (x_base + 36, 228 + wob)
            arm_l = (x_base + 20, 230 - wob)
        elif act == "reaching":
            k = min(1.0, max(0.0, (t - 14) / 1.5)) if t < 16 else max(0.0, 1 - (t - 16.5) / 1.5)
            lean = int(24 * k)
            x_base = int(310 + 120 * k)                                  # steps toward the far bin
            arm_r = (lerp(x_base + 36, 556, k), lerp(228, 216, k))
            arm_l = (x_base + 20, 230)
        elif act == "waiting":
            arm_r = (x_base + 14, 232)
            arm_l = (x_base - 14, 232)
            lean = int(2 * math.sin(t * 1.4))
        elif walking:
            arm_r = (x_base + 12 + stride * 16, 220 + abs(stride) * 6)
            arm_l = (x_base - 12 - stride * 16, 220 + abs(stride) * 6)
        # legs
        spread = int(stride * 12) if walking else 0
        cv2.line(img, (x_base - 8, 258), (x_base - 12 - spread, 292), (40, 44, 52), 9)
        cv2.line(img, (x_base + 8, 258), (x_base + 12 + spread, 292), (40, 44, 52), 9)
        # torso (hi-vis vest) and head
        cv2.rectangle(img, (x_base - 20 + lean, 196), (x_base + 20 + lean, 262), (30, 140, 245), -1)
        cv2.rectangle(img, (x_base - 20 + lean, 220), (x_base + 20 + lean, 226), (240, 240, 240), -1)
        cv2.line(img, (x_base + lean, 204), (int(arm_r[0]), int(arm_r[1])), (120, 100, 90), 8)
        cv2.line(img, (x_base + lean, 204), (int(arm_l[0]), int(arm_l[1])), (120, 100, 90), 8)
        cv2.circle(img, (x_base + lean, 176), 17, (150, 175, 215), -1)
        hat_on = not (HAT_OFF[0] <= t < HAT_OFF[1])
        if hat_on:
            cv2.ellipse(img, (x_base + lean, 170), (20, 14), 0, 180, 360, (0, 200, 255), -1)
            cv2.rectangle(img, (x_base - 22 + lean, 168), (x_base + 22 + lean, 173), (0, 170, 220), -1)
        else:
            cv2.ellipse(img, (232, 228), (16, 9), 0, 180, 360, (0, 200, 255), -1)   # hat left on the bench
    # overlays
    cv2.rectangle(img, (0, 0), (W, 26), (30, 30, 30), -1)
    cv2.putText(img, "SYNTHETIC DEMO - NOT REAL FOOTAGE", (10, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 180, 255), 1, cv2.LINE_AA)
    cv2.putText(img, "CELL 3   %02d:%02d" % (int(t) // 60, int(t) % 60), (W - 150, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (235, 235, 235), 1, cv2.LINE_AA)
    return img


def render_video(path: Path):
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(VIDEO_FPS),
           "-i", "-", "-c:v", "libx264", "-preset", "slow", "-crf", "30", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(DURATION * VIDEO_FPS):
        proc.stdin.write(draw_frame(i).tobytes())
    proc.stdin.close()
    proc.wait()


def snapshot(t: float) -> str:
    img = draw_frame(int(round(t * VIDEO_FPS)))
    img = cv2.resize(img, (360, 203), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()


# ---- analysis ----------------------------------------------------------------------------------------------------
CAT = {c.key: c.category for c in ACTIVITY_CLASSES}
CAT["uncertain"] = "UNCERTAIN"
DESCRIBE = {
    "working": "The operator works at the fixture, placing a part with both hands.",
    "reaching": "The operator leans to the right and reaches across to the far parts bin.",
    "waiting": "The operator stands idle at the bench with arms down while the conveyor is empty.",
    "walking": "The operator walks away from the workstation toward the right of the frame.",
}


def build_safety() -> dict:
    observations = []
    for t in range(DURATION):
        key = activity_at(t)
        conf = activity_confidence(t)
        observations.append(FrameObservation(
            timestamp=float(t), frame_idx=t * VIDEO_FPS, activity="uncertain" if (conf < 0.4 and key != "no_person") else key,
            category="UNCERTAIN" if (conf < 0.4 and key != "no_person") else CAT[key], activity_confidence=conf,
            rule_confidences=rule_confidences(t)))
    for obs, label in zip(observations, smooth_labels([o.activity for o in observations])):
        obs.activity, obs.category = label, CAT[label]
    segments = build_activity_segments(observations, 1.0)
    events = build_safety_events(observations, RULES, 1.0, 2.0)

    seg_dicts = []
    for s in segments:
        d = s.__dict__.copy()
        d["description"] = DESCRIBE.get(s.activity, "")
        d["snapshot"] = snapshot(s.key_timestamp) if s.duration >= 4 else None
        seg_dicts.append(d)
    ev_desc = {"helmet": "The operator works at the bench without a hard hat; it is lying on the bench.",
               "running": "The operator runs away from the workstation.",
               "lifting": "The operator bends deeply forward at the waist to reach the far bin.",
               "gloves": "The operator's hands appear bare while placing a part."}
    ev_dicts = []
    for e in events:
        d = e.__dict__.copy()
        d["description"] = ev_desc.get(e.rule_id, "")
        d["snapshot"] = snapshot(e.key_timestamp)
        ev_dicts.append(d)

    flagged = sum(1 for o in observations if any(o.rule_confidences[r.id] >= r.threshold for r in RULES))
    return {
        "job_id": "safety_demo_cell3", "video_path": f"{CLIP_ID}.mp4", "model": "cached demo (synthetic)",
        "timestamp": datetime(2026, 10, 16, 8, 0).isoformat(), "video_duration": float(DURATION), "sample_fps": 1.0,
        "vlm_usage": None,
        "rules": [r.__dict__.copy() for r in RULES],
        "stats": {"frames_analyzed": DURATION, "safety_events": len(events), "frames_with_violation": flagged,
                  "events_by_severity": {s: sum(1 for e in events if e.severity == s) for s in ("low", "medium", "high")}},
        "safety_events": ev_dicts,
        "activity": {
            "summary": summarize_activity(observations, 1.0), "segments": seg_dicts,
            "timeline": [{"timestamp": o.timestamp, "frame_idx": o.frame_idx, "activity": o.activity, "category": o.category,
                          "confidence": round(o.activity_confidence, 4), "rule_confidences": o.rule_confidences} for o in observations],
        },
    }


def build_person_count() -> dict:
    ts = [i * 0.5 for i in range(DURATION * 2)]
    counts = [0 if t >= 71 else 1 for t in ts]
    frames = [{"frame_idx": int(t * VIDEO_FPS), "timestamp": t, "person_count": c,
               "detections": [{"person_id": 0, "confidence": 0.9, "x1": 250, "y1": 160, "x2": 370, "y2": 292, "center_x": 310, "center_y": 226}] if c else []}
              for t, c in zip(ts, counts)]
    return {"job_id": "yolo_demo_cell3", "model": "yolov8n.pt (cached demo)", "timestamp": datetime(2026, 10, 16, 8, 0).isoformat(),
            "video_duration": float(DURATION),
            "statistics": {"frames_analyzed": len(ts), "frames_with_people": sum(counts), "max_persons": 1, "min_persons": 0,
                           "avg_persons": round(sum(counts) / len(counts), 3), "peak_timestamp": 0.0},
            "timeline": {"timestamps": ts, "counts": counts}, "frame_counts": frames}


def build_lss(safety: dict, person_count: dict) -> dict:
    ctx = StationContext(station_name="Assembly cell 3", process_description="Place the housing in the fixture and fasten four screws",
                         takt_time_s=60, cycle_time_s=72, shift_hours=8, operators=1, language="en")
    base = LssAgent(api_key="", knowledge=None).suggest(safety, person_count, ctx, use_llm=False)   # metrics, retrieval, ROI math
    metrics = base["metrics"]

    def card(i, title, category, priority, observation, evidence, root, rec, kb, secs, share, conf):
        c = {"id": f"K{i:02d}", "title": title, "category": category, "priority": priority, "observation": observation,
             "evidence": evidence, "root_cause": root, "recommendation": rec, "kb_card_ids": kb,
             "est_seconds_saved_per_cycle": secs, "waste_share_removed": share, "confidence": conf}
        c["roi"] = compute_roi(c, metrics, ctx)
        return c

    cards = [
        card(1, "Stop the 18 s starve at the fixture: balance the feed to takt", "NVA_WAITING", "high",
             "The operator stood idle for 18 s (00:34-00:52) with an empty conveyor. That wait alone puts the 72 s cycle 12 s over the 60 s takt.",
             [{"start_time": 34.0, "end_time": 52.0, "note": "idle, no part at the fixture"}],
             "The upstream station delivers late, so the operator is starved by the line rather than slow.",
             "Draw a Yamazumi chart for the two stations, move work from the upstream bottleneck to the one that waits, and add a kanban trigger so a part is staged two cycles before the conveyor runs empty.",
             ["KC-WAI-02", "KC-WAI-03"], 12.0, None, 0.78),
        card(2, "Bring bin B into the normal working area", "NVA_MOTION", "medium",
             "The operator leans and reaches across the bench to the far bin once per cycle (00:14-00:18, about 4 s).",
             [{"start_time": 14.0, "end_time": 18.0, "note": "reach to bin B"}],
             "Bin B sits outside forearm reach, on a stand to the right of the bench.",
             "Move bin B within forearm reach in the order of use, at elbow height, with a gravity-feed bin so the part is presented at the fixture.",
             ["KC-MOT-01", "KC-ERG-01"], 3.0, None, 0.7),
        card(3, "Standardize the post-cycle walk-out", "NVA_MOTION", "low",
             "The operator walks off at the end of the clip (01:04-01:11), including a run at 01:06-01:09.",
             [{"start_time": 64.0, "end_time": 72.0, "note": "leaves the workstation"}],
             "The reason for leaving is not visible: it may be material delivery or a break.",
             "Confirm with the operator why they left, then stage the missing item at the line side so the walk is not needed.",
             ["KC-MOT-02", "KC-GEN-01"], None, 0.3, 0.45),
    ]
    actions = [
        {"rule_id": "helmet", "severity": "high", "action": "Remind the operator at the shift-start check and keep spare hard hats at the cell entrance; use the camera alert as a reminder, not for discipline.", "kb_card_ids": ["KC-SAF-01"]},
        {"rule_id": "running", "severity": "medium", "action": "Find why the operator ran (a late part, a far andon call) and remove that reason; mark the walkway.", "kb_card_ids": ["KC-SAF-02"]},
        {"rule_id": "lifting", "severity": "medium", "action": "Raise bin B to between knee and shoulder height so the reach no longer needs a deep bend.", "kb_card_ids": ["KC-ERG-01"]},
    ]
    questions = [
        {"timestamp": 34.0, "question": "I saw an 18-second pause at 00:34. Were you waiting for a part from the upstream station?"},
        {"timestamp": 16.0, "question": "At 00:16 your hard hat was off. Did you take it off to reach bin B?"},
        {"timestamp": 64.0, "question": "You left the cell at 01:04. Were you going to fetch something?"},
    ]
    return {
        "job_id": "lss_demo_cell3", "timestamp": datetime(2026, 10, 16, 8, 0).isoformat(), "source": "llm", "model": "cached demo (authored)",
        "llm_error": None, "context": ctx.__dict__.copy() | {"notes": ""}, "metrics": metrics,
        "summary": (f"One 72 s cycle: {metrics['va_percent']:g}% of the time the operator is visible is value-adding. The 18 s wait for a part is the "
                    "largest waste and the whole overrun against the 60 s takt; two safety rules were broken (hard hat at 00:16, running at 01:06) and a "
                    "deep bend to the far bin was flagged."),
        "lss_cards": cards, "safety_actions": actions, "operator_questions": questions,
        "knowledge_cards_used": base["knowledge_cards_used"], "usage": None,
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    video = OUT / f"{CLIP_ID}.mp4"
    print("rendering", video)
    render_video(video)
    safety = build_safety()
    person = build_person_count()
    lss = build_lss(safety, person)
    result = {"success": True, "video_path": f"{CLIP_ID}.mp4", "safety": safety, "person_count": person,
              "person_count_error": None, "lss": lss,
              "demo": {"synthetic": True, "note": "Scripted scenario and authored Gemba Kaizen texts; metrics, ROI and knowledge-card retrieval use the backend's own functions."}}
    (OUT / f"{CLIP_ID}.analysis.json").write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    manifest_path = OUT / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"clips": []}
    entry = {"id": CLIP_ID, "title": "Assembly cell 3 (synthetic sample)", "video": f"/demo/{CLIP_ID}.mp4",
             "analysis": f"/demo/{CLIP_ID}.analysis.json", "duration": DURATION, "synthetic": True,
             "note": "Scripted animation with cached results. Add your own clips with `pnpm demo:add`."}
    manifest["clips"] = [c for c in manifest["clips"] if c["id"] != CLIP_ID] + [entry]
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print("events:", [(e["rule_id"], e["start_time"], e["end_time"]) for e in safety["safety_events"]])
    print("va%", safety["activity"]["summary"]["va_percent"], "waste h/shift", lss["metrics"]["projected_nva_hours_per_shift"])
    print("roi:", [(c["id"], c["roi"]) for c in lss["lss_cards"]])


if __name__ == "__main__":
    main()
