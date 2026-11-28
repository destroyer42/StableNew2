"""Continue a clip (V1-6, ``docs/work_packages/V1_motion_controls.md`` section 15): one facade for desktop and phone.

:func:`inspect_continuation` reads a finished Comfy clip job and writes nothing: its engine, length, prompt and recorded
frames, the Storyboard it already belongs to, and why it cannot make a Storyboard take when it cannot.
:func:`continue_clip` queues one sequential take through :class:`StoryboardSubmissionService`, from the clip's last
generated frame (or a chosen earlier one), extending the clip's Storyboard or creating one (D6). There is no second
builder, queue or lineage store here.

All functions read and write files; call them from a worker thread, never from Tk.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from src.controller.storyboard_submission_service import (
    ContinueRequest,
    ContinueResult,
    ContinueRow,
    StoryboardSubmissionService,
)
from src.pipeline.njr_core_v26 import thaw_json
from src.video.motion_intent import (
    MOTION_INTENT_FIELD,
    LengthPolicy,
    compose_prompt,
    length_policy,
    split_composed_prompt,
)
from src.video.sequence_plan import ROOT_PARENT, STAGE_VIDEO_WORKFLOW
from src.video.storyboard_root import StoryboardRootError, check_clip_job, recorded_clip_frames
from src.video.storyboard_tree import StoryboardTree, StoryboardTreeError
from src.video.workflow_frame_count import frame_count_policy

_TITLE_WORDS: Final = 48


class ContinueRefused(ValueError):
    """The clip cannot be continued; the message says why."""


@dataclass(frozen=True)
class ClipContinuation:
    """What a finished clip offers to continue from (read only)."""

    job_id: str
    #: Empty: the continuation is a Storyboard take.  Otherwise why it cannot be one.
    reason: str
    workflow_id: str
    workflow_version: str
    workflow_label: str
    experimental: bool
    policy: LengthPolicy | None
    #: The length of the clip's own generation, the default length of its continuation.
    frame_count: int
    #: The scene prompt and the motion phrase the clip (or its take) was queued with.
    prompt: str
    motion_phrase: str
    #: The Storyboard the clip already belongs to ("" when none) and the node to continue.
    storyboard_id: str
    parent_id: str
    #: The clip's generated frames in order when they are on disk, else empty (then only the last frame is offered).
    frame_paths: tuple[str, ...]

    @property
    def takes_storyboard(self) -> bool:
        return not self.reason


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _read_clip(repository: Any, job_id: str) -> tuple[Any, dict[str, Any]]:
    job = repository.get_job_model(job_id)
    if job is None:
        raise ContinueRefused(f"Job {job_id} was not found.")
    status = str(getattr(job.status, "value", job.status) or "")
    if status != "completed":
        raise ContinueRefused(f"Job {job_id} has not completed (it is {status}).")
    njr = getattr(job, "_normalized_record", None)
    stages = {stage.stage_type: stage for stage in getattr(njr, "stage_chain", ())}
    if STAGE_VIDEO_WORKFLOW not in stages:
        raise ContinueRefused("Only a clip made by a Comfy video workflow can be continued.")
    return njr, dict(thaw_json(stages[STAGE_VIDEO_WORKFLOW].extra) or {})


def find_clip_in_storyboards(
    service: StoryboardSubmissionService, job_id: str
) -> tuple[StoryboardTree, str] | None:
    """The newest Storyboard that holds ``job_id`` as a take's current attempt, else as its root clip."""

    as_root: tuple[StoryboardTree, str] | None = None
    for storyboard_id, _title, _updated in service.store.list_trees():
        try:
            tree = service.store.load(storyboard_id)
        except StoryboardTreeError:
            continue
        # Only the current attempt: an older attempt's clip is not what the take's cut holds.
        takes = [take for take in tree.takes if take.attempts and take.attempts[-1] == job_id]
        if takes:  # a sequential chain ends at its last position
            return tree, max(takes, key=lambda take: take.chain_position).take_id
        if as_root is None and tree.root.job_id == job_id:
            as_root = (tree, ROOT_PARENT)
    return as_root


def inspect_continuation(service: StoryboardSubmissionService, job_id: str) -> ClipContinuation:
    """Read what continuing ``job_id`` would do; nothing is created, written or queued."""

    job_id = str(job_id or "").strip()
    if not job_id:
        raise ContinueRefused("Choose a finished clip to continue.")
    repository = service.job_repository()
    njr, stage = _read_clip(repository, job_id)
    found = find_clip_in_storyboards(service, job_id)
    settings: Mapping[str, Any] = stage if found is None else found[0].root.to_dict()["settings"]
    workflow_id = str(settings.get("workflow_id") or "")
    version = str(settings.get("workflow_version") or "")
    try:
        spec = service.registry.get(workflow_id, version or None)
    except KeyError:
        spec = None
    reason = ""
    if found is None:
        try:
            check_clip_job(repository, job_id, service.registry)
        except StoryboardRootError as exc:
            reason = str(exc)
    elif spec is None:
        reason = f"{workflow_id} {version} is not available on this PC."

    recorded = _mapping(
        _mapping(thaw_json(getattr(njr, "extra_metadata", {}) or {})).get("video_workflow")
    )
    phrase = str(_mapping(recorded.get(MOTION_INTENT_FIELD)).get("motion_phrase") or "")
    segments = _mapping(stage.get("sequence_metadata")).get("segments") or ()
    prompt = str((segments[-1] if segments else stage).get("prompt") or "")
    frames: tuple[str, ...] = ()
    storyboard_id, parent_id = "", ROOT_PARENT
    if found is not None:
        tree, parent_id = found
        storyboard_id = tree.storyboard_id
        if parent_id != ROOT_PARENT:
            prompt = next(take.prompt for take in tree.takes if take.take_id == parent_id)
        cut = service.parent_cut(tree, parent_id)
        frames = () if cut is None else tuple(frame.path for frame in cut.frames)
    elif not segments:
        frames = recorded_clip_frames(repository, job_id)
    prompt, phrase = split_composed_prompt(prompt, phrase)
    declared = None if spec is None else frame_count_policy(spec)
    return ClipContinuation(
        job_id=job_id,
        reason=reason,
        workflow_id=workflow_id,
        workflow_version=version,
        workflow_label=str(getattr(spec, "display_name", "") or workflow_id),
        experimental=bool(getattr(spec, "is_experimental", False)),
        policy=None if declared is None else length_policy(declared),
        frame_count=int(settings.get("frame_count") or stage.get("frame_count") or 0),
        prompt=prompt,
        motion_phrase=phrase,
        storyboard_id=storyboard_id,
        parent_id=parent_id,
        frame_paths=frames,
    )


def continue_clip(
    service: StoryboardSubmissionService,
    clip: ClipContinuation,
    *,
    prompt: str,
    motion_phrase: str = "",
    frame_count: int | None = None,
    seed: str = "",
    negative_prompt: str = "",
    frame_index: int | None = None,
    experimental_opt_in: bool = False,
    motion_intent: Mapping[str, Any] | None = None,
    admit: Callable[[list[Any]], Sequence[str]] | None = None,
    licence_attestation: Mapping[str, Any] | None = None,
) -> ContinueResult:
    """Queue one take that continues ``clip`` from its last frame (or ``frame_index``, 0-based).

    A blank ``seed`` draws a new one and a blank ``negative_prompt`` inherits the Storyboard's. ``admit`` is the
    phone's admission (see :meth:`StoryboardSubmissionService.submit`).
    """

    if not clip.takes_storyboard:
        raise ContinueRefused(clip.reason)
    text = compose_prompt(prompt, motion_phrase)
    if not text.strip():
        raise ContinueRefused("Say what happens next; a continuation needs a prompt.")
    parent_id = clip.parent_id
    if clip.storyboard_id:
        tree = service.store.load(clip.storyboard_id)
    else:
        # Read again: a second Queue of the same clip must not make a second Storyboard.
        found = find_clip_in_storyboards(service, clip.job_id)
        if found is None:
            words = " ".join(str(prompt or text).split())[:_TITLE_WORDS]
            tree = service.create_from_clip(clip.job_id, f"Continued: {words}")
        else:
            tree, parent_id = found
    cut = service.parent_cut(tree, parent_id)
    if cut is None:
        raise ContinueRefused("This clip has no frames to continue from.")
    index = len(cut.frames) - 1 if frame_index is None else frame_index
    return service.submit(
        ContinueRequest(
            storyboard_id=tree.storyboard_id,
            expected_revision=tree.revision,
            parent_id=parent_id,
            handoff_index=index,
            mode="sequential",
            rows=(ContinueRow(prompt=text, negative_prompt=negative_prompt, seed=seed),),
            experimental_opt_in=experimental_opt_in,
            frame_count=frame_count,
            motion_intent=motion_intent,
            licence_attestation=licence_attestation,
        ),
        admit=admit,
    )


__all__ = [
    "ClipContinuation",
    "ContinueRefused",
    "continue_clip",
    "find_clip_in_storyboards",
    "inspect_continuation",
]
