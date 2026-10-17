import threading

import cv2
import numpy as np
import pytest

from vlm_action_model import (
    VLMActionDetector, VLMDetection, VLMDetectionConfig, group_vlm_segments,
)


def make_detection(timestamp, passed=True, confidence=0.8):
    return VLMDetection(timestamp=timestamp, frame_idx=int(timestamp * 10), confidence=confidence,
                        answer="Yes" if passed else "No", vlm_description="", passed=passed)


def test_group_vlm_segments_splits_on_gap():
    detections = [make_detection(t) for t in [0, 1, 2, 7, 8]] + [make_detection(4, passed=False)]

    segments = group_vlm_segments(detections, "person running", max_gap=3.0)

    assert [(s.start_time, s.end_time, s.frame_count) for s in segments] == [(0, 2, 3), (7, 8, 2)]
    assert all(s.action_label == "person running" for s in segments)


def test_group_vlm_segments_empty_when_nothing_passed():
    assert group_vlm_segments([make_detection(0, passed=False)], "x") == []


class FakeJudgeDetector(VLMActionDetector):
    """Confidence = frame brightness / 255, so frames brighter than the threshold pass."""

    def __init__(self, batch_size=2):
        self.model_name, self.batch_size = "fake-vlm", batch_size
        self._lock = threading.Lock()
        self.batches = []

    def judge_images(self, images, prompt, config):
        self.batches.append(len(images))
        return [{'confidence': float(img.mean()) / 255, 'answer': 'Yes', 'description': f'frame {int(img.mean())}'}
                for img in images]


@pytest.fixture
def bright_video(tmp_path):
    """5 seconds at 10 FPS; brightness per second is 0, 250, 250, 0, 250."""
    path = str(tmp_path / "bright.mp4")
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 48))
    for second in [0, 250, 250, 0, 250]:
        for _ in range(10):
            writer.write(np.full((48, 64, 3), second, dtype=np.uint8))
    writer.release()
    return path


def test_process_video_thresholds_and_groups(bright_video):
    detector = FakeJudgeDetector(batch_size=2)

    results = detector.process_video(bright_video, "lights on",
                                     VLMDetectionConfig(confidence_threshold=0.5, segment_gap=1.5),
                                     include_timeline=True)

    assert detector.batches == [2, 2, 1]
    assert results['model'] == "fake-vlm"
    assert results['stats']['total_frames'] == 5
    assert results['stats']['passed_detections'] == 3
    assert [(s['start_time'], s['end_time']) for s in results['segments']] == [(1.0, 2.0), (4.0, 4.0)]
    assert results['timeline_data']['action_verb'] == "lights on"
    assert results['job_id'].startswith("vlm_")


def test_process_video_rejects_unreadable_video(tmp_path):
    with pytest.raises(ValueError):
        FakeJudgeDetector().process_video(str(tmp_path / "missing.mp4"), "x")


# ---- malformed model answers must not fail a whole video ----------------------------------------------------------

def test_salvage_reads_a_truncated_frame_answer():
    from vlm_action_model import salvage_frame
    text = '{"activity": "B", "activity_confidence": 80, "rules": [{"id": "helmet", "confidence": 90}, {"id": "run'
    assert salvage_frame(text) == {'activity': 'B', 'activity_confidence': 80,
                                   'rules': [{'id': 'helmet', 'confidence': 90}]}
    assert salvage_frame("I cannot help with that") is None


def _detector(monkeypatch, answers):
    import numpy as np
    import vlm_action_model as module
    detector = module.VLMActionDetector(api_key="k", batch_size=1)
    calls = iter(answers)
    monkeypatch.setattr(module, "chat", lambda *a, **k: (next(calls), {}))
    return detector, np.zeros((8, 8, 3), dtype=np.uint8)


class _Rule:
    def __init__(self, id):
        self.id, self.prompt = id, id


def test_malformed_answer_is_retried_once(monkeypatch):
    good = '{"activity": "A", "activity_confidence": 90, "rules": [{"id": "helmet", "confidence": 80}]}'
    detector, image = _detector(monkeypatch, ['{"activity": "A", "rules": [{"id": "helmet", "confidence": 80}', good])
    [frame] = detector.analyze_frames([image], [_Rule("helmet")], "q", ["x", "y"])
    assert frame['rule_confidences'] == {'helmet': 0.8}
    assert detector.usage_snapshot()['failed_frames'] == 0


def test_unreadable_frame_counts_as_unclear_not_an_error(monkeypatch):
    detector, image = _detector(monkeypatch, ["sorry", "sorry again"])
    [frame] = detector.analyze_frames([image], [_Rule("helmet")], "q", ["x", "y"])
    assert frame['rule_confidences'] == {'helmet': 0.0}
    assert max(frame['activity_probs'].values()) == 0.5
    assert detector.usage_snapshot()['failed_frames'] == 1
