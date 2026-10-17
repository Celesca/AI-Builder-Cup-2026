import pytest
from fastapi.testclient import TestClient

import server
import voice_agent
from voice_agent import ElevenLabs, VoiceStore, build_chunks, retrieve
from lss_agent import load_knowledge

ANALYSIS = {
    "lss": {
        "summary": "The operator spends a lot of time walking to the parts rack.",
        "context": {"station_name": "Cell 3", "takt_time_s": 20, "cycle_time_s": 24, "operators": 1, "shift_hours": 8},
        "metrics": {"video_duration": 60, "va_percent": 40, "nnva_percent": 10, "nva_percent": 45,
                    "uncertain_percent": 5, "projected_nva_hours_per_shift": 3.6,
                    "waste_by_category": [{"category": "NVA_TRANSPORT", "label": "Walking and transport",
                                           "seconds": 21, "percent_of_person_time": 35,
                                           "projected_hours_per_shift": 2.8}]},
        "lss_cards": [{"id": "K1", "title": "Move the parts rack", "priority": "high", "category": "NVA_TRANSPORT",
                          "observation": "Walks 6 m per cycle", "root_cause": "Rack is far",
                          "recommendation": "Put the rack at the station",
                          "evidence": [{"start_time": 12, "end_time": 20, "note": "walks"}], "roi": None}],
        "safety_actions": [], "operator_questions": [],
    },
    "safety": {"safety_events": [{"rule_id": "helmet", "prompt": "no helmet", "severity": "high", "start_time": 42,
                                  "end_time": 47, "peak_confidence": 0.9, "description": "Worker without helmet"}],
               "activity": {"segments": []}},
}


class FakeResponse:
    def __init__(self, status_code=200, content=b"MP3", payload=None):
        self.status_code, self.content, self._payload, self.text = status_code, content, payload or {}, "err"

    def json(self):
        return self._payload


@pytest.fixture
def eleven(monkeypatch):
    client = ElevenLabs(api_key="key", store=VoiceStore(":memory:"))
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/speech-to-text"):
            return FakeResponse(payload={"text": " where is the helmet incident ", "language_code": "eng"})
        return FakeResponse()

    monkeypatch.setattr(voice_agent.requests, "post", fake_post)
    client.calls = calls
    return client


def test_chunks_cover_analysis_and_knowledge():
    ids = {c["id"] for c in build_chunks(ANALYSIS, load_knowledge())}
    assert {"summary", "metrics", "waste-NVA_TRANSPORT", "lss-K1", "incident-helmet-00:42"} <= ids
    assert any(i.startswith("KC-") for i in ids)


def test_retrieve_finds_the_matching_chunk():
    chunks = build_chunks(ANALYSIS, [])
    assert retrieve("when did the helmet incident happen", chunks)[0]["id"] == "incident-helmet-00:42"
    assert retrieve("zzzz qqqq", chunks) == []


def test_retrieve_handles_thai():
    chunks = [{"id": "a", "title": "ความปลอดภัย", "text": "คนงานไม่สวมหมวกนิรภัย", "source": "analysis"},
              {"id": "b", "title": "เวลา", "text": "เดินไปชั้นวางชิ้นส่วน", "source": "analysis"}]
    assert retrieve("หมวกนิรภัย", chunks)[0]["id"] == "a"


def test_tts_is_cached_in_the_database(eleven):
    audio, mime, cached = eleven.speak("Hello **there**")
    assert (audio, mime, cached) == (b"MP3", "audio/mpeg", False)
    assert eleven.calls[0][1]["json"]["text"] == "Hello there"
    assert eleven.speak("Hello there")[2] is True
    assert len(eleven.calls) == 1
    assert eleven.store.stats()["clips"] == 1


def test_cached_clip_plays_without_a_key(eleven):
    eleven.speak("Hello")
    eleven.api_key = ""
    assert eleven.speak("Hello")[2] is True
    with pytest.raises(RuntimeError):
        eleven.speak("A new sentence")


@pytest.fixture
def client(eleven, monkeypatch):
    monkeypatch.setattr(voice_agent, "_eleven", eleven)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(server, "PRELOAD_MODEL", False)
    with TestClient(server.app) as c:
        yield c


def test_chat_without_llm_key_returns_retrieval(client):
    body = client.post("/voice/chat", json={"message": "tell me about the helmet incident", "analysis": ANALYSIS}).json()
    assert body["source"] == "retrieval"
    assert "00:42" in body["reply"]
    assert body["sources"][0]["id"] == "incident-helmet-00:42"


def test_chat_with_llm_uses_the_retrieved_context(client, monkeypatch):
    seen = {}

    def fake_chat(messages, model, api_key, **kwargs):
        seen["prompt"] = messages[-1]["content"]
        return "The helmet incident starts at **0:42**.", {"cost": 0.0001}

    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(voice_agent, "chat", fake_chat)
    body = client.post("/voice/chat", json={"message": "helmet incident?", "analysis": ANALYSIS, "language": "th"}).json()
    assert "Worker without helmet" in seen["prompt"]
    assert body["reply"] == "The helmet incident starts at 0:42."
    assert body["source"] == "llm"


def test_speak_returns_mp3_and_reports_cache(client):
    first = client.post("/voice/speak", json={"text": "Hello"})
    second = client.post("/voice/speak", json={"text": "Hello"})
    assert first.headers["content-type"] == "audio/mpeg" and first.headers["x-voice-cache"] == "miss"
    assert second.headers["x-voice-cache"] == "hit"
    assert client.get("/voice/status").json()["audio_cache"]["clips"] == 1


def test_speak_without_key_is_503(client, eleven):
    eleven.api_key = ""
    assert client.post("/voice/speak", json={"text": "Hello"}).status_code == 503


def test_transcribe(client):
    response = client.post("/voice/transcribe", files={"file": ("a.webm", b"audio", "audio/webm")})
    assert response.json() == {"text": "where is the helmet incident", "language": "eng"}
