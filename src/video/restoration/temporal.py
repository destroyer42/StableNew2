"""Temporal stabilisation for per-frame face restoration (PR-VID-POST-304).

CodeFormer restores every frame on its own: the face is detected and aligned per frame, so the
crop jitters by a pixel or two, and the network re-hallucinates skin and teeth every time. Pasted
back, that is shimmer the generator never produced. Two deterministic, model-free filters here
remove most of it:

- ``FaceLandmarkSmoother`` tracks each face across frames and smooths its five landmarks with an
  exponential moving average, so the alignment (the affine transform the helper derives from the
  landmarks) moves smoothly. A track starts over on a large jump, a long detector dropout or a
  scene cut, because dragging a new face towards an old position would be worse than no smoothing.
- ``ResidualSmoother`` smooths what the restoration *added* (restored minus input, in the aligned
  face crop) rather than the face itself, so real expression and motion still come from the
  source frame. Where the aligned crop changed a lot between frames, the history is ignored instead
  of being ghosted onto the new content.

Everything is pure arithmetic over landmarks and crops, so the tests run it with synthetic data.
Landmark order follows the detector: left eye, right eye, nose, left mouth corner, right mouth
corner. Only ``ResidualSmoother`` needs numpy, and it imports it lazily.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

Point = tuple[float, float]
Landmarks = tuple[Point, ...]

# Weight of the *new* observation: 0.4 trails a steady ramp by 1.5 frames and halves white jitter.
DEFAULT_LANDMARK_ALPHA = 0.4
DEFAULT_RESIDUAL_ALPHA = 0.5
# A detection further than this many eye distances from a track is a different face (or a cut).
DEFAULT_MAX_JUMP = 1.0
# Frames a track may go undetected before it is dropped (detectors miss faces for a frame now and then).
DEFAULT_MAX_GAP = 2
# Mean absolute difference (0-255) between 16x16 luma thumbnails above which consecutive frames are a cut.
DEFAULT_SCENE_CUT_THRESHOLD = 32.0
# Mean absolute change (0-255) of the aligned crop at which the residual history stops being trusted.
DEFAULT_MOTION_SCALE = 24.0
_SIGNATURE_SIZE = (16, 16)


def _require_alpha(name: str, alpha: float) -> float:
    if not 0.0 < alpha <= 1.0:
        raise ValueError(f"{name} alpha must be in (0, 1], got {alpha}")
    return float(alpha)


def _as_landmarks(points: Sequence[Sequence[float]]) -> Landmarks:
    return tuple((float(point[0]), float(point[1])) for point in points)


def _centroid(landmarks: Landmarks) -> Point:
    count = len(landmarks)
    return (
        sum(point[0] for point in landmarks) / count,
        sum(point[1] for point in landmarks) / count,
    )


def _eye_distance(landmarks: Landmarks) -> float:
    return math.dist(landmarks[0], landmarks[1])


@dataclass(frozen=True)
class TrackedFace:
    """One detection after tracking: its stable id, smoothed landmarks and whether it continued a track."""

    track_id: int
    landmarks: Landmarks
    continued: bool


@dataclass
class _Track:
    track_id: int
    landmarks: Landmarks
    missed: int = 0


class FaceLandmarkSmoother:
    """Associate detections with tracks and EMA-smooth each track's landmarks."""

    def __init__(
        self,
        *,
        alpha: float = DEFAULT_LANDMARK_ALPHA,
        max_jump: float = DEFAULT_MAX_JUMP,
        max_gap: int = DEFAULT_MAX_GAP,
    ) -> None:
        self.alpha = _require_alpha("landmark", alpha)
        self.max_jump = float(max_jump)
        self.max_gap = int(max_gap)
        self._tracks: list[_Track] = []
        self._next_id = 1
        self.tracks_started = 0

    def live_track_ids(self) -> frozenset[int]:
        return frozenset(track.track_id for track in self._tracks)

    def update(
        self, detections: Sequence[Sequence[Sequence[float]]], *, scene_cut: bool = False
    ) -> list[TrackedFace]:
        """Return one ``TrackedFace`` per detection, in detection order.

        ``scene_cut`` drops every track first: a face that merely sits in the same place after a
        cut is a different shot and must not inherit the old smoothing.
        """

        if scene_cut:
            self._tracks.clear()
        observed = [_as_landmarks(detection) for detection in detections]
        matches = self._match(observed)
        results: list[TrackedFace] = []
        matched_ids: set[int] = set()
        for index, landmarks in enumerate(observed):
            track = matches.get(index)
            if track is None:
                track = _Track(self._next_id, landmarks)
                self._next_id += 1
                self.tracks_started += 1
                self._tracks.append(track)
                results.append(TrackedFace(track.track_id, landmarks, continued=False))
            else:
                track.landmarks = tuple(
                    (
                        self.alpha * new[0] + (1.0 - self.alpha) * old[0],
                        self.alpha * new[1] + (1.0 - self.alpha) * old[1],
                    )
                    for new, old in zip(landmarks, track.landmarks, strict=True)
                )
                track.missed = 0
                results.append(TrackedFace(track.track_id, track.landmarks, continued=True))
            matched_ids.add(track.track_id)
        survivors: list[_Track] = []
        for track in self._tracks:
            if track.track_id not in matched_ids:
                track.missed += 1
                if track.missed > self.max_gap:
                    continue
            survivors.append(track)
        self._tracks = survivors
        return results

    def _match(self, observed: list[Landmarks]) -> dict[int, _Track]:
        """Greedy nearest-centroid assignment, limited to ``max_jump`` eye distances; ties break by ids."""

        candidates: list[tuple[float, int, int]] = []
        for track in self._tracks:
            reach = self.max_jump * max(_eye_distance(track.landmarks), 1.0)
            centre = _centroid(track.landmarks)
            for index, landmarks in enumerate(observed):
                distance = math.dist(centre, _centroid(landmarks))
                if distance <= reach:
                    candidates.append((distance, track.track_id, index))
        by_id = {track.track_id: track for track in self._tracks}
        taken_tracks: set[int] = set()
        matches: dict[int, _Track] = {}
        for _distance, track_id, index in sorted(candidates):
            if track_id in taken_tracks or index in matches:
                continue
            taken_tracks.add(track_id)
            matches[index] = by_id[track_id]
        return matches


def frame_signature(image: Any) -> bytes:
    """A tiny luma thumbnail used only to notice a cut between consecutive frames."""

    return bytes(image.convert("L").resize(_SIGNATURE_SIZE).tobytes())


def is_scene_cut(
    previous: bytes | None,
    current: bytes,
    *,
    threshold: float = DEFAULT_SCENE_CUT_THRESHOLD,
) -> bool:
    if previous is None or len(previous) != len(current):
        return False
    difference = sum(abs(a - b) for a, b in zip(previous, current, strict=True)) / len(current)
    return difference > threshold


class ResidualSmoother:
    """Per-track recursive filter on the restoration residual in aligned face space."""

    def __init__(
        self,
        *,
        alpha: float = DEFAULT_RESIDUAL_ALPHA,
        motion_scale: float = DEFAULT_MOTION_SCALE,
    ) -> None:
        self.alpha = _require_alpha("residual", alpha)
        self.motion_scale = float(motion_scale)
        # track id -> (previous aligned input crop, previous smoothed residual), both float32.
        self._state: dict[int, tuple[Any, Any]] = {}

    def track_ids(self) -> frozenset[int]:
        return frozenset(self._state)

    def forget(self, track_id: int) -> None:
        self._state.pop(track_id, None)

    def retain(self, track_ids: frozenset[int]) -> None:
        for track_id in [known for known in self._state if known not in track_ids]:
            del self._state[track_id]

    def blend(self, track_id: int, cropped: Any, restored: Any) -> Any:
        """Return the restored crop (uint8) with its residual smoothed against this track's history."""

        import numpy as np

        crop = cropped.astype(np.float32)
        residual = restored.astype(np.float32) - crop
        previous = self._state.get(track_id)
        if previous is None or self.alpha >= 1.0:
            smoothed = residual
        else:
            previous_crop, previous_residual = previous
            motion = np.abs(crop - previous_crop).mean(axis=2, keepdims=True)
            trust = np.clip(1.0 - motion / self.motion_scale, 0.0, 1.0)
            history = (1.0 - self.alpha) * trust
            smoothed = (1.0 - history) * residual + history * previous_residual
        self._state[track_id] = (crop, smoothed)
        return np.clip(np.rint(crop + smoothed), 0, 255).astype(np.uint8)


class TemporalFaceStabilizer:
    """Per-clip state for stabilising face restoration; feed it the frames in order."""

    def __init__(
        self,
        *,
        landmark_alpha: float = DEFAULT_LANDMARK_ALPHA,
        residual_alpha: float = DEFAULT_RESIDUAL_ALPHA,
        max_jump: float = DEFAULT_MAX_JUMP,
        max_gap: int = DEFAULT_MAX_GAP,
        scene_cut_threshold: float = DEFAULT_SCENE_CUT_THRESHOLD,
    ) -> None:
        self._landmarks = FaceLandmarkSmoother(
            alpha=landmark_alpha, max_jump=max_jump, max_gap=max_gap
        )
        self._residuals = ResidualSmoother(alpha=residual_alpha)
        self._scene_cut_threshold = scene_cut_threshold
        self._signature: bytes | None = None
        self._scene_cut = False
        self._frames = 0
        self._frames_with_faces = 0
        self._face_observations = 0
        self._scene_cuts = 0

    def begin_frame(self, image: Any) -> None:
        """Note the new frame (and whether it is a cut from the previous one) before tracking."""

        signature = frame_signature(image)
        self._scene_cut = is_scene_cut(
            self._signature, signature, threshold=self._scene_cut_threshold
        )
        self._signature = signature
        self._frames += 1
        if self._scene_cut:
            self._scene_cuts += 1

    def track(self, detections: Sequence[Sequence[Sequence[float]]]) -> list[TrackedFace]:
        """Smooth this frame's landmarks; call once per frame, with an empty list when no face was found."""

        tracked = self._landmarks.update(detections, scene_cut=self._scene_cut)
        self._residuals.retain(self._landmarks.live_track_ids())
        if tracked:
            self._frames_with_faces += 1
            self._face_observations += len(tracked)
        return tracked

    def blend(self, track_id: int, cropped: Any, restored: Any) -> Any:
        return self._residuals.blend(track_id, cropped, restored)

    def forget(self, track_id: int) -> None:
        """Discard a track's restoration history (its face could not be restored this frame)."""

        self._residuals.forget(track_id)

    def residual_track_ids(self) -> frozenset[int]:
        return self._residuals.track_ids()

    def report(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "landmark_alpha": self._landmarks.alpha,
            "residual_alpha": self._residuals.alpha,
            "frames": self._frames,
            "frames_with_faces": self._frames_with_faces,
            "face_observations": self._face_observations,
            "tracks_started": self._landmarks.tracks_started,
            "scene_cuts": self._scene_cuts,
        }
