"""The records of a Storyboard Continue: what is asked, previewed and queued (PR-VID-STORY-380).

Plain data shared by ``StoryboardSubmissionService`` and its callers; nothing here reads or writes anything.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from src.video.storyboard_tree import StoryboardTree

Mode = Literal["parallel", "sequential"]


@dataclass(frozen=True, slots=True)
class ContinueRow:
    prompt: str
    negative_prompt: str
    #: Blank or ``random`` is drawn at admission; a whole number is used as given.
    seed: str


@dataclass(frozen=True, slots=True)
class ContinueRequest:
    storyboard_id: str
    expected_revision: int
    #: A take id, or ``ROOT_PARENT``.
    parent_id: str
    #: 0-based index of the handoff frame in the parent's cut; ``None`` only for an image root.
    handoff_index: int | None
    mode: Mode
    rows: tuple[ContinueRow, ...]
    experimental_opt_in: bool = False
    #: V1-6: each take's length; ``None`` inherits the root's.
    frame_count: int | None = None
    #: V1-6: the provenance-only motion intent record of the takes (D5); admission never reads it.
    motion_intent: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ContinuePreview:
    jobs: int
    segments: int
    lead_in_frames: int
    #: The length of each take's cut (parallel) or of the chain's whole cut (sequential), lead-in included.
    total_cut_frames: int
    fps: int
    workflow_id: str
    workflow_version: str
    #: Each row's seed intent (``random`` where the row left it blank); nothing is drawn by a preview.
    seeds: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ContinueResult:
    job_ids: tuple[str, ...]
    take_ids: tuple[str, ...]
    tree: StoryboardTree


__all__ = ["ContinuePreview", "ContinueRequest", "ContinueResult", "ContinueRow", "Mode"]
