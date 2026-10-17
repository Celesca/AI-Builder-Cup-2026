"""
Gemba Kaizen Agent: turns the Safety Agent's observations into Gemba Kaizen suggestions.

  1. Gemba Kaizen Engine (deterministic): VA / NVA time, waste per category, projected waste per shift,
     safety event counts, people on camera. All numbers are computed here, never by the LLM.
  2. Knowledge retrieval: countermeasure cards (knowledge/lss_cards.json) matching the observed
     waste categories and the triggered safety rules.
  3. LLM (OpenRouter, any chat model with JSON output): writes Gemba Kaizen cards, safety actions and questions
     for the operator, citing card ids and video timestamps. Without OPENROUTER_API_KEY, or if the
     call fails, rule-based cards are built from the same metrics and knowledge cards (source="rules").
  4. ROI: estimated savings from each card are turned into hours per shift / throughput gain here.
"""

import json
import logging
import os
import re
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from openrouter_client import chat, parse_json

logger = logging.getLogger(__name__)

DEFAULT_LLM_MODEL = "google/gemini-3.1-flash-lite"
KNOWLEDGE_PATH = Path(__file__).parent / "knowledge" / "lss_cards.json"

CATEGORY_LABELS = {
    "VA": "Value-adding work",
    "NNVA": "Necessary non-value-adding (inspection)",
    "NVA_MOTION": "Motion waste (walking, reaching)",
    "NVA_TRANSPORT": "Transportation waste (carrying materials)",
    "NVA_WAITING": "Waiting waste (idle)",
    "NVA_SEARCH": "Searching waste",
    "NO_PERSON": "No person on camera",
    "UNCERTAIN": "Unclear activity",
}
WASTE_CATEGORIES = ("NVA_MOTION", "NVA_TRANSPORT", "NVA_WAITING", "NVA_SEARCH", "NNVA")
LANGUAGES = {"en": "English", "th": "Thai", "ja": "Japanese"}


@dataclass
class StationContext:
    station_name: str = ""
    process_description: str = ""
    takt_time_s: Optional[float] = None
    cycle_time_s: Optional[float] = None
    cycles_per_shift: Optional[float] = None
    shift_hours: float = 8.0
    operators: int = 1
    language: str = "en"
    notes: str = ""

    def resolved_cycles_per_shift(self) -> Optional[float]:
        if self.cycles_per_shift:
            return self.cycles_per_shift
        if self.cycle_time_s:
            return self.shift_hours * 3600 / self.cycle_time_s
        return None


def mmss(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


# ============================================================================
# 1. Gemba Kaizen Engine
# ============================================================================

def compute_metrics(safety: Dict, person_count: Optional[Dict], context: StationContext) -> Dict:
    summary = safety['activity']['summary']
    person_seconds = summary['person_visible_seconds']
    by_category = summary['by_category_seconds']

    def per_shift_hours(seconds: float) -> float:
        return round(seconds / person_seconds * context.shift_hours * context.operators, 2) if person_seconds else 0.0

    waste = []
    for category in WASTE_CATEGORIES:
        seconds = by_category.get(category, 0.0)
        if seconds > 0:
            waste.append({
                'category': category,
                'label': CATEGORY_LABELS[category],
                'seconds': round(seconds, 2),
                'percent_of_person_time': round(100 * seconds / person_seconds, 1) if person_seconds else 0.0,
                'projected_hours_per_shift': per_shift_hours(seconds),
            })
    waste.sort(key=lambda w: -w['seconds'])

    longest_waste = sorted(
        (s for s in safety['activity']['segments'] if s['category'] in WASTE_CATEGORIES),
        key=lambda s: -s['duration'])[:5]

    events = safety['safety_events']
    by_rule: Dict[str, int] = {}
    for e in events:
        by_rule[e['rule_id']] = by_rule.get(e['rule_id'], 0) + 1

    metrics = {
        'video_duration': safety['video_duration'],
        'observed_seconds': summary['observed_seconds'],
        'person_visible_seconds': person_seconds,
        'va_percent': summary['va_percent'],
        'nnva_percent': summary['nnva_percent'],
        'nva_percent': summary['nva_percent'],
        'uncertain_percent': summary['uncertain_percent'],
        'waste_by_category': waste,
        'longest_waste_segments': [
            {'start': mmss(s['start_time']), 'start_time': s['start_time'], 'end_time': s['end_time'],
             'duration': s['duration'], 'activity': s['activity'], 'category': s['category']}
            for s in longest_waste
        ],
        'projected_nva_hours_per_shift': per_shift_hours(
            sum(w['seconds'] for w in waste if w['category'].startswith("NVA_"))),
        'safety': {
            'events': len(events),
            'by_severity': safety['stats']['events_by_severity'],
            'by_rule': by_rule,
            'violation_seconds': round(sum(e['duration'] for e in events), 2),
        },
        'cycles_per_shift': context.resolved_cycles_per_shift(),
    }
    if person_count:
        stats = person_count['statistics']
        metrics['people'] = {'max_persons': stats['max_persons'], 'avg_persons': stats['avg_persons'],
                             'frames_with_people': stats['frames_with_people'],
                             'frames_analyzed': stats['frames_analyzed']}
    return metrics


def compute_roi(card: Dict, metrics: Dict, context: StationContext) -> Optional[Dict]:
    """Hours saved per shift (and throughput gain) from the card's estimate; None when nothing to compute."""
    seconds_saved = card.get('est_seconds_saved_per_cycle')
    cycles = context.resolved_cycles_per_shift()
    if seconds_saved and seconds_saved > 0 and cycles:
        if context.cycle_time_s:
            seconds_saved = min(seconds_saved, context.cycle_time_s * 0.9)
        roi = {
            'hours_saved_per_shift': round(seconds_saved * cycles * context.operators / 3600, 2),
            'throughput_gain_percent': None,
            'basis': f"{seconds_saved:g} s/cycle x {cycles:.0f} cycles/shift",
        }
        if context.cycle_time_s and seconds_saved < context.cycle_time_s:
            roi['throughput_gain_percent'] = round(
                (context.cycle_time_s / (context.cycle_time_s - seconds_saved) - 1) * 100, 1)
        return roi

    share = card.get('waste_share_removed')
    waste = next((w for w in metrics['waste_by_category'] if w['category'] == card.get('category')), None)
    if share and share > 0 and waste:
        share = min(share, 1.0)
        return {
            'hours_saved_per_shift': round(share * waste['projected_hours_per_shift'], 2),
            'throughput_gain_percent': None,
            'basis': f"{share:.0%} of {waste['projected_hours_per_shift']} h/shift of {waste['category']}",
        }
    return None


# ============================================================================
# 2. Knowledge retrieval
# ============================================================================

def load_knowledge(path: Path = KNOWLEDGE_PATH) -> List[Dict]:
    with open(path) as f:
        return json.load(f)['cards']


def _words(text: str) -> set:
    return set(re.findall(r'[a-z]+', text.lower()))


def retrieve_cards(metrics: Dict, safety: Dict, cards: List[Dict], limit: int = 12) -> List[Dict]:
    """Cards for observed waste (largest first), triggered safety rules, unclear activity, and general method."""
    selected: List[Dict] = []

    def add(card):
        if card not in selected:
            selected.append(card)

    for waste in metrics['waste_by_category']:
        for card in cards:
            if card['category'] == waste['category']:
                add(card)

    triggered = {}
    for e in safety['safety_events']:
        triggered[e['rule_id']] = e['prompt']
    for rule_id, prompt in triggered.items():
        rule_words = _words(rule_id.replace('_', ' ')) | _words(prompt) | {rule_id}
        for card in cards:
            if card['category'] == "SAFETY" and (set(card['tags']) & rule_words or
                                                  any(_words(t) <= rule_words for t in card['tags'])):
                add(card)

    if metrics['uncertain_percent'] >= 15:
        for card in cards:
            if card['category'] == "UNCERTAIN":
                add(card)
    for card in cards:
        if card['category'] == "GENERAL":
            add(card)
    return selected[:limit]


# ============================================================================
# 3. LLM (OpenRouter)
# ============================================================================

def _nullable(t: str) -> Dict:
    return {"type": [t, "null"]}


LSS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "lss_cards", "safety_actions", "operator_questions"],
    "properties": {
        "summary": {"type": "string"},
        "lss_cards": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "category", "priority", "observation", "evidence", "root_cause",
                             "recommendation", "kb_card_ids", "est_seconds_saved_per_cycle",
                             "waste_share_removed", "confidence"],
                "properties": {
                    "title": {"type": "string"},
                    "category": {"type": "string", "enum": list(WASTE_CATEGORIES) + ["SAFETY", "UNCERTAIN"]},
                    "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                    "observation": {"type": "string"},
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["start_time", "end_time", "note"],
                            "properties": {"start_time": {"type": "number"}, "end_time": {"type": "number"},
                                           "note": {"type": "string"}},
                        },
                    },
                    "root_cause": {"type": "string"},
                    "recommendation": {"type": "string"},
                    "kb_card_ids": {"type": "array", "items": {"type": "string"}},
                    "est_seconds_saved_per_cycle": _nullable("number"),
                    "waste_share_removed": _nullable("number"),
                    "confidence": {"type": "number"},
                },
            },
        },
        "safety_actions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["rule_id", "severity", "action", "kb_card_ids"],
                "properties": {"rule_id": {"type": "string"},
                               "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                               "action": {"type": "string"},
                               "kb_card_ids": {"type": "array", "items": {"type": "string"}}},
            },
        },
        "operator_questions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["timestamp", "question"],
                "properties": {"timestamp": {"type": "number"}, "question": {"type": "string"}},
            },
        },
    },
}

SYSTEM_PROMPT = """You are VALZ, a Gemba Kaizen (continuous improvement, lean manufacturing) coach.
You receive what cameras observed at one workstation: activity time by Muda category measured from video,
the longest waste segments with short descriptions, safety rule violations, and countermeasure knowledge cards.

Write practical Gemba Kaizen suggestions for the plant manager:
- Base every suggestion on the observed data. Cite video evidence as start/end seconds taken from the input.
- Cite the knowledge cards you used by id in kb_card_ids. Do not invent card ids.
- Prioritize by impact: largest waste time and high-severity safety issues first. 2-5 Gemba Kaizen cards.
- Do NOT invent numbers. All measured times are given. est_seconds_saved_per_cycle only when the cycle time is
  known and the saving is clearly smaller than the observed waste per cycle, otherwise null.
  waste_share_removed is your estimate (0-1) of the share of that category's waste the countermeasure removes.
- The activity labels come from a small vision model and can be wrong: when the evidence is weak or the activity
  is UNCERTAIN, lower confidence and add an operator question instead of guessing (the voice agent will ask).
- Every triggered safety rule gets one safety action.
- operator_questions: short, friendly, about a specific moment, e.g. "I saw a 6-second pause at 00:16. Did a part jam?"
- Write all text in {language}. Keep each field short (1-2 sentences)."""


def build_llm_input(metrics: Dict, safety: Dict, context: StationContext, cards: List[Dict]) -> Dict:
    segments = safety['activity']['segments']
    waste_segments = sorted((s for s in segments if s['category'] in WASTE_CATEGORIES + ("UNCERTAIN",)),
                            key=lambda s: -s['duration'])[:25]
    va_segments = sorted((s for s in segments if s['category'] == "VA"), key=lambda s: -s['duration'])[:3]

    def seg(s):
        return {'start_time': s['start_time'], 'end_time': s['end_time'], 'duration': s['duration'],
                'activity': s['activity'], 'category': s['category'],
                'description': s.get('description') or None}

    return {
        'station': {k: v for k, v in asdict(context).items() if k != 'language' and v not in (None, "")},
        'metrics': metrics,
        'waste_segments': [seg(s) for s in sorted(waste_segments, key=lambda s: s['start_time'])],
        'value_adding_examples': [seg(s) for s in va_segments],
        'safety_events': [
            {'rule_id': e['rule_id'], 'rule': e['prompt'], 'severity': e['severity'],
             'start_time': e['start_time'], 'end_time': e['end_time'], 'duration': e['duration'],
             'peak_confidence': round(e['peak_confidence'], 2), 'description': e.get('description') or None}
            for e in safety['safety_events']
        ],
        'knowledge_cards': [{k: c[k] for k in ('id', 'category', 'title', 'symptom', 'countermeasure',
                                               'principle', 'typical_impact')} for c in cards],
    }


def call_openrouter(system: str, user: str, model: str, api_key: str, timeout: float = 120) -> Tuple[Dict, Dict]:
    """Chat completion with the Gemba Kaizen JSON schema; returns (parsed report, usage)."""
    text, usage = chat([{"role": "system", "content": system}, {"role": "user", "content": user}],
                       model, api_key, schema=LSS_SCHEMA, schema_name="lss_report", timeout=timeout)
    return parse_json(text), usage


def _number(value, default=None) -> Optional[float]:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def normalize_report(report: Dict) -> Dict:
    """Coerce LLM output into the response shape (missing fields get defaults; bad items are dropped)."""
    if not isinstance(report, dict):
        raise ValueError("LLM output is not a JSON object")

    def level(value, default="medium"):
        value = str(value or "").lower()
        return value if value in ("high", "medium", "low") else default

    cards = []
    for c in report.get('lss_cards') or []:
        if not isinstance(c, dict) or not c.get('title'):
            continue
        evidence = [{'start_time': _number(e.get('start_time'), 0.0), 'end_time': _number(e.get('end_time'), 0.0),
                     'note': str(e.get('note') or '')}
                    for e in c.get('evidence') or [] if isinstance(e, dict)]
        cards.append({
            'title': str(c['title']), 'category': str(c.get('category') or "UNCERTAIN"),
            'priority': level(c.get('priority')), 'observation': str(c.get('observation') or ''),
            'evidence': evidence, 'root_cause': str(c.get('root_cause') or ''),
            'recommendation': str(c.get('recommendation') or ''),
            'kb_card_ids': [str(i) for i in c.get('kb_card_ids') or []],
            'est_seconds_saved_per_cycle': _number(c.get('est_seconds_saved_per_cycle')),
            'waste_share_removed': _number(c.get('waste_share_removed')),
            'confidence': min(1.0, max(0.0, _number(c.get('confidence'), 0.5))),
        })
    actions = [{'rule_id': str(a.get('rule_id') or ''), 'severity': level(a.get('severity')),
                'action': str(a.get('action') or ''), 'kb_card_ids': [str(i) for i in a.get('kb_card_ids') or []]}
               for a in report.get('safety_actions') or [] if isinstance(a, dict) and a.get('action')]
    questions = [{'timestamp': _number(q.get('timestamp'), 0.0), 'question': str(q['question'])}
                 for q in report.get('operator_questions') or [] if isinstance(q, dict) and q.get('question')]
    return {'summary': str(report.get('summary') or ''), 'lss_cards': cards, 'safety_actions': actions,
            'operator_questions': questions}


# ============================================================================
# Rule-based fallback
# ============================================================================

def rule_based_report(metrics: Dict, safety: Dict, context: StationContext, cards: List[Dict]) -> Dict:
    segments = safety['activity']['segments']
    lss_cards = []
    for waste in metrics['waste_by_category'][:3]:
        in_category = [s for s in segments if s['category'] == waste['category']]
        activity_time: Dict[str, float] = {}
        for seg in in_category:
            activity_time[seg['activity']] = activity_time.get(seg['activity'], 0.0) + seg['duration']
        main_activity = max(activity_time, key=activity_time.get) if activity_time else ""
        candidates = [c for c in cards if c['category'] == waste['category']]
        # Prefer the card about the activity seen most (walking -> layout card, not reach card)
        card = next((c for c in candidates if main_activity in c['tags']), candidates[0] if candidates else None)
        if card is None:
            continue
        evidence = sorted(in_category, key=lambda s: -s['duration'])[:3]
        lss_cards.append({
            'title': card['title'],
            'category': waste['category'],
            'priority': "high" if waste['percent_of_person_time'] >= 20 else
                        "medium" if waste['percent_of_person_time'] >= 8 else "low",
            'observation': f"{waste['label']}: {waste['seconds']:g} s ({waste['percent_of_person_time']}% "
                           f"of the time a person is visible).",
            'evidence': [{'start_time': s['start_time'], 'end_time': s['end_time'],
                          'note': s.get('description') or s['activity']} for s in evidence],
            'root_cause': card['symptom'],
            'recommendation': card['countermeasure'],
            'kb_card_ids': [card['id']],
            'est_seconds_saved_per_cycle': None,
            'waste_share_removed': 0.3,
            'confidence': 0.4,
        })

    safety_actions, seen = [], set()
    for event in safety['safety_events']:
        if event['rule_id'] in seen:
            continue
        seen.add(event['rule_id'])
        rule_words = _words(event['rule_id'].replace('_', ' ')) | _words(event['prompt'])
        card = next((c for c in cards if c['category'] == "SAFETY" and set(c['tags']) & rule_words), None)
        safety_actions.append({
            'rule_id': event['rule_id'], 'severity': event['severity'],
            'action': card['countermeasure'] if card else f"Investigate and stop: {event['prompt']}.",
            'kb_card_ids': [card['id']] if card else [],
        })

    questions = []
    for s in sorted(segments, key=lambda s: -s['duration']):
        if s['category'] == "NVA_WAITING" and s['duration'] >= 5:
            questions.append({'timestamp': s['start_time'],
                              'question': f"I saw a {s['duration']:.0f}-second pause at {mmss(s['start_time'])}. "
                                          f"What were you waiting for?"})
        elif s['category'] == "UNCERTAIN" and s['duration'] >= 3:
            questions.append({'timestamp': s['start_time'],
                              'question': f"What were you doing at {mmss(s['start_time'])}? I couldn't tell."})
        if len(questions) >= 3:
            break

    top = metrics['waste_by_category'][0] if metrics['waste_by_category'] else None
    summary = (f"Value-adding {metrics['va_percent']}% / non-value-adding {metrics['nva_percent']}% of person time. "
               + (f"Largest waste: {top['label']} ({top['percent_of_person_time']}%). " if top else "")
               + f"{metrics['safety']['events']} safety event(s).")
    return {'summary': summary, 'lss_cards': lss_cards, 'safety_actions': safety_actions,
            'operator_questions': questions}


# ============================================================================
# Agent
# ============================================================================

class LssAgent:
    def __init__(self, model: Optional[str] = None, api_key: Optional[str] = None,
                 knowledge: Optional[List[Dict]] = None, timeout: float = 120):
        self.model = model or os.getenv("LSS_LLM_MODEL") or DEFAULT_LLM_MODEL
        self.api_key = api_key if api_key is not None else os.getenv("OPENROUTER_API_KEY", "")
        self.knowledge = knowledge if knowledge is not None else load_knowledge()
        self.timeout = timeout

    @property
    def llm_configured(self) -> bool:
        return bool(self.api_key)

    def suggest(self, safety: Dict, person_count: Optional[Dict] = None,
                context: Optional[StationContext] = None, use_llm: bool = True) -> Dict:
        context = context or StationContext()
        job_id = f"lss_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        metrics = compute_metrics(safety, person_count, context)
        cards = retrieve_cards(metrics, safety, self.knowledge)
        known_ids = {c['id'] for c in self.knowledge}

        report, source, llm_error, usage = None, "rules", None, None
        if use_llm and self.llm_configured:
            try:
                system = SYSTEM_PROMPT.format(language=LANGUAGES.get(context.language, "English"))
                user = json.dumps(build_llm_input(metrics, safety, context, cards), ensure_ascii=False)
                raw, usage = call_openrouter(system, user, self.model, self.api_key, self.timeout)
                report = normalize_report(raw)
                source = "llm"
            except Exception as e:
                logger.exception("Gemba Kaizen LLM call failed, using rule-based suggestions")
                llm_error = str(e)
        elif use_llm:
            llm_error = "OPENROUTER_API_KEY is not set"
        if report is None:
            report = rule_based_report(metrics, safety, context, cards)

        lss_cards = []
        for i, card in enumerate(report.get('lss_cards') or [], start=1):
            card = {**card, 'id': f"K{i:02d}",
                    'kb_card_ids': [c for c in card.get('kb_card_ids') or [] if c in known_ids]}
            card['roi'] = compute_roi(card, metrics, context)
            lss_cards.append(card)
        safety_actions = [{**a, 'kb_card_ids': [c for c in a.get('kb_card_ids') or [] if c in known_ids]}
                          for a in report.get('safety_actions') or []]

        logger.info(f"🧭 [{job_id}] source={source} cards={len(lss_cards)} safety_actions={len(safety_actions)}")
        return {
            'job_id': job_id,
            'timestamp': datetime.now().isoformat(),
            'source': source,
            'model': self.model if source == "llm" else None,
            'llm_error': llm_error,
            'context': asdict(context),
            'metrics': metrics,
            'summary': report.get('summary', ''),
            'lss_cards': lss_cards,
            'safety_actions': safety_actions,
            'operator_questions': report.get('operator_questions') or [],
            'knowledge_cards_used': [{'id': c['id'], 'title': c['title'], 'source': c['source']} for c in cards],
            'usage': {k: usage.get(k) for k in ('prompt_tokens', 'completion_tokens', 'total_tokens', 'cost')
                      if k in usage} if usage else None,
        }


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Run the Gemba Kaizen Agent on a saved Safety Agent JSON result")
    parser.add_argument("safety_json")
    parser.add_argument("--cycle-time", type=float)
    parser.add_argument("--language", default="en", choices=sorted(LANGUAGES))
    args = parser.parse_args()

    with open(args.safety_json) as f:
        safety_result = json.load(f)
    result = LssAgent().suggest(safety_result, None,
                                   StationContext(cycle_time_s=args.cycle_time, language=args.language))
    print(json.dumps(result, indent=2, ensure_ascii=False))
