"""Frames-out Comfy workflows: StableNew encodes the PNG frames Comfy saved (PR-VID-WAN-324).

A stock ``SaveVideo`` node writes whatever codec and bitrate Comfy picks (about 1.5 Mbps on the Wan graph) and gives
StableNew no frames. A workflow whose catalog entry declares ``backend_defaults["output_policy"] = {"mode":
"frames", "fps": N}`` ends in ``SaveImage`` instead. The backend then encodes the downloaded frames with the one
StableNew encoder (CRF, BT.709 tags, cancellation) and records every frame's SHA-256, so the exact last frame is a
verifiable artifact for segment chaining and replay can re-check the frames it derived the clip from.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src.controller.runtime_state import CancelToken
from src.pipeline.video import VideoEncodeSettings
from src.video.video_export import export_image_sequence_video

FRAMES_MODE = "frames"
_NUMBER = re.compile(r"(\d+)")


def frames_output_fps(spec: Any) -> int | None:
    """The frame rate a frames-out workflow declares, or ``None`` when its output is a video file."""

    policy = (getattr(spec, "backend_defaults", None) or {}).get("output_policy")
    if not isinstance(policy, Mapping) or policy.get("mode") != FRAMES_MODE:
        return None
    try:
        fps = int(policy.get("fps") or 0)
    except (TypeError, ValueError):
        fps = 0
    if fps < 1:
        raise ValueError(
            f"Workflow '{getattr(spec, 'workflow_id', '?')}' declares frames output without a frame rate"
        )
    return fps


def natural_frame_order(paths: Sequence[str | Path]) -> list[Path]:
    """Frames in playback order: by the numbers in the name, so ``f_9`` sorts before ``f_10``."""

    def key(path: Path) -> tuple[Any, ...]:
        return tuple(
            (0, int(part)) if part.isdigit() else (1, part)
            for part in _NUMBER.split(path.name)
            if part
        )

    return sorted((Path(path) for path in paths), key=key)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class FramesOutRecord:
    """What was encoded from the frames, for the manifest and replay."""

    video_path: str
    fps: int
    frame_count: int
    expected_frame_count: int | None
    first_frame_path: str
    last_frame_path: str
    last_frame_sha256: str
    frame_sha256: list[str]
    encoder: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def summary(self) -> dict[str, Any]:
        """The record without the per-frame list, for places with a size budget (container metadata)."""

        data = asdict(self)
        digests = data.pop("frame_sha256")
        data["frame_sha256_digest"] = hashlib.sha256(",".join(digests).encode("ascii")).hexdigest()
        return data


def encode_frames_out(
    *,
    frame_paths: Sequence[str | Path],
    output_dir: str | Path,
    stem: str,
    fps: int,
    expected_frame_count: int | None = None,
    settings: VideoEncodeSettings | None = None,
    cancel_token: CancelToken | None = None,
) -> FramesOutRecord:
    """Encode ``frame_paths`` (any order) to ``<output_dir>/<stem>.mp4`` and describe the result.

    A run that produced no frames raises; a count that differs from the frozen ``expected_frame_count`` is
    recorded (a physical run decides whether that is a fault) and never silently dropped.
    """

    ordered = natural_frame_order(frame_paths)
    if not ordered:
        raise RuntimeError("The workflow completed without saving any frames to encode")
    resolved = settings or VideoEncodeSettings()
    video_path = export_image_sequence_video(
        image_paths=ordered,
        output_path=Path(output_dir) / f"{stem}.mp4",
        fps=fps,
        settings=resolved,
        cancel_token=cancel_token,
    )
    digests = [_sha256(path) for path in ordered]
    return FramesOutRecord(
        video_path=str(video_path),
        fps=fps,
        frame_count=len(ordered),
        expected_frame_count=expected_frame_count,
        first_frame_path=str(ordered[0]),
        last_frame_path=str(ordered[-1]),
        last_frame_sha256=digests[-1],
        frame_sha256=digests,
        encoder={"crf": resolved.crf, "preset": resolved.preset, "pix_fmt": resolved.pix_fmt},
    )


__all__ = [
    "FRAMES_MODE",
    "FramesOutRecord",
    "encode_frames_out",
    "frames_output_fps",
    "natural_frame_order",
]
