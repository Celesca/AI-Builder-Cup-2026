"""
Safety Agent: watches a workstation video with a vision model (OpenRouter) and produces the evidence the Gemba Kaizen Agent reasons on.

Per sampled frame, the VLM answers (one request per frame, see vlm_action_model.analyze_frames):
  1. Safety rules: one Yes/No question per rule ("is <prompt> happening?"), P(Yes) is the confidence
  2. Activity: one multiple-choice question ("what is the worker doing?"), mapped to a Muda category
     (VA, NNVA, NVA_MOTION, NVA_TRANSPORT, NVA_WAITING, NVA_SEARCH, NO_PERSON, or UNCERTAIN when unsure)

Then:
  3. Passed frames of each rule are grouped into safety events; activity frames into activity segments
  4. The key frame of each safety event and of the longest activity segments is described in one sentence
     and (optionally) attached as a small JPEG snapshot, as evidence for people and for the Gemba Kaizen Agent

Time is measured from frame timestamps, never by the VLM: each sampled frame stands for 1 / sample_fps seconds.
"""

import base64
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple

import cv2
import numpy as np

from video_utils import get_video_duration, iter_sampled_frames

logger = logging.getLogger(__name__)

SEVERITIES = ("low", "medium", "high")


@dataclass
class SafetyRule:
    id: str
    prompt: str
    severity: str = "medium"
    threshold: float = 0.6


DEFAULT_RULES: List[SafetyRule] = [
    SafetyRule("no_helmet", "a person who is not wearing a safety helmet or hard hat", "high"),
    SafetyRule("running", "a person running", "medium"),
    SafetyRule("phone_use", "a person using a mobile phone", "medium"),
    SafetyRule("person_down", "a person lying on the floor or falling down", "high"),
]


@dataclass(frozen=True)
class ActivityClass:
    key: str
    option: str     # text shown to the VLM
    category: str   # Muda category used by the Gemba Kaizen Agent


# Order matters only for the letter shown to the VLM (A, B, C, ...)
ACTIVITY_CLASSES: List[ActivityClass] = [
    ActivityClass("working", "assembling, machining or working on a part with hands or tools", "VA"),
    ActivityClass("inspecting", "inspecting, measuring or checking a part", "NNVA"),
    ActivityClass("walking", "walking or moving around without carrying anything", "NVA_MOTION"),
    ActivityClass("reaching", "reaching, bending or stretching to get something", "NVA_MOTION"),
    ActivityClass("carrying", "carrying, pushing or moving materials", "NVA_TRANSPORT"),
    ActivityClass("searching", "searching or looking around for a tool or part", "NVA_SEARCH"),
    ActivityClass("waiting", "standing or sitting idle, waiting, not working", "NVA_WAITING"),
    ActivityClass("no_person", "no person is visible", "NO_PERSON"),
]
ACTIVITY_QUESTION = "What is the main person in this image doing? Choose the best option."
DESCRIBE_QUESTION = "Describe in one short sentence what the people in this image are doing."
UNCERTAIN = "UNCERTAIN"


@dataclass
class SafetyAgentConfig:
    sample_fps: float = 1.0
    max_frames: int = 240               # longer videos are sampled more sparsely to stay under this
    segment_gap: float = 2.0            # seconds; passed frames closer than this form one safety event
    activity_min_confidence: float = 0.4  # below this the activity is UNCERTAIN
    max_descriptions: int = 12          # key frames described by the VLM (safety events first)
    include_snapshots: bool = True


@dataclass
class FrameObservation:
    timestamp: float
    frame_idx: int
    activity: str
    category: str
    activity_confidence: float
    rule_confidences: Dict[str, float]


@dataclass
class ActivitySegment:
    start_time: float
    end_time: float
    duration: float
    activity: str
    category: str
    confidence: float
    frame_count: int
    key_frame_idx: int
    key_timestamp: float
    description: str = ""
    snapshot: Optional[str] = None


@dataclass
class SafetyEvent:
    rule_id: str
    prompt: str
    severity: str
    start_time: float
    end_time: float
    duration: float
    peak_confidence: float
    mean_confidence: float
    frame_count: int
    key_frame_idx: int
    key_timestamp: float
    description: str = ""
    snapshot: Optional[str] = None


def slugify(text: str, fallback: str = "rule") -> str:
    slug = re.sub(r'[^a-z0-9]+', '_', text.lower()).strip('_')
    return slug[:40] or fallback


def parse_rules_text(text: str) -> List[SafetyRule]:
    """
    One rule per line (or comma separated on a single line). An optional severity prefix sets the severity:
      high: not wearing a helmet
      running
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if len(lines) == 1 and ',' in lines[0] and ':' not in lines[0]:
        lines = [p.strip() for p in lines[0].split(',') if p.strip()]

    rules, seen = [], set()
    for line in lines:
        severity = "medium"
        head, sep, rest = line.partition(':')
        if sep and head.strip().lower() in SEVERITIES:
            severity, line = head.strip().lower(), rest.strip()
        if not line:
            continue
        rule_id = slugify(line)
        while rule_id in seen:
            rule_id += "_"
        seen.add(rule_id)
        rules.append(SafetyRule(rule_id, line, severity))
    return rules


def frame_seconds(sample_fps: float) -> float:
    return 1.0 / sample_fps


def smooth_labels(labels: List[str]) -> List[str]:
    """Remove single-frame flickers: A B A -> A A A (a 2B VLM is noisy frame to frame)."""
    smoothed = list(labels)
    for i in range(1, len(labels) - 1):
        if labels[i - 1] == labels[i + 1] != labels[i]:
            smoothed[i] = labels[i - 1]
    return smoothed


def build_activity_segments(observations: List[FrameObservation], sample_fps: float) -> List[ActivitySegment]:
    """Merge consecutive frames with the same activity into segments."""
    step = frame_seconds(sample_fps)
    segments: List[ActivitySegment] = []
    group: List[FrameObservation] = []

    def close():
        key = max(group, key=lambda o: o.activity_confidence)
        segments.append(ActivitySegment(
            start_time=group[0].timestamp,
            end_time=group[-1].timestamp + step,
            duration=round(len(group) * step, 3),
            activity=group[0].activity,
            category=group[0].category,
            confidence=float(np.mean([o.activity_confidence for o in group])),
            frame_count=len(group),
            key_frame_idx=key.frame_idx,
            key_timestamp=key.timestamp,
        ))

    for obs in observations:
        if group and (obs.activity != group[-1].activity or obs.timestamp - group[-1].timestamp > 1.5 * step):
            close()
            group = []
        group.append(obs)
    if group:
        close()
    return segments


def build_safety_events(observations: List[FrameObservation], rules: List[SafetyRule],
                        sample_fps: float, max_gap: float) -> List[SafetyEvent]:
    """Group frames where a rule passed its threshold; a gap > max_gap seconds starts a new event."""
    step = frame_seconds(sample_fps)
    events: List[SafetyEvent] = []
    for rule in rules:
        hits = [o for o in observations if o.rule_confidences.get(rule.id, 0.0) >= rule.threshold]
        group: List[FrameObservation] = []

        def close():
            confidences = [o.rule_confidences[rule.id] for o in group]
            key = group[int(np.argmax(confidences))]
            events.append(SafetyEvent(
                rule_id=rule.id, prompt=rule.prompt, severity=rule.severity,
                start_time=group[0].timestamp,
                end_time=group[-1].timestamp + step,
                duration=round(group[-1].timestamp - group[0].timestamp + step, 3),
                peak_confidence=float(max(confidences)),
                mean_confidence=float(np.mean(confidences)),
                frame_count=len(group),
                key_frame_idx=key.frame_idx,
                key_timestamp=key.timestamp,
            ))

        for obs in hits:
            if group and obs.timestamp - group[-1].timestamp > max_gap:
                close()
                group = []
            group.append(obs)
        if group:
            close()

    severity_rank = {s: i for i, s in enumerate(reversed(SEVERITIES))}
    return sorted(events, key=lambda e: (e.start_time, severity_rank.get(e.severity, 9)))


def summarize_activity(observations: List[FrameObservation], sample_fps: float) -> Dict:
    """Seconds per activity and per Muda category, and VA / NVA percentages of the time a person is visible."""
    step = frame_seconds(sample_fps)
    by_activity: Dict[str, float] = defaultdict(float)
    by_category: Dict[str, float] = defaultdict(float)
    for obs in observations:
        by_activity[obs.activity] += step
        by_category[obs.category] += step

    observed = sum(by_category.values())
    person_time = observed - by_category.get("NO_PERSON", 0.0)
    nva_time = sum(v for k, v in by_category.items() if k.startswith("NVA_"))

    def pct(value: float) -> float:
        return round(100 * value / person_time, 1) if person_time else 0.0

    return {
        'observed_seconds': round(observed, 3),
        'person_visible_seconds': round(person_time, 3),
        'by_activity_seconds': {k: round(v, 3) for k, v in sorted(by_activity.items(), key=lambda kv: -kv[1])},
        'by_category_seconds': {k: round(v, 3) for k, v in sorted(by_category.items(), key=lambda kv: -kv[1])},
        'va_percent': pct(by_category.get("VA", 0.0)),
        'nnva_percent': pct(by_category.get("NNVA", 0.0)),
        'nva_percent': pct(nva_time),
        'uncertain_percent': pct(by_category.get(UNCERTAIN, 0.0)),
    }


def read_frames_at(video_path: str, frame_indices: Iterable[int]) -> Dict[int, np.ndarray]:
    """Read specific frames (RGB) by index."""
    frames: Dict[int, np.ndarray] = {}
    cap = cv2.VideoCapture(video_path)
    try:
        for idx in sorted(set(frame_indices)):
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = cap.read()
            if ok:
                frames[idx] = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    finally:
        cap.release()
    return frames


def encode_snapshot(frame: np.ndarray, max_side: int = 360, quality: int = 70) -> str:
    """Small JPEG data URI of an RGB frame."""
    h, w = frame.shape[:2]
    scale = min(1.0, max_side / max(h, w))
    if scale < 1:
        frame = cv2.resize(frame, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode('.jpg', cv2.cvtColor(frame, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, quality])
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode() if ok else ""


class SafetyAgent:
    """Runs safety rules + activity classification on a shared VLMActionDetector (OpenRouter)."""

    def __init__(self, vlm):
        self.vlm = vlm

    def _observe_batch(self, batch: List[Dict], rules: List[SafetyRule],
                       config: SafetyAgentConfig) -> List[FrameObservation]:
        images = [f['frame'] for f in batch]
        options = [c.option for c in ACTIVITY_CLASSES]
        analyses = self.vlm.analyze_frames(images, rules, ACTIVITY_QUESTION, options)

        observations = []
        for frame_data, analysis in zip(batch, analyses):
            probs = analysis['activity_probs']
            best_index = int(np.argmax([probs[o] for o in options]))
            best, confidence = ACTIVITY_CLASSES[best_index], probs[options[best_index]]
            uncertain = confidence < config.activity_min_confidence
            observations.append(FrameObservation(
                timestamp=frame_data['timestamp'],
                frame_idx=frame_data['frame_idx'],
                activity=UNCERTAIN.lower() if uncertain else best.key,
                category=UNCERTAIN if uncertain else best.category,
                activity_confidence=float(confidence),
                rule_confidences={rule.id: analysis['rule_confidences'].get(rule.id, 0.0) for rule in rules},
            ))
        return observations

    def observe(self, video_path: str, rules: List[SafetyRule], config: SafetyAgentConfig,
                sample_fps: float) -> List[FrameObservation]:
        observations: List[FrameObservation] = []
        batch: List[Dict] = []
        batch_size = getattr(self.vlm, 'batch_size', 4)
        for frame_data in iter_sampled_frames(video_path, sample_fps):
            batch.append(frame_data)
            if len(batch) >= batch_size:
                observations.extend(self._observe_batch(batch, rules, config))
                batch = []
        if batch:
            observations.extend(self._observe_batch(batch, rules, config))
        return observations

    def _add_evidence(self, video_path: str, items: List, config: SafetyAgentConfig):
        """Describe (and snapshot) the key frame of each item, up to max_descriptions VLM calls."""
        described = items[:config.max_descriptions]
        if not described and not config.include_snapshots:
            return
        frames = read_frames_at(video_path, [item.key_frame_idx for item in items])
        if described:
            available = [item for item in described if item.key_frame_idx in frames]
            batch_size = getattr(self.vlm, 'batch_size', 4)
            for start in range(0, len(available), batch_size):
                chunk = available[start:start + batch_size]
                texts = self.vlm.describe_images([frames[i.key_frame_idx] for i in chunk], DESCRIBE_QUESTION)
                for item, text in zip(chunk, texts):
                    item.description = text
        if config.include_snapshots:
            for item in items:
                if item.key_frame_idx in frames:
                    item.snapshot = encode_snapshot(frames[item.key_frame_idx])

    def process_video(self, video_path: str, rules: Optional[List[SafetyRule]] = None,
                      config: Optional[SafetyAgentConfig] = None) -> Dict:
        rules = rules if rules is not None else DEFAULT_RULES
        config = config or SafetyAgentConfig()
        job_id = f"safety_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"

        video_duration = get_video_duration(video_path)
        sample_fps = config.sample_fps
        if video_duration and video_duration * sample_fps > config.max_frames:
            sample_fps = config.max_frames / video_duration
        logger.info(f"🦺 [{job_id}] {video_path}: {len(rules)} rules at {sample_fps:.2f} fps")
        usage_before = self.vlm.usage_snapshot() if hasattr(self.vlm, 'usage_snapshot') else None

        with self.vlm._lock:
            observations = self.observe(video_path, rules, config, sample_fps)
            if not observations:
                raise ValueError("No frames could be read from the video")
            # Flicker smoothing on the activity labels, keeping category in sync
            category_of = {c.key: c.category for c in ACTIVITY_CLASSES}
            category_of[UNCERTAIN.lower()] = UNCERTAIN
            for obs, label in zip(observations, smooth_labels([o.activity for o in observations])):
                obs.activity, obs.category = label, category_of[label]

            segments = build_activity_segments(observations, sample_fps)
            events = build_safety_events(observations, rules, sample_fps, config.segment_gap)
            # Evidence: every safety event first, then the longest activity segments
            longest = sorted(segments, key=lambda s: -s.duration)
            self._add_evidence(video_path, events + longest, config)

        video_duration = video_duration or observations[-1].timestamp + frame_seconds(sample_fps)
        severity_counts = {s: sum(1 for e in events if e.severity == s) for s in SEVERITIES}
        flagged_frames = sum(1 for o in observations
                             if any(o.rule_confidences.get(r.id, 0) >= r.threshold for r in rules))

        result = {
            'job_id': job_id,
            'video_path': video_path,
            'model': getattr(self.vlm, 'model_name', ''),
            'timestamp': datetime.now().isoformat(),
            'video_duration': video_duration,
            'sample_fps': round(sample_fps, 4),
            'vlm_usage': None,
            'rules': [asdict(r) for r in rules],
            'stats': {
                'frames_analyzed': len(observations),
                'safety_events': len(events),
                'frames_with_violation': flagged_frames,
                'events_by_severity': severity_counts,
            },
            'safety_events': [asdict(e) for e in events],
            'activity': {
                'summary': summarize_activity(observations, sample_fps),
                'segments': [asdict(s) for s in segments],
                'timeline': [
                    {'timestamp': o.timestamp, 'frame_idx': o.frame_idx, 'activity': o.activity,
                     'category': o.category, 'confidence': round(o.activity_confidence, 4),
                     'rule_confidences': {k: round(v, 4) for k, v in o.rule_confidences.items()}}
                    for o in observations
                ],
            },
        }
        if usage_before is not None:
            usage_after = self.vlm.usage_snapshot()
            result['vlm_usage'] = {k: round(usage_after[k] - usage_before[k], 6) for k in usage_after}
        logger.info(f"📊 [{job_id}] frames={len(observations)} events={len(events)} "
                    f"VA={result['activity']['summary']['va_percent']}%")
        return result


if __name__ == "__main__":
    import argparse
    import json

    import os

    from vlm_action_model import VLM_MODEL_NAME, VLMActionDetector

    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Run the Safety Agent (OpenRouter VLM) on a video file")
    parser.add_argument("video_path")
    parser.add_argument("--rules", help="Rules, one per line or comma separated (default: built-in rules)")
    parser.add_argument("--fps", type=float, default=1.0)
    args = parser.parse_args()

    agent = SafetyAgent(VLMActionDetector(api_key=os.environ["OPENROUTER_API_KEY"],
                                          model_name=os.getenv("VLM_MODEL") or VLM_MODEL_NAME))
    output = agent.process_video(args.video_path, parse_rules_text(args.rules) if args.rules else None,
                                 SafetyAgentConfig(sample_fps=args.fps, include_snapshots=False))
    output['activity'].pop('timeline')
    print(json.dumps(output, indent=2, default=str))
