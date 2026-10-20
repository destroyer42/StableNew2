"""Deterministic clip measurements for the video eval kit (PR-VID-EVAL-320).

These are guardrails, not a quality score. A high motion value does not mean the requested movement
happened, and no number here picks a winner: the owner's rating does. The metrics exist to make
regressions visible at a glance: a clip that freezes, flickers, drifts in colour or loses detail.

Frames come from the bounded review decoder (``src/video/review_preview.py``: at most 120 frames,
downscaled to at most 256 px, contained and cancellable), so measuring is cheap and identical on every
machine. Values are computed on luma in 0..1 and reported as percentages of full scale, except colour
drift (0..255 RGB distance) and sharpness retention (a ratio).
"""

from __future__ import annotations

import math
import os
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from src.video.review_preview import PreviewClip, PreviewResult, prepare_review_preview

METRICS_SCHEMA = "stablenew.video-eval-metrics.v1"
#: Frames averaged at each end of the clip for drift and detail retention.
_END_WINDOW = 3
_EPSILON = 1e-9


@dataclass(frozen=True)
class ClipMetrics:
    """What one clip measured. ``None`` means the clip is too short for that measure."""

    frames_measured: int
    reported_frame_count: int | None
    truncated: bool
    fps: float | None
    duration_seconds: float | None
    width: int
    height: int
    file_bytes: int
    bitrate_kbps: float | None
    #: Mean absolute luma change between consecutive frames (% of full scale).
    motion: float | None
    #: Mean absolute second temporal difference of luma (% of full scale): jerky or flickering change.
    jitter: float | None
    #: ``jitter / (2 * motion)``: about 0 for steady motion, 1 for frame-to-frame alternation.
    jitter_ratio: float | None
    #: Mean absolute second difference of whole-frame brightness (% of full scale).
    brightness_flicker: float | None
    #: Distance between the mean RGB colour of the first and last frames (0..255 scale).
    color_drift: float | None
    #: Mean luma gradient of the last frames divided by the first frames (below 1 = detail lost).
    sharpness_retention: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ClipMeasurement:
    path: str
    ok: bool
    metrics: ClipMetrics | None = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": METRICS_SCHEMA,
            "path": self.path,
            "ok": self.ok,
            "message": self.message,
            "metrics": self.metrics.to_dict() if self.metrics is not None else None,
        }


def _round(value: float | None, digits: int = 4) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(float(value), digits)


def frames_from_clip(clip: PreviewClip) -> np.ndarray:
    """Decoded preview frames as ``float32`` RGB in 0..1, shape ``(frames, height, width, 3)``."""

    expected = clip.frame_count * clip.frame_bytes
    buffer = np.frombuffer(clip.raw[:expected], dtype=np.uint8)
    return buffer.reshape(clip.frame_count, clip.height, clip.width, 3).astype(np.float32) / 255.0


def _luma(frames: np.ndarray) -> np.ndarray:
    weights = np.array([0.299, 0.587, 0.114], dtype=np.float32)
    return np.asarray(frames @ weights, dtype=np.float32)


def _gradient(luma: np.ndarray) -> float:
    dx = np.abs(np.diff(luma, axis=-1)).mean()
    dy = np.abs(np.diff(luma, axis=-2)).mean()
    return float(dx + dy)


def compute_frame_metrics(frames: np.ndarray) -> dict[str, float | None]:
    """The temporal and colour measures of ``frames`` (``(T, H, W, 3)`` floats in 0..1)."""

    count = int(frames.shape[0])
    luma = _luma(frames)
    motion = jitter = ratio = flicker = None
    if count >= 2:
        motion = float(np.abs(np.diff(luma, axis=0)).mean()) * 100.0
    if count >= 3:
        jitter = float(np.abs(np.diff(luma, n=2, axis=0)).mean()) * 100.0
        ratio = jitter / (2.0 * motion) if motion is not None and motion > _EPSILON else 0.0
        brightness = luma.mean(axis=(1, 2))
        flicker = float(np.abs(np.diff(brightness, n=2)).mean()) * 100.0
    drift = retention = None
    if count >= 2:
        window = max(1, min(_END_WINDOW, count // 2))
        head, tail = frames[:window], frames[-window:]
        drift = float(np.linalg.norm(tail.mean(axis=(0, 1, 2)) - head.mean(axis=(0, 1, 2)))) * 255.0
        head_detail = _gradient(luma[:window])
        retention = _gradient(luma[-window:]) / head_detail if head_detail > _EPSILON else None
    return {
        "motion": _round(motion),
        "jitter": _round(jitter),
        "jitter_ratio": _round(ratio),
        "brightness_flicker": _round(flicker),
        "color_drift": _round(drift, 2),
        "sharpness_retention": _round(retention),
    }


def metrics_from_clip(clip: PreviewClip, *, file_bytes: int) -> ClipMetrics:
    measures = compute_frame_metrics(frames_from_clip(clip))
    duration = clip.duration_seconds
    bitrate = (file_bytes * 8 / duration / 1000.0) if duration and duration > 0 else None
    return ClipMetrics(
        frames_measured=clip.frame_count,
        reported_frame_count=clip.reported_frame_count,
        truncated=clip.truncated,
        fps=clip.fps,
        duration_seconds=_round(duration, 3),
        width=clip.source_width,
        height=clip.source_height,
        file_bytes=int(file_bytes),
        bitrate_kbps=_round(bitrate, 1),
        **measures,
    )


def measure_clip(
    path: str | Path,
    *,
    decode: Callable[..., PreviewResult] = prepare_review_preview,
    cancel: threading.Event | None = None,
) -> ClipMeasurement:
    """Decode the bounded preview of ``path`` and measure it. Never raises for a bad file."""

    text = str(path)
    result = decode(text, cancel=cancel)
    if not result.ok or result.clip is None:
        return ClipMeasurement(path=text, ok=False, message=result.message or "decode failed")
    if result.clip.frame_count < 1:
        return ClipMeasurement(path=text, ok=False, message="the clip has no frames")
    try:
        size = os.path.getsize(text)
    except OSError:
        size = 0
    return ClipMeasurement(
        path=text, ok=True, metrics=metrics_from_clip(result.clip, file_bytes=size)
    )


__all__ = [
    "METRICS_SCHEMA",
    "ClipMeasurement",
    "ClipMetrics",
    "compute_frame_metrics",
    "frames_from_clip",
    "measure_clip",
    "metrics_from_clip",
]
