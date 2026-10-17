import json

import pytest

import openrouter_client
from lss_agent import (
    LssAgent, StationContext, compute_metrics, compute_roi, load_knowledge, retrieve_cards,
)


def segment(start, end, activity, category, description=""):
    return {'start_time': start, 'end_time': end, 'duration': end - start, 'activity': activity,
            'category': category, 'confidence': 0.8, 'frame_count': int(end - start), 'key_frame_idx': 0,
            'key_timestamp': start, 'description': description, 'snapshot': None}


def make_safety():
    """60 s observed: 30 s working, 18 s waiting, 6 s walking, 6 s no person; one helmet violation."""
    return {
        'job_id': 'safety_test', 'video_path': 'clip.mp4', 'model': 'fake', 'timestamp': '', 'video_duration': 60.0,
        'sample_fps': 1.0,
        'rules': [{'id': 'no_helmet', 'prompt': 'a person who is not wearing a safety helmet', 'severity': 'high',
                   'threshold': 0.6}],
        'stats': {'frames_analyzed': 60, 'safety_events': 1, 'frames_with_violation': 4,
                  'events_by_severity': {'low': 0, 'medium': 0, 'high': 1}},
        'safety_events': [{'rule_id': 'no_helmet', 'prompt': 'a person who is not wearing a safety helmet',
                           'severity': 'high', 'start_time': 10.0, 'end_time': 14.0, 'duration': 4.0,
                           'peak_confidence': 0.9, 'mean_confidence': 0.8, 'frame_count': 4, 'key_frame_idx': 300,
                           'key_timestamp': 11.0, 'description': 'A worker without a helmet.', 'snapshot': None}],
        'activity': {
            'summary': {'observed_seconds': 60.0, 'person_visible_seconds': 54.0,
                        'by_activity_seconds': {'working': 30.0, 'waiting': 18.0, 'walking': 6.0, 'no_person': 6.0},
                        'by_category_seconds': {'VA': 30.0, 'NVA_WAITING': 18.0, 'NVA_MOTION': 6.0, 'NO_PERSON': 6.0},
                        'va_percent': 55.6, 'nnva_percent': 0.0, 'nva_percent': 44.4, 'uncertain_percent': 0.0},
            'segments': [segment(0, 30, 'working', 'VA', 'Assembling a part.'),
                         segment(30, 48, 'waiting', 'NVA_WAITING', 'Standing idle.'),
                         segment(48, 54, 'walking', 'NVA_MOTION'),
                         segment(54, 60, 'no_person', 'NO_PERSON')],
            'timeline': [],
        },
    }


def test_metrics_and_projection():
    metrics = compute_metrics(make_safety(), None, StationContext(shift_hours=8))

    assert [w['category'] for w in metrics['waste_by_category']] == ['NVA_WAITING', 'NVA_MOTION']
    waiting = metrics['waste_by_category'][0]
    assert waiting['percent_of_person_time'] == 33.3
    assert waiting['projected_hours_per_shift'] == pytest.approx(18 / 54 * 8, abs=0.01)
    assert metrics['projected_nva_hours_per_shift'] == pytest.approx(24 / 54 * 8, abs=0.01)
    assert metrics['longest_waste_segments'][0]['start'] == "00:30"
    assert metrics['safety']['by_rule'] == {'no_helmet': 1}
    assert 'people' not in metrics


def test_retrieval_matches_waste_and_safety_rules():
    safety = make_safety()
    cards = retrieve_cards(compute_metrics(safety, None, StationContext()), safety, load_knowledge())
    ids = [c['id'] for c in cards]

    assert ids[0].startswith("KC-WAI")              # largest waste first
    assert any(i.startswith("KC-MOT") for i in ids)
    assert "KC-SAF-01" in ids                        # helmet rule -> head protection card
    assert "KC-SAF-02" not in ids                    # running was not triggered
    assert "KC-STD-02" in ids                        # general method cards always included


def test_roi_from_seconds_per_cycle_and_from_waste_share():
    metrics = compute_metrics(make_safety(), None, StationContext())
    ctx = StationContext(cycle_time_s=20.0, shift_hours=8)
    roi = compute_roi({'est_seconds_saved_per_cycle': 2.0, 'category': 'NVA_WAITING'}, metrics, ctx)
    assert roi['hours_saved_per_shift'] == pytest.approx(2.0 * 1440 / 3600, abs=0.01)
    assert roi['throughput_gain_percent'] == pytest.approx(11.1, abs=0.1)

    roi = compute_roi({'est_seconds_saved_per_cycle': None, 'waste_share_removed': 0.5, 'category': 'NVA_WAITING'},
                      metrics, StationContext())
    assert roi['hours_saved_per_shift'] == pytest.approx(0.5 * 18 / 54 * 8, abs=0.01)
    assert compute_roi({'category': 'NVA_SEARCH', 'waste_share_removed': 0.5}, metrics, StationContext()) is None


def test_rule_based_without_api_key():
    result = LssAgent(api_key="").suggest(make_safety(), None, StationContext())

    assert result['source'] == "rules"
    assert result['llm_error'] == "OPENROUTER_API_KEY is not set"
    assert [c['category'] for c in result['lss_cards']] == ['NVA_WAITING', 'NVA_MOTION']
    assert result['lss_cards'][1]['kb_card_ids'] == ['KC-MOT-02']   # walking -> layout card, not reach card
    assert result['lss_cards'][0]['id'] == "K01"
    assert result['lss_cards'][0]['evidence'][0]['start_time'] == 30
    assert result['lss_cards'][0]['roi']['hours_saved_per_shift'] > 0
    assert result['safety_actions'][0]['kb_card_ids'] == ["KC-SAF-01"]
    assert "18-second pause at 00:30" in result['operator_questions'][0]['question']


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code, self._payload, self.text = status_code, payload, json.dumps(payload)

    def json(self):
        return self._payload


def llm_payload(content):
    return {'choices': [{'message': {'content': content}}], 'usage': {'prompt_tokens': 1000, 'completion_tokens': 200}}


LLM_REPORT = {
    'summary': 'Waiting is the main waste.',
    'lss_cards': [{
        'title': 'Balance the line', 'category': 'NVA_WAITING', 'priority': 'high',
        'observation': '18 s idle at 00:30.', 'evidence': [{'start_time': 30, 'end_time': 48, 'note': 'idle'}],
        'root_cause': 'Starved by upstream.', 'recommendation': 'Yamazumi and rebalance.',
        'kb_card_ids': ['KC-WAI-02', 'KC-FAKE-99'], 'est_seconds_saved_per_cycle': None,
        'waste_share_removed': 0.6, 'confidence': 0.7}],
    'safety_actions': [{'rule_id': 'no_helmet', 'severity': 'high', 'action': 'Helmets at entry.',
                        'kb_card_ids': ['KC-SAF-01']}],
    'operator_questions': [{'timestamp': 30, 'question': 'What were you waiting for?'}],
}


def test_llm_report_is_used_and_cleaned(monkeypatch):
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append({'url': url, 'body': json, 'auth': headers['Authorization']})
        return FakeResponse(200, llm_payload("```json\n" + __import__('json').dumps(LLM_REPORT) + "\n```"))

    monkeypatch.setattr(openrouter_client.requests, "post", fake_post)
    result = LssAgent(api_key="sk-test", model="test/model").suggest(
        make_safety(), None, StationContext(language="th", station_name="Cell 3"))

    assert result['source'] == "llm" and result['model'] == "test/model"
    assert result['lss_cards'][0]['kb_card_ids'] == ['KC-WAI-02']   # unknown card id dropped
    assert result['lss_cards'][0]['roi']['hours_saved_per_shift'] == pytest.approx(0.6 * 18 / 54 * 8, abs=0.01)
    assert result['usage'] == {'prompt_tokens': 1000, 'completion_tokens': 200}

    body = calls[0]['body']
    assert calls[0]['auth'] == "Bearer sk-test"
    assert body['response_format']['type'] == "json_schema"
    assert "Thai" in body['messages'][0]['content']
    user = json.loads(body['messages'][1]['content'])
    assert user['station']['station_name'] == "Cell 3"
    assert 'snapshot' not in json.dumps(user)
    assert any(c['id'] == 'KC-SAF-01' for c in user['knowledge_cards'])


def test_llm_falls_back_to_json_object_then_rules(monkeypatch):
    responses = [FakeResponse(400, {'error': 'schema not supported'}), FakeResponse(200, llm_payload(json.dumps(LLM_REPORT)))]
    monkeypatch.setattr(openrouter_client.requests, "post", lambda *a, **kw: responses.pop(0))
    assert LssAgent(api_key="k").suggest(make_safety())['source'] == "llm"

    monkeypatch.setattr(openrouter_client.requests, "post", lambda *a, **kw: FakeResponse(500, {'error': 'down'}))
    result = LssAgent(api_key="k").suggest(make_safety())
    assert result['source'] == "rules"
    assert "HTTP 500" in result['llm_error']


def test_malformed_llm_output_is_normalized_or_falls_back(monkeypatch):
    messy = {'summary': 'ok', 'lss_cards': [{'title': 'Fix waiting', 'priority': 'URGENT', 'confidence': '0.8',
                                               'evidence': [{'start_time': '30'}]}, {'no_title': True}],
             'safety_actions': [{'action': 'Helmets'}], 'operator_questions': [{'question': 'Why?'}]}
    monkeypatch.setattr(openrouter_client.requests, "post", lambda *a, **kw: FakeResponse(200, llm_payload(json.dumps(messy))))
    result = LssAgent(api_key="k").suggest(make_safety())
    assert result['source'] == "llm"
    [card] = result['lss_cards']
    assert (card['priority'], card['confidence'], card['evidence'][0]['start_time']) == ("medium", 0.8, 30.0)
    assert result['operator_questions'] == [{'timestamp': 0.0, 'question': 'Why?'}]

    monkeypatch.setattr(openrouter_client.requests, "post", lambda *a, **kw: FakeResponse(200, llm_payload("not json")))
    assert LssAgent(api_key="k").suggest(make_safety())['source'] == "rules"
