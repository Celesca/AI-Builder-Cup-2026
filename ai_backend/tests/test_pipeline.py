import cv2
import numpy as np
import pytest

from video_action_model import (
    Detection, DetectionConfig, get_video_duration, group_segments, iter_sampled_frames,
)


def make_detection(timestamp, passed=True, confidence=0.6):
    return Detection(timestamp=timestamp, frame_idx=int(timestamp * 30), confidence=confidence,
                     blip_description="", similarity_scores={}, passed=passed)


def test_group_segments_splits_on_gap():
    detections = [make_detection(t) for t in [0, 1, 2, 7, 8]] + [make_detection(4, passed=False)]

    segments = group_segments(detections, "run", max_gap=3.0)

    assert [(s.start_time, s.end_time, s.frame_count) for s in segments] == [(0, 2, 3), (7, 8, 2)]
    assert all(s.action_label == "run" for s in segments)


def test_group_segments_empty_when_nothing_passed():
    assert group_segments([make_detection(0, passed=False)], "run") == []


def test_config_normalizes_weights():
    assert DetectionConfig(person_weight=1, action_weight=1, context_weight=2).normalized_weights() == (0.25, 0.25, 0.5)


def test_config_rejects_zero_weights():
    with pytest.raises(ValueError):
        DetectionConfig(person_weight=0, action_weight=0, context_weight=0).normalized_weights()


@pytest.fixture
def synthetic_video(tmp_path):
    path = str(tmp_path / "synthetic.mp4")
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 48))
    for i in range(50):  # 5 seconds at 10 FPS
        writer.write(np.full((48, 64, 3), i * 5, dtype=np.uint8))
    writer.release()
    return path


def test_iter_sampled_frames_samples_at_requested_fps(synthetic_video):
    frames = list(iter_sampled_frames(synthetic_video, sample_fps=1.0))

    assert [f['frame_idx'] for f in frames] == [0, 10, 20, 30, 40]
    assert [f['timestamp'] for f in frames] == [0.0, 1.0, 2.0, 3.0, 4.0]
    assert frames[0]['frame'].shape == (48, 64, 3)


def test_get_video_duration(synthetic_video):
    assert get_video_duration(synthetic_video) == pytest.approx(5.0)


def test_iter_sampled_frames_rejects_missing_file(tmp_path):
    with pytest.raises(ValueError):
        list(iter_sampled_frames(str(tmp_path / "missing.mp4")))
