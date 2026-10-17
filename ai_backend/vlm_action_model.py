"""
VLM video action detection: a hosted vision model (OpenRouter, default Qwen3 flash) judges sampled frames.

Pipeline per video:
  1. Sample frames at `sample_fps` (default 1 FPS), streamed - same sampler as the BLIP pipeline
  2. Ask the VLM per frame: is "<prompt>" happening? It answers Yes/No with a 0-100 confidence (+ a description)
  3. A frame passes when P(Yes) >= confidence_threshold
  4. Group passed frames into segments (a gap larger than `segment_gap` seconds starts a new segment)

The VLM judges the prompt directly, so prompts can describe conditions, e.g. "worker not wearing a helmet".
For the Safety Agent, `analyze_frames` answers the activity question and all safety rules in ONE request per frame.

Runs anywhere (no model weights, no torch): requests go out in parallel, `batch_size` at a time.
Confidences are what the model reports (integers 0-100), so they are coarser than token probabilities.
"""

import base64
import contextlib
import io
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Dict, Iterator, List, Optional

import numpy as np
from PIL import Image

from openrouter_client import chat, parse_json
from video_utils import create_timeline_viz_data, get_video_duration, iter_sampled_frames

logger = logging.getLogger(__name__)

VLM_MODEL_NAME = "qwen/qwen3.7-flash"

FRAME_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["activity", "activity_confidence", "rules"],
    "properties": {
        "activity": {"type": "string"},
        "activity_confidence": {"type": "integer"},
        "rules": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "confidence"],
                "properties": {"id": {"type": "string"}, "confidence": {"type": "integer"}},
            },
        },
    },
}

JUDGE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer", "confidence", "description"],
    "properties": {
        "answer": {"type": "string", "enum": ["Yes", "No"]},
        "confidence": {"type": "integer"},
        "description": {"type": "string"},
    },
}


@dataclass
class VLMDetectionConfig:
    confidence_threshold: float = 0.5
    sample_fps: float = 1.0
    segment_gap: float = 3.0
    describe: bool = True


@dataclass
class VLMDetection:
    timestamp: float
    frame_idx: int
    confidence: float
    answer: str
    vlm_description: str
    passed: bool


@dataclass
class VLMActionSegment:
    start_time: float
    end_time: float
    confidence: float
    frame_count: int
    action_label: str
    detections: List[VLMDetection] = field(default_factory=list)


def group_vlm_segments(detections: List[VLMDetection], action_label: str,
                       max_gap: float = 3.0) -> List[VLMActionSegment]:
    """Group passed detections into segments; a gap > max_gap seconds starts a new segment."""
    passed = sorted((d for d in detections if d.passed), key=lambda d: d.timestamp)
    segments: List[VLMActionSegment] = []
    current_group: List[VLMDetection] = []

    def close():
        segments.append(VLMActionSegment(
            start_time=current_group[0].timestamp,
            end_time=current_group[-1].timestamp,
            confidence=float(np.mean([d.confidence for d in current_group])),
            frame_count=len(current_group),
            action_label=action_label,
            detections=list(current_group),
        ))

    for detection in passed:
        if current_group and detection.timestamp - current_group[-1].timestamp > max_gap:
            close()
            current_group = []
        current_group.append(detection)
    if current_group:
        close()

    return segments


def to_fraction(value, default: float = 0.0) -> float:
    """Confidence 0-100 (int) -> 0-1; a non-integer value up to 1.0 is taken as already a fraction."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if 0.0 < number < 1.0:
        return number
    return min(1.0, max(0.0, number / 100.0))


def salvage_frame(text: str) -> Optional[Dict]:
    """What can still be read from a frame answer that is not valid JSON (cut off, a stray comma, text around it)."""
    activity = re.search(r'"activity"\s*:\s*"([^"]*)"', text)
    activity_confidence = re.search(r'"activity_confidence"\s*:\s*(\d+)', text)
    rules = [{'id': i, 'confidence': int(c)} for i, c in
             re.findall(r'"id"\s*:\s*"([^"]+)"\s*,\s*"confidence"\s*:\s*(\d+)', text)]
    if not activity and not rules:
        return None
    return {'activity': activity.group(1) if activity else '',
            'activity_confidence': int(activity_confidence.group(1)) if activity_confidence else None,
            'rules': rules}


def probs_from_choice(options: List[str], letter: str, confidence: float) -> Dict[str, float]:
    """Spread probability over the options: the chosen one gets `confidence`, the rest share the remainder."""
    index = ord(letter.strip().upper()[:1] or 'A') - ord('A')
    index = index if 0 <= index < len(options) else len(options) - 1
    rest = (1.0 - confidence) / max(1, len(options) - 1)
    return {option: (confidence if i == index else rest) for i, option in enumerate(options)}


class VLMActionDetector:
    def __init__(self, api_key: str, model_name: str = VLM_MODEL_NAME, batch_size: int = 4,
                 max_image_side: int = 640, timeout: float = 90):
        if not api_key:
            raise ValueError("An OpenRouter API key is required")
        self.api_key = api_key
        self.model_name = model_name
        self.batch_size = batch_size
        self.max_image_side = max_image_side
        self.timeout = timeout
        # Network bound and stateless: requests can overlap, so there is no inference lock
        self._lock = contextlib.nullcontext()
        self._usage_lock = threading.Lock()
        self._usage = {'calls': 0, 'prompt_tokens': 0, 'completion_tokens': 0, 'cost': 0.0, 'failed_frames': 0}
        logger.info(f"✅ VLMActionDetector ready ({self.model_name} via OpenRouter, {batch_size} parallel requests)")

    # ---- usage accounting -------------------------------------------------

    def usage_snapshot(self) -> Dict:
        with self._usage_lock:
            return dict(self._usage)

    def _add_usage(self, usage: Dict):
        with self._usage_lock:
            self._usage['calls'] += 1
            self._usage['prompt_tokens'] += usage.get('prompt_tokens') or 0
            self._usage['completion_tokens'] += usage.get('completion_tokens') or 0
            self._usage['cost'] += usage.get('cost') or 0.0

    # ---- requests ---------------------------------------------------------

    def _data_uri(self, image: np.ndarray) -> str:
        """JPEG data URI, downscaled so the longest side is at most max_image_side (fewer vision tokens, cheaper)."""
        pil = Image.fromarray(image)
        scale = self.max_image_side / max(pil.size)
        if scale < 1:
            pil = pil.resize((max(1, round(pil.width * scale)), max(1, round(pil.height * scale))))
        buffer = io.BytesIO()
        pil.save(buffer, format="JPEG", quality=80)
        return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()

    def _ask(self, image: np.ndarray, text: str, schema: Optional[Dict] = None, schema_name: str = "frame",
             max_tokens: int = 300) -> str:
        messages = [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": self._data_uri(image)}},
            {"type": "text", "text": text},
        ]}]
        content, usage = chat(messages, self.model_name, self.api_key, schema=schema, schema_name=schema_name,
                              timeout=self.timeout, temperature=0.0, max_tokens=max_tokens,
                              reasoning={'enabled': False})
        self._add_usage(usage)
        return content

    def _map(self, function, images: List[np.ndarray]) -> List:
        with ThreadPoolExecutor(max_workers=max(1, self.batch_size)) as pool:
            return list(pool.map(function, images))

    # ---- used by the Safety Agent -----------------------------------------

    def analyze_frames(self, images: List[np.ndarray], rules: List, question: str, options: List[str]) -> List[Dict]:
        """
        Activity probabilities and a confidence per safety rule for each frame (rules need `.id` and `.prompt`).
        One request per frame answers everything.
        """
        letters = [chr(ord('A') + i) for i in range(len(options))]
        listing = "\n".join(f"{letter}. {option}" for letter, option in zip(letters, options))
        rule_lines = "\n".join(f"- {rule.id}: {rule.prompt}" for rule in rules) or "(none)"
        text = (
            "You are checking one frame from a workplace camera.\n\n"
            f"1. Activity. {question}\n{listing}\n"
            "Answer with the letter in `activity` and your confidence 0-100 as an integer in `activity_confidence`.\n\n"
            "2. Safety rules. For every rule below, put its id and an integer 0-100 in `rules`: how sure you are that "
            "the situation is clearly visible in this image (0 = not visible, 100 = certain).\n"
            f"{rule_lines}\n\nReturn JSON only."
        )

        budget = max(300, 100 + 60 * len(rules))  # the answer grows with the number of rules

        def read(image: np.ndarray) -> Optional[Dict]:
            """The frame's answer; a malformed one is retried once with more room, then salvaged, then given up on."""
            for tokens in (budget, budget * 2):
                answer = self._ask(image, text, FRAME_SCHEMA, "frame_analysis", max_tokens=tokens)
                try:
                    return parse_json(answer)
                except ValueError:
                    salvaged = salvage_frame(answer)
                    if salvaged and len(salvaged['rules']) == len(rules):
                        return salvaged
            return None

        def analyze(image: np.ndarray) -> Dict:
            data = read(image)
            if data is None:
                # One unreadable frame must not fail the whole video: it counts as unclear, with no rule triggered
                with self._usage_lock:
                    self._usage['failed_frames'] += 1
                return {'activity_probs': {option: 1.0 / len(options) for option in options},
                        'rule_confidences': {rule.id: 0.0 for rule in rules}}
            by_id = {str(r.get('id')): r.get('confidence') for r in data.get('rules') or [] if isinstance(r, dict)}
            return {
                'activity_probs': probs_from_choice(options, str(data.get('activity') or ''),
                                                    to_fraction(data.get('activity_confidence'), 0.5)),
                'rule_confidences': {rule.id: to_fraction(by_id.get(rule.id)) for rule in rules},
            }

        return self._map(analyze, images)

    def describe_images(self, images: List[np.ndarray], question: str, max_new_tokens: int = 40) -> List[str]:
        """Free-text answer per frame (e.g. a one-sentence description)."""
        return self._map(lambda image: self._ask(image, question, max_tokens=max_new_tokens * 2).strip(), images)

    # ---- /vlm_action ------------------------------------------------------

    def judge_images(self, images: List[np.ndarray], prompt: str, config: VLMDetectionConfig) -> List[Dict]:
        """Yes/No with a confidence (and a short description) for a batch of RGB frames."""
        text = (f'Is this happening in the image: "{prompt}"?\n'
                'Answer Yes or No in `answer`, your confidence in that answer (integer 0-100) in `confidence`, '
                + ('and one short sentence describing what the people are doing in `description`.'
                   if config.describe else 'and leave `description` empty.') + '\nReturn JSON only.')

        def judge(image: np.ndarray) -> Dict:
            data = parse_json(self._ask(image, text, JUDGE_SCHEMA, "yes_no", max_tokens=150))
            confidence = to_fraction(data.get('confidence'), 0.5)
            is_yes = str(data.get('answer')).strip().lower() == "yes"
            return {'confidence': confidence if is_yes else 1.0 - confidence,   # P(Yes)
                    'answer': "Yes" if is_yes else "No",
                    'description': str(data.get('description') or '').strip() if config.describe else ''}

        return self._map(judge, images)

    def _detect_batch(self, batch: List[Dict], prompt: str, config: VLMDetectionConfig) -> List[VLMDetection]:
        judgements = self.judge_images([f['frame'] for f in batch], prompt, config)
        return [
            VLMDetection(
                timestamp=frame_data['timestamp'],
                frame_idx=frame_data['frame_idx'],
                confidence=j['confidence'],
                answer=j['answer'],
                vlm_description=j['description'],
                passed=j['confidence'] >= config.confidence_threshold,
            )
            for frame_data, j in zip(batch, judgements)
        ]

    def detect_frames(self, frames: Iterator[Dict], prompt: str, config: VLMDetectionConfig) -> List[VLMDetection]:
        """Judge frames in batches of `batch_size`."""
        detections: List[VLMDetection] = []
        batch: List[Dict] = []
        for frame_data in frames:
            batch.append(frame_data)
            if len(batch) >= self.batch_size:
                detections.extend(self._detect_batch(batch, prompt, config))
                batch = []
        if batch:
            detections.extend(self._detect_batch(batch, prompt, config))
        return detections

    def process_video(self, video_path: str, prompt: str, config: Optional[VLMDetectionConfig] = None,
                      include_timeline: bool = False) -> Dict:
        """🎬 Run the full pipeline on a video file and return results as a dict."""
        config = config or VLMDetectionConfig()
        job_id = f"vlm_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"

        logger.info(f"🎬 [{job_id}] Processing {video_path} with prompt '{prompt}'")

        frames = iter_sampled_frames(video_path, config.sample_fps)
        all_detections = self.detect_frames(frames, prompt, config)

        if not all_detections:
            raise ValueError("No frames could be read from the video")

        video_duration = get_video_duration(video_path) or all_detections[-1].timestamp
        segments = group_vlm_segments(all_detections, prompt, config.segment_gap)
        passed_detections = [d for d in all_detections if d.passed]

        results = {
            'job_id': job_id,
            'video_path': video_path,
            'prompt': prompt,
            'model': self.model_name,
            'timestamp': datetime.now().isoformat(),
            'video_duration': video_duration,
            'stats': {
                'total_frames': len(all_detections),
                'passed_detections': len(passed_detections),
                'success_rate': len(passed_detections) / len(all_detections) * 100,
                'segments_found': len(segments),
            },
            # 🎯 Only passed detections, to keep the JSON small
            'passed_detections_only': [asdict(d) for d in passed_detections],
            'segments': [asdict(s) for s in segments],
        }

        if include_timeline:
            results['timeline_data'] = create_timeline_viz_data(segments, prompt, prompt, job_id, video_duration)

        logger.info(f"📊 [{job_id}] passed={len(passed_detections)}/{len(all_detections)} segments={len(segments)}")
        return results


if __name__ == "__main__":
    import argparse
    import json
    import os

    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Run VLM action detection (OpenRouter) on a video file")
    parser.add_argument("video_path")
    parser.add_argument("prompt", help="e.g. 'worker not wearing a helmet'")
    parser.add_argument("--fps", type=float, default=1.0)
    args = parser.parse_args()

    detector = VLMActionDetector(api_key=os.environ["OPENROUTER_API_KEY"],
                                 model_name=os.getenv("VLM_MODEL") or VLM_MODEL_NAME)
    results = detector.process_video(args.video_path, args.prompt, VLMDetectionConfig(sample_fps=args.fps),
                                     include_timeline=True)
    print(json.dumps({k: v for k, v in results.items() if k != 'passed_detections_only'}, indent=2, default=str))
    print(json.dumps(detector.usage_snapshot()))
