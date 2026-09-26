"""PR-VID-184 pure-stdlib tracking/scoring over ``detect_runner.py``'s per-frame person-box JSON.

No numpy/cv2/onnxruntime dependency here -- only plain floats read back from JSON -- so this
module imports cleanly in the StableNew ``.venv`` even though detection itself must run in the
disposable CPU-only environment (see ``detect_runner.py``'s module docstring).

Computes the three detector-dependent Phase C metrics (``primary_subject_continuity``,
``ghost_actor_persistence``, ``root_translation_fraction``) via a simple greedy nearest-centroid
single-object tracker: the box closest (by centroid distance) to the previous frame's chosen box
continues the primary track; any other box present in the same frame counts as a candidate
"ghost" (a second, non-primary detection). This is deliberately simple -- it has no identity/ReID
model, so it cannot confirm the primary track actually matches the *reference image's* identity,
only that a single detection persists continuously. That scope limit is recorded in
PR-VID-184's report, not hidden.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

Box = list[float]  # [x1, y1, x2, y2, score]


def _centroid(box: Box) -> tuple[float, float]:
    x1, y1, x2, y2 = box[:4]
    return (x1 + x2) / 2.0, (y1 + y2) / 2.0


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


@dataclass(frozen=True, slots=True)
class TrackingResult:
    frame_count: int
    frame_width: int
    primary_present_frames: int
    max_ghost_run: int
    root_translation_fraction: float
    first_centroid_x: float | None
    last_centroid_x: float | None

    @property
    def primary_subject_continuity(self) -> float:
        if self.frame_count == 0:
            return 0.0
        return self.primary_present_frames / self.frame_count

    @property
    def ghost_actor_persistence(self) -> int:
        return self.max_ghost_run


def track(payload: dict[str, Any], *, max_jump_fraction: float = 0.35) -> TrackingResult:
    """Greedy nearest-centroid single-track over ``payload['frames']``.

    ``max_jump_fraction`` bounds how far (as a fraction of frame width) the primary track may
    jump between consecutive frames before treating the detection as lost rather than continued;
    this prevents the tracker from silently hopping onto a ghost figure.
    """

    frames: list[list[Box]] = payload["frames"]
    width = int(payload["frame_width"])
    max_jump = width * max_jump_fraction

    primary_present = 0
    ghost_run = 0
    max_ghost_run = 0
    prev_centroid: tuple[float, float] | None = None
    first_centroid_x: float | None = None
    last_centroid_x: float | None = None

    for boxes in frames:
        if not boxes:
            prev_centroid = None
            ghost_run = 0
            continue

        centroids = [_centroid(b) for b in boxes]
        if prev_centroid is None:
            # (Re)acquire on the largest box -- the most likely real subject, not a distant
            # false positive.
            areas = [(b[2] - b[0]) * (b[3] - b[1]) for b in boxes]
            chosen = max(range(len(boxes)), key=lambda i: areas[i])
        else:
            distances = [_distance(prev_centroid, c) for c in centroids]
            chosen = min(range(len(boxes)), key=lambda i: distances[i])
            if distances[chosen] > max_jump:
                prev_centroid = None
                ghost_run = 0
                continue

        primary_present += 1
        prev_centroid = centroids[chosen]
        if first_centroid_x is None:
            first_centroid_x = centroids[chosen][0]
        last_centroid_x = centroids[chosen][0]

        others = len(boxes) - 1
        if others > 0:
            ghost_run += 1
            max_ghost_run = max(max_ghost_run, ghost_run)
        else:
            ghost_run = 0

    if first_centroid_x is not None and last_centroid_x is not None and width > 0:
        root_translation_fraction = abs(last_centroid_x - first_centroid_x) / width
    else:
        root_translation_fraction = 0.0

    return TrackingResult(
        frame_count=len(frames),
        frame_width=width,
        primary_present_frames=primary_present,
        max_ghost_run=max_ghost_run,
        root_translation_fraction=root_translation_fraction,
        first_centroid_x=first_centroid_x,
        last_centroid_x=last_centroid_x,
    )


def load_and_track(json_path: Path) -> TrackingResult:
    payload = json.loads(Path(json_path).read_text(encoding="utf-8"))
    return track(payload)


__all__ = ["Box", "TrackingResult", "track", "load_and_track"]
