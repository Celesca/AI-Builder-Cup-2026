# Video Action Detection API (OpenRouter VLM + Gemba Kaizen agent + YOLO; BLIP optional)
#
# CPU build (default):
#   docker build -t video-action-api .
# CUDA build (needs an NVIDIA GPU + nvidia-container-toolkit at run time):
#   docker build -t video-action-api --build-arg TORCH_INDEX_URL=https://download.pytorch.org/whl/cu124 .

FROM python:3.13-slim

ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/app/.cache/huggingface \
    YOLO_MODEL=/app/models/yolov8n.pt

# libglib2.0-0 is needed by opencv-python-headless; ffmpeg makes browser-playable previews (/video/preview)
RUN apt-get update \
    && apt-get install -y --no-install-recommends libglib2.0-0 ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install torch + torchvision from the chosen index first so requirements.txt does not pull the
# default (CUDA, multi-GB) wheels on a CPU build
RUN pip install torch torchvision --index-url ${TORCH_INDEX_URL}

COPY requirements.txt .
# ultralytics pulls in opencv-python (needs libGL); swap it back for the headless build.
# Both packages share the cv2 folder, so headless must be reinstalled after the uninstall.
RUN pip install -r requirements.txt \
    && python -m spacy download en_core_web_sm \
    && pip uninstall -y opencv-python \
    && pip install --force-reinstall --no-deps opencv-python-headless

# YOLOv8 nano weights are small (~6 MB), so bake them into the image
RUN mkdir -p /app/models \
    && python -c "from ultralytics import YOLO; YOLO('${YOLO_MODEL}')" \
    && test -f ${YOLO_MODEL}

COPY annotate_video.py video_convert.py video_utils.py openrouter_client.py vlm_action_model.py safety_agent.py lss_agent.py voice_agent.py \
    video_action_model.py person_count_model.py server.py ./
COPY knowledge ./knowledge
COPY static ./static

RUN useradd --create-home --uid 1000 app \
    && mkdir -p ${HF_HOME} /app/data \
    && chown -R app:app /app
USER app

# Only the /video_action (BLIP) endpoints use local weights (~2 GB, downloaded on first use into HF_HOME); the VLM and
# the Gemba Kaizen agent run on OpenRouter, so this image needs no GPU and about 1 GB of RAM
VOLUME ["/app/.cache/huggingface", "/app/data"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=4)"

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
