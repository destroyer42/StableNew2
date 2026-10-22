"""Operator shots in, ``sequence_intent`` out (PR-VID-SEQ-331A).

The Video Workflow tab lets an operator describe a multi-segment clip as an ordered list of shots. This module only
turns that list into the intent mapping ``freeze_sequence_plan`` already accepts; admission stays the one authority on
what is legal (frame counts, seeds, anchor shape, workflow limits), so nothing here re-validates beyond what a form can
say before a file is read.

* Shot 0 starts from the form's source image.
* Shot N with a keyframe starts from that authored image (the ``provided`` anchor policy: a hard cut to a known image,
  no overlap frame is dropped).
* Shot N without a keyframe starts from the exact last frame of the shot before it (``carry_last_frame``).

Pure: no file is opened, nothing is queued.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from src.video.sequence_plan import (
    ANCHOR_IMAGE_SUFFIXES,
    ANCHOR_PROVIDED,
    MAX_SEQUENCE_SEGMENTS,
)

#: A sequence of one shot is just a clip; the single-clip Queue button makes it.
MIN_SHOTS: Final = 2
MAX_SHOTS: Final = MAX_SEQUENCE_SEGMENTS


@dataclass(frozen=True, slots=True)
class ShotDraft:
    """One shot as the operator typed it. Blank text means "use the form's value" (or a random seed)."""

    prompt: str = ""
    frame_count: int | None = None
    keyframe_path: str = ""
    seed: str = ""

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> ShotDraft:
        count = data.get("frame_count")
        try:
            frame_count = None if count in (None, "") else int(str(count).strip())
        except ValueError:
            frame_count = None
        return cls(
            prompt=str(data.get("prompt") or "").strip(),
            frame_count=frame_count,
            keyframe_path=str(data.get("keyframe_path") or "").strip(),
            seed=str(data.get("seed") or "").strip(),
        )


def shot_problems(shots: Sequence[ShotDraft]) -> list[str]:
    """What is wrong with the shot list before any file is read; empty means admission may be asked."""

    problems: list[str] = []
    if len(shots) < MIN_SHOTS:
        problems.append(
            f"A sequence needs at least {MIN_SHOTS} shots; use the Queue button for a single clip."
        )
    if len(shots) > MAX_SHOTS:
        problems.append(f"A sequence can have at most {MAX_SHOTS} shots (it has {len(shots)}).")
    for position, shot in enumerate(shots, start=1):
        if shot.frame_count is None:
            problems.append(f"Shot {position}: choose a length.")
        if shot.keyframe_path and position > 1:
            suffix = Path(shot.keyframe_path).suffix.lower()
            if suffix not in ANCHOR_IMAGE_SUFFIXES:
                problems.append(
                    f"Shot {position}: the keyframe must be an image file, not {suffix or 'a folder'}."
                )
    return problems


def build_sequence_intent(shots: Sequence[ShotDraft], *, clip_name: str = "") -> dict[str, Any]:
    """The ``sequence_intent`` for ``shots``; raises ``ValueError`` when ``shot_problems`` is not empty."""

    problems = shot_problems(shots)
    if problems:
        raise ValueError(" ".join(problems))
    segments: list[dict[str, Any]] = []
    for position, shot in enumerate(shots):
        segment: dict[str, Any] = {"frame_count": shot.frame_count}
        if shot.prompt:
            segment["prompt"] = shot.prompt
        if shot.seed:
            segment["seed"] = shot.seed
        # Shot 0 always starts from the source image; a keyframe typed there would silently do nothing, so it is ignored.
        if position > 0 and shot.keyframe_path:
            segment["anchor"] = {"policy": ANCHOR_PROVIDED, "path": shot.keyframe_path}
        segments.append(segment)
    intent: dict[str, Any] = {"segments": segments}
    if clip_name.strip():
        intent["assembly"] = {"clip_name": clip_name.strip()}
    return intent


__all__ = ["MAX_SHOTS", "MIN_SHOTS", "ShotDraft", "build_sequence_intent", "shot_problems"]
