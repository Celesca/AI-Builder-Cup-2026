"""
Video Action Detection FastAPI Server (BLIP pipeline + OpenRouter VLM pipeline + YOLO person counting,
BLIP and YOLO ported from Celesca/valz)

Endpoints:
  GET  /health                       - health check
  GET  /video_action/status          - BLIP detector status
  POST /video_action/detect          - detect actions (+ count people) in a video from URL (JSON body)
  POST /video_action/detect/upload   - detect actions (+ count people) in an uploaded video (multipart)
  GET  /vlm_action/status            - VLM (OpenRouter) detector status
  POST /vlm_action/detect            - detect actions with the VLM (+ count people) in a video from URL (JSON body)
  POST /vlm_action/detect/upload     - detect actions with the VLM (+ count people) in an uploaded video (multipart)
  GET  /person_count/status          - YOLO person counter status
  POST /person_count/detect          - count people in a video from URL (JSON body)
  POST /person_count/detect/upload   - count people in an uploaded video (multipart)

VALZ pipeline (Safety Agent -> Gemba Kaizen Agent):
  POST /safety/detect                - Safety Agent: safety rules + activity timeline (VLM), video from URL
  POST /safety/detect/upload         - Safety Agent on an uploaded video
  GET  /lss/status                - Gemba Kaizen Agent status (LLM configured, model, knowledge cards)
  POST /lss/suggest               - Gemba Kaizen Agent: Gemba Kaizen cards from a Safety Agent result (JSON)
  POST /analysis/analyze                - full pipeline on a video from URL
  POST /analysis/analyze/upload         - full pipeline on an uploaded video
  GET  /demo                         - upload page for the full pipeline

Browser preview:
  POST /video/preview                - re-encode an uploaded video to H.264 MP4 so a browser can play it (needs ffmpeg)

Voice Agent (chat over the analysis, ElevenLabs speech):
  GET  /voice/status                 - ElevenLabs / LLM configured, voice, audio cache size
  POST /voice/chat                   - RAG answer to a question about an analysis (JSON)
  POST /voice/speak                  - text to speech (MP3), cached in the voice database
  POST /voice/transcribe             - speech to text (multipart audio)
"""

import json
import logging
import os
import shutil
import tempfile
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Annotated, Any, Callable, Dict, List, Literal, Optional, Tuple, Union
from urllib.parse import urlparse

import requests
import uvicorn
from fastapi import Body, Depends, FastAPI, Form, HTTPException, Query, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel, Field

# Optional .env (OPENROUTER_API_KEY, ...); python-dotenv comes with uvicorn[standard]
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import video action detection model
try:
    from video_action_model import (
        BLIP_MODEL_NAME, SIMILARITY_MODEL_NAME, ActionDetector, DetectionConfig,
    )
    VIDEO_ACTION_AVAILABLE = True
    IMPORT_ERROR = None
except ImportError as e:
    VIDEO_ACTION_AVAILABLE = False
    ActionDetector = None
    IMPORT_ERROR = str(e)
    logger.warning(f"Video action detection not available: {e}")

# Import the OpenRouter VLM action detector (optional: the BLIP line works without it)
try:
    from vlm_action_model import VLM_MODEL_NAME, VLMActionDetector, VLMDetectionConfig
    VLM_ACTION_AVAILABLE = True
    VLM_IMPORT_ERROR = None
except ImportError as e:
    VLM_ACTION_AVAILABLE = False
    VLMActionDetector = None
    VLM_MODEL_NAME = None
    VLM_IMPORT_ERROR = str(e)
    logger.warning(f"VLM action detection not available: {e}")

from video_convert import ConversionError, convert_for_browser
from voice_agent import router as voice_router  # Voice Agent: needs only requests + sqlite3

# Safety Agent + Gemba Kaizen Agent (the Safety Agent runs on the OpenRouter VLM detector)
try:
    from lss_agent import LssAgent, StationContext
    from safety_agent import DEFAULT_RULES, SafetyAgent, SafetyAgentConfig, SafetyRule, parse_rules_text, slugify
    ANALYSIS_AVAILABLE = True
    ANALYSIS_IMPORT_ERROR = None
except ImportError as e:
    ANALYSIS_AVAILABLE = False
    ANALYSIS_IMPORT_ERROR = str(e)
    logger.warning(f"VALZ pipeline not available: {e}")

# Import YOLO person counter (optional: action detection works without it)
try:
    from person_count_model import PersonCountConfig, PersonCounter
    PERSON_COUNT_AVAILABLE = True
    PERSON_COUNT_IMPORT_ERROR = None
except ImportError as e:
    PERSON_COUNT_AVAILABLE = False
    PersonCounter = None
    PERSON_COUNT_IMPORT_ERROR = str(e)
    logger.warning(f"Person counting not available: {e}")

PRELOAD_MODEL = os.getenv("PRELOAD_MODEL", "1") == "1"
BATCH_SIZE = int(os.getenv("BLIP_BATCH_SIZE", "8"))
VLM_MODEL = os.getenv("VLM_MODEL") or VLM_MODEL_NAME  # any OpenRouter model that accepts images
VLM_CONCURRENCY = int(os.getenv("VLM_CONCURRENCY", "4"))  # parallel VLM requests
VLM_MAX_IMAGE_SIDE = int(os.getenv("VLM_MAX_IMAGE_SIDE", "640"))
YOLO_MODEL = os.getenv("YOLO_MODEL", "yolov8n.pt")
YOLO_BATCH_SIZE = int(os.getenv("YOLO_BATCH_SIZE", "16"))
YOLO_DEVICE = os.getenv("YOLO_DEVICE") or None  # default: cuda if available, else cpu
MAX_VIDEO_MB = int(os.getenv("MAX_VIDEO_MB", "500"))
VIDEO_EXTENSIONS = ['.mp4', '.avi', '.mov', '.mkv', '.webm', '.flv', '.wmv']


# ============================================================================
# Model lifecycle (models are loaded once and shared by all requests)
# ============================================================================

_detector = None
_detector_error: Optional[str] = IMPORT_ERROR
_detector_lock = threading.Lock()

_vlm_detector = None
_vlm_detector_error: Optional[str] = VLM_IMPORT_ERROR
_vlm_detector_lock = threading.Lock()

_counter = None
_counter_error: Optional[str] = PERSON_COUNT_IMPORT_ERROR
_counter_lock = threading.Lock()

def load_detector():
    global _detector, _detector_error
    if not VIDEO_ACTION_AVAILABLE:
        return None
    with _detector_lock:
        if _detector is None:
            try:
                logger.info("Initializing video action detector...")
                _detector = ActionDetector(batch_size=BATCH_SIZE)
                _detector_error = None
            except Exception as e:
                logger.exception("Failed to initialize video action detector")
                _detector_error = str(e)
    return _detector


def load_vlm_detector():
    global _vlm_detector, _vlm_detector_error
    if not VLM_ACTION_AVAILABLE:
        return None
    with _vlm_detector_lock:
        if _vlm_detector is None:
            try:
                api_key = os.getenv("OPENROUTER_API_KEY", "")
                if not api_key:
                    raise RuntimeError("OPENROUTER_API_KEY is not set")
                logger.info(f"Initializing VLM action detector ({VLM_MODEL} via OpenRouter)...")
                _vlm_detector = VLMActionDetector(api_key=api_key, model_name=VLM_MODEL, batch_size=VLM_CONCURRENCY,
                                                  max_image_side=VLM_MAX_IMAGE_SIDE)
                _vlm_detector_error = None
            except Exception as e:
                logger.exception("Failed to initialize VLM action detector")
                _vlm_detector_error = str(e)
    return _vlm_detector


def load_counter():
    global _counter, _counter_error
    if not PERSON_COUNT_AVAILABLE:
        return None
    with _counter_lock:
        if _counter is None:
            try:
                logger.info("Initializing YOLO person counter...")
                _counter = PersonCounter(model_name=YOLO_MODEL, device=YOLO_DEVICE, batch_size=YOLO_BATCH_SIZE)
                _counter_error = None
            except Exception as e:
                logger.exception("Failed to initialize YOLO person counter")
                _counter_error = str(e)
    return _counter


def get_detector():
    detector = load_detector()
    if detector is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Video action detection is not available: {_detector_error}"
        )
    return detector


def get_vlm_detector():
    detector = load_vlm_detector()
    if detector is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"VLM action detection is not available: {_vlm_detector_error}"
        )
    return detector


def get_counter():
    counter = load_counter()
    if counter is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Person counting is not available: {_counter_error}"
        )
    return counter


_lss_agent = None


def get_lss_agent():
    """The Gemba Kaizen Agent is cheap to build (no model): created on first use, reading OPENROUTER_API_KEY then."""
    global _lss_agent
    if not ANALYSIS_AVAILABLE:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=f"VALZ pipeline is not available: {ANALYSIS_IMPORT_ERROR}")
    if _lss_agent is None:
        _lss_agent = LssAgent()
    return _lss_agent


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Video Action Detection API starting...")
    if PRELOAD_MODEL:
        await run_in_threadpool(load_counter)
        await run_in_threadpool(load_detector)
    await run_in_threadpool(load_vlm_detector)  # no weights to load: just checks OPENROUTER_API_KEY
    yield


API_DESCRIPTION = """
Find **when an action happens** in a video from a text prompt (e.g. `person running`), and **count the people** in it.

* **video_action**: BLIP captions sampled frames, MiniLM compares each caption with the prompt.
  YOLO counts people in parallel unless `count_people=false`.
* **vlm_action**: a vision model on OpenRouter (default `qwen/qwen3.7-flash`) answers Yes/No per sampled frame
  ("is `<prompt>` happening?") with a 0-100 confidence. Prompts can describe conditions, e.g. `worker not wearing a helmet`.
  YOLO counts people in parallel unless `count_people=false`.
* **person_count**: YOLOv8 nano person counting only.
* **VALZ pipeline** (proof of concept): the **Safety Agent** (`/safety`) checks safety rules such as
  `not wearing a helmet` or `running` and labels what the worker does per frame (value-adding, walking, waiting, ...);
  the **Gemba Kaizen Agent** (`/lss`) turns that into Gemba Kaizen cards with ROI, citing a lean knowledge base,
  using an LLM through OpenRouter (rule-based without `OPENROUTER_API_KEY`). Both agents run on OpenRouter models,
  so this needs no GPU and no model weights. `/analysis/analyze` runs both;
  `/demo` is an upload page for it.

Videos can be uploaded (multipart) or given as a direct file URL (YouTube is not supported).
The raw OpenAPI spec is at [`/openapi.json`](/openapi.json); a copy is kept in `ai_backend/openapi.json`.
"""

OPENAPI_TAGS = [
    {"name": "video_action", "description": "Action detection with BLIP + MiniLM, plus parallel YOLO person counting"},
    {"name": "vlm_action", "description": "Action detection with an OpenRouter vision model, plus parallel YOLO person counting"},
    {"name": "person_count", "description": "Person counting with YOLO only"},
    {"name": "safety_agent", "description": "Safety rules + activity (Muda) timeline with an OpenRouter vision model"},
    {"name": "lss_agent", "description": "Gemba Kaizen suggestions from Safety Agent results (LLM via OpenRouter + knowledge cards)"},
    {"name": "analysis_pipeline", "description": "Safety Agent -> Gemba Kaizen Agent in one call"},
    {"name": "video_preview", "description": "H.264 MP4 preview of an uploaded video, for browsers that cannot play the original"},
    {"name": "voice_agent", "description": "Chat over the analysis (RAG + OpenRouter LLM) with ElevenLabs speech in and out"},
    {"name": "health", "description": "Service and model status"},
]

# Initialize FastAPI app
app = FastAPI(
    title="Video Action Detection API",
    description=API_DESCRIPTION,
    version="1.3.0",
    lifespan=lifespan,
    openapi_tags=OPENAPI_TAGS,
    # operationId = function name, so generated clients get names like `detectVideoActionFromUpload`
    generate_unique_id_function=lambda route: route.name,
)

# CORS: comma-separated list in ALLOWED_ORIGINS env var (default = allow all)
_allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "*")
ALLOWED_ORIGINS = [o.strip() for o in _allowed_origins_env.split(",")] if _allowed_origins_env != "*" else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    # Read by the dashboard when it uploads straight to the backend (annotated video counts, download progress)
    expose_headers=["Content-Length", "Content-Disposition", "X-Safety-Events", "X-Annotated-Frames"],
)


# ============================================================================
# Pydantic Models: requests
# ============================================================================

class PersonCountParams(BaseModel):
    person_confidence: float = Field(0.5, ge=0.0, le=1.0, description="YOLO detection confidence threshold")
    person_sample_fps: float = Field(2.0, gt=0.0, le=30.0, description="Frames per second of video counted by YOLO")

    def to_person_config(self) -> "PersonCountConfig":
        return PersonCountConfig(confidence_threshold=self.person_confidence, sample_fps=self.person_sample_fps)


class DetectionParams(PersonCountParams):
    person_weight: float = Field(0.2, ge=0.0, le=1.0, description="Weight for person detection component")
    action_weight: float = Field(0.7, ge=0.0, le=1.0, description="Weight for action detection component")
    context_weight: float = Field(0.1, ge=0.0, le=1.0, description="Weight for context detection component")
    similarity_threshold: float = Field(0.5, ge=0.0, le=1.0, description="Overall similarity threshold")
    action_threshold: float = Field(0.4, ge=0.0, le=1.0, description="Action-specific threshold")
    sample_fps: float = Field(1.0, gt=0.0, le=10.0, description="Frames sampled per second of video")
    segment_gap: float = Field(3.0, ge=0.0, description="Max gap (seconds) between frames in one segment")
    return_timeline: bool = Field(True, description="Whether to return timeline visualization data")
    count_people: bool = Field(True, description="Also count people with YOLO, in parallel with action detection")

    def to_config(self) -> "DetectionConfig":
        return DetectionConfig(**self.model_dump(include=set(DetectionConfig.__dataclass_fields__)))


class VideoActionRequest(DetectionParams):
    """Action detection on a video at a direct URL"""
    video_url: str = Field(..., description="Direct http(s) URL of a video file (not YouTube)",
                           examples=["https://example.com/video.mp4"])
    prompt: str = Field(..., min_length=1, description="Action to find", examples=["person running"])


class VideoActionUpload(DetectionParams):
    """Action detection on an uploaded video (multipart form)"""
    file: UploadFile = Field(..., description="Video file (mp4, avi, mov, mkv, webm, flv, wmv)")
    prompt: str = Field(..., min_length=1, description="Action to find", examples=["person running"])


class VLMDetectionParams(PersonCountParams):
    confidence_threshold: float = Field(0.5, ge=0.0, le=1.0,
                                        description="Minimum P(Yes) for a frame to pass")
    sample_fps: float = Field(1.0, gt=0.0, le=10.0, description="Frames sampled per second of video")
    segment_gap: float = Field(3.0, ge=0.0, description="Max gap (seconds) between frames in one segment")
    describe: bool = Field(True, description="Also ask the VLM for a one-sentence description of each frame "
                                             "(slower; false scores Yes/No only)")
    return_timeline: bool = Field(True, description="Whether to return timeline visualization data")
    count_people: bool = Field(True, description="Also count people with YOLO, in parallel with action detection")

    def to_config(self) -> "VLMDetectionConfig":
        return VLMDetectionConfig(**self.model_dump(include={'confidence_threshold', 'sample_fps',
                                                             'segment_gap', 'describe'}))


class VLMActionRequest(VLMDetectionParams):
    """VLM action detection on a video at a direct URL"""
    video_url: str = Field(..., description="Direct http(s) URL of a video file (not YouTube)",
                           examples=["https://example.com/video.mp4"])
    prompt: str = Field(..., min_length=1, max_length=500, description="Action or situation to find",
                        examples=["worker not wearing a helmet"])


class VLMActionUpload(VLMDetectionParams):
    """VLM action detection on an uploaded video (multipart form)"""
    file: UploadFile = Field(..., description="Video file (mp4, avi, mov, mkv, webm, flv, wmv)")
    prompt: str = Field(..., min_length=1, max_length=500, description="Action or situation to find",
                        examples=["worker not wearing a helmet"])


class SafetyRuleModel(BaseModel):
    """One safety rule: the VLM is asked "is <prompt> happening?" per frame"""
    id: Optional[str] = Field(None, description="Short id; generated from the prompt when empty", examples=["no_helmet"])
    prompt: str = Field(..., min_length=1, max_length=300, examples=["a person who is not wearing a safety helmet"])
    severity: Literal["low", "medium", "high"] = "medium"
    threshold: float = Field(0.6, ge=0.0, le=1.0, description="Minimum P(Yes) for a frame to count as a violation")


class SafetyParams(PersonCountParams):
    sample_fps: float = Field(1.0, gt=0.0, le=5.0, description="Frames analyzed per second of video")
    max_frames: int = Field(240, ge=1, le=1200,
                            description="Longer videos are sampled more sparsely so at most this many frames are analyzed")
    segment_gap: float = Field(2.0, ge=0.0, description="Seconds; violations closer than this form one event")
    activity_min_confidence: float = Field(0.4, ge=0.0, le=1.0,
                                           description="Below this the frame's activity is UNCERTAIN")
    max_descriptions: int = Field(12, ge=0, le=40, description="Key frames described in one sentence by the VLM")
    include_snapshots: bool = Field(True, description="Attach a small JPEG (data URI) of each key frame")
    count_people: bool = Field(True, description="Also count people with YOLO, in parallel")

    def to_safety_config(self) -> "SafetyAgentConfig":
        return SafetyAgentConfig(**self.model_dump(include={'sample_fps', 'max_frames', 'segment_gap',
                                                            'activity_min_confidence', 'max_descriptions',
                                                            'include_snapshots'}))


class StationFields(BaseModel):
    station_name: str = Field("", max_length=200, examples=["Assembly cell 3"])
    process_description: str = Field("", max_length=2000, description="What the station does / the SOP in short",
                                     examples=["Fasten 4 screws on the motor housing and inspect"])
    takt_time_s: Optional[float] = Field(None, gt=0, description="Takt time in seconds, if known")
    cycle_time_s: Optional[float] = Field(None, gt=0, description="Typical cycle time in seconds, if known")
    cycles_per_shift: Optional[float] = Field(None, gt=0, description="Default: shift_hours * 3600 / cycle_time_s")
    shift_hours: float = Field(8.0, gt=0, le=24)
    operators: int = Field(1, ge=1, le=100, description="Operators doing this work (scales hours saved)")
    language: Literal["en", "th", "ja"] = Field("en", description="Language of the Gemba Kaizen suggestions")
    notes: str = Field("", max_length=2000, description="Anything else the Gemba Kaizen Agent should know")

    def to_context(self) -> "StationContext":
        return StationContext(**self.model_dump(include=set(StationContext.__dataclass_fields__)))


class SafetyRequest(SafetyParams):
    """Safety Agent on a video at a direct URL"""
    video_url: str = Field(..., description="Direct http(s) URL of a video file (not YouTube)",
                           examples=["https://example.com/video.mp4"])
    rules: Optional[List[SafetyRuleModel]] = Field(None, description="Default: built-in rules (helmet, running, phone, person down)")


class SafetyUpload(SafetyParams):
    """Safety Agent on an uploaded video (multipart form)"""
    file: UploadFile = Field(..., description="Video file (mp4, avi, mov, mkv, webm, flv, wmv)")
    rules: str = Field("", description="One rule per line, optional severity prefix (`high: not wearing a helmet`), "
                                       "or a JSON list of rule objects. Empty = built-in rules.",
                       examples=["high: a person who is not wearing a safety helmet\nmedium: a person running"])


class AnalysisRequest(SafetyRequest, StationFields):
    """Full pipeline on a video at a direct URL"""
    use_llm: bool = Field(True, description="false = rule-based Gemba Kaizen cards only")


class AnalysisUpload(SafetyUpload, StationFields):
    """Full pipeline on an uploaded video (multipart form)"""
    use_llm: bool = Field(True, description="false = rule-based Gemba Kaizen cards only")


class PersonCountRequest(PersonCountParams):
    """Person counting on a video at a direct URL"""
    video_url: str = Field(..., description="Direct http(s) URL of a video file (not YouTube)",
                           examples=["https://example.com/video.mp4"])


class PersonCountUpload(PersonCountParams):
    """Person counting on an uploaded video (multipart form)"""
    file: UploadFile = Field(..., description="Video file (mp4, avi, mov, mkv, webm, flv, wmv)")


# ============================================================================
# Pydantic Models: responses
# ============================================================================

class SimilarityScores(BaseModel):
    """Cosine similarity between prompt and caption components (0 when a side has no words for it)"""
    person: float
    action: float
    context: float
    weighted: float = Field(..., description="Weighted sum using the normalized person/action/context weights")


class VideoActionDetection(BaseModel):
    """One sampled frame scored against the prompt"""
    timestamp: float = Field(..., description="Seconds from the start of the video")
    frame_idx: int = Field(..., description="Index in the original video's frames")
    confidence: float = Field(..., description="Equal to similarity_scores.weighted")
    blip_description: str = Field(..., description="BLIP caption of the frame",
                                  examples=["a man running down a street"])
    similarity_scores: SimilarityScores
    passed: bool = Field(..., description="weighted >= similarity_threshold and action >= action_threshold")


class VideoActionSegment(BaseModel):
    """Passed frames grouped in time (a gap > segment_gap seconds starts a new segment)"""
    start_time: float = Field(..., description="Seconds; timestamp of the first passed frame")
    end_time: float = Field(..., description="Seconds; timestamp of the last passed frame")
    confidence: float = Field(..., description="Mean confidence of the segment's detections")
    frame_count: int
    action_label: str = Field(..., description="Same as action_verb")
    detections: List[VideoActionDetection]


class ActionStats(BaseModel):
    total_frames: int = Field(..., description="Number of sampled (analyzed) frames")
    total_detections: int = Field(..., description="Same as total_frames")
    passed_detections: int
    success_rate: float = Field(..., description="passed_detections / total_detections * 100")
    segments_found: int


class TimelineSegment(BaseModel):
    index: int
    start_time: float
    end_time: float
    duration: float = Field(..., description="end_time - start_time")
    confidence: float
    action_label: str
    frame_count: int


class TimelineVisualization(BaseModel):
    """Compact segment list for drawing a timeline"""
    job_id: str
    prompt: str
    action_verb: str
    video_duration: float
    segments: List[TimelineSegment]


class PersonBox(BaseModel):
    """One detected person, in pixel coordinates of the original frame"""
    person_id: int = Field(..., description="Index within this frame; not a tracked identity")
    confidence: float
    x1: int
    y1: int
    x2: int
    y2: int
    center_x: int
    center_y: int


class FramePersonCount(BaseModel):
    """Person count for one sampled frame"""
    frame_idx: int = Field(..., description="Index in the original video's frames")
    timestamp: float = Field(..., description="Seconds from the start of the video")
    person_count: int
    detections: List[PersonBox]


class PersonCountStatistics(BaseModel):
    frames_analyzed: int = Field(..., description="Number of sampled frames")
    frames_with_people: int
    max_persons: int = Field(..., description="Most people visible in a single frame")
    min_persons: int
    avg_persons: float
    peak_timestamp: float = Field(..., description="Seconds; first frame with max_persons")


class PersonCountTimeline(BaseModel):
    """Parallel arrays for charting the count over time"""
    timestamps: List[float]
    counts: List[int]


class PersonCountResult(BaseModel):
    """YOLO person counting result"""
    job_id: str = Field(..., examples=["yolo_20261015_165833_644600"])
    model: str = Field(..., description="YOLO weights used", examples=["yolov8n.pt"])
    timestamp: str = Field(..., description="Server time when processing finished (ISO 8601)")
    video_duration: float = Field(..., description="Seconds")
    statistics: PersonCountStatistics
    timeline: PersonCountTimeline
    frame_counts: List[FramePersonCount] = Field(..., description="One entry per sampled frame")


class PersonCountResponse(PersonCountResult):
    """Standalone person counting result"""
    success: bool
    video_path: Optional[str] = Field(None, description="The video URL or uploaded filename")


class VideoActionResponse(BaseModel):
    """Action detection result, with the parallel person count"""
    success: bool
    job_id: str = Field(..., examples=["job_20261015_165833_644730"])
    video_path: Optional[str] = Field(None, description="The video URL or uploaded filename")
    prompt: str
    action_verb: str = Field(..., description="Main verb extracted from the prompt", examples=["run"])
    timestamp: str = Field(..., description="Server time when processing finished (ISO 8601)")
    video_duration: float = Field(..., description="Seconds")
    stats: ActionStats
    passed_detections: List[VideoActionDetection] = Field(..., description="Frames that passed both thresholds")
    segments: List[VideoActionSegment]
    timeline_visualization: Optional[TimelineVisualization] = Field(
        None, description="Null when return_timeline=false or no segments were found")
    person_count: Optional[PersonCountResult] = Field(
        None, description="Null when count_people=false or counting failed")
    person_count_error: Optional[str] = Field(None, description="Why person_count is null, if counting was requested")
    error: Optional[str] = None


class VLMActionDetection(BaseModel):
    """One sampled frame judged by the VLM"""
    timestamp: float = Field(..., description="Seconds from the start of the video")
    frame_idx: int = Field(..., description="Index in the original video's frames")
    confidence: float = Field(..., description="Probability of Yes (0-1), from the confidence the model reports")
    answer: Literal["Yes", "No"] = Field(..., description="The VLM's answer")
    vlm_description: str = Field(..., description="One-sentence description of the frame; empty when describe=false",
                                 examples=["A worker is welding a metal frame without a helmet."])
    passed: bool = Field(..., description="confidence >= confidence_threshold")


class VLMActionSegment(BaseModel):
    """Passed frames grouped in time (a gap > segment_gap seconds starts a new segment)"""
    start_time: float = Field(..., description="Seconds; timestamp of the first passed frame")
    end_time: float = Field(..., description="Seconds; timestamp of the last passed frame")
    confidence: float = Field(..., description="Mean confidence of the segment's detections")
    frame_count: int
    action_label: str = Field(..., description="Same as prompt")
    detections: List[VLMActionDetection]


class VLMActionStats(BaseModel):
    total_frames: int = Field(..., description="Number of sampled (analyzed) frames")
    passed_detections: int
    success_rate: float = Field(..., description="passed_detections / total_frames * 100")
    segments_found: int


class VLMActionResponse(BaseModel):
    """VLM action detection result, with the parallel person count"""
    success: bool
    job_id: str = Field(..., examples=["vlm_20261015_165833_644730"])
    video_path: Optional[str] = Field(None, description="The video URL or uploaded filename")
    prompt: str
    model: str = Field(..., description="VLM used", examples=["qwen/qwen3.7-flash"])
    timestamp: str = Field(..., description="Server time when processing finished (ISO 8601)")
    video_duration: float = Field(..., description="Seconds")
    stats: VLMActionStats
    passed_detections: List[VLMActionDetection] = Field(..., description="Frames that passed confidence_threshold")
    segments: List[VLMActionSegment]
    timeline_visualization: Optional[TimelineVisualization] = Field(
        None, description="Null when return_timeline=false or no segments were found; action_verb is the prompt")
    person_count: Optional[PersonCountResult] = Field(
        None, description="Null when count_people=false or counting failed")
    person_count_error: Optional[str] = Field(None, description="Why person_count is null, if counting was requested")
    error: Optional[str] = None


class SafetyRuleOut(BaseModel):
    id: str
    prompt: str
    severity: Literal["low", "medium", "high"]
    threshold: float


class SafetyEventOut(BaseModel):
    """Consecutive frames where one rule was violated"""
    rule_id: str
    prompt: str
    severity: Literal["low", "medium", "high"]
    start_time: float = Field(..., description="Seconds")
    end_time: float = Field(..., description="Seconds (end of the last flagged frame)")
    duration: float
    peak_confidence: float
    mean_confidence: float
    frame_count: int
    key_frame_idx: int = Field(..., description="Frame with the highest confidence")
    key_timestamp: float
    description: str = Field("", description="VLM description of the key frame (empty past max_descriptions)")
    snapshot: Optional[str] = Field(None, description="JPEG data URI of the key frame")


class ActivitySegmentOut(BaseModel):
    """Consecutive frames with the same activity"""
    start_time: float
    end_time: float
    duration: float
    activity: str = Field(..., examples=["working", "walking", "reaching", "carrying", "searching", "waiting",
                                         "inspecting", "no_person", "uncertain"])
    category: str = Field(..., examples=["VA", "NNVA", "NVA_MOTION", "NVA_TRANSPORT", "NVA_WAITING",
                                         "NVA_SEARCH", "NO_PERSON", "UNCERTAIN"])
    confidence: float
    frame_count: int
    key_frame_idx: int
    key_timestamp: float
    description: str = ""
    snapshot: Optional[str] = None


class ActivityFrame(BaseModel):
    timestamp: float
    frame_idx: int
    activity: str
    category: str
    confidence: float
    rule_confidences: Dict[str, float] = Field(..., description="P(Yes) per rule id")


class ActivitySummary(BaseModel):
    observed_seconds: float
    person_visible_seconds: float
    by_activity_seconds: Dict[str, float]
    by_category_seconds: Dict[str, float]
    va_percent: float = Field(..., description="Percent of the time a person is visible")
    nnva_percent: float
    nva_percent: float
    uncertain_percent: float


class ActivityResult(BaseModel):
    summary: ActivitySummary
    segments: List[ActivitySegmentOut]
    timeline: List[ActivityFrame] = Field(default_factory=list, description="One entry per analyzed frame")


class SafetyStats(BaseModel):
    frames_analyzed: int
    safety_events: int
    frames_with_violation: int
    events_by_severity: Dict[str, int]


class SafetyAgentResult(BaseModel):
    """Safety Agent output; also the input of /lss/suggest"""
    job_id: str = Field(..., examples=["safety_20261015_165833_644730"])
    video_path: Optional[str] = None
    model: str = ""
    timestamp: str = ""
    video_duration: float
    sample_fps: float = Field(..., description="Effective sampling rate (lower than requested for long videos)")
    vlm_usage: Optional[Dict[str, float]] = Field(
        None, description="Cloud backend only: requests, tokens and cost (USD, as reported by OpenRouter) of this run")
    rules: List[SafetyRuleOut]
    stats: SafetyStats
    safety_events: List[SafetyEventOut]
    activity: ActivityResult


class SafetyResponse(SafetyAgentResult):
    success: bool
    person_count: Optional[PersonCountResult] = None
    person_count_error: Optional[str] = None


class LssEvidence(BaseModel):
    start_time: float
    end_time: float
    note: str


class LssROI(BaseModel):
    hours_saved_per_shift: float
    throughput_gain_percent: Optional[float] = None
    basis: str = Field(..., description="How the number was computed")


class LssCardOut(BaseModel):
    id: str = Field(..., examples=["K01"])
    title: str
    category: str
    priority: Literal["high", "medium", "low"]
    observation: str
    evidence: List[LssEvidence]
    root_cause: str
    recommendation: str
    kb_card_ids: List[str] = Field(..., description="Knowledge cards the suggestion is based on")
    est_seconds_saved_per_cycle: Optional[float] = None
    waste_share_removed: Optional[float] = Field(None, description="Estimated share (0-1) of the category's waste removed")
    confidence: float
    roi: Optional[LssROI] = Field(None, description="Computed by the Gemba Kaizen Engine, not the LLM")


class SafetyAction(BaseModel):
    rule_id: str
    severity: Literal["low", "medium", "high"]
    action: str
    kb_card_ids: List[str]


class OperatorQuestion(BaseModel):
    timestamp: float = Field(..., description="Seconds into the video")
    question: str


class KnowledgeCardRef(BaseModel):
    id: str
    title: str
    source: str


class WasteMetric(BaseModel):
    category: str
    label: str
    seconds: float
    percent_of_person_time: float
    projected_hours_per_shift: float


class WasteSegmentMetric(BaseModel):
    start: str = Field(..., description="MM:SS")
    start_time: float
    end_time: float
    duration: float
    activity: str
    category: str


class SafetyMetrics(BaseModel):
    events: int
    by_severity: Dict[str, int]
    by_rule: Dict[str, int]
    violation_seconds: float


class PeopleMetrics(BaseModel):
    max_persons: int
    avg_persons: float
    frames_with_people: int
    frames_analyzed: int


class LssMetrics(BaseModel):
    video_duration: float
    observed_seconds: float
    person_visible_seconds: float
    va_percent: float
    nnva_percent: float
    nva_percent: float
    uncertain_percent: float
    waste_by_category: List[WasteMetric]
    longest_waste_segments: List[WasteSegmentMetric]
    projected_nva_hours_per_shift: float
    safety: SafetyMetrics
    cycles_per_shift: Optional[float] = None
    people: Optional[PeopleMetrics] = None


class LssResult(BaseModel):
    """Gemba Kaizen Agent output"""
    job_id: str = Field(..., examples=["lss_20261015_165833_644730"])
    timestamp: str
    source: Literal["llm", "rules"] = Field(..., description="rules = no LLM key, use_llm=false, or the LLM call failed")
    model: Optional[str] = Field(None, description="OpenRouter model id when source=llm")
    llm_error: Optional[str] = None
    context: StationFields
    metrics: LssMetrics
    summary: str
    lss_cards: List[LssCardOut] = Field(..., title="Gemba Kaizen Cards")
    safety_actions: List[SafetyAction]
    operator_questions: List[OperatorQuestion]
    knowledge_cards_used: List[KnowledgeCardRef]
    usage: Optional[Dict[str, Any]] = Field(None, description="LLM token usage reported by OpenRouter")


class LssRequest(BaseModel):
    """Send a Safety Agent result (and optional person count) to the Gemba Kaizen Agent"""
    safety: SafetyAgentResult
    person_count: Optional[PersonCountResult] = None
    context: StationFields = Field(default_factory=StationFields)
    use_llm: bool = True


class AnalysisResponse(BaseModel):
    """Full pipeline result: Safety Agent -> Gemba Kaizen Agent"""
    success: bool
    video_path: Optional[str] = None
    safety: SafetyAgentResult
    person_count: Optional[PersonCountResult] = None
    person_count_error: Optional[str] = None
    lss: LssResult


class LssStatus(BaseModel):
    pipeline_available: bool
    llm_configured: bool = Field(..., description="OPENROUTER_API_KEY is set")
    model: Optional[str] = None
    knowledge_cards: int
    default_rules: List[SafetyRuleOut]
    error: Optional[str] = None


class ErrorResponse(BaseModel):
    detail: str = Field(..., examples=["File must be a video"])


class ValidationErrorItem(BaseModel):
    loc: List[Union[str, int]]
    msg: str
    type: str


class ValidationErrorResponse(BaseModel):
    detail: Union[str, List[ValidationErrorItem]] = Field(
        ..., description="A list for invalid parameters; a string when the video cannot be read or all weights are 0")


class RootResponse(BaseModel):
    name: str
    docs: str
    openapi: str
    endpoints: List[str]


class HealthResponse(BaseModel):
    status: Literal["healthy", "degraded"] = Field(..., description="degraded until a video detector is usable: the VLM (OPENROUTER_API_KEY set) or BLIP (loaded)")
    video_action_available: bool
    detector_loaded: bool
    vlm_action_available: bool
    vlm_detector_loaded: bool
    person_count_available: bool
    counter_loaded: bool
    message: str


class VideoActionFeatures(BaseModel):
    action_detection: bool
    timeline_visualization: bool
    custom_weights: bool
    batched_inference: bool
    parallel_person_count: bool


class VideoActionModelInfo(BaseModel):
    blip_model: str
    similarity_model: str


class VideoActionStatus(BaseModel):
    video_action_available: bool
    detector_loaded: bool
    device: Optional[str] = Field(None, description="cuda, mps or cpu; null until loaded")
    spacy_loaded: bool
    error: Optional[str] = None
    supported_formats: List[str]
    features: VideoActionFeatures
    model_info: Optional[VideoActionModelInfo] = None


class VLMActionStatus(BaseModel):
    vlm_action_available: bool
    detector_loaded: bool
    api_key_configured: bool = Field(..., description="OPENROUTER_API_KEY is set")
    model: Optional[str] = Field(None, description="OpenRouter model id (VLM_MODEL)")
    batch_size: int = Field(..., description="Parallel VLM requests (VLM_CONCURRENCY)")
    max_image_side: int = Field(..., description="Frames are downscaled to this longest side before the VLM")
    error: Optional[str] = None
    supported_formats: List[str]
    parallel_person_count: bool


class PersonCountStatus(BaseModel):
    person_count_available: bool
    counter_loaded: bool
    model: str
    device: Optional[str] = Field(None, description="cuda or cpu; null until loaded")
    error: Optional[str] = None
    supported_formats: List[str]


def _errors(*codes: int) -> Dict[int, Dict[str, Any]]:
    """Documented error responses for the OpenAPI spec."""
    catalog = {
        400: {"model": ErrorResponse, "description": "Not a video, bad or YouTube URL, or download failed"},
        413: {"model": ErrorResponse, "description": "Video is larger than MAX_VIDEO_MB"},
        422: {"model": ValidationErrorResponse, "description": "Invalid parameters, or the video cannot be read"},
        500: {"model": ErrorResponse, "description": "Inference failed"},
        503: {"model": ErrorResponse, "description": "The model is not available"},
    }
    return {code: catalog[code] for code in codes}


# ============================================================================
# Helper Functions
# ============================================================================

def download_video_from_url(url: str) -> str:
    """Download a direct video URL to a temp file and return its path."""
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="video_url must be an http(s) URL")
    if any(p in parsed.netloc.lower() for p in ['youtube.com', 'youtu.be']):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="YouTube URLs are not supported. Use a direct video file URL or upload the video."
        )

    file_extension = next((ext for ext in VIDEO_EXTENSIONS if parsed.path.lower().endswith(ext)), '.mp4')
    max_bytes = MAX_VIDEO_MB * 1024 * 1024
    headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'video/*,*/*;q=0.9'}

    temp_path = None
    try:
        with requests.get(url, stream=True, timeout=60, headers=headers) as response:
            response.raise_for_status()
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as temp_file:
                temp_path = temp_file.name
                downloaded = 0
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    downloaded += len(chunk)
                    if downloaded > max_bytes:
                        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                                            detail=f"Video exceeds {MAX_VIDEO_MB} MB")
                    temp_file.write(chunk)
    except requests.RequestException as e:
        _cleanup(temp_path)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Download failed: {e}")
    except HTTPException:
        _cleanup(temp_path)
        raise

    if os.path.getsize(temp_path) == 0:
        _cleanup(temp_path)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Downloaded video is empty")

    logger.info(f"Video downloaded: {temp_path} ({downloaded} bytes)")
    return temp_path


def save_upload(file: UploadFile) -> str:
    """Validate an uploaded video and save it to a temp file; returns its path."""
    extension = os.path.splitext(file.filename or '')[1].lower()
    is_video_type = (file.content_type or '').startswith('video/')
    if not is_video_type and extension not in VIDEO_EXTENSIONS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File must be a video")

    with tempfile.NamedTemporaryFile(delete=False, suffix=extension or '.mp4') as temp_file:
        temp_path = temp_file.name
        shutil.copyfileobj(file.file, temp_file, length=1024 * 1024)
    if os.path.getsize(temp_path) > MAX_VIDEO_MB * 1024 * 1024:
        _cleanup(temp_path)
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail=f"Video exceeds {MAX_VIDEO_MB} MB")

    logger.info(f"Video uploaded and saved to: {temp_path}")
    return temp_path


def _cleanup(path: Optional[str]):
    if path and os.path.exists(path):
        os.unlink(path)


def _collect_person_count(future: Optional[Future], params) -> Tuple[Optional[Dict], Optional[str]]:
    """Result of the parallel YOLO run; a counting failure never fails the action detection request."""
    if not params.count_people:
        return None, None
    if future is None:
        return None, f"Person counting is not available: {_counter_error}"
    try:
        return future.result(), None
    except Exception as e:
        logger.exception("Person counting failed")
        return None, str(e)


def _run_with_person_count(run: Callable[[], Dict], counter, video_path: str, params,
                           name: str) -> Tuple[Dict, Optional[Dict], Optional[str]]:
    # YOLO runs in a second thread while the action model runs here; leaving the `with` waits for both,
    # so the caller can safely delete the video afterwards
    with ThreadPoolExecutor(max_workers=1) as pool:
        count_future = pool.submit(counter.process_video, video_path, params.to_person_config()) \
            if counter is not None else None
        try:
            results = run()
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except Exception as e:
            logger.exception(f"{name} failed")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                                detail=f"{name} failed: {e}")
        person_count, person_count_error = _collect_person_count(count_future, params)
    return results, person_count, person_count_error


def _detect_with_person_count(detector, counter, video_path: str, prompt: str, params,
                              name: str) -> Tuple[Dict, Optional[Dict], Optional[str]]:
    return _run_with_person_count(
        lambda: detector.process_video(video_path=video_path, prompt=prompt, config=params.to_config(),
                                       include_timeline=params.return_timeline),
        counter, video_path, params, name)


def resolve_rules(rules) -> List["SafetyRule"]:
    """Rules from JSON objects, a JSON string, or text (one per line); empty = built-in rules."""
    if isinstance(rules, str):
        text = rules.strip()
        if not text:
            return list(DEFAULT_RULES)
        if text.startswith('['):
            try:
                rules = [SafetyRuleModel(**r) for r in json.loads(text)]
            except Exception as e:
                raise HTTPException(status_code=422, detail=f"Invalid rules JSON: {e}")
        else:
            parsed = parse_rules_text(text)
            if not parsed:
                raise HTTPException(status_code=422, detail="No safety rules found in `rules`")
            return parsed
    if not rules:
        return list(DEFAULT_RULES)

    resolved, seen = [], set()
    for rule in rules:
        rule_id = rule.id or slugify(rule.prompt)
        while rule_id in seen:
            rule_id += "_"
        seen.add(rule_id)
        resolved.append(SafetyRule(rule_id, rule.prompt, rule.severity, rule.threshold))
    return resolved


def run_safety(vlm, counter, video_path: str, rules: List["SafetyRule"], params: SafetyParams,
               source: str) -> Tuple[Dict, Optional[Dict], Optional[str]]:
    agent = SafetyAgent(vlm)
    results, person_count, person_count_error = _run_with_person_count(
        lambda: agent.process_video(video_path, rules, params.to_safety_config()),
        counter, video_path, params, "Safety Agent")
    results['video_path'] = source
    logger.info(f"Safety Agent completed. Job ID: {results['job_id']}")
    return results, person_count, person_count_error


def run_lss(lss_agent, safety: Dict, person_count: Optional[Dict], context: "StationContext",
               use_llm: bool) -> Dict:
    try:
        return lss_agent.suggest(safety, person_count, context, use_llm=use_llm)
    except Exception as e:
        logger.exception("Gemba Kaizen Agent failed")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Gemba Kaizen Agent failed: {e}")


def run_analysis(vlm, counter, lss_agent, video_path: str, params, source: str) -> AnalysisResponse:
    rules = resolve_rules(params.rules)
    safety, person_count, person_count_error = run_safety(vlm, counter, video_path, rules, params, source)
    lss = run_lss(lss_agent, safety, person_count, params.to_context(), params.use_llm)
    return AnalysisResponse(success=True, video_path=source, safety=safety, person_count=person_count,
                         person_count_error=person_count_error, lss=lss)


def run_detection(detector, counter, video_path: str, prompt: str, params: DetectionParams,
                  source: str) -> VideoActionResponse:
    results, person_count, person_count_error = _detect_with_person_count(
        detector, counter, video_path, prompt, params, "Video action detection")

    logger.info(f"Video action detection completed. Job ID: {results['job_id']}")
    return VideoActionResponse(
        success=True,
        job_id=results['job_id'],
        video_path=source,
        prompt=results['prompt'],
        action_verb=results['action_verb'],
        timestamp=results['timestamp'],
        video_duration=results['video_duration'],
        stats=results['stats'],
        passed_detections=results['passed_detections_only'],
        segments=results['segments'],
        timeline_visualization=results.get('timeline_data'),
        person_count=person_count,
        person_count_error=person_count_error,
    )


def run_vlm_detection(detector, counter, video_path: str, prompt: str, params: VLMDetectionParams,
                      source: str) -> VLMActionResponse:
    results, person_count, person_count_error = _detect_with_person_count(
        detector, counter, video_path, prompt, params, "VLM action detection")

    logger.info(f"VLM action detection completed. Job ID: {results['job_id']}")
    return VLMActionResponse(
        success=True,
        job_id=results['job_id'],
        video_path=source,
        prompt=results['prompt'],
        model=results['model'],
        timestamp=results['timestamp'],
        video_duration=results['video_duration'],
        stats=results['stats'],
        passed_detections=results['passed_detections_only'],
        segments=results['segments'],
        timeline_visualization=results.get('timeline_data'),
        person_count=person_count,
        person_count_error=person_count_error,
    )


def run_person_count(counter, video_path: str, params: PersonCountParams, source: str) -> PersonCountResponse:
    try:
        results = counter.process_video(video_path, params.to_person_config())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Person counting failed")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"Person counting failed: {e}")

    logger.info(f"Person counting completed. Job ID: {results['job_id']}")
    return PersonCountResponse(success=True, **{**results, 'video_path': source})


# ============================================================================
# API Endpoints
# ============================================================================
# Endpoints are sync `def` so FastAPI runs the heavy inference in its threadpool
# instead of blocking the event loop.

VIDEO_ACTION_EXAMPLES = {
    "basic": {
        "summary": "Find an action (defaults)",
        "value": {"video_url": "https://example.com/video.mp4", "prompt": "person running"},
    },
    "tuned": {
        "summary": "Stricter action match, no person count",
        "value": {"video_url": "https://example.com/video.mp4", "prompt": "person falling down",
                  "action_weight": 0.8, "action_threshold": 0.5, "sample_fps": 2.0, "count_people": False},
    },
}

VLM_ACTION_EXAMPLES = {
    "basic": {
        "summary": "Find an action (defaults)",
        "value": {"video_url": "https://example.com/video.mp4", "prompt": "person running"},
    },
    "safety": {
        "summary": "Safety check, Yes/No only (faster), no person count",
        "value": {"video_url": "https://example.com/video.mp4", "prompt": "worker not wearing a helmet",
                  "confidence_threshold": 0.6, "describe": False, "count_people": False},
    },
}

ANALYSIS_EXAMPLES = {
    "default_rules": {
        "summary": "Built-in safety rules, rule-based Gemba Kaizen without LLM",
        "value": {"video_url": "https://example.com/video.mp4", "use_llm": False},
    },
    "custom": {
        "summary": "Custom rules + station context, Gemba Kaizen in Thai",
        "value": {"video_url": "https://example.com/video.mp4",
                  "rules": [{"id": "no_helmet", "prompt": "a person who is not wearing a safety helmet",
                             "severity": "high"},
                            {"prompt": "a person running", "severity": "medium"}],
                  "station_name": "Assembly cell 3", "process_description": "Fasten 4 screws and inspect",
                  "cycle_time_s": 21.4, "language": "th"},
    },
}

PERSON_COUNT_EXAMPLES = {
    "basic": {
        "summary": "Count people (defaults)",
        "value": {"video_url": "https://example.com/video.mp4"},
    },
}


@app.get("/", response_model=RootResponse, tags=["health"], summary="API index")
def root():
    return {
        "name": "Video Action Detection API",
        "docs": "/docs",
        "openapi": "/openapi.json",
        "endpoints": ["/health", "/video_action/status", "/video_action/detect", "/video_action/detect/upload",
                      "/vlm_action/status", "/vlm_action/detect", "/vlm_action/detect/upload",
                      "/person_count/status", "/person_count/detect", "/person_count/detect/upload",
                      "/safety/detect", "/safety/detect/upload", "/safety/annotate", "/safety/annotate/upload", "/lss/status", "/lss/suggest",
                      "/analysis/analyze", "/analysis/analyze/upload", "/demo"],
    }


@app.get("/health", response_model=HealthResponse, tags=["health"], summary="Health check")
def health_check():
    detector_loaded = _detector is not None
    vlm_ready = _vlm_detector is not None
    return {
        "status": "healthy" if detector_loaded or vlm_ready else "degraded",
        "video_action_available": VIDEO_ACTION_AVAILABLE,
        "detector_loaded": detector_loaded,
        "vlm_action_available": VLM_ACTION_AVAILABLE,
        "vlm_detector_loaded": _vlm_detector is not None,
        "person_count_available": PERSON_COUNT_AVAILABLE,
        "counter_loaded": _counter is not None,
        "message": "API is running and a video detector is ready" if detector_loaded or vlm_ready
        else "API is running but no video detector is ready: set OPENROUTER_API_KEY for the VLM "
             f"(VLM: {_vlm_detector_error or 'not loaded yet'}; BLIP: {_detector_error or 'not loaded yet'})",
    }


@app.get("/video_action/status", response_model=VideoActionStatus, tags=["video_action"],
         summary="Action detector status")
def get_video_action_status():
    return {
        "video_action_available": VIDEO_ACTION_AVAILABLE,
        "detector_loaded": _detector is not None,
        "device": getattr(_detector, 'device', None),
        "spacy_loaded": getattr(_detector, 'nlp', None) is not None,
        "error": _detector_error,
        "supported_formats": [ext.lstrip('.') for ext in VIDEO_EXTENSIONS],
        "features": {
            "action_detection": True,
            "timeline_visualization": True,
            "custom_weights": True,
            "batched_inference": True,
            "parallel_person_count": PERSON_COUNT_AVAILABLE,
        },
        "model_info": {
            "blip_model": BLIP_MODEL_NAME,
            "similarity_model": SIMILARITY_MODEL_NAME,
        } if VIDEO_ACTION_AVAILABLE else None,
    }


@app.get("/vlm_action/status", response_model=VLMActionStatus, tags=["vlm_action"],
         summary="VLM (OpenRouter) detector status")
def get_vlm_action_status():
    return {
        "vlm_action_available": VLM_ACTION_AVAILABLE,
        "detector_loaded": _vlm_detector is not None,
        "api_key_configured": bool(os.getenv("OPENROUTER_API_KEY")),
        "model": VLM_MODEL,
        "batch_size": VLM_CONCURRENCY,
        "max_image_side": VLM_MAX_IMAGE_SIDE,
        "error": _vlm_detector_error,
        "supported_formats": [ext.lstrip('.') for ext in VIDEO_EXTENSIONS],
        "parallel_person_count": PERSON_COUNT_AVAILABLE,
    }


@app.get("/person_count/status", response_model=PersonCountStatus, tags=["person_count"],
         summary="Person counter status")
def get_person_count_status():
    return {
        "person_count_available": PERSON_COUNT_AVAILABLE,
        "counter_loaded": _counter is not None,
        "model": YOLO_MODEL,
        "device": getattr(_counter, 'device', None),
        "error": _counter_error,
        "supported_formats": [ext.lstrip('.') for ext in VIDEO_EXTENSIONS],
    }


@app.post("/video_action/detect", response_model=VideoActionResponse, tags=["video_action"],
          summary="Detect an action in a video from a URL", responses=_errors(400, 413, 422, 500, 503))
def detect_video_action_from_url(
    request: Annotated[VideoActionRequest, Body(openapi_examples=VIDEO_ACTION_EXAMPLES)],
    detector=Depends(get_detector),
):
    """
    Download a video from a direct file URL (not YouTube) and find the frames that match `prompt`,
    using BLIP captions compared with MiniLM embeddings.
    With `count_people` (default true), YOLO counts people in parallel and fills `person_count`.
    """
    counter = load_counter() if request.count_people else None
    temp_video_path = download_video_from_url(request.video_url)
    try:
        return run_detection(detector, counter, temp_video_path, request.prompt, request, request.video_url)
    finally:
        _cleanup(temp_video_path)


@app.post("/video_action/detect/upload", response_model=VideoActionResponse, tags=["video_action"],
          summary="Detect an action in an uploaded video", responses=_errors(400, 413, 422, 500, 503))
def detect_video_action_from_upload(
    form: Annotated[VideoActionUpload, Form(media_type="multipart/form-data")],
    detector=Depends(get_detector),
):
    """
    Upload a video (mp4, avi, mov, ...) and find the frames that match `prompt`,
    using BLIP captions compared with MiniLM embeddings.
    With `count_people` (default true), YOLO counts people in parallel and fills `person_count`.
    """
    counter = load_counter() if form.count_people else None
    temp_video_path = save_upload(form.file)
    try:
        return run_detection(detector, counter, temp_video_path, form.prompt, form, form.file.filename or '')
    finally:
        _cleanup(temp_video_path)


@app.post("/vlm_action/detect", response_model=VLMActionResponse, tags=["vlm_action"],
          summary="Detect an action in a video from a URL with the VLM", responses=_errors(400, 413, 422, 500, 503))
def detect_vlm_action_from_url(
    request: Annotated[VLMActionRequest, Body(openapi_examples=VLM_ACTION_EXAMPLES)],
    detector=Depends(get_vlm_detector),
):
    """
    Download a video from a direct file URL (not YouTube) and find the frames where `prompt` is happening,
    by asking the vision model a Yes/No question per sampled frame.
    With `count_people` (default true), YOLO counts people in parallel and fills `person_count`.
    """
    counter = load_counter() if request.count_people else None
    temp_video_path = download_video_from_url(request.video_url)
    try:
        return run_vlm_detection(detector, counter, temp_video_path, request.prompt, request, request.video_url)
    finally:
        _cleanup(temp_video_path)


@app.post("/vlm_action/detect/upload", response_model=VLMActionResponse, tags=["vlm_action"],
          summary="Detect an action in an uploaded video with the VLM", responses=_errors(400, 413, 422, 500, 503))
def detect_vlm_action_from_upload(
    form: Annotated[VLMActionUpload, Form(media_type="multipart/form-data")],
    detector=Depends(get_vlm_detector),
):
    """
    Upload a video (mp4, avi, mov, ...) and find the frames where `prompt` is happening,
    by asking the vision model a Yes/No question per sampled frame.
    With `count_people` (default true), YOLO counts people in parallel and fills `person_count`.
    """
    counter = load_counter() if form.count_people else None
    temp_video_path = save_upload(form.file)
    try:
        return run_vlm_detection(detector, counter, temp_video_path, form.prompt, form, form.file.filename or '')
    finally:
        _cleanup(temp_video_path)


@app.post("/person_count/detect", response_model=PersonCountResponse, tags=["person_count"],
          summary="Count people in a video from a URL", responses=_errors(400, 413, 422, 500, 503))
def count_people_from_url(
    request: Annotated[PersonCountRequest, Body(openapi_examples=PERSON_COUNT_EXAMPLES)],
    counter=Depends(get_counter),
):
    """
    Download a video from a direct file URL (not YouTube) and count people per sampled frame with YOLOv8 nano.
    """
    temp_video_path = download_video_from_url(request.video_url)
    try:
        return run_person_count(counter, temp_video_path, request, request.video_url)
    finally:
        _cleanup(temp_video_path)


@app.post("/person_count/detect/upload", response_model=PersonCountResponse, tags=["person_count"],
          summary="Count people in an uploaded video", responses=_errors(400, 413, 422, 500, 503))
def count_people_from_upload(
    form: Annotated[PersonCountUpload, Form(media_type="multipart/form-data")],
    counter=Depends(get_counter),
):
    """
    Upload a video (mp4, avi, mov, ...) and count people per sampled frame with YOLOv8 nano.
    """
    temp_video_path = save_upload(form.file)
    try:
        return run_person_count(counter, temp_video_path, form, form.file.filename or '')
    finally:
        _cleanup(temp_video_path)


@app.post("/safety/detect", response_model=SafetyResponse, tags=["safety_agent"],
          summary="Safety Agent on a video from a URL", responses=_errors(400, 413, 422, 500, 503))
def detect_safety_from_url(request: SafetyRequest, vlm=Depends(get_vlm_detector)):
    """
    Check safety rules (Yes/No per frame) and label the worker's activity per frame with the vision model.
    Returns safety events, activity segments with Muda categories, and key-frame evidence.
    """
    get_lss_agent()  # 503 if the pipeline modules are missing
    rules = resolve_rules(request.rules)
    counter = load_counter() if request.count_people else None
    temp_video_path = download_video_from_url(request.video_url)
    try:
        results, person_count, error = run_safety(vlm, counter, temp_video_path, rules, request, request.video_url)
    finally:
        _cleanup(temp_video_path)
    return SafetyResponse(success=True, person_count=person_count, person_count_error=error, **results)


@app.post("/safety/detect/upload", response_model=SafetyResponse, tags=["safety_agent"],
          summary="Safety Agent on an uploaded video", responses=_errors(400, 413, 422, 500, 503))
def detect_safety_from_upload(
    form: Annotated[SafetyUpload, Form(media_type="multipart/form-data")],
    vlm=Depends(get_vlm_detector),
):
    """
    Upload a video and check safety rules + activity per frame with the vision model.
    `rules`: one per line with an optional severity prefix, e.g. `high: not wearing a helmet`.
    """
    get_lss_agent()
    rules = resolve_rules(form.rules)
    counter = load_counter() if form.count_people else None
    temp_video_path = save_upload(form.file)
    try:
        results, person_count, error = run_safety(vlm, counter, temp_video_path, rules, form, form.file.filename or '')
    finally:
        _cleanup(temp_video_path)
    return SafetyResponse(success=True, person_count=person_count, person_count_error=error, **results)


def _annotated_response(vlm, video_path: str, rules, params, source: str, margin: float, cleanup_source):
    """Run the Safety Agent, render the annotated video and return it as a file."""
    from annotate_video import render_annotated_video
    counter = load_counter()
    fd, target = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    try:
        results, _, _ = run_safety(vlm, None, video_path, rules, params, source)
        stats = render_annotated_video(video_path, target, results, counter, near_miss_margin=margin)
    except ValueError as e:
        _cleanup(target)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except Exception:
        _cleanup(target)
        raise
    finally:
        cleanup_source()
    logger.info(f"Annotated video: {stats}")
    return FileResponse(target, media_type="video/mp4", filename="annotated.mp4",
                        headers={"X-Safety-Events": str(len(results['safety_events'])),
                                 "X-Annotated-Frames": str(stats['annotated_frames'])},
                        background=BackgroundTask(_cleanup, target))


@app.post("/safety/annotate", tags=["safety_agent"], summary="Annotated safety video from a URL",
          responses={200: {"content": {"video/mp4": {}}, "description": "MP4 with boxes + rule names"},
                     **_errors(400, 413, 422, 500, 503)})
def annotate_safety_from_url(request: SafetyRequest,
                             near_miss_margin: float = Query(0.15, ge=0.0, le=1.0,
                                                             description="Draw amber NEAR MISS boxes within this confidence of the threshold"),
                             vlm=Depends(get_vlm_detector)):
    """Run the Safety Agent, then return the video with person boxes and the rule name on every violation / near miss."""
    get_lss_agent()
    rules = resolve_rules(request.rules)
    path = download_video_from_url(request.video_url)
    return _annotated_response(vlm, path, rules, request, request.video_url, near_miss_margin, lambda: _cleanup(path))


@app.post("/safety/annotate/upload", tags=["safety_agent"], summary="Annotated safety video from an upload",
          responses={200: {"content": {"video/mp4": {}}, "description": "MP4 with boxes + rule names"},
                     **_errors(400, 413, 422, 500, 503)})
def annotate_safety_from_upload(
    form: Annotated[SafetyUpload, Form(media_type="multipart/form-data")],
    near_miss_margin: float = Query(0.15, ge=0.0, le=1.0),
    vlm=Depends(get_vlm_detector),
):
    """Upload a video; get it back with person boxes and the rule name on every violation / near miss."""
    get_lss_agent()
    rules = resolve_rules(form.rules)
    path = save_upload(form.file)
    return _annotated_response(vlm, path, rules, form, form.file.filename or '', near_miss_margin, lambda: _cleanup(path))


@app.get("/lss/status", response_model=LssStatus, tags=["lss_agent"], summary="Gemba Kaizen Agent status")
def get_lss_status():
    if not ANALYSIS_AVAILABLE:
        return {"pipeline_available": False, "llm_configured": False, "knowledge_cards": 0, "default_rules": [],
                "error": ANALYSIS_IMPORT_ERROR}
    agent = get_lss_agent()
    return {
        "pipeline_available": True,
        "llm_configured": agent.llm_configured,
        "model": agent.model,
        "knowledge_cards": len(agent.knowledge),
        "default_rules": [vars(r) for r in DEFAULT_RULES],
    }


@app.post("/lss/suggest", response_model=LssResult, tags=["lss_agent"],
          summary="Gemba Kaizen suggestions from a Safety Agent result", responses=_errors(422, 500, 503))
def suggest_lss(request: LssRequest, lss_agent=Depends(get_lss_agent)):
    """
    Send the `safety` result of `/safety/detect*` (plus `person_count`, optional) and the station context.
    The Gemba Kaizen Engine computes VA / NVA time and ROI; the LLM (OpenRouter) writes Gemba Kaizen cards citing
    knowledge cards and video timestamps. Without `OPENROUTER_API_KEY` the cards are rule-based.
    """
    person_count = request.person_count.model_dump() if request.person_count else None
    return run_lss(lss_agent, request.safety.model_dump(), person_count, request.context.to_context(),
                      request.use_llm)


@app.post("/analysis/analyze", response_model=AnalysisResponse, tags=["analysis_pipeline"],
          summary="Safety Agent -> Gemba Kaizen Agent on a video from a URL", responses=_errors(400, 413, 422, 500, 503))
def analyze_pipeline_from_url(
    request: Annotated[AnalysisRequest, Body(openapi_examples=ANALYSIS_EXAMPLES)],
    vlm=Depends(get_vlm_detector),
    lss_agent=Depends(get_lss_agent),
):
    """Full pipeline: safety rules + activity timeline (VLM), people count (YOLO), then Gemba Kaizen cards."""
    counter = load_counter() if request.count_people else None
    temp_video_path = download_video_from_url(request.video_url)
    try:
        return run_analysis(vlm, counter, lss_agent, temp_video_path, request, request.video_url)
    finally:
        _cleanup(temp_video_path)


@app.post("/analysis/analyze/upload", response_model=AnalysisResponse, tags=["analysis_pipeline"],
          summary="Safety Agent -> Gemba Kaizen Agent on an uploaded video", responses=_errors(400, 413, 422, 500, 503))
def analyze_pipeline_from_upload(
    form: Annotated[AnalysisUpload, Form(media_type="multipart/form-data")],
    vlm=Depends(get_vlm_detector),
    lss_agent=Depends(get_lss_agent),
):
    """
    Upload a workstation video: safety rules + activity timeline (VLM), people count (YOLO), then Gemba Kaizen cards.
    Try it from the browser at [/demo](/demo).
    """
    counter = load_counter() if form.count_people else None
    temp_video_path = save_upload(form.file)
    try:
        return run_analysis(vlm, counter, lss_agent, temp_video_path, form, form.file.filename or '')
    finally:
        _cleanup(temp_video_path)


DEMO_PAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "demo.html")


app.include_router(voice_router)


@app.post("/video/preview", tags=["video_preview"], summary="H.264 MP4 preview of an uploaded video",
          responses={200: {"content": {"video/mp4": {}}, "description": "H.264 MP4, at most 1280 px wide, no audio"},
                     **_errors(400, 413, 422, 503)})
def video_preview(file: UploadFile):
    """
    For videos the browser cannot play (HEVC, MPEG-4 part 2, AVI, MKV ...). Analysis does not need this: it reads the
    original. Frame timing is kept, so analysis timestamps match the preview. Needs `ffmpeg` on the server.
    """
    source = save_upload(file)
    fd, target = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    try:
        convert_for_browser(source, target)
    except ConversionError as e:
        _cleanup(source)
        _cleanup(target)
        unavailable = "not installed" in str(e)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE if unavailable
                            else status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    _cleanup(source)
    return FileResponse(target, media_type="video/mp4", filename="preview.mp4",
                        background=BackgroundTask(_cleanup, target))


@app.get("/demo", include_in_schema=False)
def demo_page():
    return FileResponse(DEMO_PAGE, media_type="text/html")


def export_openapi(path: str):
    """Write the OpenAPI spec to a file (for frontend type generation)."""
    import json
    with open(path, "w") as f:
        json.dump(app.openapi(), f, indent=2)
        f.write("\n")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Video Action Detection API")
    parser.add_argument("--port", type=int, default=8000, help="Port to run on")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    parser.add_argument("--export-openapi", metavar="PATH", help="Write the OpenAPI spec to PATH and exit")
    args = parser.parse_args()

    if args.export_openapi:
        export_openapi(args.export_openapi)
        logger.info(f"OpenAPI spec written to {args.export_openapi}")
    else:
        logger.info("Starting Video Action Detection API...")
        uvicorn.run("server:app", host=args.host, port=args.port, reload=args.reload, log_level="info")
