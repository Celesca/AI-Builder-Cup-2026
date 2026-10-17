"""
Voice Agent: a chatbot over the VALZ analysis, with ElevenLabs speech.

- RAG: the analysis the dashboard holds (Gemba Kaizen summary, waste metrics, Gemba Kaizen cards, incidents, activity segments)
  and the Gemba Kaizen knowledge cards are cut into small chunks; the ones that match the question go to the LLM.
  Plain keyword scoring (BM25-style), no embeddings: fine for the few dozen chunks one analysis produces.
- Chat: an OpenRouter LLM answers from those chunks only. Without OPENROUTER_API_KEY the best chunks are returned as is.
- Voice out: ElevenLabs text-to-speech. Every clip is stored in a SQLite database keyed by voice, model and text,
  so the same sentence is only paid for once (and keeps playing when ElevenLabs is unreachable).
- Voice in: ElevenLabs speech-to-text (Scribe), which detects the language itself.
"""

import hashlib
import math
import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from fastapi import APIRouter, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field

from lss_agent import KNOWLEDGE_PATH, load_knowledge, mmss
from openrouter_client import chat

ELEVENLABS_URL = os.getenv("ELEVENLABS_URL", "https://api.elevenlabs.io")  # override: proxy / tests
DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # "Rachel", a premade voice every account has
DEFAULT_TTS_MODEL = "eleven_flash_v2_5"  # cheap and fast; set ELEVENLABS_TTS_MODEL=eleven_v3 for the widest language list
DEFAULT_STT_MODEL = "scribe_v1"
DEFAULT_DB_PATH = str(Path(__file__).parent / "data" / "voice.db")
MAX_TTS_CHARS = 1500
MAX_AUDIO_BYTES = 25 * 1024 * 1024
LANGUAGES = {"en": "English", "th": "Thai", "ja": "Japanese"}

SYSTEM_PROMPT = """You are the VALZ voice assistant. You talk to a plant manager or lean engineer about one CCTV analysis of a work station.

Rules:
- Answer only from the CONTEXT chunks. If the answer is not in them, say you do not know and what they could check instead.
- Your answer is read aloud: plain sentences, no markdown, no bullet lists, no emoji. Two or three sentences unless asked for more.
- Say times as minutes:seconds (for example 0:42) so the user can jump to them. Do not invent numbers.
- Cite a knowledge card by its title when you use one.
- Reply in {language}."""


# ============================================================================
# Voice database (audio cache)
# ============================================================================

class VoiceStore:
    """SQLite store for generated speech. One row per (voice, model, text)."""

    def __init__(self, path: Optional[str] = None):
        self.path = path or os.getenv("VOICE_DB_PATH") or DEFAULT_DB_PATH
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS audio (key TEXT PRIMARY KEY, voice_id TEXT, model_id TEXT, text TEXT, "
            "mime TEXT, data BLOB, created_at REAL, hits INTEGER DEFAULT 0)")
        self._db.commit()

    @staticmethod
    def key(voice_id: str, model_id: str, text: str) -> str:
        return hashlib.sha256(f"{voice_id}\n{model_id}\n{text}".encode("utf-8")).hexdigest()

    def get(self, key: str) -> Optional[Tuple[bytes, str]]:
        with self._lock:
            row = self._db.execute("SELECT data, mime FROM audio WHERE key = ?", (key,)).fetchone()
            if row:
                self._db.execute("UPDATE audio SET hits = hits + 1 WHERE key = ?", (key,))
                self._db.commit()
        return (row[0], row[1]) if row else None

    def put(self, key: str, voice_id: str, model_id: str, text: str, data: bytes, mime: str):
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO audio (key, voice_id, model_id, text, mime, data, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)", (key, voice_id, model_id, text, mime, data, time.time()))
            self._db.commit()

    def stats(self) -> Dict[str, int]:
        with self._lock:
            clips, size, hits = self._db.execute(
                "SELECT COUNT(*), COALESCE(SUM(LENGTH(data)), 0), COALESCE(SUM(hits), 0) FROM audio").fetchone()
        return {"clips": clips, "bytes": size, "replays": hits}


# ============================================================================
# ElevenLabs
# ============================================================================

class ElevenLabs:
    def __init__(self, api_key: Optional[str] = None, voice_id: Optional[str] = None,
                 tts_model: Optional[str] = None, stt_model: Optional[str] = None,
                 store: Optional[VoiceStore] = None, timeout: float = 60):
        self.api_key = api_key if api_key is not None else os.getenv("ELEVENLABS_API_KEY", "")
        self.voice_id = voice_id or os.getenv("ELEVENLABS_VOICE_ID") or DEFAULT_VOICE_ID
        self.tts_model = tts_model or os.getenv("ELEVENLABS_TTS_MODEL") or DEFAULT_TTS_MODEL
        self.stt_model = stt_model or os.getenv("ELEVENLABS_STT_MODEL") or DEFAULT_STT_MODEL
        self.store = store or VoiceStore()
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def speak(self, text: str, voice_id: Optional[str] = None) -> Tuple[bytes, str, bool]:
        """(audio, mime type, served from the database). Raises RuntimeError when ElevenLabs fails."""
        voice = voice_id or self.voice_id
        text = clean_for_speech(text)[:MAX_TTS_CHARS]
        if not text:
            raise ValueError("Nothing to say")
        key = self.store.key(voice, self.tts_model, text)
        cached = self.store.get(key)
        if cached:
            return cached[0], cached[1], True
        if not self.configured:
            raise RuntimeError("ELEVENLABS_API_KEY is not set")
        response = requests.post(
            f"{ELEVENLABS_URL}/v1/text-to-speech/{voice}", params={"output_format": "mp3_44100_64"},
            headers={"xi-api-key": self.api_key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
            json={"text": text, "model_id": self.tts_model}, timeout=self.timeout)
        if response.status_code != 200:
            raise RuntimeError(f"ElevenLabs HTTP {response.status_code}: {response.text[:200]}")
        self.store.put(key, voice, self.tts_model, text, response.content, "audio/mpeg")
        return response.content, "audio/mpeg", False

    def transcribe(self, audio: bytes, filename: str, content_type: str) -> Dict[str, Any]:
        if not self.configured:
            raise RuntimeError("ELEVENLABS_API_KEY is not set")
        response = requests.post(
            f"{ELEVENLABS_URL}/v1/speech-to-text", headers={"xi-api-key": self.api_key},
            data={"model_id": self.stt_model}, files={"file": (filename, audio, content_type)},
            timeout=self.timeout * 2)
        if response.status_code != 200:
            raise RuntimeError(f"ElevenLabs HTTP {response.status_code}: {response.text[:200]}")
        body = response.json()
        return {"text": (body.get("text") or "").strip(), "language": body.get("language_code")}


def clean_for_speech(text: str) -> str:
    """Strip markdown and spacing, which a voice would read out loud or stumble on."""
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"[*_`#>]+", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


# ============================================================================
# RAG over the analysis
# ============================================================================

def _text(value: Any) -> str:
    return str(value).strip() if value not in (None, "") else ""


def build_chunks(analysis: Dict, knowledge: List[Dict]) -> List[Dict]:
    """Small retrievable passages: {id, title, text, source}. `analysis` is a /analysis/analyze response (snapshots optional)."""
    chunks: List[Dict] = []

    def add(chunk_id: str, title: str, text: str, source: str):
        if text.strip():
            chunks.append({"id": chunk_id, "title": title, "text": text.strip(), "source": source})

    lss = analysis.get("lss") or {}
    safety = analysis.get("safety") or {}
    context = lss.get("context") or {}
    metrics = lss.get("metrics") or {}

    if context:
        add("station", "Station", f"Station {context.get('station_name') or 'unnamed'}. "
            f"{_text(context.get('process_description'))} Takt time {context.get('takt_time_s')} s, "
            f"cycle time {context.get('cycle_time_s')} s, {context.get('operators')} operator(s), "
            f"{context.get('shift_hours')} hour shift. {_text(context.get('notes'))}", "analysis")
    add("summary", "Gemba Kaizen summary", _text(lss.get("summary")), "analysis")
    if metrics:
        add("metrics", "Time breakdown",
            f"Of {metrics.get('video_duration')} s of video, {metrics.get('va_percent')}% of the operator's time was "
            f"value-adding, {metrics.get('nnva_percent')}% necessary non-value-adding, {metrics.get('nva_percent')}% waste "
            f"and {metrics.get('uncertain_percent')}% unclear. Waste projected to a shift: "
            f"{metrics.get('projected_nva_hours_per_shift')} hours.", "analysis")
        for waste in metrics.get("waste_by_category") or []:
            add(f"waste-{waste.get('category')}", f"Waste: {waste.get('label')}",
                f"{waste.get('label')} took {waste.get('seconds')} s, {waste.get('percent_of_person_time')}% of the "
                f"operator's time, about {waste.get('projected_hours_per_shift')} hours per shift.", "analysis")
    for event in safety.get("safety_events") or []:
        add(f"incident-{event.get('rule_id')}-{mmss(event.get('start_time', 0))}",
            f"Incident: {event.get('rule_id')}",
            f"Safety incident, rule '{event.get('prompt')}' ({event.get('severity')} severity), from "
            f"{mmss(event.get('start_time', 0))} to {mmss(event.get('end_time', 0))}, peak confidence "
            f"{event.get('peak_confidence')}. {_text(event.get('description'))}", "analysis")
    for action in lss.get("safety_actions") or []:
        add(f"action-{action.get('rule_id')}", f"Safety action: {action.get('rule_id')}",
            f"For rule {action.get('rule_id')} ({action.get('severity')}): {_text(action.get('action'))}", "analysis")
    for card in lss.get("lss_cards") or []:
        roi = card.get("roi") or {}
        evidence = "; ".join(f"{mmss(e.get('start_time', 0))}-{mmss(e.get('end_time', 0))} {_text(e.get('note'))}"
                             for e in card.get("evidence") or [])
        add(f"lss-{card.get('id')}", f"Gemba Kaizen: {card.get('title')}",
            f"{card.get('title')} ({card.get('priority')} priority, {card.get('category')}). Observation: "
            f"{_text(card.get('observation'))} Root cause: {_text(card.get('root_cause'))} Recommendation: "
            f"{_text(card.get('recommendation'))} Evidence: {evidence}. ROI: {_text(roi.get('basis'))}", "analysis")
    for question in lss.get("operator_questions") or []:
        add(f"question-{mmss(question.get('timestamp', 0))}", "Question for the operator",
            f"At {mmss(question.get('timestamp', 0))}, ask the operator: {_text(question.get('question'))}", "analysis")
    for segment in (safety.get("activity") or {}).get("segments", [])[:40]:
        add(f"segment-{mmss(segment.get('start_time', 0))}", "Activity",
            f"From {mmss(segment.get('start_time', 0))} to {mmss(segment.get('end_time', 0))} the operator was "
            f"{_text(segment.get('activity'))} ({segment.get('category')}). {_text(segment.get('description'))}", "analysis")
    count = (analysis.get("person_count") or {}).get("statistics")
    if count:
        add("people", "People in the video",
            f"Up to {count.get('max_persons')} people at once, {count.get('avg_persons')} on average.", "analysis")

    for card in knowledge:
        add(card["id"], f"Lean card: {card['title']}",
            f"{card['title']}. Symptom: {card['symptom']} Countermeasure: {card['countermeasure']} "
            f"Source: {card.get('source', '')}", "knowledge")
    return chunks


def tokens(text: str) -> List[str]:
    """Latin words, plus character bigrams for Thai and Japanese, which have no spaces between words."""
    text = text.lower()
    out = re.findall(r"[a-z0-9]+", text)
    for run in re.findall(r"[^\x00-\x7f\W]+", text):
        out.extend(run[i:i + 2] for i in range(max(1, len(run) - 1)))
    return out


def retrieve(query: str, chunks: List[Dict], limit: int = 6) -> List[Dict]:
    """The `limit` chunks that best match the query (BM25). Chunks with no match are never returned."""
    docs = [tokens(c["title"] + " " + c["text"]) for c in chunks]
    if not docs:
        return []
    average = sum(len(d) for d in docs) / len(docs) or 1
    frequency: Dict[str, int] = {}
    for doc in docs:
        for term in set(doc):
            frequency[term] = frequency.get(term, 0) + 1
    query_terms = set(tokens(query))
    scored = []
    for chunk, doc in zip(chunks, docs):
        score = 0.0
        for term in query_terms:
            tf = doc.count(term)
            if not tf:
                continue
            idf = math.log(1 + (len(docs) - frequency[term] + 0.5) / (frequency[term] + 0.5))
            score += idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * len(doc) / average))
        if score > 0:
            scored.append((score, chunk))
    scored.sort(key=lambda pair: -pair[0])
    return [c for _, c in scored[:limit]]


def answer(question: str, history: List[Dict], analysis: Dict, knowledge: List[Dict], language: str,
           model: str, api_key: str) -> Dict:
    """Retrieve, then let the LLM answer from the chunks (or return the best chunks when there is no key)."""
    chunks = build_chunks(analysis, knowledge)
    # The last few turns count towards the query, so "and the second one?" still finds its topic
    recent = " ".join(m["content"] for m in history[-4:] if m["role"] == "user")
    hits = retrieve(f"{recent} {question}", chunks)
    overview = [c for c in chunks if c["id"] in ("summary", "metrics") and c not in hits]
    selected = hits + overview[:2] if hits else overview[:2]
    sources = [{"id": c["id"], "title": c["title"], "source": c["source"]} for c in selected]

    if not api_key:
        if not selected:
            text = "I have no analysis to answer from yet. Load a video and run the analysis first."
        else:
            text = " ".join(c["text"] for c in selected[:2])
        return {"reply": text, "sources": sources, "source": "retrieval", "model": None, "usage": None}

    context = "\n\n".join(f"[{c['id']}] {c['title']}\n{c['text']}" for c in selected) or "(no analysis loaded)"
    messages = [{"role": "system", "content": SYSTEM_PROMPT.format(language=LANGUAGES.get(language, "English"))}]
    messages += [{"role": m["role"], "content": m["content"]} for m in history[-6:]]
    messages.append({"role": "user", "content": f"CONTEXT:\n{context}\n\nQUESTION: {question}"})
    text, usage = chat(messages, model, api_key, temperature=0.3, max_tokens=500)
    return {"reply": clean_for_speech(text), "sources": sources, "source": "llm", "model": model, "usage": usage or None}


# ============================================================================
# API
# ============================================================================

class VoiceMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., max_length=4000)


class VoiceChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000, description="The user's question")
    history: List[VoiceMessage] = Field(default_factory=list, description="Earlier turns, oldest first")
    analysis: Dict[str, Any] = Field(default_factory=dict,
                                     description="The /analysis/analyze response the dashboard holds (snapshots can be left out)")
    language: str = Field("en", description="Reply language: en, th or ja")


class VoiceSource(BaseModel):
    id: str
    title: str
    source: str = Field(..., description="analysis or knowledge")


class VoiceChatResponse(BaseModel):
    reply: str
    sources: List[VoiceSource]
    source: str = Field(..., description="llm, or retrieval when no OpenRouter key is set")
    model: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None


class VoiceTranscript(BaseModel):
    text: str
    language: Optional[str] = None


class VoiceStatus(BaseModel):
    elevenlabs_configured: bool
    llm_configured: bool
    llm_model: str
    tts_model: str
    stt_model: str
    voice_id: str
    audio_cache: Dict[str, int]


class VoiceSpeakRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    voice_id: Optional[str] = Field(None, description="Defaults to ELEVENLABS_VOICE_ID")


router = APIRouter(prefix="/voice", tags=["voice_agent"])

_eleven: Optional[ElevenLabs] = None
_knowledge: Optional[List[Dict]] = None


def get_eleven() -> ElevenLabs:
    global _eleven
    if _eleven is None:
        _eleven = ElevenLabs()
    return _eleven


def get_knowledge() -> List[Dict]:
    global _knowledge
    if _knowledge is None:
        _knowledge = load_knowledge(KNOWLEDGE_PATH)
    return _knowledge


def llm_model() -> str:
    return os.getenv("VOICE_LLM_MODEL") or os.getenv("LSS_LLM_MODEL") or "google/gemini-3.1-flash-lite"


@router.get("/status", response_model=VoiceStatus, summary="Voice Agent status")
def voice_status():
    eleven = get_eleven()
    return {"elevenlabs_configured": eleven.configured, "llm_configured": bool(os.getenv("OPENROUTER_API_KEY")),
            "llm_model": llm_model(), "tts_model": eleven.tts_model, "stt_model": eleven.stt_model,
            "voice_id": eleven.voice_id, "audio_cache": eleven.store.stats()}


@router.post("/chat", response_model=VoiceChatResponse, summary="Answer a question about the analysis")
def voice_chat(request: VoiceChatRequest):
    """RAG over the analysis you send and the Gemba Kaizen knowledge cards; the answer is plain text meant to be read aloud."""
    try:
        return answer(request.message, [m.model_dump() for m in request.history], request.analysis, get_knowledge(),
                      request.language, llm_model(), os.getenv("OPENROUTER_API_KEY", ""))
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))


@router.post("/speak", summary="Text to speech (ElevenLabs, cached in the voice database)",
             responses={200: {"content": {"audio/mpeg": {}}, "description": "MP3 audio"}})
def voice_speak(request: VoiceSpeakRequest):
    eleven = get_eleven()
    try:
        audio, mime, cached = eleven.speak(request.text, request.voice_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except RuntimeError as e:
        code = status.HTTP_503_SERVICE_UNAVAILABLE if not eleven.configured else status.HTTP_502_BAD_GATEWAY
        raise HTTPException(status_code=code, detail=str(e))
    return Response(content=audio, media_type=mime, headers={"X-Voice-Cache": "hit" if cached else "miss"})


@router.post("/transcribe", response_model=VoiceTranscript, summary="Speech to text (ElevenLabs Scribe)")
def voice_transcribe(file: UploadFile):
    eleven = get_eleven()
    audio = file.file.read(MAX_AUDIO_BYTES + 1)
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Audio is larger than 25 MB")
    if not audio:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Empty audio")
    try:
        return eleven.transcribe(audio, file.filename or "speech.webm", file.content_type or "audio/webm")
    except RuntimeError as e:
        code = status.HTTP_503_SERVICE_UNAVAILABLE if not eleven.configured else status.HTTP_502_BAD_GATEWAY
        raise HTTPException(status_code=code, detail=str(e))
