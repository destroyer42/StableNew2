"""The phone's ``continue_clip`` (V1-6): what continuing a published video would queue, compiled on the PC.

The video's job is found only by repository evidence (``resolve_known_clip``) and read through the V1-6 facade
(``src.controller.continue_clip``). Nothing is written or queued while preparing a Storyboard continuation; its take is
built when the request is admitted, through the admission the caller gives (``admit_phone_records``). A clip whose
engine cannot make Storyboard takes is offered as an ordinary Make Video of its last frame instead, and the summary
says so. Refusals are the schema's closed detail codes (``SiteOutputError``). Worker-safe; never Tk.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from src.app.site_media_files import SiteOutputError, inside
from src.controller.continue_clip import (
    ClipContinuation,
    ContinueRefused,
    continue_clip,
    inspect_continuation,
)
from src.controller.ports.default_runtime_ports import DefaultWorkflowRegistryPort
from src.controller.storyboard_submission_service import StoryboardSubmissionService
from src.pipeline.policy_warnings import PolicyWarning
from src.video.licence_attestation import attestation_record, declared_attestation
from src.video.motion_intent import compose_prompt
from src.video.rife_runtime import find_rife_executable
from src.video.storyboard_import import resolve_known_clip
from src.video.storyboard_root import StoryboardRootError, clip_last_frame
from src.video.video_workflow_njr_builder import VideoWorkflowNjrBuilder
from src.video.workflow_warnings import accepted_workflow_warnings

#: Where a fallback's decoded last frame is kept, under the Output root.
FRAMES_FOLDER: Final = "continue_frames"
_PROMPT_SHOWN: Final = 120

#: ``njrs -> admitted job ids``, crossing ``JobService.submit_njrs`` once.
AdmitRecords = Callable[[list[Any]], Sequence[str]]
#: ``(output root, image, its sha256, prompt, seed) -> (spec, preview input)``: ``site_phone_video.gateway_make_video``.
MakeVideo = Callable[[Path, Path, str, str, int], tuple[Any, Any]]


@dataclass(frozen=True)
class PhoneContinuation:
    """One compiled ``continue_clip``: what the summary shows and how it is admitted.

    Exactly one of ``build`` (a Storyboard take, built on admission) and ``video`` (the fallback's Make Video) is set.
    """

    lines: tuple[str, ...]
    warnings: tuple[PolicyWarning, ...]
    #: Everything that decides what would be queued, without ids or the seed.
    identity: tuple[str, ...]
    build: Callable[[AdmitRecords], list[str]] | None = None
    video: Any = None


def phone_storyboard_service(
    repository: Any, root: Path, jobs: Callable[[], Any]
) -> StoryboardSubmissionService:
    """The desktop's Storyboard service over the same repository and store, with its own builder: the gateway's
    worker never reaches into the tab's controller."""

    registry = DefaultWorkflowRegistryPort()
    return StoryboardSubmissionService(
        njr_builder=VideoWorkflowNjrBuilder(
            workflow_registry=registry, output_dir_provider=lambda: str(root)
        ),
        workflow_registry=registry,
        job_service=jobs,
        repository=lambda: repository,
        output_root=lambda: str(root),
        smooth_takes=lambda: find_rife_executable() is not None,
    )


def _job_of(repository: Any, path: Path) -> str:
    known = resolve_known_clip(path, repository=repository)
    if known.job_id is None:
        raise SiteOutputError("provenance_unverified")
    return str(known.job_id)


def _shown(prompt: str) -> str:
    text = " ".join(prompt.split())
    return text if len(text) <= _PROMPT_SHOWN else text[: _PROMPT_SHOWN - 1] + "…"


def _length(clip: ClipContinuation) -> str:
    if clip.policy is None:
        return ""
    return f"{clip.policy.seconds(clip.frame_count):.1f} s"


def compile_continuation(
    service: StoryboardSubmissionService,
    root: Path,
    path: Path,
    digest: str,
    text: str,
    seed: int,
    *,
    video: MakeVideo,
) -> PhoneContinuation:
    """Continue the clip at ``path`` (already re-hashed as ``digest``) with ``text``, or its own prompt when blank."""

    repository = service.job_repository()
    job_id = _job_of(repository, path)
    try:
        clip = inspect_continuation(service, job_id)
    except ContinueRefused as exc:
        raise SiteOutputError("operation_unsupported") from exc
    prompt = text.strip() or compose_prompt(clip.prompt, clip.motion_phrase).strip()
    if not prompt:
        raise SiteOutputError("prompt_required")
    if not clip.takes_storyboard:
        return _from_last_frame(service, root, clip, prompt, seed, video=video)
    spec = service.registry.get(clip.workflow_id, clip.workflow_version or None)
    # VID-CAND-LTX25: the phone's confirm of a summary that states the sentence is the operator's attestation.
    attestation = declared_attestation(clip.workflow_id)

    def build(admit: AdmitRecords) -> list[str]:
        result = continue_clip(
            service,
            inspect_continuation(service, job_id),
            prompt=prompt,
            seed=str(seed),
            experimental_opt_in=clip.experimental,
            admit=admit,
            licence_attestation=None if attestation is None else attestation_record(attestation),
        )
        return list(result.job_ids)

    where = "its Storyboard" if clip.storyboard_id else "a new Storyboard"
    return PhoneContinuation(
        lines=(
            f"Continues from the clip's last frame, in {where}.",
            " · ".join(part for part in (clip.workflow_label, _length(clip), "new seed") if part),
            f"Prompt: {_shown(prompt)}",
            *(() if attestation is None else (attestation.text,)),
        ),
        warnings=accepted_workflow_warnings(spec, opted_in=clip.experimental),
        identity=(
            "continue_clip",
            job_id,
            clip.workflow_id,
            clip.workflow_version,
            str(clip.frame_count),
            prompt,
            digest,
            *(() if attestation is None else (attestation.version,)),
        ),
        build=build,
    )


def _from_last_frame(
    service: StoryboardSubmissionService,
    root: Path,
    clip: ClipContinuation,
    prompt: str,
    seed: int,
    *,
    video: MakeVideo,
) -> PhoneContinuation:
    folder = root / FRAMES_FOLDER / clip.job_id
    try:
        frame = Path(clip_last_frame(service.job_repository(), clip.job_id, folder))
        inside(root, frame)
        frame_digest = hashlib.sha256(frame.read_bytes()).hexdigest()
    except (StoryboardRootError, OSError) as exc:
        raise SiteOutputError("operation_unsupported") from exc
    spec, preview = video(root, frame, frame_digest, prompt, seed)
    return PhoneContinuation(
        lines=(
            "This clip's engine cannot continue in a Storyboard.",
            "Makes a new clip from its last frame instead.",
            f"{spec.display_name} · new seed",
            f"Prompt: {_shown(prompt)}",
        ),
        warnings=(),
        identity=("continue_clip", clip.job_id, *spec.registry_key, prompt, frame_digest),
        video=preview,
    )


__all__ = [
    "AdmitRecords",
    "PhoneContinuation",
    "compile_continuation",
    "phone_storyboard_service",
]
