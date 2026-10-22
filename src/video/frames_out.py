"""Frames-out Comfy workflows: StableNew encodes the PNG frames Comfy saved (PR-VID-WAN-324).

A stock ``SaveVideo`` node writes whatever codec and bitrate Comfy picks (about 1.5 Mbps on the Wan graph) and gives
StableNew no frames. A workflow whose catalog entry declares ``backend_defaults["output_policy"] = {"mode":
"frames", "fps": N}`` ends in ``SaveImage`` instead. The backend then encodes the downloaded frames with the one
StableNew encoder (CRF, BT.709 tags, cancellation) and records every frame's SHA-256, so the exact last frame is a
verifiable artifact for segment chaining and replay can re-check the frames it derived the clip from.

Every listed frame must exist and decode before anything is encoded, and the encoder is told to fail rather than skip
one, so a hash is never recorded for a frame the clip does not hold. The localized frames are reconciled against the
count frozen at admission (``reconciliation``: match / missing / extra, counter gaps and repeats). A difference is
recorded and logged but does not fail the job: whether it should is an owner decision taken before 1.3.0 is
registered, and the PR-VID-WAN-324 acceptance run requires an exact match.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src.controller.runtime_state import CancelToken
from src.pipeline.video import VideoEncodeSettings
from src.video.video_export import export_image_sequence_video

logger = logging.getLogger(__name__)

FRAMES_MODE = "frames"
_NUMBER = re.compile(r"(\d+)")

COUNT_MATCH = "match"
COUNT_MISSING = "missing"
COUNT_EXTRA = "extra"
COUNT_MISSING_AND_EXTRA = "missing_and_extra"
COUNT_UNVERIFIED = "unverified"
_LISTED_GAPS = 64  # the reconciliation also rides in container metadata, so its lists stay bounded


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


def _frame_number(path: Path) -> int | None:
    """The counter Comfy's ``SaveImage`` puts last in the name (``prefix_00007_.png`` -> 7)."""

    numbers = _NUMBER.findall(path.stem)
    return int(numbers[-1]) if numbers else None


def reconcile_frame_count(
    ordered: Sequence[str | Path], expected_frame_count: int | None
) -> dict[str, Any]:
    """Compare the frames on disk with the count frozen at admission, without judging the job.

    ``missing``: fewer frames than frozen, or a gap in the counters. ``extra``: more frames than frozen, or a
    repeated counter. Both can hold at once. With no frozen count and no gap or repeat it is ``unverified``.
    """

    paths = [Path(path) for path in ordered]
    numbers = [_frame_number(path) for path in paths]
    numbered = sorted(number for number in numbers if number is not None)
    repeated = sorted({number for number in numbered if numbered.count(number) > 1})
    gaps: list[int] = []
    gap_count = 0
    if numbered and len(numbered) == len(paths):
        present = sorted(set(numbered))
        for left, right in zip(present, present[1:], strict=False):
            missing_count = right - left - 1
            gap_count += missing_count
            sample_count = min(missing_count, _LISTED_GAPS - len(gaps))
            gaps.extend(range(left + 1, left + 1 + sample_count))
    actual = len(paths)
    missing = bool(gaps) or (expected_frame_count is not None and actual < expected_frame_count)
    extra = bool(repeated) or (expected_frame_count is not None and actual > expected_frame_count)
    if missing and extra:
        status = COUNT_MISSING_AND_EXTRA
    elif missing:
        status = COUNT_MISSING
    elif extra:
        status = COUNT_EXTRA
    elif expected_frame_count is None:
        status = COUNT_UNVERIFIED
    else:
        status = COUNT_MATCH
    return {
        "status": status,
        "expected_frame_count": expected_frame_count,
        "actual_frame_count": actual,
        "difference": None if expected_frame_count is None else actual - expected_frame_count,
        "sequence_gap_count": gap_count,
        "sequence_gaps": gaps,
        "repeated_numbers": repeated[:_LISTED_GAPS],
        "unnumbered_frames": sum(1 for number in numbers if number is None),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verified_digests(ordered: Sequence[Path]) -> list[str]:
    """SHA-256 of every frame, after proving each one exists and decodes; one error names every bad frame."""

    from PIL import Image

    digests: list[str] = []
    missing: list[str] = []
    unreadable: list[str] = []
    for path in ordered:
        if not path.is_file():
            missing.append(path.name)
            continue
        try:
            with Image.open(path) as image:
                image.load()
            digests.append(_sha256(path))
        except Exception as exc:  # noqa: BLE001 - any decode failure makes the frame unusable
            unreadable.append(f"{path.name} ({type(exc).__name__})")
    if missing or unreadable:
        parts = []
        if missing:
            parts.append("missing: " + ", ".join(missing))
        if unreadable:
            parts.append("unreadable: " + ", ".join(unreadable))
        raise RuntimeError(
            f"{len(missing) + len(unreadable)} of {len(ordered)} saved frames cannot be encoded ("
            + "; ".join(parts)
            + ")"
        )
    return digests


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
    frame_paths: list[str]
    frame_sha256: list[str]
    reconciliation: dict[str, Any]
    encoder: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def summary(self) -> dict[str, Any]:
        """The record without the per-frame lists, for places with a size budget (container metadata)."""

        data = asdict(self)
        data.pop("frame_paths")
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

    A run that produced no frames, or a listed frame that is missing or does not decode, raises before encoding;
    the encoder then fails rather than skip a frame, so every recorded hash is a frame of the clip. A count that
    differs from the frozen ``expected_frame_count`` is reconciled, logged and recorded, never silently dropped.
    """

    ordered = natural_frame_order(frame_paths)
    if not ordered:
        raise RuntimeError("The workflow completed without saving any frames to encode")
    digests = _verified_digests(ordered)
    reconciliation = reconcile_frame_count(ordered, expected_frame_count)
    if reconciliation["status"] not in (COUNT_MATCH, COUNT_UNVERIFIED):
        logger.warning("Frames-out frame count does not reconcile: %s", reconciliation)
    resolved = settings or VideoEncodeSettings()
    video_path = export_image_sequence_video(
        image_paths=ordered,
        output_path=Path(output_dir) / f"{stem}.mp4",
        fps=fps,
        settings=resolved,
        cancel_token=cancel_token,
        require_all_frames=True,
    )
    return FramesOutRecord(
        video_path=str(video_path),
        fps=fps,
        frame_count=len(ordered),
        expected_frame_count=expected_frame_count,
        first_frame_path=str(ordered[0]),
        last_frame_path=str(ordered[-1]),
        last_frame_sha256=digests[-1],
        frame_paths=[str(path) for path in ordered],
        frame_sha256=digests,
        reconciliation=reconciliation,
        encoder={"crf": resolved.crf, "preset": resolved.preset, "pix_fmt": resolved.pix_fmt},
    )


__all__ = [
    "COUNT_EXTRA",
    "COUNT_MATCH",
    "COUNT_MISSING",
    "COUNT_MISSING_AND_EXTRA",
    "COUNT_UNVERIFIED",
    "FRAMES_MODE",
    "FramesOutRecord",
    "encode_frames_out",
    "frames_output_fps",
    "natural_frame_order",
    "reconcile_frame_count",
]
