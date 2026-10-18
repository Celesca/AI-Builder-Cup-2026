"""
Render an annotated copy of a video: person boxes (YOLO) labelled with the safety rule when a rule passed its
threshold (red, VIOLATION) or came within `near_miss_margin` of it (amber, NEAR MISS). Without a rule hit, the box
carries the VLM's activity label instead (green value-adding, blue waste, grey unclear), so every person is boxed.

The VLM scores whole frames, not people, so a rule hit is drawn on every detected person in that frame.
VLM observations are sparse (about 1 FPS): each one is held until the next. YOLO runs every few frames and is held too.
"""

import bisect
import logging
import os
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from video_convert import ConversionError, convert_for_browser, ffmpeg_available

logger = logging.getLogger(__name__)

RED = (0, 0, 230)      # BGR
AMBER = (0, 165, 255)
GREEN = (60, 170, 60)
BLUE = (200, 110, 30)
GREY = (140, 140, 140)
# Short Muda names for the activity label (Hershey fonts are ASCII only)
CATEGORY_SHORT = {
    'VA': 'value-adding', 'NNVA': 'necessary, no value', 'NVA_MOTION': 'motion waste',
    'NVA_TRANSPORT': 'transport waste', 'NVA_WAITING': 'waiting waste', 'NVA_SEARCH': 'searching waste',
    'UNCERTAIN': 'unclear',
}
BOX_FPS = 5.0          # YOLO runs this many times per second of video


def active_rules(rule_confidences: Dict[str, float], rules: List[Dict], margin: float) -> List[Tuple[str, str, float]]:
    """(rule_id, 'VIOLATION' | 'NEAR MISS', confidence) for the rules that passed or nearly passed, worst first."""
    hits = []
    for rule in rules:
        conf = rule_confidences.get(rule['id'], 0.0)
        if conf >= rule['threshold']:
            hits.append((rule['id'], 'VIOLATION', conf))
        elif conf >= rule['threshold'] - margin:
            hits.append((rule['id'], 'NEAR MISS', conf))
    return sorted(hits, key=lambda h: (h[1] != 'VIOLATION', -h[2]))


def _label(hit: Tuple[str, str, float]) -> str:
    rule_id, kind, conf = hit
    return f"{kind}: {rule_id} {conf:.2f}"


def activity_tag(observation: Dict) -> Optional[Tuple[str, Tuple[int, int, int]]]:
    """(label, colour) for a sampled frame's activity, or None when there is nobody to label."""
    category = observation.get('category')
    if category not in CATEGORY_SHORT:
        return None
    color = GREEN if category == 'VA' else GREY if category == 'UNCERTAIN' else BLUE
    return f"{observation.get('activity', '')} - {CATEGORY_SHORT[category]}", color


def draw_activity(frame: np.ndarray, boxes: List[Tuple[int, int, int, int]], tag: Tuple[str, Tuple[int, int, int]]) -> None:
    """A thin box with the activity label on each person. Draw in place on a BGR frame."""
    text, color = tag
    scale = max(0.5, frame.shape[1] / 1280)
    thick = max(1, int(round(2 * scale)))
    for x1, y1, x2, y2 in boxes:
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, thick)
        (tw, th), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.55 * scale, thick)
        top = y1 - th - base - 4 if y1 - th - base - 4 >= 0 else y1
        cv2.rectangle(frame, (x1, top), (x1 + tw + 6, top + th + base + 4), color, -1)
        cv2.putText(frame, text, (x1 + 3, top + th + 1), cv2.FONT_HERSHEY_SIMPLEX, 0.55 * scale,
                    (255, 255, 255), thick, cv2.LINE_AA)


def draw_hits(frame: np.ndarray, boxes: List[Tuple[int, int, int, int]], hits: List[Tuple[str, str, float]]) -> None:
    """Draw in place on a BGR frame."""
    if not hits:
        return
    color = RED if hits[0][1] == 'VIOLATION' else AMBER
    scale = max(0.5, frame.shape[1] / 1280)
    thick = max(1, int(round(2 * scale)))
    for x1, y1, x2, y2 in boxes:
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, thick + 1)
        for i, hit in enumerate(hits):
            text = _label(hit)
            hit_color = RED if hit[1] == 'VIOLATION' else AMBER
            (tw, th), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6 * scale, thick)
            top = y1 - (i + 1) * (th + base + 4)
            if top < 0:  # no room above the box: stack inside it
                top = y1 + i * (th + base + 4)
            cv2.rectangle(frame, (x1, top), (x1 + tw + 6, top + th + base + 4), hit_color, -1)
            cv2.putText(frame, text, (x1 + 3, top + th + 1), cv2.FONT_HERSHEY_SIMPLEX, 0.6 * scale,
                        (255, 255, 255), thick, cv2.LINE_AA)
    # Banner so a hit is visible even when YOLO found nobody
    banner = " | ".join(_label(h) for h in hits)
    cv2.rectangle(frame, (0, 0), (frame.shape[1], int(30 * scale) + 6), color, -1)
    cv2.putText(frame, banner, (8, int(22 * scale) + 3), cv2.FONT_HERSHEY_SIMPLEX, 0.7 * scale,
                (255, 255, 255), thick, cv2.LINE_AA)


def detect_person_boxes(counter, frame_bgr: np.ndarray, confidence: float) -> List[Tuple[int, int, int, int]]:
    with counter._lock:
        result = counter.model.predict([frame_bgr], conf=confidence, classes=[0], device=counter.device,
                                       verbose=False)[0]
    if result.boxes is None:
        return []
    return [tuple(int(v) for v in b) for b in result.boxes.xyxy.cpu().numpy()]


def render_annotated_video(video_path: str, out_path: str, safety_result: Dict, counter,
                           near_miss_margin: float = 0.15, person_confidence: float = 0.4) -> Dict:
    """Write an H.264 MP4 (mp4v if ffmpeg is missing) to `out_path`. Returns small stats."""
    rules = safety_result['rules']
    timeline = safety_result['activity']['timeline']
    times = [o['timestamp'] for o in timeline]

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    width, height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    raw_path = out_path + ".raw.mp4"
    writer = cv2.VideoWriter(raw_path, cv2.VideoWriter_fourcc(*'mp4v'), fps, (width, height))
    step = max(1, int(round(fps / BOX_FPS)))
    boxes: List[Tuple[int, int, int, int]] = []
    annotated_frames = labelled_frames = frame_idx = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            i = bisect.bisect_right(times, frame_idx / fps) - 1
            hits = active_rules(timeline[i]['rule_confidences'], rules, near_miss_margin) if i >= 0 else []
            tag = activity_tag(timeline[i]) if i >= 0 else None
            if hits or tag:
                if frame_idx % step == 0 or not boxes:
                    boxes = detect_person_boxes(counter, frame, person_confidence) if counter else []
                if hits:
                    draw_hits(frame, boxes, hits)
                    annotated_frames += 1
                elif boxes:
                    draw_activity(frame, boxes, tag)
                    labelled_frames += 1
            else:
                boxes = []
            writer.write(frame)
            frame_idx += 1
    finally:
        cap.release()
        writer.release()

    try:
        if not ffmpeg_available():
            raise ConversionError("no ffmpeg")
        convert_for_browser(raw_path, out_path)
        os.remove(raw_path)
    except ConversionError as e:
        logger.warning(f"Annotated video left as mp4v ({e})")
        os.replace(raw_path, out_path)
    return {'frames': frame_idx, 'annotated_frames': annotated_frames, 'labelled_frames': labelled_frames}
