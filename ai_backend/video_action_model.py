"""
BLIP video action detection pipeline (ported from Celesca/valz `video_action_model.py`).

Pipeline per video:
  1. Sample frames at `sample_fps` (default 1 FPS), streamed - frames are never all held in memory
  2. Caption each frame with BLIP (batched)
  3. Split prompt and caption into person / action / context components (spaCy, with a fallback)
  4. Score each component with MiniLM sentence embeddings, combine with weights
  5. A frame passes when weighted >= similarity_threshold and action >= action_threshold
  6. Group passed frames into segments (a gap larger than `segment_gap` seconds starts a new segment)

Models are loaded once per ActionDetector; weights/thresholds are per-call via DetectionConfig.
"""

import logging
import threading
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Dict, Iterator, List, Optional, Tuple

import numpy as np
import torch
from PIL import Image
from sentence_transformers import SentenceTransformer
from transformers import BlipForConditionalGeneration, BlipProcessor

from video_utils import create_timeline_viz_data, get_video_duration, iter_sampled_frames  # noqa: F401 (re-exported)

# Optional spaCy
try:
    import spacy
    SPACY_AVAILABLE = True
except ImportError:
    SPACY_AVAILABLE = False

logger = logging.getLogger(__name__)

BLIP_MODEL_NAME = "Salesforce/blip-image-captioning-large"
SIMILARITY_MODEL_NAME = "all-MiniLM-L6-v2"
SPACY_MODEL_NAME = "en_core_web_sm"

PERSON_WORDS = {'person', 'people', 'man', 'woman', 'child', 'someone', 'individual'}


@dataclass
class DetectionConfig:
    person_weight: float = 0.2
    action_weight: float = 0.7
    context_weight: float = 0.1
    similarity_threshold: float = 0.5
    action_threshold: float = 0.4
    sample_fps: float = 1.0
    segment_gap: float = 3.0

    def normalized_weights(self) -> Tuple[float, float, float]:
        total = self.person_weight + self.action_weight + self.context_weight
        if total <= 0:
            raise ValueError("person_weight + action_weight + context_weight must be greater than 0")
        return (self.person_weight / total, self.action_weight / total, self.context_weight / total)


@dataclass
class Detection:
    timestamp: float
    frame_idx: int
    confidence: float
    blip_description: str
    similarity_scores: Dict[str, float]
    passed: bool


@dataclass
class ActionSegment:
    start_time: float
    end_time: float
    confidence: float
    frame_count: int
    action_label: str
    detections: List[Detection] = field(default_factory=list)


def select_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def group_segments(detections: List[Detection], action_label: str, max_gap: float = 3.0) -> List[ActionSegment]:
    """Group passed detections into segments; a gap > max_gap seconds starts a new segment."""
    passed = sorted((d for d in detections if d.passed), key=lambda d: d.timestamp)
    segments = []
    current_group: List[Detection] = []

    for detection in passed:
        if current_group and detection.timestamp - current_group[-1].timestamp > max_gap:
            segments.append(_create_segment(current_group, action_label))
            current_group = []
        current_group.append(detection)

    if current_group:
        segments.append(_create_segment(current_group, action_label))

    return segments


def _create_segment(detections: List[Detection], action_label: str) -> ActionSegment:
    return ActionSegment(
        start_time=detections[0].timestamp,
        end_time=detections[-1].timestamp,
        confidence=float(np.mean([d.confidence for d in detections])),
        frame_count=len(detections),
        action_label=action_label,
        detections=detections,
    )


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denom) if denom else 0.0


class ActionDetector:
    def __init__(self, device: Optional[str] = None, batch_size: int = 8,
                 blip_model_name: str = BLIP_MODEL_NAME,
                 similarity_model_name: str = SIMILARITY_MODEL_NAME):
        self.device = device or select_device()
        self.batch_size = batch_size
        self.blip_model_name = blip_model_name
        self.similarity_model_name = similarity_model_name
        # One inference at a time: the models are shared across requests
        self._lock = threading.Lock()

        self._init_models()
        logger.info(f"✅ ActionDetector ready on {self.device} (spaCy: {self.nlp is not None})")

    def _init_models(self):
        # BLIP
        self.blip_processor = BlipProcessor.from_pretrained(self.blip_model_name)
        self.blip_model = BlipForConditionalGeneration.from_pretrained(self.blip_model_name)
        self.blip_model.to(self.device)
        self.blip_model.eval()

        # Similarity
        self.similarity_model = SentenceTransformer(self.similarity_model_name, device=self.device)

        # NER
        self.nlp = None
        if SPACY_AVAILABLE:
            try:
                self.nlp = spacy.load(SPACY_MODEL_NAME)
            except OSError:
                logger.warning(f"spaCy model '{SPACY_MODEL_NAME}' not installed - using keyword fallback")

    def extract_action_verb(self, prompt: str) -> str:
        """🎯 Extract main action verb from prompt using NER (no corpus!)"""
        if self.nlp:
            doc = self.nlp(prompt)
            for token in doc:
                if (token.pos_ == 'VERB' and token.dep_ in ['ROOT', 'ccomp', 'xcomp']) or \
                   (token.tag_ in ['VBG'] and token.dep_ in ['amod', 'acl', 'ROOT']):
                    return token.lemma_.lower()

        # Fallback: simple pattern matching
        for word in prompt.lower().split():
            if word.endswith('ing') and len(word) > 4:
                return word

        return "action"  # Ultimate fallback

    def parse_ner(self, text: str) -> Dict[str, List[str]]:
        """Extract person / action / context components."""
        components = {'persons': [], 'actions': [], 'contexts': []}

        if self.nlp:
            doc = self.nlp(text)
            for token in doc:
                text_lower = token.text.lower()
                if text_lower in PERSON_WORDS or (token.pos_ == 'NOUN' and token.dep_ == 'nsubj'):
                    components['persons'].append(text_lower)
                elif (token.pos_ == 'VERB' and token.dep_ in ['ROOT', 'ccomp', 'xcomp']) or \
                     (token.tag_ in ['VBG', 'VBN', 'VBD']):
                    components['actions'].append(token.lemma_.lower())
                elif token.pos_ in ['ADJ', 'ADV', 'NOUN'] and len(text_lower) > 2:
                    components['contexts'].append(text_lower)
        else:
            words = text.lower().split()
            components['persons'] = [w for w in words if w in PERSON_WORDS]
            components['actions'] = [w for w in words if (w.endswith('ing') or w.endswith('ed')) and len(w) > 3]
            components['contexts'] = [w for w in words
                                      if w not in components['persons'] + components['actions'] and len(w) > 2]

        return components

    def _embed_components(self, components: Dict[str, List[str]]) -> Dict[str, Optional[np.ndarray]]:
        """Embed each non-empty component in one encode call."""
        keys = [k for k, words in components.items() if words]
        embeddings: Dict[str, Optional[np.ndarray]] = {k: None for k in components}
        if keys:
            vectors = self.similarity_model.encode([' '.join(components[k]) for k in keys])
            for key, vector in zip(keys, vectors):
                embeddings[key] = vector
        return embeddings

    def score_caption(self, prompt_embeddings: Dict[str, Optional[np.ndarray]], caption: str,
                      weights: Tuple[float, float, float]) -> Dict[str, float]:
        """Calculate NER-weighted similarity between the (pre-embedded) prompt and a caption."""
        caption_embeddings = self._embed_components(self.parse_ner(caption))

        def sim(key: str) -> float:
            a, b = prompt_embeddings[key], caption_embeddings[key]
            return _cosine(a, b) if a is not None and b is not None else 0.0

        person_sim, action_sim, context_sim = sim('persons'), sim('actions'), sim('contexts')
        person_w, action_w, context_w = weights
        weighted = person_w * person_sim + action_w * action_sim + context_w * context_sim

        return {'person': person_sim, 'action': action_sim, 'context': context_sim, 'weighted': weighted}

    def caption_images(self, images: List[np.ndarray]) -> List[str]:
        """BLIP captions for a batch of RGB frames."""
        pil_images = [Image.fromarray(img) for img in images]
        inputs = self.blip_processor(images=pil_images, return_tensors="pt").to(self.device)
        with torch.inference_mode():
            generated_ids = self.blip_model.generate(**inputs, max_length=50, num_beams=5)
        return [c.strip() for c in self.blip_processor.batch_decode(generated_ids, skip_special_tokens=True)]

    def _detect_batch(self, batch: List[Dict], prompt_embeddings, config: DetectionConfig,
                      weights: Tuple[float, float, float]) -> List[Detection]:
        captions = self.caption_images([f['frame'] for f in batch])
        detections = []
        for frame_data, caption in zip(batch, captions):
            scores = self.score_caption(prompt_embeddings, caption, weights)
            passed = scores['weighted'] >= config.similarity_threshold and \
                scores['action'] >= config.action_threshold
            detections.append(Detection(
                timestamp=frame_data['timestamp'],
                frame_idx=frame_data['frame_idx'],
                confidence=scores['weighted'],
                blip_description=caption,
                similarity_scores=scores,
                passed=passed,
            ))
        return detections

    def detect_frames(self, frames: Iterator[Dict], prompt: str, config: DetectionConfig) -> List[Detection]:
        """Caption and score frames in batches of `batch_size`."""
        weights = config.normalized_weights()
        prompt_embeddings = self._embed_components(self.parse_ner(prompt))

        detections: List[Detection] = []
        batch: List[Dict] = []
        for frame_data in frames:
            batch.append(frame_data)
            if len(batch) >= self.batch_size:
                detections.extend(self._detect_batch(batch, prompt_embeddings, config, weights))
                batch = []
        if batch:
            detections.extend(self._detect_batch(batch, prompt_embeddings, config, weights))
        return detections

    @staticmethod
    def create_timeline_viz_data(segments: List[ActionSegment], prompt: str, action_verb: str,
                                 job_id: str, video_duration: float) -> Optional[Dict]:
        return create_timeline_viz_data(segments, prompt, action_verb, job_id, video_duration)

    def process_video(self, video_path: str, prompt: str, config: Optional[DetectionConfig] = None,
                      include_timeline: bool = False) -> Dict:
        """🎬 Run the full pipeline on a video file and return results as a dict."""
        config = config or DetectionConfig()
        config.normalized_weights()  # validate before doing any work
        job_id = f"job_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"

        logger.info(f"🎬 [{job_id}] Processing {video_path} with prompt '{prompt}'")

        with self._lock:
            frames = iter_sampled_frames(video_path, config.sample_fps)
            all_detections = self.detect_frames(frames, prompt, config)

        if not all_detections:
            raise ValueError("No frames could be read from the video")

        video_duration = get_video_duration(video_path) or all_detections[-1].timestamp
        action_verb = self.extract_action_verb(prompt)
        segments = group_segments(all_detections, action_verb, config.segment_gap)
        passed_detections = [d for d in all_detections if d.passed]

        results = {
            'job_id': job_id,
            'video_path': video_path,
            'prompt': prompt,
            'action_verb': action_verb,
            'timestamp': datetime.now().isoformat(),
            'video_duration': video_duration,
            'stats': {
                'total_frames': len(all_detections),
                'total_detections': len(all_detections),
                'passed_detections': len(passed_detections),
                'success_rate': len(passed_detections) / len(all_detections) * 100,
                'segments_found': len(segments),
            },
            # 🎯 Only passed detections, to keep the JSON small
            'passed_detections_only': [asdict(d) for d in passed_detections],
            'segments': [asdict(s) for s in segments],
        }

        if include_timeline:
            results['timeline_data'] = self.create_timeline_viz_data(
                segments, prompt, action_verb, job_id, video_duration)

        logger.info(f"📊 [{job_id}] verb='{action_verb}' passed={len(passed_detections)}/{len(all_detections)} "
                    f"segments={len(segments)}")
        return results


if __name__ == "__main__":
    import argparse
    import json

    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Run BLIP action detection on a video file")
    parser.add_argument("video_path")
    parser.add_argument("prompt", help="e.g. 'person running'")
    args = parser.parse_args()

    detector = ActionDetector()
    results = detector.process_video(args.video_path, args.prompt, include_timeline=True)
    print(json.dumps({k: v for k, v in results.items() if k != 'passed_detections_only'}, indent=2, default=str))
