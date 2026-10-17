import threading
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
import torch

from person_count_model import PersonCountConfig, PersonCounter


class FakeYOLO:
    """Returns one person per 100 brightness levels of the frame, so counts are predictable."""

    def __init__(self):
        self.calls = []

    def predict(self, images, conf, classes, device, verbose):
        self.calls.append({'batch': len(images), 'conf': conf, 'classes': classes})
        results = []
        for img in images:
            n = int(img.mean()) // 100
            xyxy = torch.tensor([[10.0 * i, 0.0, 10.0 * i + 9, 20.0] for i in range(n)]).reshape(n, 4)
            results.append(SimpleNamespace(boxes=SimpleNamespace(xyxy=xyxy, conf=torch.full((n,), 0.9))))
        return results


def make_counter(batch_size=2):
    counter = PersonCounter.__new__(PersonCounter)
    counter.model_name, counter.device, counter.batch_size = "fake.pt", "cpu", batch_size
    counter._lock = threading.Lock()
    counter.model = FakeYOLO()
    return counter


@pytest.fixture
def people_video(tmp_path):
    """4 seconds at 10 FPS; brightness (= fake person count * 100) is 0, 100, 200, 0 per second."""
    path = str(tmp_path / "people.mp4")
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 48))
    for second in [0, 1, 2, 0]:
        for _ in range(10):
            writer.write(np.full((48, 64, 3), second * 100 + 20, dtype=np.uint8))
    writer.release()
    return path


def test_process_video_counts_and_stats(people_video):
    counter = make_counter()

    results = counter.process_video(people_video, PersonCountConfig(confidence_threshold=0.3, sample_fps=1.0))

    assert results['timeline'] == {'timestamps': [0.0, 1.0, 2.0, 3.0], 'counts': [0, 1, 2, 0]}
    assert results['statistics'] == {
        'frames_analyzed': 4, 'frames_with_people': 2, 'max_persons': 2, 'min_persons': 0,
        'avg_persons': 0.75, 'peak_timestamp': 2.0,
    }
    assert results['video_duration'] == pytest.approx(4.0)
    assert results['frame_counts'][2]['detections'][1] == {
        'person_id': 1, 'confidence': pytest.approx(0.9), 'x1': 10, 'y1': 0, 'x2': 19, 'y2': 20,
        'center_x': 14, 'center_y': 10,
    }


def test_process_video_batches_frames_and_filters_people(people_video):
    counter = make_counter(batch_size=3)

    counter.process_video(people_video, PersonCountConfig(confidence_threshold=0.3, sample_fps=1.0))

    assert [c['batch'] for c in counter.model.calls] == [3, 1]
    assert all(c['classes'] == [0] and c['conf'] == 0.3 for c in counter.model.calls)


def test_process_video_rejects_missing_file(tmp_path):
    with pytest.raises(ValueError):
        make_counter().process_video(str(tmp_path / "missing.mp4"))
