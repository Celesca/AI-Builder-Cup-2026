import pytest
from fastapi.testclient import TestClient

import server
from lss_agent import LssAgent
from test_api import FakeCounter
from test_safety_agent import FakeVLM


@pytest.fixture
def video_bytes(tmp_path):
    import cv2
    import numpy as np
    path = str(tmp_path / "work.mp4")
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 48))
    for value in [220] * 30 + [20] * 30:
        writer.write(np.full((48, 64, 3), value, dtype=np.uint8))
    writer.release()
    with open(path, 'rb') as f:
        return f.read()


@pytest.fixture
def api_client(monkeypatch):
    counter = FakeCounter()
    monkeypatch.setattr(server, "PRELOAD_MODEL", False)
    monkeypatch.setattr(server, "load_counter", lambda: counter)
    server.app.dependency_overrides[server.get_vlm_detector] = FakeVLM
    server.app.dependency_overrides[server.get_lss_agent] = lambda: LssAgent(api_key="")
    with TestClient(server.app) as c:
        c.counter = counter
        yield c
    server.app.dependency_overrides.clear()


def test_analysis_upload_runs_safety_then_lss(api_client, video_bytes):
    response = api_client.post(
        "/analysis/analyze/upload",
        data={"rules": "high: a person not wearing a helmet\nrunning", "station_name": "Cell 3",
              "cycle_time_s": "20", "language": "th"},
        files={"file": ("work.mp4", video_bytes, "video/mp4")},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body['success'] is True and body['video_path'] == "work.mp4"
    assert [r['id'] for r in body['safety']['rules']] == ["a_person_not_wearing_a_helmet", "running"]
    assert body['safety']['safety_events'][0]['severity'] == "high"
    assert body['safety']['activity']['summary']['va_percent'] == 50.0
    assert body['person_count']['statistics']['max_persons'] == 2

    lss = body['lss']
    assert lss['source'] == "rules"
    assert lss['context']['station_name'] == "Cell 3" and lss['context']['language'] == "th"
    assert lss['lss_cards'][0]['category'] == "NVA_WAITING"
    assert lss['metrics']['people']['max_persons'] == 2
    assert lss['safety_actions'][0]['kb_card_ids'] == ["KC-SAF-01"]


def test_safety_upload_default_rules_and_no_counting(api_client, video_bytes):
    response = api_client.post("/safety/detect/upload", data={"count_people": "false", "include_snapshots": "false"},
                                 files={"file": ("work.mp4", video_bytes, "video/mp4")})

    assert response.status_code == 200, response.text
    body = response.json()
    assert [r['id'] for r in body['rules']] == ["no_helmet", "running", "phone_use", "person_down"]
    assert body['person_count'] is None and api_client.counter.calls == []
    assert body['safety_events'][0]['snapshot'] is None


def test_safety_result_can_be_sent_to_lss(api_client, video_bytes):
    safety = api_client.post("/safety/detect/upload", data={"rules": "high: helmet missing"},
                               files={"file": ("work.mp4", video_bytes, "video/mp4")}).json()
    person_count = safety.pop('person_count')
    for key in ('success', 'person_count_error'):
        safety.pop(key)

    response = api_client.post("/lss/suggest", json={
        "safety": safety, "person_count": person_count, "context": {"cycle_time_s": 30}, "use_llm": False})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body['metrics']['cycles_per_shift'] == 960
    assert body['safety_actions'][0]['rule_id'] == "helmet_missing"


def test_rules_json_and_invalid_rules(api_client, video_bytes):
    files = {"file": ("work.mp4", video_bytes, "video/mp4")}
    ok = api_client.post("/safety/detect/upload", files=files,
                           data={"rules": '[{"prompt": "a helmet is missing", "severity": "high", "threshold": 0.9}]'})
    assert ok.status_code == 200
    assert ok.json()['rules'][0] == {'id': 'a_helmet_is_missing', 'prompt': 'a helmet is missing',
                                     'severity': 'high', 'threshold': 0.9}

    bad = api_client.post("/safety/detect/upload", files={"file": ("work.mp4", video_bytes, "video/mp4")},
                            data={"rules": '[{"severity": "high"}]'})
    assert bad.status_code == 422


def test_analysis_url_cleans_up(api_client, video_bytes, monkeypatch, tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(video_bytes)
    monkeypatch.setattr(server, "download_video_from_url", lambda url: str(video))

    response = api_client.post("/analysis/analyze", json={
        "video_url": "https://example.com/v.mp4", "use_llm": False, "count_people": False,
        "rules": [{"prompt": "a person not wearing a helmet", "severity": "high"}]})

    assert response.status_code == 200, response.text
    assert response.json()['lss']['source'] == "rules"
    assert not video.exists()


def test_unreadable_upload_is_422(api_client):
    response = api_client.post("/analysis/analyze/upload", files={"file": ("x.mp4", b"not a video", "video/mp4")})
    assert response.status_code == 422


def test_lss_status_and_demo(api_client, monkeypatch):
    monkeypatch.setattr(server, "_lss_agent", LssAgent(api_key="sk", model="m/x"))
    status = api_client.get("/lss/status").json()
    assert status['llm_configured'] is True and status['model'] == "m/x"
    assert status['knowledge_cards'] >= 10 and len(status['default_rules']) == 4

    demo = api_client.get("/demo")
    assert demo.status_code == 200 and "VALZ pipeline demo" in demo.text


def test_vlm_status_reports_key_and_model(api_client, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    status = api_client.get("/vlm_action/status").json()
    assert status['api_key_configured'] is True and status['model'] == server.VLM_MODEL
    assert 'device' not in status

    monkeypatch.delenv("OPENROUTER_API_KEY")
    assert api_client.get("/vlm_action/status").json()['api_key_configured'] is False


def test_vlm_detector_needs_api_key(monkeypatch):
    monkeypatch.setattr(server, "_vlm_detector", None)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    assert server.load_vlm_detector() is None
    assert server._vlm_detector_error == "OPENROUTER_API_KEY is not set"

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    detector = server.load_vlm_detector()
    assert detector.model_name == server.VLM_MODEL and detector.batch_size == server.VLM_CONCURRENCY
    monkeypatch.setattr(server, "_vlm_detector", None)


def test_health_reflects_vlm_readiness(monkeypatch):
    monkeypatch.setattr(server, "PRELOAD_MODEL", False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(server, "_detector", None)
    monkeypatch.setattr(server, "_vlm_detector", None)
    with TestClient(server.app) as c:
        degraded = c.get("/health").json()
        monkeypatch.setattr(server, "_vlm_detector", object())
        healthy = c.get("/health").json()
    assert degraded['status'] == "degraded" and "OPENROUTER_API_KEY" in degraded['message']
    assert healthy['status'] == "healthy" and healthy['vlm_detector_loaded'] is True
