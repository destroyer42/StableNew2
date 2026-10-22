"""Reconstruct one Video Workflow experiment from canonical persisted jobs (PR-VID-QUALITY-211).

A review group is *not* a stored entity.  It is recovered, read-only, from the immutable
``LearningJobContext`` every arm of a one-variable experiment froze into its NJR
(``VideoWorkflowExperimentService``), starting from any one job id.  Nothing here looks at directory
names, file name prefixes or timestamps, and nothing is written, queued, retried or repaired.

Rules this module enforces (each has a test):

* the selected job must itself be a Video Workflow experiment arm, otherwise there is no group;
* sibling candidates come from one bounded repository window (``list_experiment_sibling_entries``) and
  are accepted only when their own NJR carries the same experiment id as a ``video_workflow`` source;
  replay descendants and any other source kind that merely mention the id are excluded, never merged;
* duplicate or out-of-range arm indices and arms that differ outside the tested control are refused with
  an actionable message (the PR-VID-194 ``assert_one_variable`` gate is reused, not re-implemented);
* an arm is ``PLAYABLE`` only when the repository says it completed and its recorded primary video bundle
  names an accessible, supported file.  Every other outcome stays visible with its own state.

It imports nothing from the GUI, controller or learning layers.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from src.pipeline.job_models_v2 import NormalizedJobRecord, SourceKind, WorkloadKind
from src.pipeline.njr_core_v26 import thaw_json
from src.queue.job_history_store import INTERRUPTED_RESTART_ACTION_REQUIRED, JobHistoryEntry
from src.queue.job_model import JobStatus
from src.utils.njr_identity import snapshot_fingerprint
from src.utils.snapshot_builder_v2 import normalized_job_from_snapshot
from src.video.video_artifact_helpers import video_bundle_from_result
from src.video.video_workflow_experiment import (
    ARM_LABELS,
    ExperimentArm,
    ExperimentRefused,
    assert_one_variable,
)
from src.video.workflow_controls import OPERATOR_CONTROLS_KEY

#: Containers the bounded preview decoder is asked to read.  The review never transcodes or rewrites them.
SUPPORTED_VIDEO_SUFFIXES = frozenset({".mp4", ".webm", ".mov", ".mkv", ".avi", ".gif"})
_STATE_TEXT_LIMIT = 240


class ReviewGroupError(ValueError):
    """The group cannot be built; ``code`` is stable for callers/tests, the message is operator language."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ArmState(str, Enum):
    PLAYABLE = "playable"
    PENDING = "pending"
    RUNNING = "running"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"
    NO_OUTPUT = "no_output"
    MISSING = "missing"
    UNSUPPORTED = "unsupported"


class RepositoryReader(Protocol):
    """The two read-only repository calls the group needs."""

    def get_job(self, job_id: str) -> JobHistoryEntry | None: ...

    def list_experiment_sibling_entries(
        self, job_id: str, experiment_id: str
    ) -> list[JobHistoryEntry]: ...


@dataclass(frozen=True)
class ReviewArm:
    label: str
    index: int
    value: Any  # the resolved tested value, exactly as the immutable NJR recorded it
    job_id: str
    state: ArmState
    state_text: str
    njr_fingerprint: str
    artifact_path: str | None = None
    #: Filled by the review service (hashing reads the whole file, so it is never done here).
    artifact_sha256: str = ""
    artifact_bytes: int = 0

    @property
    def playable(self) -> bool:
        return self.state is ArmState.PLAYABLE


@dataclass(frozen=True)
class ReviewOverview:
    """What stayed identical across the arms, read from the immutable NJR of the lowest arm."""

    workflow_id: str
    workflow_version: str
    backend_id: str
    seed: int | None
    frame_count: int | None
    fps: float | None
    prompt: str
    negative_prompt: str
    source_image_path: str
    prepared_source_path: str
    driving_video_path: str
    driving_video_sha256: str
    #: ``{"derived": {path, sha256}, "original": {path, sha256}, "settings": {...}}`` or empty.
    motion_source_preparation: Mapping[str, Any] = field(default_factory=dict)
    fixed_controls: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReviewGroup:
    experiment_id: str
    experiment_name: str
    variable_name: str
    arms: tuple[ReviewArm, ...]
    overview: ReviewOverview
    selected_job_id: str
    #: Same-experiment candidates that were deliberately not merged (for example replay descendants).
    excluded_job_ids: tuple[str, ...] = ()

    def arm_for_job(self, job_id: str) -> ReviewArm | None:
        return next((arm for arm in self.arms if arm.job_id == job_id), None)

    @property
    def playable_arms(self) -> tuple[ReviewArm, ...]:
        return tuple(arm for arm in self.arms if arm.playable)


def _clean(text: Any, limit: int = _STATE_TEXT_LIMIT) -> str:
    return "".join(ch for ch in str(text or "") if ch.isprintable())[:limit]


def _njr_of(entry: JobHistoryEntry) -> NormalizedJobRecord | None:
    snapshot = entry.snapshot if isinstance(entry.snapshot, Mapping) else {}
    try:
        return normalized_job_from_snapshot(snapshot)
    except Exception:  # noqa: BLE001 - a stored row that cannot be rebuilt is simply "not an arm"
        return None


def _workflow_block(njr: NormalizedJobRecord) -> dict[str, Any] | None:
    try:
        block = thaw_json(njr.config).get("video_workflow")
    except Exception:  # noqa: BLE001
        return None
    return block if isinstance(block, dict) and block.get("workflow_id") else None


def _is_experiment_arm(njr: NormalizedJobRecord | None) -> bool:
    return (
        njr is not None
        and njr.source.kind is SourceKind.VIDEO_WORKFLOW
        and njr.workload_kind is WorkloadKind.VIDEO
        and njr.learning_context is not None
        and bool(njr.learning_context.experiment_id)
        and _workflow_block(njr) is not None
    )


def snapshot_is_experiment_arm(snapshot: Mapping[str, Any] | None) -> bool:
    """Cheap, dict-level check that a stored snapshot is a Video Workflow experiment arm.

    Used to decide whether a History action is offered; it does not deserialize the NJR.  The full
    validation still happens in ``build_review_group`` when the review is opened.
    """

    normalized = snapshot.get("normalized_job") if isinstance(snapshot, Mapping) else None
    if not isinstance(normalized, Mapping):
        return False
    source = normalized.get("source")
    provenance = normalized.get("provenance")
    workload = normalized.get("workload")
    config = workload.get("config") if isinstance(workload, Mapping) else None
    context = provenance.get("learning_context") if isinstance(provenance, Mapping) else None
    workflow = config.get("video_workflow") if isinstance(config, Mapping) else None
    return (
        isinstance(source, Mapping)
        and source.get("kind") == SourceKind.VIDEO_WORKFLOW.value
        and isinstance(context, Mapping)
        and bool(context.get("experiment_id"))
        and isinstance(workflow, Mapping)
        and bool(workflow.get("workflow_id"))
    )


def bundle_video_path(bundle: Mapping[str, Any]) -> tuple[str | None, str]:
    """``(path, reason)``: the bundle's primary video, or why there is none."""

    candidates: list[str] = []
    primary = bundle.get("primary_path")
    if primary:
        candidates.append(str(primary))
    for key in ("video_paths", "gif_paths"):
        items = bundle.get(key)
        if isinstance(items, list):
            candidates.extend(str(item) for item in items if item)
    for candidate in candidates:
        if Path(candidate).suffix.lower() in SUPPORTED_VIDEO_SUFFIXES:
            return candidate, ""
    if candidates:
        suffix = Path(candidates[0]).suffix.lower() or "no extension"
        return None, f"The recorded output is not a supported video file ({_clean(suffix, 16)})."
    if bundle.get("frame_paths"):
        return None, "The job exported a frame sequence, not a video file."
    return None, "The job recorded no video output."


def classify_entry(
    entry: JobHistoryEntry, *, is_file: Callable[[str], bool] = os.path.isfile
) -> tuple[ArmState, str, str | None]:
    """``(state, operator text, primary artifact path)`` from the canonical history entry alone."""

    envelope = entry.error_envelope
    if envelope is not None and envelope.error_type == INTERRUPTED_RESTART_ACTION_REQUIRED:
        return (
            ArmState.INTERRUPTED,
            "Interrupted by a restart; the job needs operator action and has no reviewable video.",
            None,
        )
    if entry.status is JobStatus.QUEUED:
        return ArmState.PENDING, "Queued; not finished yet.", None
    if entry.status is JobStatus.RUNNING:
        return ArmState.RUNNING, "Running; not finished yet.", None
    if entry.status is JobStatus.CANCELLED:
        return ArmState.CANCELLED, "Cancelled; no reviewable video.", None
    result = entry.result if isinstance(entry.result, dict) else {}
    if entry.status is JobStatus.FAILED or result.get("error"):
        detail = _clean(entry.error_message or result.get("error"), 160)
        return ArmState.FAILED, "Failed" + (f": {detail}" if detail else "."), None
    bundle = video_bundle_from_result(result)
    if bundle is None:
        return ArmState.NO_OUTPUT, "Completed, but no video output was recorded.", None
    path, reason = bundle_video_path(bundle)
    if path is None:
        return ArmState.UNSUPPORTED, reason, None
    try:
        present = bool(is_file(path))
    except (OSError, ValueError):
        present = False
    if not present:
        return ArmState.MISSING, f"The output file is missing or unreadable: {_clean(path)}", path
    return ArmState.PLAYABLE, "Ready to review.", path


def _overview(njr: NormalizedJobRecord, variable_name: str) -> ReviewOverview:
    block = _workflow_block(njr) or {}
    controls = dict(block.get(OPERATOR_CONTROLS_KEY) or {})
    controls.pop(variable_name, None)
    preparation = block.get("motion_source_preparation")
    summary: dict[str, Any] = {}
    if isinstance(preparation, dict):
        for side in ("original", "derived"):
            part = preparation.get(side)
            if isinstance(part, dict):
                summary[side] = {key: part.get(key) for key in ("path", "sha256")}
        if isinstance(preparation.get("settings"), dict):
            summary["settings"] = dict(preparation["settings"])
    source_preparation = block.get("source_preparation")
    original_source = (
        str(source_preparation.get("original_source_path") or "")
        if isinstance(source_preparation, dict)
        else ""
    )
    prepared = str(njr.input_image_paths[0]) if njr.input_image_paths else ""
    fps = block.get("fps")
    frame_count = block.get("frame_count")
    seed = block.get("seed")
    return ReviewOverview(
        workflow_id=str(block.get("workflow_id") or ""),
        workflow_version=str(block.get("workflow_version") or ""),
        backend_id=str(block.get("backend_id") or ""),
        seed=seed if isinstance(seed, int) and not isinstance(seed, bool) else None,
        frame_count=frame_count if isinstance(frame_count, int) else None,
        fps=float(fps) if isinstance(fps, (int, float)) and not isinstance(fps, bool) else None,
        prompt=str(block.get("prompt") or ""),
        negative_prompt=str(block.get("negative_prompt") or ""),
        source_image_path=original_source or prepared,
        prepared_source_path=prepared,
        driving_video_path=str(block.get("pose_video_path") or ""),
        driving_video_sha256=str(block.get("pose_video_sha256") or ""),
        motion_source_preparation=summary,
        fixed_controls=controls,
    )


def build_review_group(
    repository: RepositoryReader,
    job_id: str,
    *,
    is_file: Callable[[str], bool] = os.path.isfile,
) -> ReviewGroup:
    """The experiment ``job_id`` belongs to, or ``ReviewGroupError`` saying why there is none."""

    selected_id = str(job_id or "").strip()
    if not selected_id:
        raise ReviewGroupError("no_job", "Enter or select a job id to review.")
    entry = repository.get_job(selected_id)
    if entry is None:
        raise ReviewGroupError("unknown_job", f"No job {selected_id!r} exists in the job history.")
    selected = _njr_of(entry)
    if not _is_experiment_arm(selected):
        raise ReviewGroupError(
            "not_video_experiment",
            f"Job {selected_id} is not an arm of a Video Workflow experiment, so there is nothing "
            "to compare. (Single Video Workflow jobs, native SVD jobs and replays are not "
            "experiment arms.)",
        )
    assert selected is not None and selected.learning_context is not None
    context = selected.learning_context
    experiment_id = context.experiment_id

    candidates = repository.list_experiment_sibling_entries(selected_id, experiment_id)
    if not any(candidate.job_id == selected_id for candidate in candidates):
        candidates = [entry, *candidates]
    arms_by_index: dict[int, tuple[JobHistoryEntry, NormalizedJobRecord]] = {}
    excluded: list[str] = []
    for candidate in candidates:
        njr = selected if candidate.job_id == selected_id else _njr_of(candidate)
        candidate_context = njr.learning_context if njr is not None else None
        if candidate_context is None or candidate_context.experiment_id != experiment_id:
            continue  # the id appeared incidentally in the stored text; not a member at all
        if not _is_experiment_arm(njr):
            excluded.append(candidate.job_id)  # a replay descendant or another source kind
            continue
        assert njr is not None
        index = candidate_context.variant_index
        if not 0 <= index < len(ARM_LABELS):
            raise ReviewGroupError(
                "conflict",
                f"Job {candidate.job_id} claims arm index {index} of experiment {experiment_id}; "
                f"valid arms are 0 to {len(ARM_LABELS) - 1}. The experiment is not reviewed.",
            )
        if index in arms_by_index:
            raise ReviewGroupError(
                "conflict",
                f"Jobs {arms_by_index[index][0].job_id} and {candidate.job_id} both claim arm "
                f"{ARM_LABELS[index]} of experiment {experiment_id}. The provenance is ambiguous, so "
                "the experiment is not reviewed.",
            )
        arms_by_index[index] = (candidate, njr)

    ordered = sorted(arms_by_index)
    experiment_arms = [
        ExperimentArm(
            label=ARM_LABELS[index],
            index=index,
            value=thaw_json(arms_by_index[index][1].learning_context.variant_value),  # type: ignore[union-attr]
            njr=arms_by_index[index][1],
        )
        for index in ordered
    ]
    if len(experiment_arms) >= 2:
        try:
            assert_one_variable(
                experiment_arms,
                variable_name=context.variable_under_test,
                variable_label=context.variable_under_test,
                experiment_id=experiment_id,
                experiment_name=context.experiment_name,
            )
        except ExperimentRefused as exc:
            raise ReviewGroupError(
                "conflict",
                f"The stored jobs of experiment {experiment_id} do not agree: {exc} "
                "The experiment is not reviewed.",
            ) from exc

    arms: list[ReviewArm] = []
    for arm in experiment_arms:
        arm_entry = arms_by_index[arm.index][0]
        state, text, path = classify_entry(arm_entry, is_file=is_file)
        arms.append(
            ReviewArm(
                label=arm.label,
                index=arm.index,
                value=arm.value,
                job_id=arm_entry.job_id,
                state=state,
                state_text=text,
                njr_fingerprint=snapshot_fingerprint(arm_entry.snapshot or {}),
                artifact_path=path,
            )
        )
    return ReviewGroup(
        experiment_id=experiment_id,
        experiment_name=context.experiment_name,
        variable_name=context.variable_under_test,
        arms=tuple(arms),
        overview=_overview(arms_by_index[ordered[0]][1], context.variable_under_test),
        selected_job_id=selected_id,
        excluded_job_ids=tuple(sorted(set(excluded))),
    )


__all__ = [
    "SUPPORTED_VIDEO_SUFFIXES",
    "ArmState",
    "RepositoryReader",
    "ReviewArm",
    "ReviewGroup",
    "ReviewGroupError",
    "ReviewOverview",
    "build_review_group",
    "bundle_video_path",
    "classify_entry",
    "snapshot_is_experiment_arm",
]
