"""Video helpers shared by the action detectors and the Safety Agent (OpenCV + NumPy only, no ML libraries)."""

from typing import Dict, Iterator, List, Optional

import cv2
import numpy as np


def iter_sampled_frames(video_path: str, sample_fps: float = 1.0) -> Iterator[Dict]:
    """Yield RGB frames at roughly `sample_fps`, reading the video sequentially."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video: {video_path}")

    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        if not fps or fps <= 0 or np.isnan(fps):
            raise ValueError("Video has no valid FPS metadata")

        step = max(1, int(round(fps / sample_fps)))
        frame_idx = 0
        while cap.grab():
            if frame_idx % step == 0:
                ret, frame = cap.retrieve()
                if ret:
                    yield {
                        'frame': cv2.cvtColor(frame, cv2.COLOR_BGR2RGB),
                        'frame_idx': frame_idx,
                        'timestamp': frame_idx / fps,
                    }
            frame_idx += 1
    finally:
        cap.release()


def get_video_duration(video_path: str) -> float:
    cap = cv2.VideoCapture(video_path)
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        if not fps or fps <= 0 or total_frames <= 0:
            return 0.0
        return float(total_frames / fps)
    finally:
        cap.release()


def create_timeline_viz_data(segments: List, prompt: str, action_verb: str, job_id: str,
                             video_duration: float) -> Optional[Dict]:
    """🎬 Timeline data for the frontend to render (segments need start_time, end_time, confidence, frame_count)."""
    if not segments:
        return None

    return {
        'job_id': job_id,
        'prompt': prompt,
        'action_verb': action_verb,
        'video_duration': video_duration,
        'segments': [
            {
                'index': i,
                'start_time': s.start_time,
                'end_time': s.end_time,
                'duration': s.end_time - s.start_time,
                'confidence': s.confidence,
                'action_label': action_verb,
                'frame_count': s.frame_count,
            }
            for i, s in enumerate(segments)
        ],
    }
