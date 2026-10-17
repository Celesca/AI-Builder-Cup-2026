import io
import os
import threading

import pytest
from fastapi.testclient import TestClient

import server
from video_action_model import DetectionConfig


class FakeDetector:
    device = "cpu"
    nlp = None

    def __init__(self):
        self.calls = []

    def process_video(self, video_path, prompt, config=None, include_timeline=False):
        config.normalized_weights()
        self.calls.append({'video_path': video_path, 'prompt': prompt, 'config': config})
        detection = {
            'timestamp': 1.0, 'frame_idx': 30, 'confidence': 0.8,
            'blip_description': 'a man running down a street',
            'similarity_scores': {'person': 1.0, 'action': 0.9, 'context': 0.1, 'weighted': 0.8},
            'passed': True,
        }
        return {
            'job_id': 'job_test', 'video_path': video_path, 'prompt': prompt, 'action_verb': 'run',
            'timestamp': '2026-10-15T00:00:00', 'video_duration': 5.0,
            'stats': {'total_frames': 5, 'total_detections': 5, 'passed_detections': 1,
                      'success_rate': 20.0, 'segments_found': 1},
            'passed_detections_only': [detection],
            'segments': [{'start_time': 1.0, 'end_time': 1.0, 'confidence': 0.8, 'frame_count': 1,
                          'action_label': 'run', 'detections': [detection]}],
            'timeline_data': {
                'job_id': 'job_test', 'prompt': prompt, 'action_verb': 'run', 'video_duration': 5.0,
                'segments': [{'index': 0, 'start_time': 1.0, 'end_time': 1.0, 'duration': 0.0,
                              'confidence': 0.8, 'action_label': 'run', 'frame_count': 1}],
            } if include_timeline else None,
        }


class FakeCounter:
    device = "cpu"

    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def process_video(self, video_path, config=None):
        self.calls.append({'video_path': video_path, 'config': config, 'thread': threading.get_ident()})
        if self.error:
            raise self.error
        return {
            'job_id': 'yolo_test', 'video_path': video_path, 'model': 'yolov8n.pt',
            'timestamp': '2026-10-15T00:00:00', 'video_duration': 5.0,
            'statistics': {'frames_analyzed': 2, 'frames_with_people': 1, 'max_persons': 2, 'min_persons': 0,
                           'avg_persons': 1.0, 'peak_timestamp': 0.0},
            'timeline': {'timestamps': [0.0, 0.5], 'counts': [2, 0]},
            'frame_counts': [
                {'frame_idx': 0, 'timestamp': 0.0, 'person_count': 2, 'detections': [
                    {'person_id': i, 'confidence': 0.9, 'x1': 0, 'y1': 0, 'x2': 10, 'y2': 20,
                     'center_x': 5, 'center_y': 10} for i in range(2)]},
                {'frame_idx': 15, 'timestamp': 0.5, 'person_count': 0, 'detections': []},
            ],
        }


class FakeVLMDetector:
    model_name = "qwen/qwen3.7-flash"

    def __init__(self):
        self.calls = []

    def process_video(self, video_path, prompt, config=None, include_timeline=False):
        self.calls.append({'video_path': video_path, 'prompt': prompt, 'config': config})
        detection = {
            'timestamp': 2.0, 'frame_idx': 60, 'confidence': 0.93, 'answer': 'Yes',
            'vlm_description': 'A worker is welding without a helmet.', 'passed': True,
        }
        return {
            'job_id': 'vlm_test', 'video_path': video_path, 'prompt': prompt, 'model': self.model_name,
            'timestamp': '2026-10-15T00:00:00', 'video_duration': 5.0,
            'stats': {'total_frames': 5, 'passed_detections': 1, 'success_rate': 20.0, 'segments_found': 1},
            'passed_detections_only': [detection],
            'segments': [{'start_time': 2.0, 'end_time': 2.0, 'confidence': 0.93, 'frame_count': 1,
                          'action_label': prompt, 'detections': [detection]}],
            'timeline_data': {
                'job_id': 'vlm_test', 'prompt': prompt, 'action_verb': prompt, 'video_duration': 5.0,
                'segments': [{'index': 0, 'start_time': 2.0, 'end_time': 2.0, 'duration': 0.0,
                              'confidence': 0.93, 'action_label': prompt, 'frame_count': 1}],
            } if include_timeline else None,
        }


@pytest.fixture
def fake_vlm_detector():
    return FakeVLMDetector()


@pytest.fixture
def fake_detector():
    return FakeDetector()


@pytest.fixture
def fake_counter():
    return FakeCounter()


@pytest.fixture
def client(fake_detector, fake_vlm_detector, fake_counter, monkeypatch):
    monkeypatch.setattr(server, "PRELOAD_MODEL", False)
    monkeypatch.setattr(server, "load_counter", lambda: fake_counter)
    server.app.dependency_overrides[server.get_detector] = lambda: fake_detector
    server.app.dependency_overrides[server.get_vlm_detector] = lambda: fake_vlm_detector
    server.app.dependency_overrides[server.get_counter] = lambda: fake_counter
    with TestClient(server.app) as c:
        yield c
    server.app.dependency_overrides.clear()


def upload(client, filename="clip.mp4", content_type="video/mp4", **form):
    data = {"prompt": "person running", **form}
    files = {"file": (filename, io.BytesIO(b"fake-video-bytes"), content_type)}
    return client.post("/video_action/detect/upload", data=data, files=files)


def test_upload_returns_detection_response(client, fake_detector):
    response = upload(client, action_weight="0.9", sample_fps="2")

    assert response.status_code == 200
    body = response.json()
    assert body['success'] is True
    assert body['action_verb'] == 'run'
    assert body['video_path'] == 'clip.mp4'
    assert body['segments'][0]['detections'][0]['blip_description'] == 'a man running down a street'
    assert body['timeline_visualization']['job_id'] == 'job_test'
    assert body['timeline_visualization']['segments'][0]['duration'] == 0.0

    config = fake_detector.calls[0]['config']
    assert isinstance(config, DetectionConfig)
    assert config.action_weight == 0.9
    assert config.sample_fps == 2.0


def test_upload_accepts_octet_stream_with_video_extension(client):
    assert upload(client, filename="clip.mov", content_type="application/octet-stream").status_code == 200


def test_upload_rejects_non_video(client):
    response = upload(client, filename="notes.txt", content_type="text/plain")
    assert response.status_code == 400


def test_upload_rejects_out_of_range_weight(client):
    assert upload(client, action_weight="1.5").status_code == 422


def test_upload_rejects_all_zero_weights(client):
    response = upload(client, person_weight="0", action_weight="0", context_weight="0")
    assert response.status_code == 422


def test_upload_temp_file_is_removed(client, fake_detector):
    import os
    upload(client)
    assert not os.path.exists(fake_detector.calls[0]['video_path'])


def test_url_rejects_youtube(client):
    response = client.post("/video_action/detect",
                           json={"video_url": "https://www.youtube.com/watch?v=abc", "prompt": "person running"})
    assert response.status_code == 400


def test_url_rejects_non_http_scheme(client):
    response = client.post("/video_action/detect", json={"video_url": "file:///etc/passwd", "prompt": "x"})
    assert response.status_code == 400


def test_url_downloads_and_detects(client, fake_detector, monkeypatch, tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"bytes")
    monkeypatch.setattr(server, "download_video_from_url", lambda url: str(video))

    response = client.post("/video_action/detect",
                           json={"video_url": "https://example.com/v.mp4", "prompt": "person running",
                                 "return_timeline": False})

    assert response.status_code == 200
    assert response.json()['video_path'] == "https://example.com/v.mp4"
    assert response.json()['timeline_visualization'] is None
    assert not video.exists()


def test_detector_unavailable_returns_503(monkeypatch):
    monkeypatch.setattr(server, "PRELOAD_MODEL", False)
    monkeypatch.setattr(server, "load_detector", lambda: None)
    with TestClient(server.app) as c:
        response = upload(c)
    assert response.status_code == 503


def test_upload_counts_people_by_default(client, fake_counter):
    response = upload(client, person_confidence="0.3", person_sample_fps="4")

    assert response.status_code == 200
    body = response.json()
    assert body['person_count']['statistics']['max_persons'] == 2
    assert body['person_count']['frame_counts'][0]['detections'][1]['person_id'] == 1
    assert body['person_count_error'] is None

    config = fake_counter.calls[0]['config']
    assert (config.confidence_threshold, config.sample_fps) == (0.3, 4.0)


def test_upload_skips_counting_when_disabled(client, fake_counter):
    response = upload(client, count_people="false")

    assert response.status_code == 200
    assert response.json()['person_count'] is None
    assert response.json()['person_count_error'] is None
    assert fake_counter.calls == []


def test_counting_failure_does_not_fail_action_detection(client, monkeypatch):
    monkeypatch.setattr(server, "load_counter", lambda: FakeCounter(error=RuntimeError("boom")))

    response = upload(client)

    assert response.status_code == 200
    assert response.json()['person_count'] is None
    assert response.json()['person_count_error'] == "boom"
    assert response.json()['segments']


def test_counter_unavailable_reports_error(client, monkeypatch):
    monkeypatch.setattr(server, "load_counter", lambda: None)

    response = upload(client)

    assert response.status_code == 200
    assert response.json()['person_count'] is None
    assert response.json()['person_count_error'].startswith("Person counting is not available")


def test_counting_runs_in_parallel_with_action_detection(client, fake_detector, fake_counter):
    # Both models wait on the same barrier: it only releases if they run at the same time
    barrier = threading.Barrier(2, timeout=5)
    detect, count = fake_detector.process_video, fake_counter.process_video
    fake_detector.process_video = lambda *a, **kw: (barrier.wait(), detect(*a, **kw))[1]
    fake_counter.process_video = lambda *a, **kw: (barrier.wait(), count(*a, **kw))[1]

    response = upload(client)

    assert response.status_code == 200
    assert response.json()['person_count']['statistics']['max_persons'] == 2


def test_person_count_upload(client, fake_counter):
    files = {"file": ("clip.mp4", io.BytesIO(b"fake-video-bytes"), "video/mp4")}
    response = client.post("/person_count/detect/upload", data={"person_sample_fps": "1"}, files=files)

    assert response.status_code == 200
    body = response.json()
    assert body['success'] is True
    assert body['video_path'] == 'clip.mp4'
    assert body['timeline']['counts'] == [2, 0]
    assert fake_counter.calls[0]['config'].sample_fps == 1.0


def test_person_count_upload_rejects_non_video(client):
    files = {"file": ("notes.txt", io.BytesIO(b"x"), "text/plain")}
    assert client.post("/person_count/detect/upload", files=files).status_code == 400


def test_person_count_url(client, monkeypatch, tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"bytes")
    monkeypatch.setattr(server, "download_video_from_url", lambda url: str(video))

    response = client.post("/person_count/detect", json={"video_url": "https://example.com/v.mp4"})

    assert response.status_code == 200
    assert response.json()['video_path'] == "https://example.com/v.mp4"
    assert not video.exists()


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert 'detector_loaded' in response.json()


def test_openapi_json_is_up_to_date():
    # Regenerate with: python server.py --export-openapi openapi.json
    import json
    from pathlib import Path
    committed = json.loads((Path(__file__).parent.parent / "openapi.json").read_text())
    assert committed == server.app.openapi(), "openapi.json is stale: run python server.py --export-openapi openapi.json"


def test_openapi_documents_all_endpoints():
    spec = server.app.openapi()
    for path in ["/video_action/detect", "/video_action/detect/upload",
                 "/vlm_action/detect", "/vlm_action/detect/upload",
                 "/safety/detect", "/safety/detect/upload", "/analysis/analyze", "/analysis/analyze/upload",
                 "/person_count/detect", "/person_count/detect/upload"]:
        responses = spec['paths'][path]['post']['responses']
        assert {'200', '400', '413', '422', '500', '503'} <= set(responses)
    assert spec['paths']['/health']['get']['responses']['200']['content']['application/json']['schema'] == \
        {'$ref': '#/components/schemas/HealthResponse'}


def vlm_upload(client, filename="clip.mp4", content_type="video/mp4", **form):
    data = {"prompt": "worker not wearing a helmet", **form}
    files = {"file": (filename, io.BytesIO(b"fake-video-bytes"), content_type)}
    return client.post("/vlm_action/detect/upload", data=data, files=files)


def test_vlm_upload_returns_detection_response(client, fake_vlm_detector, fake_counter):
    response = vlm_upload(client, confidence_threshold="0.7", sample_fps="2", describe="false")

    assert response.status_code == 200
    body = response.json()
    assert body['success'] is True
    assert body['model'] == "qwen/qwen3.7-flash"
    assert body['video_path'] == 'clip.mp4'
    assert body['passed_detections'][0]['answer'] == 'Yes'
    assert body['segments'][0]['action_label'] == 'worker not wearing a helmet'
    assert body['timeline_visualization']['job_id'] == 'vlm_test'
    assert body['person_count']['statistics']['max_persons'] == 2

    config = fake_vlm_detector.calls[0]['config']
    assert (config.confidence_threshold, config.sample_fps, config.describe) == (0.7, 2.0, False)
    assert not os.path.exists(fake_vlm_detector.calls[0]['video_path'])


def test_vlm_upload_rejects_non_video(client):
    assert vlm_upload(client, filename="notes.txt", content_type="text/plain").status_code == 400


def test_vlm_upload_rejects_out_of_range_threshold(client):
    assert vlm_upload(client, confidence_threshold="1.5").status_code == 422


def test_vlm_url_downloads_and_detects(client, fake_counter, monkeypatch, tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"bytes")
    monkeypatch.setattr(server, "download_video_from_url", lambda url: str(video))

    response = client.post("/vlm_action/detect",
                           json={"video_url": "https://example.com/v.mp4", "prompt": "person running",
                                 "return_timeline": False, "count_people": False})

    assert response.status_code == 200
    assert response.json()['timeline_visualization'] is None
    assert response.json()['person_count'] is None
    assert fake_counter.calls == []
    assert not video.exists()


def test_vlm_url_rejects_youtube(client):
    response = client.post("/vlm_action/detect",
                           json={"video_url": "https://youtu.be/abc", "prompt": "person running"})
    assert response.status_code == 400


def test_vlm_counting_runs_in_parallel(client, fake_vlm_detector, fake_counter):
    barrier = threading.Barrier(2, timeout=5)
    detect, count = fake_vlm_detector.process_video, fake_counter.process_video
    fake_vlm_detector.process_video = lambda *a, **kw: (barrier.wait(), detect(*a, **kw))[1]
    fake_counter.process_video = lambda *a, **kw: (barrier.wait(), count(*a, **kw))[1]

    assert vlm_upload(client).status_code == 200


def test_vlm_detector_unavailable_returns_503(monkeypatch):
    monkeypatch.setattr(server, "PRELOAD_MODEL", False)
    monkeypatch.setattr(server, "load_vlm_detector", lambda: None)
    with TestClient(server.app) as c:
        assert vlm_upload(c).status_code == 503


def test_vlm_status(client):
    response = client.get("/vlm_action/status")
    assert response.status_code == 200
    assert response.json()['model'] == server.VLM_MODEL
