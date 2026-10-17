"""
YOLO person counting pipeline (ported from Celesca/valz `yolo_person_counter.py`).

Pipeline per video:
  1. Sample frames at `sample_fps` (default 2 FPS), streamed with the same sampler as the BLIP pipeline
  2. Run YOLO (default YOLOv8 nano) on batches of frames, keeping only the COCO `person` class
  3. Report per-frame counts with boxes, plus max / min / average over the video

The model is small (~6 MB) and fast, so it can run in parallel with the BLIP action pipeline.
"""

import logging
import threading
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Dict, Iterator, List, Optional

import numpy as np
from ultralytics import YOLO

from video_action_model import get_video_duration, iter_sampled_frames, select_device

logger = logging.getLogger(__name__)

YOLO_MODEL_NAME = "yolov8n.pt"
PERSON_CLASS_ID = 0  # COCO


def select_yolo_device() -> str:
    # Never MPS: running YOLO and BLIP on MPS from two threads at once segfaults the process.
    # The nano model is fast enough on CPU, so it can run there while BLIP uses the GPU.
    device = select_device()
    return "cpu" if device == "mps" else device


@dataclass
class PersonCountConfig:
    confidence_threshold: float = 0.5
    sample_fps: float = 2.0


@dataclass
class PersonBox:
    person_id: int  # index within the frame, not a track ID
    confidence: float
    x1: int
    y1: int
    x2: int
    y2: int
    center_x: int
    center_y: int


@dataclass
class FrameCount:
    frame_idx: int
    timestamp: float
    person_count: int
    detections: List[PersonBox] = field(default_factory=list)


class PersonCounter:
    def __init__(self, model_name: str = YOLO_MODEL_NAME, device: Optional[str] = None, batch_size: int = 16):
        self.model_name = model_name
        self.device = device or select_yolo_device()
        self.batch_size = batch_size
        # One inference at a time per counter; the BLIP detector has its own lock, so both can run together
        self._lock = threading.Lock()

        self.model = YOLO(model_name)
        logger.info(f"✅ PersonCounter ready ({model_name} on {self.device})")

    def count_batch(self, batch: List[Dict], config: PersonCountConfig) -> List[FrameCount]:
        """Run YOLO on a batch of sampled RGB frames."""
        # Ultralytics treats numpy input as BGR
        images = [np.ascontiguousarray(f['frame'][..., ::-1]) for f in batch]
        results = self.model.predict(images, conf=config.confidence_threshold, classes=[PERSON_CLASS_ID],
                                     device=self.device, verbose=False)

        counts = []
        for frame_data, result in zip(batch, results):
            boxes = result.boxes
            xyxy = boxes.xyxy.cpu().numpy().astype(int) if boxes is not None else []
            confs = boxes.conf.cpu().numpy() if boxes is not None else []
            detections = [
                PersonBox(person_id=i, confidence=float(conf),
                          x1=int(x1), y1=int(y1), x2=int(x2), y2=int(y2),
                          center_x=int((x1 + x2) // 2), center_y=int((y1 + y2) // 2))
                for i, ((x1, y1, x2, y2), conf) in enumerate(zip(xyxy, confs))
            ]
            counts.append(FrameCount(frame_idx=frame_data['frame_idx'], timestamp=frame_data['timestamp'],
                                     person_count=len(detections), detections=detections))
        return counts

    def count_frames(self, frames: Iterator[Dict], config: PersonCountConfig) -> List[FrameCount]:
        """Count people in frames, in batches of `batch_size`."""
        counts: List[FrameCount] = []
        batch: List[Dict] = []
        for frame_data in frames:
            batch.append(frame_data)
            if len(batch) >= self.batch_size:
                counts.extend(self.count_batch(batch, config))
                batch = []
        if batch:
            counts.extend(self.count_batch(batch, config))
        return counts

    def process_video(self, video_path: str, config: Optional[PersonCountConfig] = None) -> Dict:
        """👥 Count people over a video file and return results as a dict."""
        config = config or PersonCountConfig()
        job_id = f"yolo_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"

        logger.info(f"👥 [{job_id}] Counting people in {video_path}")

        with self._lock:
            frame_counts = self.count_frames(iter_sampled_frames(video_path, config.sample_fps), config)

        if not frame_counts:
            raise ValueError("No frames could be read from the video")

        video_duration = get_video_duration(video_path) or frame_counts[-1].timestamp
        counts = [fc.person_count for fc in frame_counts]
        max_count = max(counts)
        peak = next(fc for fc in frame_counts if fc.person_count == max_count)

        results = {
            'job_id': job_id,
            'video_path': video_path,
            'model': self.model_name,
            'timestamp': datetime.now().isoformat(),
            'video_duration': video_duration,
            'statistics': {
                'frames_analyzed': len(frame_counts),
                'frames_with_people': sum(1 for c in counts if c > 0),
                'max_persons': max_count,
                'min_persons': min(counts),
                'avg_persons': float(np.mean(counts)),
                'peak_timestamp': peak.timestamp,
            },
            'timeline': {
                'timestamps': [fc.timestamp for fc in frame_counts],
                'counts': counts,
            },
            'frame_counts': [asdict(fc) for fc in frame_counts],
        }

        logger.info(f"📊 [{job_id}] max={max_count} avg={results['statistics']['avg_persons']:.2f} "
                    f"frames={len(frame_counts)}")
        return results


if __name__ == "__main__":
    import argparse
    import json

    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Count people in a video file with YOLO")
    parser.add_argument("video_path")
    parser.add_argument("--model", default=YOLO_MODEL_NAME)
    parser.add_argument("--sample-fps", type=float, default=2.0)
    args = parser.parse_args()

    counter = PersonCounter(model_name=args.model)
    results = counter.process_video(args.video_path, PersonCountConfig(sample_fps=args.sample_fps))
    print(json.dumps({k: v for k, v in results.items() if k != 'frame_counts'}, indent=2))
