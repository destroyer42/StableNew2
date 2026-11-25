"""Global image-motion diagnostics: driving reference versus generated result (PR-VID-MOTION-410).

What this is: the mean absolute luma change between consecutive frames of two bounded review previews, turned into a
motion-energy trace per clip, and a handful of timing statistics about those traces (when the clip is active, whether it
freezes, how the two traces line up on a common time basis).

What it is **not**: pose fidelity, proof that the *intended subject* moved, or a quality score. A moving background, a
camera move, a lighting change or a duplicate figure produce the same trace as the intended movement; the driver and the
result differ in colour, scene, framing and subject, so raw pixel similarity is meaningless and none is computed. Every
result carries ``kind = "global_image_motion_diagnostic"`` and its limitations, and ``subject_attachment_evidence`` and
``validated_pose_fidelity`` are always ``False``. There is no composite score and no pass/fail threshold: human-rated action
achievement, subject attachment, identity and fidelity are separate evidence.

Failure is a value: a missing or undecodable clip, no reported frame rate, a static driver, a zero-variance trace or too few
samples yield ``unavailable`` / ``insufficient_evidence`` with the reason, never zero.

CPU only, NumPy only, on frames the existing bounded decoder produced (``src/video/review_preview.py``).
"""

from __future__ import annotations

import math
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

from src.video.review_preview import PreviewClip, PreviewResult, prepare_review_preview
from src.video.video_eval_metrics import frames_from_clip

DIAGNOSTIC_SCHEMA = "stablenew.video-eval-motion-diagnostic.v1"
DIAGNOSTIC_KIND = "global_image_motion_diagnostic"
STATUS_OK = "ok"
STATUS_INSUFFICIENT = "insufficient_evidence"
STATUS_UNAVAILABLE = "unavailable"

#: Percent of full scale. Below this peak a clip is *static* for diagnostic purposes.
STATIC_PEAK = 0.05
#: Percent of full scale. A frame pair with less change than this is a repeated (held or duplicated) frame.
REPEAT_EPSILON = 0.02
#: A frame interval is *active* above this fraction of the clip's own peak energy.
ACTIVE_FRACTION = 0.2
#: Consecutive repeated frame pairs that make a *frozen interval* worth reporting.
FROZEN_MIN_PAIRS = 3
#: Fewest samples on the common grid for a correlation or lag to mean anything.
MIN_SAMPLES = 6
MAX_LAG_SECONDS = 1.0
#: A best lag below this correlation is "no aligned peak", not a measured displacement.
MIN_LAG_CORRELATION = 0.2
_SMOOTH = 3
_EPSILON = 1e-9
#: A trace whose spread is below this fraction of its level is constant, not a signal.
_FLAT_RATIO = 0.02

LIMITATIONS = (
    "Global image-motion diagnostic only: mean luma change between consecutive preview frames. It is not human pose "
    "fidelity and does not show that the intended subject moved.",
    "Camera moves, moving backgrounds, lighting changes and duplicate figures produce the same signal as the intended "
    "movement. Driver and result differ in colour, scene, framing and subject, so no pixel similarity is computed.",
    "Measured on the bounded review preview (the first 120 frames at no more than 256 px). It is a guardrail, not a "
    "score: action achievement, subject attachment, identity and motion fidelity are judged by the operator.",
)


@dataclass(frozen=True)
class DiagnosticClip:
    """One decoded preview, reduced to luma, or the reason there is none."""

    label: str
    luma: np.ndarray | None = None
    fps: float | None = None
    reported_frames: int | None = None
    truncated: bool = False
    problem: str = ""

    @property
    def frames(self) -> int:
        return 0 if self.luma is None else int(self.luma.shape[0])


def clip_from_preview(clip: PreviewClip, label: str) -> DiagnosticClip:
    rgb = frames_from_clip(clip)
    weights = np.array([0.299, 0.587, 0.114], dtype=np.float32)
    return DiagnosticClip(
        label=label,
        luma=np.asarray(rgb @ weights, dtype=np.float32),
        fps=clip.fps,
        reported_frames=clip.reported_frame_count,
        truncated=clip.truncated,
    )


def _round(value: float | None, digits: int = 4) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(float(value), digits)


def motion_energy(luma: np.ndarray) -> np.ndarray:
    """Mean absolute luma change between consecutive frames, in percent of full scale (length ``T - 1``)."""

    if luma.shape[0] < 2:
        return np.zeros(0, dtype=np.float64)
    return np.abs(np.diff(luma.astype(np.float64), axis=0)).mean(axis=(1, 2)) * 100.0


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Maximal runs ``[start, end)`` of True values."""

    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, value in enumerate(mask):
        if value and start is None:
            start = index
        elif not value and start is not None:
            runs.append((start, index))
            start = None
    if start is not None:
        runs.append((start, len(mask)))
    return runs


@dataclass(frozen=True)
class _Trace:
    energy: np.ndarray
    fps: float | None
    repeated: np.ndarray
    held_tail: int

    @property
    def peak(self) -> float:
        return float(self.energy.max()) if self.energy.size else 0.0

    @property
    def static(self) -> bool:
        return self.peak < STATIC_PEAK

    @property
    def active(self) -> np.ndarray:
        if self.static:
            return np.zeros(self.energy.shape, dtype=bool)
        return self.energy >= ACTIVE_FRACTION * self.peak


def _trace(clip: DiagnosticClip) -> _Trace | None:
    if clip.luma is None or clip.frames < 2:
        return None
    energy = motion_energy(clip.luma)
    repeated = energy < REPEAT_EPSILON
    tail = 0
    for flag in repeated[::-1]:
        if not flag:
            break
        tail += 1
    return _Trace(energy, clip.fps if clip.fps and clip.fps > 0 else None, repeated, tail)


def _seconds(index: float, fps: float | None) -> float | None:
    return None if fps is None else index / fps


def describe_clip(clip: DiagnosticClip) -> dict[str, Any]:
    """Single-clip facts: activity window, repeated frames and frozen intervals. Unavailable values are ``None``."""

    base: dict[str, Any] = {
        "label": clip.label,
        "frames_measured": clip.frames,
        "reported_frames": clip.reported_frames,
        "preview_truncated": clip.truncated,
        "fps": _round(clip.fps),
    }
    trace = _trace(clip)
    if trace is None:
        return {
            **base,
            "status": STATUS_UNAVAILABLE,
            "reason": clip.problem or "fewer than two frames",
        }
    pairs = int(trace.energy.size)
    active = trace.active
    runs = [run for run in _runs(trace.repeated) if run[1] - run[0] >= FROZEN_MIN_PAIRS]
    on = np.flatnonzero(active)
    mean_active = float(trace.energy[active].mean()) if active.any() else None
    return {
        **base,
        "status": STATUS_OK if trace.fps else STATUS_INSUFFICIENT,
        "reason": "" if trace.fps else "no frame rate reported; timing is unavailable",
        "duration_seconds": _round(_seconds(clip.frames, trace.fps)),
        "peak_energy": _round(trace.peak),
        "mean_active_energy": _round(mean_active),
        "static": trace.static,
        "active_seconds": _round(_seconds(int(active.sum()), trace.fps)),
        "onset_seconds": _round(_seconds(int(on[0]), trace.fps)) if on.size else None,
        "offset_seconds": _round(_seconds(int(on[-1]) + 1, trace.fps)) if on.size else None,
        "repeated_frame_ratio": _round(float(trace.repeated.sum()) / pairs if pairs else None),
        "held_tail_frames": trace.held_tail,
        "held_tail_seconds": _round(_seconds(trace.held_tail, trace.fps)),
        "frozen_intervals": [
            {
                "start_seconds": _round(_seconds(a, trace.fps)),
                "end_seconds": _round(_seconds(b, trace.fps)),
            }
            for a, b in runs
        ],
    }


def _resample(trace: _Trace, grid: np.ndarray) -> np.ndarray:
    """Zero-order hold of the energy at the times in ``grid`` (seconds), each clip on its own frame clock."""

    assert trace.fps is not None
    index = np.clip(np.floor(grid * trace.fps + 1e-9).astype(int), 0, trace.energy.size - 1)
    return np.asarray(trace.energy[index], dtype=np.float64)


def _smooth(values: np.ndarray) -> np.ndarray:
    if values.size < _SMOOTH:
        return values
    kernel = np.ones(_SMOOTH) / _SMOOTH
    padded = np.pad(values, (_SMOOTH // 2, _SMOOTH // 2), mode="edge")
    return np.convolve(padded, kernel, mode="valid")


def _zscore(values: np.ndarray) -> np.ndarray | None:
    """Standardized trace, or ``None`` when it is flat (float noise on a constant counts as flat)."""

    spread = float(values.std())
    level = max(abs(float(values.mean())), STATIC_PEAK)
    if spread < _FLAT_RATIO * level:
        return None
    return (values - float(values.mean())) / spread


def _best_lag(a: np.ndarray, b: np.ndarray, step: float) -> tuple[float | None, float | None]:
    """The lag (seconds; positive = ``b`` happens later than ``a``) with the highest normalized cross-correlation."""

    limit = int(min(MAX_LAG_SECONDS / step, 0.25 * a.size))
    best_lag, best_value = 0, -2.0
    for lag in range(-limit, limit + 1):
        left = a[max(0, -lag) : a.size - max(0, lag)]
        right = b[max(0, lag) : b.size - max(0, -lag)]
        if left.size < MIN_SAMPLES:
            continue
        x, y = _zscore(left), _zscore(right)
        if x is None or y is None:
            continue
        value = float((x * y).mean())
        if value > best_value:
            best_lag, best_value = lag, value
    if best_value < MIN_LAG_CORRELATION:
        return None, None if best_value < -1.5 else _round(best_value)
    return _round(best_lag * step), _round(best_value)


def compare_clips(driver: DiagnosticClip, result: DiagnosticClip) -> dict[str, Any]:
    """The full diagnostic for one driving reference and one generated clip. Never raises for bad media."""

    out: dict[str, Any] = {
        "schema": DIAGNOSTIC_SCHEMA,
        "kind": DIAGNOSTIC_KIND,
        "limitations": list(LIMITATIONS),
        "subject_attachment_evidence": False,
        "validated_pose_fidelity": False,
        "driver": describe_clip(driver),
        "result": describe_clip(result),
        "comparison": None,
        "reasons": [],
    }
    reasons: list[str] = out["reasons"]
    d_trace, r_trace = _trace(driver), _trace(result)
    if d_trace is None:
        reasons.append(
            f"driving reference unavailable: {driver.problem or 'fewer than two frames'}"
        )
    if r_trace is None:
        reasons.append(f"generated clip unavailable: {result.problem or 'fewer than two frames'}")
    if d_trace is None or r_trace is None:
        out["status"] = STATUS_UNAVAILABLE
        return out
    if d_trace.fps is None or r_trace.fps is None:
        reasons.append(
            "a clip reports no frame rate, so the two cannot be placed on a common time basis"
        )
        out["status"] = STATUS_INSUFFICIENT
        return out
    if driver.truncated or result.truncated:
        reasons.append(
            "a preview holds only the first frames of its clip; the comparison covers that window only"
        )
    if d_trace.static:
        reasons.append(
            "the driving reference shows no global image motion, so there is no trace to compare against"
        )
        out["status"] = STATUS_INSUFFICIENT
        return out

    step = 1.0 / max(d_trace.fps, r_trace.fps)
    # A prepared driver that is shorter than the output holds its last frame; that hold is not motion to reproduce.
    driver_effective = (d_trace.energy.size - d_trace.held_tail) / d_trace.fps
    overlap = min(driver_effective, r_trace.energy.size / r_trace.fps)
    count = int(overlap / step)
    comparison: dict[str, Any] = {
        "common_time_basis": "seconds from the first frame; each clip on its own frame clock (zero-order hold)",
        "grid_step_seconds": _round(step, 6),
        "compared_seconds": _round(count * step),
        "driver_held_tail_seconds": _round(d_trace.held_tail / d_trace.fps),
        "result_held_tail_seconds": _round(r_trace.held_tail / r_trace.fps),
        "duration_difference_seconds": _round(
            abs(d_trace.energy.size / d_trace.fps - r_trace.energy.size / r_trace.fps)
        ),
        "fps_differs": abs(d_trace.fps - r_trace.fps) > 1e-6,
    }
    d_mean, r_mean = (
        describe_clip(driver).get("mean_active_energy"),
        describe_clip(result).get("mean_active_energy"),
    )
    comparison["relative_motion_magnitude"] = (
        _round(r_mean / d_mean)
        if isinstance(d_mean, float) and isinstance(r_mean, float) and d_mean > 0
        else None
    )
    d_on, r_on = np.flatnonzero(d_trace.active), np.flatnonzero(r_trace.active)
    comparison["onset_displacement_seconds"] = (
        _round(r_on[0] / r_trace.fps - d_on[0] / d_trace.fps) if d_on.size and r_on.size else None
    )
    comparison["offset_displacement_seconds"] = (
        _round((r_on[-1] + 1) / r_trace.fps - (d_on[-1] + 1) / d_trace.fps)
        if d_on.size and r_on.size
        else None
    )
    if count < MIN_SAMPLES:
        reasons.append("too few overlapping samples to compare the traces")
        comparison.update(trace_correlation=None, lag_seconds=None, lag_correlation=None)
        out["comparison"], out["status"] = comparison, STATUS_INSUFFICIENT
        return out
    grid = (np.arange(count) + 0.5) * step
    left = _smooth(_resample(d_trace, grid))
    right = _smooth(_resample(r_trace, grid))
    driver_active = (
        _resample(_Trace(d_trace.active.astype(float), d_trace.fps, d_trace.repeated, 0), grid)
        > 0.5
    )
    frozen_while_driving = right < REPEAT_EPSILON
    comparison["result_frozen_while_driver_active_seconds"] = _round(
        float(np.count_nonzero(frozen_while_driving & driver_active)) * step
    )
    x, y = _zscore(left), _zscore(right)
    if x is None or y is None:
        reasons.append(
            "the generated clip's motion trace has no variation (a frozen or constant-motion clip)"
            if y is None
            else "the driving trace has no variation over the compared window"
        )
        comparison.update(trace_correlation=None, lag_seconds=None, lag_correlation=None)
        out["comparison"], out["status"] = comparison, STATUS_INSUFFICIENT
        return out
    comparison["trace_correlation"] = _round(float((x * y).mean()))
    lag, lag_value = _best_lag(left, right, step)
    comparison["lag_seconds"], comparison["lag_correlation"] = lag, lag_value
    if lag is None:
        reasons.append("no aligned peak between the traces, so no timing displacement is reported")
    out["comparison"], out["status"] = comparison, STATUS_OK
    return out


# --------------------------------------------------------------------------------------- decoding


Decoder = Callable[..., PreviewResult]


class PreviewCache:
    """Decoded previews keyed by path, so one driving reference is decoded once for every arm that used it."""

    def __init__(self, decode: Decoder = prepare_review_preview) -> None:
        self._decode = decode
        self._clips: dict[str, DiagnosticClip] = {}

    def clip(self, path: str, label: str, cancel: threading.Event | None = None) -> DiagnosticClip:
        cached = self._clips.get(path)
        if cached is not None:
            return DiagnosticClip(
                label,
                cached.luma,
                cached.fps,
                cached.reported_frames,
                cached.truncated,
                cached.problem,
            )
        result = self._decode(path, cancel=cancel)
        if not result.ok or result.clip is None or result.clip.frame_count < 1:
            found = DiagnosticClip(label, problem=result.message or "decode failed")
        else:
            found = clip_from_preview(result.clip, label)
        self._clips[path] = found
        return found


def diagnose_paths(
    driver_path: str | None,
    result_path: str | None,
    *,
    cache: PreviewCache | None = None,
    cancel: threading.Event | None = None,
) -> dict[str, Any]:
    """Decode both bounded previews and compare them. A missing path is an unavailable diagnostic, not an error."""

    previews = cache or PreviewCache()
    driver = (
        previews.clip(driver_path, "driving reference", cancel)
        if driver_path
        else DiagnosticClip("driving reference", problem="no driving reference file is available")
    )
    result = (
        previews.clip(result_path, "generated clip", cancel)
        if result_path
        else DiagnosticClip("generated clip", problem="no generated clip is available")
    )
    return compare_clips(driver, result)


def unavailable(reason: str) -> dict[str, Any]:
    """A diagnostic that could not be attempted (for example the driving context changed)."""

    return {
        "schema": DIAGNOSTIC_SCHEMA,
        "kind": DIAGNOSTIC_KIND,
        "status": STATUS_UNAVAILABLE,
        "reasons": [reason],
        "limitations": list(LIMITATIONS),
        "subject_attachment_evidence": False,
        "validated_pose_fidelity": False,
        "driver": None,
        "result": None,
        "comparison": None,
    }


__all__ = [
    "DIAGNOSTIC_KIND",
    "DIAGNOSTIC_SCHEMA",
    "LIMITATIONS",
    "STATUS_INSUFFICIENT",
    "STATUS_OK",
    "STATUS_UNAVAILABLE",
    "DiagnosticClip",
    "PreviewCache",
    "clip_from_preview",
    "compare_clips",
    "describe_clip",
    "diagnose_paths",
    "motion_energy",
    "unavailable",
]
