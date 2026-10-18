import json

import numpy as np
import pytest

import openrouter_client
from safety_agent import ACTIVITY_CLASSES, ACTIVITY_QUESTION, SafetyAgent, SafetyAgentConfig, SafetyRule
from vlm_action_model import VLMActionDetector, VLMDetectionConfig, probs_from_choice, to_fraction

OPTIONS = [c.option for c in ACTIVITY_CLASSES]
RULES = [SafetyRule("no_helmet", "a person not wearing a helmet", "high"), SafetyRule("running", "a person running")]


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code, self._payload, self.text = status_code, payload, json.dumps(payload)

    def json(self):
        return self._payload


def reply(content, cost=0.0001):
    return FakeResponse(200, {'choices': [{'message': {'content': json.dumps(content)}}],
                              'usage': {'prompt_tokens': 600, 'completion_tokens': 40, 'cost': cost}})


@pytest.fixture
def vlm():
    return VLMActionDetector(api_key="sk-test", model_name="test/vision", batch_size=2)


def frame(value):
    return np.full((48, 64, 3), value, dtype=np.uint8)


def test_to_fraction_and_probs():
    assert [to_fraction(v) for v in (80, "80", 0.8, 0, 100, 250, None, "x")] == [0.8, 0.8, 0.8, 0.0, 1.0, 1.0, 0.0, 0.0]
    probs = probs_from_choice(["a", "b", "c"], "b", 0.8)
    assert probs == {"a": pytest.approx(0.1), "b": 0.8, "c": pytest.approx(0.1)}
    assert probs_from_choice(["a", "b"], "Z", 0.6)["b"] == 0.6   # unknown letter -> last option


def test_analyze_frames_one_request_per_frame(vlm, monkeypatch):
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append(json)
        return reply({'activity': 'G', 'activity_confidence': 90,
                      'rules': [{'id': 'no_helmet', 'confidence': 85}, {'id': 'running', 'confidence': 5}]})

    monkeypatch.setattr(openrouter_client.requests, "post", fake_post)
    results = vlm.analyze_frames([frame(10), frame(200)], RULES, ACTIVITY_QUESTION, OPTIONS)

    assert len(calls) == 2                                          # frames, not frames x questions
    assert results[0]['rule_confidences'] == {'no_helmet': 0.85, 'running': 0.05}
    assert results[0]['activity_probs'][OPTIONS[6]] == 0.9           # letter G = waiting
    body = calls[0]
    assert body['model'] == "test/vision" and body['response_format']['type'] == "json_schema"
    content = body['messages'][0]['content']
    assert content[0]['image_url']['url'].startswith("data:image/jpeg;base64,")
    assert "no_helmet: a person not wearing a helmet" in content[1]['text'] and "G. " in content[1]['text']
    assert vlm.usage_snapshot() == {'calls': 2, 'prompt_tokens': 1200, 'completion_tokens': 80, 'cost': pytest.approx(0.0002),
                                      'failed_frames': 0}


def test_missing_rule_in_answer_counts_as_not_visible(vlm, monkeypatch):
    monkeypatch.setattr(openrouter_client.requests, "post", lambda *a, **kw: reply(
        {'activity': 'A', 'activity_confidence': 70, 'rules': [{'id': 'running', 'confidence': 90}]}))
    [result] = vlm.analyze_frames([frame(1)], RULES, ACTIVITY_QUESTION, OPTIONS)
    assert result['rule_confidences'] == {'no_helmet': 0.0, 'running': 0.9}


def test_judge_images_turns_answer_confidence_into_p_yes(monkeypatch):
    vlm = VLMActionDetector(api_key="sk-test", model_name="test/vision", batch_size=1)   # one worker: answers arrive in frame order
    answers = iter([{'answer': 'No', 'confidence': 90, 'description': ''},
                    {'answer': 'Yes', 'confidence': 80, 'description': 'A man runs.'}])
    monkeypatch.setattr(openrouter_client.requests, "post", lambda *a, **kw: reply(next(answers)))

    no, yes = vlm.judge_images([frame(1), frame(2)], "person running", VLMDetectionConfig(describe=True))

    assert (no['answer'], round(no['confidence'], 2)) == ("No", 0.1)
    assert (yes['answer'], yes['confidence'], yes['description']) == ("Yes", 0.8, "A man runs.")


def test_safety_agent_runs_on_cloud_backend_and_reports_usage(vlm, monkeypatch, tmp_path):
    import cv2

    path = str(tmp_path / "work.mp4")
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 48))
    for value in [220] * 20 + [20] * 20:
        writer.write(np.full((48, 64, 3), value, dtype=np.uint8))
    writer.release()

    def fake_post(url, headers, json, timeout):
        text = json['messages'][0]['content'][1]['text']
        if 'Return JSON only' in text:
            # Alternate on image size is not possible (same size): answer by call order is racy, so answer "working"
            return reply({'activity': 'A', 'activity_confidence': 90,
                          'rules': [{'id': 'no_helmet', 'confidence': 90}, {'id': 'running', 'confidence': 0}]})
        return FakeResponse(200, {'choices': [{'message': {'content': 'A worker at a bench.'}}],
                                  'usage': {'prompt_tokens': 300, 'completion_tokens': 10, 'cost': 0.00005}})

    monkeypatch.setattr(openrouter_client.requests, "post", fake_post)
    result = SafetyAgent(vlm).process_video(path, RULES, SafetyAgentConfig(sample_fps=1.0, include_snapshots=False))

    assert result['stats']['frames_analyzed'] == 4
    assert [e['rule_id'] for e in result['safety_events']] == ['no_helmet']
    assert result['safety_events'][0]['description'] == "A worker at a bench."
    assert result['activity']['summary']['va_percent'] == 100.0
    usage = result['vlm_usage']
    assert usage['calls'] == 4 + 1 + 1       # 4 frames + the event key frame + the longest activity segment
    assert usage['cost'] == pytest.approx(4 * 0.0001 + 2 * 0.00005)


def test_api_key_is_required():
    with pytest.raises(ValueError):
        VLMActionDetector(api_key="")


def test_vision_calls_turn_reasoning_off_and_retry_without_it_when_refused(vlm, monkeypatch):
    bodies = []

    def fake_post(url, headers, json, timeout):
        bodies.append(dict(json))
        if "reasoning" in json:
            return FakeResponse(400, {'error': 'unsupported parameter: reasoning'})
        return reply({'activity': 'A', 'activity_confidence': 90, 'rules': [{'id': 'no_helmet', 'confidence': 10},
                                                                              {'id': 'running', 'confidence': 5}]})

    monkeypatch.setattr(openrouter_client.requests, "post", fake_post)
    monkeypatch.setattr(openrouter_client, "OPENROUTER_URL", "https://openrouter.ai/api/v1/chat/completions")
    [result] = vlm.analyze_frames([frame(10)], RULES, ACTIVITY_QUESTION, OPTIONS)
    assert bodies[0]['reasoning'] == {'enabled': False} and 'reasoning' not in bodies[1]
    assert result['rule_confidences'] == {'no_helmet': 0.1, 'running': 0.05}
