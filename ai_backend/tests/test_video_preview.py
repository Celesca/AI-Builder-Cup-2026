import shutil

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

import server

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(server, "PRELOAD_MODEL", False)
    monkeypatch.setattr(server, "load_counter", lambda: None)
    with TestClient(server.app) as c:
        yield c


@pytest.fixture
def mp4v_video(tmp_path):
    """MPEG-4 part 2, which browsers cannot play."""
    path = str(tmp_path / "old.mp4")
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 10, (320, 240))
    for i in range(30):
        writer.write(np.full((240, 320, 3), i * 8, dtype=np.uint8))
    writer.release()
    return path


@needs_ffmpeg
def test_preview_is_h264_with_the_same_duration(client, mp4v_video, tmp_path):
    with open(mp4v_video, "rb") as f:
        response = client.post("/video/preview", files={"file": ("old.mp4", f, "video/mp4")})
    assert response.status_code == 200 and response.headers["content-type"] == "video/mp4"
    out = tmp_path / "preview.mp4"
    out.write_bytes(response.content)
    import subprocess
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name:format=duration",
                            "-of", "default=nw=1", str(out)], capture_output=True, text=True).stdout
    assert "codec_name=h264" in probe
    assert abs(float(probe.split("duration=")[1].split()[0]) - 3.0) < 0.2


def test_preview_rejects_non_video(client):
    response = client.post("/video/preview", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert response.status_code == 400


def test_preview_without_ffmpeg_is_503(client, monkeypatch, mp4v_video):
    monkeypatch.setattr("video_convert.ffmpeg_available", lambda: False)
    with open(mp4v_video, "rb") as f:
        response = client.post("/video/preview", files={"file": ("old.mp4", f, "video/mp4")})
    assert response.status_code == 503 and "ffmpeg" in response.json()["detail"]
