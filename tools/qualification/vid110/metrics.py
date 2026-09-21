"""Objective clip metrics (motion, drift, identity proxies) and contact sheets."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # numpy/cv2 come from the optional svd extra; import them lazily
    import numpy as np


_FLOW_WIDTH = 256


@dataclass(frozen=True)
class ClipMetrics:
    frames: int
    fps: float
    width: int
    height: int
    duration_s: float
    local_motion_px: float  # mean per-frame flow after removing global (camera) translation
    camera_drift_px: float  # mean per-frame magnitude of the median (global) flow
    motion_area_fraction: float  # share of pixels moving more than 0.5 px between frames
    temporal_jitter: float  # mean |second difference| of luminance (flicker proxy)
    identity_hist_mean: float | None  # HSV-histogram correlation of frames vs the source image
    identity_hist_min: float | None

    def as_dict(self) -> dict[str, Any]:
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in asdict(self).items()}


def read_frames(path: Path, *, max_frames: int | None = None) -> tuple[list[np.ndarray], float]:
    import cv2

    capture = cv2.VideoCapture(str(path))
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    frames: list[np.ndarray] = []
    while True:
        ok, frame = capture.read()
        if not ok or (max_frames is not None and len(frames) >= max_frames):
            break
        frames.append(frame)
    capture.release()
    return frames, fps


def _small(frame: np.ndarray) -> np.ndarray:
    import cv2

    height, width = frame.shape[:2]
    scale = _FLOW_WIDTH / width
    return cv2.resize(
        frame, (_FLOW_WIDTH, max(1, int(height * scale))), interpolation=cv2.INTER_AREA
    )


def _hsv_hist(image: np.ndarray) -> np.ndarray:
    import cv2

    hsv = cv2.cvtColor(_small(image), cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [16, 16], [0, 180, 0, 256])
    return cv2.normalize(hist, hist).flatten()


def clip_metrics(video: Path, *, source_image: Path | None = None) -> ClipMetrics:
    import cv2
    import numpy as np

    frames, fps = read_frames(video)
    if len(frames) < 2:
        raise ValueError(f"{video} has fewer than 2 decodable frames")
    gray = [cv2.cvtColor(_small(f), cv2.COLOR_BGR2GRAY) for f in frames]
    local, drift, area = [], [], []
    for previous, current in zip(gray, gray[1:], strict=False):
        flow = cv2.calcOpticalFlowFarneback(previous, current, None, 0.5, 3, 15, 3, 5, 1.2, 0)
        vectors = flow.reshape(-1, 2)
        global_shift = np.median(vectors, axis=0)
        residual = np.linalg.norm(vectors - global_shift, axis=1)
        local.append(float(residual.mean()))
        drift.append(float(np.linalg.norm(global_shift)))
        area.append(float((np.linalg.norm(vectors, axis=1) > 0.5).mean()))
    luminance = np.array([g.mean() for g in gray], dtype=np.float64)
    jitter = float(np.abs(np.diff(luminance, n=2)).mean()) if len(luminance) > 2 else 0.0
    identity: list[float] = []
    if source_image is not None:
        source = cv2.imread(str(source_image))
        if source is not None:
            reference = _hsv_hist(source)
            identity = [
                float(cv2.compareHist(reference, _hsv_hist(f), cv2.HISTCMP_CORREL)) for f in frames
            ]
    height, width = frames[0].shape[:2]
    return ClipMetrics(
        frames=len(frames),
        fps=fps,
        width=width,
        height=height,
        duration_s=len(frames) / fps if fps else 0.0,
        local_motion_px=float(np.mean(local)),
        camera_drift_px=float(np.mean(drift)),
        motion_area_fraction=float(np.mean(area)),
        temporal_jitter=jitter,
        identity_hist_mean=float(np.mean(identity)) if identity else None,
        identity_hist_min=float(np.min(identity)) if identity else None,
    )


def contact_sheet(video: Path, target: Path, *, columns: int = 6, count: int = 12) -> Path:
    import cv2
    import numpy as np

    """Evenly sampled frames tiled into one PNG for visual scoring."""

    frames, _ = read_frames(video)
    indices = np.linspace(0, len(frames) - 1, num=min(count, len(frames))).astype(int)
    tiles = [
        cv2.resize(frames[i], (320, int(320 * frames[i].shape[0] / frames[i].shape[1])))
        for i in indices
    ]
    rows = []
    for start in range(0, len(tiles), columns):
        row = tiles[start : start + columns]
        while len(row) < columns:
            row.append(np.zeros_like(tiles[0]))
        rows.append(np.hstack(row))
    target.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(target), np.vstack(rows))
    return target


def motion_curve(video: Path) -> list[float]:
    """Per-frame local-motion magnitude (camera translation removed) for curve comparison."""

    import cv2
    import numpy as np

    frames, _ = read_frames(video)
    gray = [cv2.cvtColor(_small(f), cv2.COLOR_BGR2GRAY) for f in frames]
    curve: list[float] = []
    for previous, current in zip(gray, gray[1:], strict=False):
        flow = cv2.calcOpticalFlowFarneback(previous, current, None, 0.5, 3, 15, 3, 5, 1.2, 0)
        vectors = flow.reshape(-1, 2)
        residual = np.linalg.norm(vectors - np.median(vectors, axis=0), axis=1)
        curve.append(float(residual.mean()))
    return curve


def curve_correlation(a: list[float], b: list[float]) -> float:
    """Pearson correlation of two motion curves resampled to a common length."""

    import numpy as np

    length = min(len(a), len(b))
    if length < 3:
        return 0.0
    xs = np.interp(np.linspace(0, 1, length), np.linspace(0, 1, len(a)), a)
    ys = np.interp(np.linspace(0, 1, length), np.linspace(0, 1, len(b)), b)
    if xs.std() == 0 or ys.std() == 0:
        return 0.0
    return float(np.corrcoef(xs, ys)[0, 1])
