"""Media validation and identity: an output counts only if it decodes."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_image(path: Path) -> dict[str, Any]:
    """Decode every pixel (not just the header) so a truncated PNG fails."""

    from PIL import Image

    path = Path(path)
    info: dict[str, Any] = {"path": str(path), "kind": "image", "valid": False}
    try:
        with Image.open(path) as image:
            image.load()
            info.update(
                width=image.width, height=image.height, format=image.format, mode=image.mode
            )
        info.update(sha256=sha256_file(path), size=path.stat().st_size, valid=True)
    except Exception as exc:  # noqa: BLE001 - any decode failure is the finding
        info["error"] = f"{type(exc).__name__}: {exc}"
    return info


def find_ffprobe() -> str | None:
    found = shutil.which("ffprobe")
    if found:
        return found
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        sibling = Path(ffmpeg).with_name(
            "ffprobe.exe" if ffmpeg.lower().endswith(".exe") else "ffprobe"
        )
        if sibling.is_file():
            return str(sibling)
    return None


def _inspect_video_ffmpeg(path: Path, info: dict[str, Any]) -> dict[str, Any]:
    """Decode with FFmpeg when OpenCV (an optional dependency) is not installed."""

    ffmpeg = shutil.which("ffmpeg")
    probe = find_ffprobe()
    if not ffmpeg or not probe:
        info["error"] = "neither OpenCV nor FFmpeg/ffprobe is available to decode video"
        return info
    out = subprocess.run(
        [
            probe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,avg_frame_rate",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    stream = (json.loads(out.stdout or "{}").get("streams") or [{}])[0]
    num, _, den = str(stream.get("avg_frame_rate") or "0/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 0.0
    decode = subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-f",
            "null",
            "-progress",
            "pipe:1",
            "-",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    frames = [
        int(line.split("=")[1]) for line in decode.stdout.splitlines() if line.startswith("frame=")
    ]
    decoded = frames[-1] if frames else 0
    info.update(
        fps=round(fps, 3),
        width=int(stream.get("width") or 0),
        height=int(stream.get("height") or 0),
        decoded_frames=decoded,
        sha256=sha256_file(path),
        size=path.stat().st_size,
        decoder="ffmpeg",
    )
    info["valid"] = decode.returncode == 0 and decoded > 0 and info["width"] > 0 and fps > 0
    return info


def inspect_video(path: Path) -> dict[str, Any]:
    """Probe stream facts, then decode every frame; ``valid`` requires a decodable, non-empty stream."""

    path = Path(path)
    info: dict[str, Any] = {"path": str(path), "kind": "video", "valid": False}
    try:
        try:
            import cv2
        except ImportError:
            return _inspect_video_ffmpeg(path, info)

        capture = cv2.VideoCapture(str(path))
        try:
            fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
            width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            decoded = 0
            while True:
                ok, _frame = capture.read()
                if not ok:
                    break
                decoded += 1
        finally:
            capture.release()
        info.update(
            fps=round(fps, 3),
            width=width,
            height=height,
            decoded_frames=decoded,
            sha256=sha256_file(path),
            size=path.stat().st_size,
            decoder="opencv",
        )
        info["valid"] = decoded > 0 and width > 0 and height > 0 and fps > 0
    except Exception as exc:  # noqa: BLE001
        info["error"] = f"{type(exc).__name__}: {exc}"
    probe = find_ffprobe()
    if probe:
        try:
            out = subprocess.run(
                [
                    probe,
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=codec_name,nb_frames,avg_frame_rate",
                    "-of",
                    "json",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            stream = (json.loads(out.stdout or "{}").get("streams") or [{}])[0]
            info["codec"] = stream.get("codec_name")
            info["container_frames"] = stream.get("nb_frames")
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    return info


def inspect_media(path: Path) -> dict[str, Any]:
    suffix = Path(path).suffix.lower()
    if suffix in {".mp4", ".webm", ".mov", ".mkv"}:
        return inspect_video(path)
    return inspect_image(path)
