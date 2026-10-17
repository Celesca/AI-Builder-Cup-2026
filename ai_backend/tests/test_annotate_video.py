import cv2
import numpy as np

from annotate_video import active_rules, render_annotated_video

RULES = [{'id': 'no_helmet', 'threshold': 0.6}, {'id': 'running', 'threshold': 0.6}]


def test_active_rules_violation_and_near_miss():
    hits = active_rules({'no_helmet': 0.7, 'running': 0.5}, RULES, 0.15)
    assert hits == [('no_helmet', 'VIOLATION', 0.7), ('running', 'NEAR MISS', 0.5)]
    assert active_rules({'no_helmet': 0.2, 'running': 0.1}, RULES, 0.15) == []


class FakeBoxes:
    def __init__(self, a): self.xyxy = type('T', (), {'cpu': lambda s: type('N', (), {'numpy': lambda s2: a})()})()


class FakeCounter:
    import threading
    _lock = threading.Lock()
    device = 'cpu'

    class model:
        @staticmethod
        def predict(*a, **k):
            return [type('R', (), {'boxes': FakeBoxes(np.array([[20, 30, 100, 150]]))})()]


def test_render(tmp_path):
    src = str(tmp_path / "in.mp4")
    w = cv2.VideoWriter(src, cv2.VideoWriter_fourcc(*'mp4v'), 10, (320, 240))
    for _ in range(30):
        w.write(np.zeros((240, 320, 3), np.uint8))
    w.release()
    result = {'rules': RULES, 'activity': {'timeline': [
        {'timestamp': 0.0, 'rule_confidences': {'no_helmet': 0.1}},
        {'timestamp': 1.0, 'rule_confidences': {'no_helmet': 0.9}},
        {'timestamp': 2.0, 'rule_confidences': {'no_helmet': 0.5}}]}}
    out = str(tmp_path / "out.mp4")
    stats = render_annotated_video(src, out, result, FakeCounter())
    assert stats['frames'] == 30 and stats['annotated_frames'] == 20
    cap = cv2.VideoCapture(out)
    ok, frame = cap.read()
    assert ok and frame.shape[:2] == (240, 320)
