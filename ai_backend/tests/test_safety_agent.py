import threading

import cv2
import numpy as np
import pytest

from safety_agent import (
    ACTIVITY_CLASSES, FrameObservation, SafetyAgent, SafetyAgentConfig, SafetyRule, build_activity_segments,
    build_safety_events, parse_rules_text, smooth_labels, summarize_activity,
)

OPTIONS = [c.option for c in ACTIVITY_CLASSES]


class FakeVLM:
    """
    Frame brightness drives the answers:
      bright (> 128) -> 'working' and the 'helmet' rule fires; dark -> 'waiting', no violation.
    """
    model_name = "fake-vlm"
    device = "cpu"
    batch_size = 3

    def __init__(self):
        self._lock = threading.Lock()
        self.calls = {'analyze': 0, 'describe': 0}

    def analyze_frames(self, images, rules, question, options):
        self.calls['analyze'] += 1
        assert options == OPTIONS
        out = []
        for img in images:
            bright = img.mean() > 128
            probs = {o: 0.0 for o in options}
            probs[OPTIONS[0] if bright else OPTIONS[6]] = 0.9
            probs[OPTIONS[2]] = 0.1
            out.append({'activity_probs': probs,
                        'rule_confidences': {r.id: 0.95 if bright and "helmet" in r.prompt else 0.05 for r in rules}})
        return out

    def describe_images(self, images, question, max_new_tokens=40):
        self.calls['describe'] += 1
        return [f"brightness {int(img.mean())}" for img in images]


@pytest.fixture
def work_video(tmp_path):
    """6 seconds at 10 FPS: bright (working) for 3 s, dark (waiting) for 3 s."""
    path = str(tmp_path / "work.mp4")
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 48))
    for value in [220] * 30 + [20] * 30:
        writer.write(np.full((48, 64, 3), value, dtype=np.uint8))
    writer.release()
    return path


RULES = [SafetyRule("no_helmet", "a person not wearing a helmet", "high"), SafetyRule("running", "a person running")]


def test_process_video_builds_segments_events_and_summary(work_video):
    vlm = FakeVLM()
    result = SafetyAgent(vlm).process_video(work_video, RULES, SafetyAgentConfig(sample_fps=1.0))

    assert result['stats']['frames_analyzed'] == 6
    assert [(s['activity'], s['start_time'], s['end_time'], s['duration']) for s in result['activity']['segments']] == \
        [('working', 0.0, 3.0, 3.0), ('waiting', 3.0, 6.0, 3.0)]
    summary = result['activity']['summary']
    assert summary['va_percent'] == 50.0 and summary['nva_percent'] == 50.0
    assert summary['by_category_seconds'] == {'VA': 3.0, 'NVA_WAITING': 3.0}

    [event] = result['safety_events']
    assert (event['rule_id'], event['severity'], event['start_time'], event['end_time']) == ('no_helmet', 'high', 0.0, 3.0)
    assert event['description'].startswith("brightness")
    assert event['snapshot'].startswith("data:image/jpeg;base64,")
    assert result['stats']['events_by_severity'] == {'low': 0, 'medium': 0, 'high': 1}

    # 6 frames in batches of 3
    assert vlm.calls['analyze'] == 2
    assert result['vlm_usage'] is None


def test_max_frames_lowers_sample_rate(work_video):
    result = SafetyAgent(FakeVLM()).process_video(
        work_video, RULES, SafetyAgentConfig(sample_fps=2.0, max_frames=3, include_snapshots=False))
    assert result['sample_fps'] == 0.5
    assert result['stats']['frames_analyzed'] == 3


def test_low_activity_confidence_is_uncertain(work_video):
    result = SafetyAgent(FakeVLM()).process_video(
        work_video, [], SafetyAgentConfig(activity_min_confidence=0.95, max_descriptions=0, include_snapshots=False))
    assert {s['category'] for s in result['activity']['segments']} == {'UNCERTAIN'}
    assert result['activity']['summary']['uncertain_percent'] == 100.0


def test_unreadable_video_raises(tmp_path):
    with pytest.raises(ValueError):
        SafetyAgent(FakeVLM()).process_video(str(tmp_path / "missing.mp4"), RULES)


def obs(t, activity="working", category="VA", rules=None):
    return FrameObservation(timestamp=t, frame_idx=int(t * 10), activity=activity, category=category,
                            activity_confidence=0.9, rule_confidences=rules or {})


def test_safety_events_split_on_gap():
    observations = [obs(t, rules={'r': 0.9 if t in (0, 1, 5) else 0.1}) for t in range(7)]
    events = build_safety_events(observations, [SafetyRule('r', 'x', 'low', 0.6)], 1.0, max_gap=2.0)
    assert [(e.start_time, e.end_time, e.frame_count) for e in events] == [(0, 2.0, 2), (5, 6.0, 1)]


def test_activity_segments_and_summary_ignore_no_person():
    observations = [obs(0), obs(1), obs(2, "no_person", "NO_PERSON"), obs(3, "walking", "NVA_MOTION")]
    segments = build_activity_segments(observations, 1.0)
    assert [s.activity for s in segments] == ["working", "no_person", "walking"]
    summary = summarize_activity(observations, 1.0)
    assert summary['person_visible_seconds'] == 3.0
    assert (summary['va_percent'], summary['nva_percent']) == (66.7, 33.3)


def test_smooth_labels_removes_single_frame_flicker():
    assert smooth_labels(list("AABAACCDC")) == list("AAAAACCCC")


@pytest.mark.parametrize("text, expected", [
    ("high: not wearing a helmet\nrunning", [("not_wearing_a_helmet", "high"), ("running", "medium")]),
    ("running, phone use", [("running", "medium"), ("phone_use", "medium")]),
    ("low: running\nrunning", [("running", "low"), ("running_", "medium")]),
    ("\n\n", []),
])
def test_parse_rules_text(text, expected):
    assert [(r.id, r.severity) for r in parse_rules_text(text)] == expected
