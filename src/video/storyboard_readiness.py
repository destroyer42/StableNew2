"""Read-only source identity and workflow projections for editable Storyboards; admission stays authoritative."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from src.video.sequence_admission import (
    read_still_size,
    segment_prompt_problem,
    sha256_file,
    workflow_segment_errors,
)
from src.video.sequence_shots import shot_problems
from src.video.storyboard import StoryboardDraft, StoryboardError
from src.video.workflow_frame_count import frame_count_policy, legal_frame_counts


def linked_images(draft: StoryboardDraft) -> list[tuple[str, str, str]]:
    return [("Source image", draft.source_path, draft.source_sha256)] + [
        (f"Shot {i + 1} authored anchor", s.keyframe_path, s.keyframe_sha256)
        for i, s in enumerate(draft.shots)
        if s.keyframe_path
    ]


def image_status(label: str, path: str, recorded: str) -> str:
    if not path or not Path(path).is_file():
        return f"{label}: missing image ({path or 'choose a source image'})."
    try:
        read_still_size(path, label=label)
        actual = sha256_file(path)
    except (OSError, ValueError) as exc:
        return f"{label}: unreadable image: {exc}"
    if not recorded:
        return f"{label}: identity not recorded; check readiness to record the selected file."
    if actual != recorded:
        return f"{label}: content changed (SHA-256 mismatch); explicitly Accept Current Media before queueing."
    return ""


def record_images(draft: StoryboardDraft, *, accept_changed: bool = False) -> StoryboardDraft:
    """Record new selections only. An existing identity changes only with explicit operator acceptance."""

    def identity(path: str, previous: str) -> str:
        if previous and not accept_changed:
            return previous
        if not path or not Path(path).is_file():
            return "" if accept_changed else previous
        read_still_size(path, label="Selected media")
        return sha256_file(path)

    return replace(
        draft,
        source_sha256=identity(draft.source_path, draft.source_sha256),
        shots=tuple(
            replace(s, keyframe_sha256=identity(s.keyframe_path, s.keyframe_sha256))
            for s in draft.shots
        ),
    )


def verify_images(draft: StoryboardDraft) -> None:
    problems = [
        problem
        for label, path, digest in linked_images(draft)
        if (problem := image_status(label, path, digest))
    ]
    if problems:
        raise StoryboardError(" ".join(problems))


def unsupported_controls(form: dict[str, Any]) -> list[str]:
    problems = []
    for key in (
        "end_anchor_path",
        "mid_anchor_paths",
        "pose_video_path",
        "operator_controls",
        "motion_source_preparation",
        "motion_library_asset",
    ):
        if form.get(key):
            problems.append(f"Sequence cannot carry {key}; clear it before queueing.")
    if (form.get("camera_intent") or {}).get("preset", "none") not in ("", "none"):
        problems.append("Sequence cannot carry camera controls.")
    if (form.get("depth_input") or {}).get("mode", "none") not in ("", "none"):
        problems.append("Sequence cannot carry depth controls.")
    if (form.get("interpolation") or {}).get("enabled"):
        problems.append(
            "RIFE smoothing is not applied inside a sequence; the sequence is assembled from each segment's original frames."
        )
    return problems


@dataclass(frozen=True)
class StoryboardReadiness:
    summary: str
    problems: tuple[str, ...]


def readiness(draft: StoryboardDraft, registry: Any, form: dict[str, Any]) -> StoryboardReadiness:
    problems = shot_problems(draft.shots) + unsupported_controls(form)
    fps = 0
    workflow = f"{draft.workflow_id} {draft.workflow_version}".strip() or "No workflow selected"
    if draft.backend != "comfy":
        problems.append(
            "This authoring surface submits Comfy sequences only; native SVD Resume/Replay remains in History."
        )
    try:
        spec = registry.get(draft.workflow_id, draft.workflow_version)
        policy = frame_count_policy(spec)
        fps = int(policy["fps"]) if policy else 0
        form_prompt = str(form.get("prompt") or "").strip()
        for position, shot in enumerate(draft.shots):
            # A blank shot prompt inherits the form's; with both blank the shot is named, not the workflow.
            prompt_problem = segment_prompt_problem(
                spec, shot.prompt.strip() or None, form_prompt, position=position
            )
            if prompt_problem:
                problems.append(prompt_problem)
            problems.extend(
                workflow_segment_errors(
                    spec,
                    spec,
                    shot.frame_count or 0,
                    fps,
                    experimental_opt_in=form.get("experimental_opt_in") is True,
                )
            )
        legal = legal_frame_counts(spec)
        lengths = f"Legal native frames: {', '.join(map(str, legal)) or 'none'}."
    except (KeyError, ValueError) as exc:
        problems.append(f"Selected workflow/version unavailable: {exc}")
        lengths = "Legal native frames: unavailable."
    statuses = []
    for label, path, digest in linked_images(draft):
        problem = image_status(label, path, digest)
        if problem:
            problems.append(problem)
        statuses.append(problem or f"{label}: verified SHA-256.")
    frames = sum(s.frame_count or 0 for s in draft.shots)
    duration = (
        f"approximately {frames / fps:.2f} seconds before overlap trims"
        if fps
        else "duration unknown"
    )
    boundaries = [
        f"Shot {i + 1}: {'form source' if i == 0 else 'provided authored anchor' if s.keyframe_path else 'carried final frame'}; seed {s.seed or ('form seed / random' if i == 0 else 'random at admission')}"
        for i, s in enumerate(draft.shots)
    ]
    summary = "\n".join(
        [
            f"Authoring summary (not a frozen plan): {len(draft.shots)} shots, {frames} native frames; {duration}.",
            f"Workflow: {workflow}. {lengths}",
            *statuses,
            *boundaries,
        ]
    )
    return StoryboardReadiness(summary, tuple(dict.fromkeys(problems)))
