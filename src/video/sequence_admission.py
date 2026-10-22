"""Admission of a multi-segment video job: intent in, frozen ``SequencePlan`` out (PR-VID-SEQ-330-CORE).

Everything that can be wrong with a sequence is refused here, before a single NJR exists, with a message written for
the operator: a frame count the backend cannot generate, an anchor that is missing, is not an image or has the wrong
shape, an override the plan does not know, a workflow the sequence layer cannot drive, too many segments or frames.
What survives is concrete: each segment's seed, frame count, workflow identity, prompts and anchor hash.

Supported today (anything else is refused, never approximated):

* ``video_workflow``: approved, prompt-directed image-to-video Comfy workflows that take only a source image, a
  prompt, a seed and a frame count, declare no operator controls, and share one frame rate and one source-preparation
  policy across the sequence (today the Wan2.2 TI2V-5B versions).
* ``svd_native``: native SVD XT, same model for every segment, per-segment seed and frame count.

The module reads the files the plan names (hashing authored anchors) and nothing else; it starts no runtime.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Final

from PIL import Image

from src.video.sequence_plan import (
    ANCHOR_CARRY,
    ANCHOR_IMAGE_SUFFIXES,
    ANCHOR_PROVIDED,
    ANCHOR_SOURCE,
    BACKEND_FOR_STAGE,
    MAX_SEED_SVD,
    MAX_SEED_WORKFLOW,
    STAGE_SVD_NATIVE,
    STAGE_VIDEO_WORKFLOW,
    SegmentSpec,
    SequenceAssembly,
    SequenceColorMatch,
    SequencePlan,
    SequencePlanError,
    default_overlap,
    sanitize_clip_name,
)

INTENT_KEYS: Final = frozenset({"sequence_id", "assembly", "color_match", "segments"})
SEGMENT_INTENT_KEYS: Final = frozenset(
    {
        "seed",
        "frame_count",
        "workflow_id",
        "workflow_version",
        "prompt",
        "negative_prompt",
        "anchor",
        "overlap_frames",
    }
)
ANCHOR_INTENT_KEYS: Final = frozenset({"policy", "path"})
#: Declared inputs a sequence-capable workflow may require; anything beyond them (a driving video, an end anchor)
#: is something the sequence layer has no way to supply.
SUPPORTED_REQUIRED_INPUTS: Final = frozenset(
    {"source_image", "prompt", "seed", "target_width", "target_height", "frame_count"}
)

FileHasher = Callable[[str | Path], str]


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _strict(kind: str, data: Mapping[str, Any], allowed: frozenset[str]) -> None:
    extra = sorted(set(data) - allowed)
    if extra:
        raise SequencePlanError(
            f"unknown {kind} field(s) {', '.join(repr(key) for key in extra)}; "
            f"only {', '.join(sorted(allowed))} may be set"
        )


def _concrete_seed(value: Any, *, label: str, max_seed: int) -> int:
    text = str(value if value is not None else "").strip()
    if not text or text.lower() == "random":
        return secrets.randbelow(max_seed + 1)  # frozen here; never drawn at run time
    try:
        seed = int(text)
    except (TypeError, ValueError) as exc:
        raise SequencePlanError(f"{label}: seed must be a whole number or 'random'") from exc
    if not 0 <= seed <= max_seed:
        raise SequencePlanError(f"{label}: seed must be between 0 and {max_seed}")
    return seed


def _whole(value: Any, *, label: str, field: str) -> int:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise SequencePlanError(f"{label}: {field} must be a whole number") from exc
    return number


def workflow_segment_errors(
    spec: Any,
    base_spec: Any,
    frame_count: int,
    plan_fps: int,
    *,
    experimental_opt_in: bool = False,
) -> list[str]:
    """Why ``spec`` cannot be a segment of a sequence started with ``base_spec`` (empty when it can)."""

    from src.video.workflow_frame_count import frame_count_policy, parse_frame_count

    name = f"{spec.workflow_id} {spec.workflow_version}"
    errors: list[str] = []
    if getattr(spec, "backend_id", None) != "comfy":
        errors.append(f"{name} is not a Comfy workflow")
    experimental = bool(getattr(spec, "is_experimental", False))
    if experimental and not experimental_opt_in:
        errors.append(
            f"{name} is experimental and this job has not opted in; the opt-in is recorded per job"
        )
    elif not experimental and getattr(spec, "governance_state", None) != "approved":
        errors.append(
            f"{name} is not approved for production; a sequence runs only approved workflows"
        )
    required = set(getattr(spec, "required_input_names", ()))
    unsupported = sorted(required - SUPPORTED_REQUIRED_INPUTS)
    if unsupported:
        errors.append(
            f"{name} requires {', '.join(unsupported)}, which a sequence cannot supply "
            "(sequences drive prompt-directed image-to-video workflows only)"
        )
    defaults = getattr(spec, "backend_defaults", None) or {}
    if defaults.get("operator_controls"):
        errors.append(
            f"{name} declares operator controls, which a sequence does not carry per segment"
        )
    policy = frame_count_policy(spec)
    if policy is None:
        errors.append(
            f"{name} has no declared frame-count policy, so a segment length cannot be validated"
        )
    else:
        try:
            parse_frame_count(spec, frame_count)
        except ValueError as exc:
            errors.append(str(exc))
        if int(policy["fps"]) != plan_fps:
            errors.append(
                f"{name} plays at {policy['fps']} fps but this sequence plays at {plan_fps}; "
                "every segment must share one frame rate"
            )
    if defaults.get("source_preparation") != (
        getattr(base_spec, "backend_defaults", None) or {}
    ).get("source_preparation"):
        errors.append(f"{name} prepares its source differently from the sequence's first workflow")
    return errors


def _resolve_workflow(registry: Any, workflow_id: str, version: str, *, label: str) -> Any:
    """The offerable spec (approved or experimental, never disabled); governance is judged by the caller."""

    try:
        return registry.get(workflow_id, version)
    except KeyError as exc:  # WorkflowLookupError is a KeyError with a readable message
        raise SequencePlanError(f"{label}: {exc}") from exc


def read_still_size(path: str | Path, *, label: str) -> tuple[int, int]:
    """The ``(width, height)`` of a decodable still image; a missing, corrupt or non-image file is refused."""

    target = Path(path)
    if not target.is_file():
        raise SequencePlanError(f"{label}: the image does not exist or was moved: {target}")
    try:
        with Image.open(target) as image:
            image.load()
            width, height = image.size
        return int(width), int(height)
    except Exception as exc:  # noqa: BLE001 - an unreadable file is a refusal with a reason, not a crash
        raise SequencePlanError(f"{label}: {target.name} is not a readable image: {exc}") from exc


def _check_provided_anchor(
    path_text: str,
    *,
    label: str,
    hash_file: FileHasher,
    target: tuple[int, int] | None,
) -> tuple[str, str]:
    path = Path(path_text).expanduser()
    if path.suffix.lower() not in ANCHOR_IMAGE_SUFFIXES:
        raise SequencePlanError(
            f"{label}: anchor {path.name} is not an image ({', '.join(sorted(ANCHOR_IMAGE_SUFFIXES))}); "
            "a video file is never used as an anchor"
        )
    if not path.is_file():
        raise SequencePlanError(f"{label}: the anchor image does not exist or was moved: {path}")
    path = path.resolve()
    width, height = read_still_size(path, label=f"{label} anchor")
    if target is not None and (width, height) != target:
        raise SequencePlanError(
            f"{label}: the anchor is {width}x{height} but this sequence is exactly {target[0]}x{target[1]}; "
            "resize or crop it first, a start frame is never stretched or cropped for you"
        )
    return str(path), hash_file(path)


def _segment_source(
    source: Mapping[str, Any] | None, *, hash_file: FileHasher
) -> dict[str, str] | None:
    """Segment 0's frozen input: the exact image it starts from, hashed (re-checked before it dispatches)."""

    if source is None:
        return None
    path = Path(str(source.get("path") or "")).expanduser()
    read_still_size(path, label="segment 0 source")
    return {"path": str(path), "sha256": str(source.get("sha256") or hash_file(path))}


def freeze_sequence_plan(
    intent: Mapping[str, Any],
    *,
    stage: str,
    fps: int,
    base_prompt: str = "",
    base_negative_prompt: str = "",
    base_workflow: tuple[str, str] | None = None,
    registry: Any = None,
    target_size: tuple[int, int] | None = None,
    segment_zero_seed: int | None = None,
    svd_max_frames: int | None = None,
    model_id: str | None = None,
    experimental_opt_in: bool = False,
    source: Mapping[str, Any] | None = None,
    continuity: Mapping[str, Any] | None = None,
    plan_origin: Mapping[str, Any] | None = None,
    hash_file: FileHasher = sha256_file,
) -> SequencePlan:
    """Validate ``intent`` and return the plan the NJR freezes. Raises ``SequencePlanError`` for anything wrong.

    ``base_*`` are the job's own frozen values: a segment that does not set a prompt or workflow uses them.
    ``segment_zero_seed`` is the seed already frozen for the job's first segment, so the plan and the single-clip
    inputs agree.
    """

    if not isinstance(intent, Mapping):
        raise SequencePlanError("the sequence intent must be a mapping")
    _strict("sequence", intent, INTENT_KEYS)
    if stage not in (STAGE_VIDEO_WORKFLOW, STAGE_SVD_NATIVE):
        raise SequencePlanError(f"sequences run on video_workflow or svd_native, not {stage!r}")
    segment_intents = intent.get("segments")
    if not isinstance(segment_intents, (list, tuple)) or not segment_intents:
        raise SequencePlanError("a sequence needs a list of segments")
    max_seed = MAX_SEED_SVD if stage == STAGE_SVD_NATIVE else MAX_SEED_WORKFLOW
    base_spec = None
    if stage == STAGE_VIDEO_WORKFLOW:
        if registry is None or base_workflow is None:
            raise SequencePlanError(
                "a workflow sequence needs the workflow registry and its first workflow"
            )
        base_spec = _resolve_workflow(registry, *base_workflow, label="the sequence's workflow")

    segments: list[SegmentSpec] = []
    errors: list[str] = []
    for position, raw in enumerate(segment_intents):
        label = f"segment {position}"
        if not isinstance(raw, Mapping):
            raise SequencePlanError(f"{label} must be a mapping")
        _strict(label, raw, SEGMENT_INTENT_KEYS)
        anchor = raw.get("anchor") or {}
        if not isinstance(anchor, Mapping):
            raise SequencePlanError(f"{label}: anchor must be a mapping")
        _strict(f"{label} anchor", anchor, ANCHOR_INTENT_KEYS)
        policy = str(anchor.get("policy") or (ANCHOR_SOURCE if position == 0 else ANCHOR_CARRY))
        frame_count = _whole(raw.get("frame_count"), label=label, field="frame_count")
        seed = (
            segment_zero_seed
            if position == 0
            and segment_zero_seed is not None
            and raw.get("seed") in (None, "", "random")
            else _concrete_seed(raw.get("seed"), label=label, max_seed=max_seed)
        )
        workflow_id = workflow_version = None
        prompt = negative = ""
        if stage == STAGE_VIDEO_WORKFLOW:
            assert base_spec is not None and base_workflow is not None
            workflow_id = str(raw.get("workflow_id") or base_workflow[0]).strip()
            workflow_version = str(raw.get("workflow_version") or "").strip()
            if not workflow_version:
                if workflow_id != base_workflow[0]:
                    raise SequencePlanError(
                        f"{label}: name the exact version of workflow {workflow_id!r}"
                    )
                workflow_version = base_workflow[1]
            spec = _resolve_workflow(registry, workflow_id, workflow_version, label=label)
            errors.extend(
                f"{label}: {text}"
                for text in workflow_segment_errors(
                    spec, base_spec, frame_count, fps, experimental_opt_in=experimental_opt_in
                )
            )
            prompt = str(
                raw.get("prompt") if raw.get("prompt") is not None else base_prompt
            ).strip()
            negative = str(
                raw.get("negative_prompt")
                if raw.get("negative_prompt") is not None
                else base_negative_prompt
            ).strip()
            if "prompt" in set(getattr(spec, "required_input_names", ())) and not prompt:
                errors.append(
                    f"{label}: {spec.workflow_id} {spec.workflow_version} needs a prompt describing the "
                    "motion; an explicitly empty prompt is refused, not replaced by another"
                )
        else:
            for forbidden in ("workflow_id", "workflow_version", "prompt", "negative_prompt"):
                if str(raw.get(forbidden) or "").strip():
                    raise SequencePlanError(f"{label}: native SVD takes no {forbidden}")
            if svd_max_frames is not None and frame_count > svd_max_frames:
                errors.append(
                    f"{label}: native SVD generates at most {svd_max_frames} frames per segment "
                    f"(requested {frame_count})"
                )
        anchor_path = anchor_sha = None
        if policy == ANCHOR_PROVIDED:
            path_text = str(anchor.get("path") or "").strip()
            if not path_text:
                raise SequencePlanError(f"{label}: a provided anchor needs an image path")
            anchor_path, anchor_sha = _check_provided_anchor(
                path_text,
                label=label,
                hash_file=hash_file,
                target=target_size if stage == STAGE_VIDEO_WORKFLOW else None,
            )
        elif anchor.get("path"):
            raise SequencePlanError(f"{label}: anchor policy {policy!r} takes no image path")
        overlap = (
            default_overlap(policy, position)
            if raw.get("overlap_frames") is None
            else _whole(raw["overlap_frames"], label=label, field="overlap_frames")
        )
        segments.append(
            SegmentSpec(
                index=position,
                seed=seed,
                frame_count=frame_count,
                anchor_policy=policy,
                workflow_id=workflow_id,
                workflow_version=workflow_version,
                prompt=prompt,
                negative_prompt=negative,
                anchor_path=anchor_path,
                anchor_sha256=anchor_sha,
                overlap_frames=overlap,
            )
        )
    assembly_raw = intent.get("assembly") or {}
    if not isinstance(assembly_raw, Mapping):
        raise SequencePlanError("the sequence assembly must be a mapping")
    assembly = SequenceAssembly.from_dict(assembly_raw) if assembly_raw else SequenceAssembly()
    plan = SequencePlan(
        sequence_id=str(intent.get("sequence_id") or uuid.uuid4().hex).strip(),
        stage=stage,
        backend=BACKEND_FOR_STAGE[stage],
        model_id=model_id,
        experimental_opt_in=bool(experimental_opt_in),
        source=_segment_source(source, hash_file=hash_file),
        continuity=None if continuity is None else dict(continuity),
        plan_origin=None if plan_origin is None else dict(plan_origin),
        fps=int(fps),
        segments=tuple(segments),
        assembly=assembly,
        color_match=SequenceColorMatch.from_value(intent.get("color_match")),
        target_width=None if target_size is None else int(target_size[0]),
        target_height=None if target_size is None else int(target_size[1]),
    )
    errors.extend(plan.validate())
    if errors:
        raise SequencePlanError("; ".join(dict.fromkeys(errors)))
    return plan


def verify_plan_source(
    plan: SequencePlan, source_path: str | Path, *, hash_file: FileHasher = sha256_file
) -> None:
    """Refuse when segment 0's input is not the exact image that was frozen with the plan."""

    if plan.source is None:
        return
    path = Path(source_path)
    if not path.is_file():
        raise SequencePlanError(f"the sequence's source image is missing: {path}")
    if hash_file(path) != plan.source["sha256"]:
        raise SequencePlanError(f"the sequence's source image changed since it was queued: {path}")


def verify_provided_anchors(
    plan: SequencePlan, *, hash_file: FileHasher = sha256_file, from_segment: int = 0
) -> None:
    """Refuse when an authored anchor is missing or no longer the image that was queued.

    ``from_segment`` skips segments that are already finished (a resume only needs the suffix's anchors)."""

    problems: list[str] = []
    for segment in plan.segments[from_segment:]:
        if segment.anchor_policy != ANCHOR_PROVIDED or not segment.anchor_path:
            continue
        path = Path(segment.anchor_path)
        if not path.is_file():
            problems.append(f"segment {segment.index} anchor is missing: {path}")
        elif hash_file(path) != segment.anchor_sha256:
            problems.append(f"segment {segment.index} anchor changed since it was queued: {path}")
    if problems:
        raise SequencePlanError("; ".join(problems))


__all__ = [
    "SUPPORTED_REQUIRED_INPUTS",
    "freeze_sequence_plan",
    "read_still_size",
    "sanitize_clip_name",
    "sha256_file",
    "verify_plan_source",
    "verify_provided_anchors",
    "workflow_segment_errors",
]
