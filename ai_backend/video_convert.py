"""
Browser preview conversion: re-encode any video the backend can read to H.264 MP4 that every browser plays.

Analysis never needs this (OpenCV reads the original); it only gives the dashboard a playable preview of
HEVC / MPEG-4 / AVI / MKV files. Frame timing is kept, so timestamps in the analysis still match the preview.
One conversion runs at a time (a small VM has little RAM), and the output is capped at 1280 px wide with no audio.
"""

import shutil
import subprocess
import threading

PREVIEW_WIDTH = 1280
_one_at_a_time = threading.Semaphore(1)


class ConversionError(RuntimeError):
    pass


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def convert_for_browser(src: str, dst: str, timeout: float = 900) -> None:
    """Write an H.264 MP4 preview of `src` to `dst`. Raises ConversionError (message safe to show)."""
    if not ffmpeg_available():
        raise ConversionError("ffmpeg is not installed on the backend")
    command = [
        "ffmpeg", "-y", "-v", "error", "-i", src,
        "-vf", f"scale='min({PREVIEW_WIDTH},iw)':-2",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p",
        "-an", "-movflags", "+faststart", dst,
    ]
    with _one_at_a_time:
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise ConversionError("The conversion took too long")
    if result.returncode != 0:
        raise ConversionError(f"ffmpeg could not read this video: {result.stderr.strip()[-200:]}")
