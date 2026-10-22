"""Resume a failed or interrupted sequence job as a NEW job (PR-VID-SEQ-330-CORE).

A resume never mutates the job that failed and never bypasses the queue. ``build_resume_njr`` re-verifies the parent's
ledger (pinned by SHA-256) and every artifact of the finished prefix, then returns a new NJR with parent lineage (the
ordinary replay identity) whose stage config also carries ``sequence_resume``. The caller admits it through
``JobService.submit_njrs`` like any other job. When the runner executes it, ``VideoSequenceExecutor`` verifies the same
things again before dispatching anything, copies the prefix's artifacts into the new run directory and runs only the
unfinished suffix, so the new job never depends on a parent directory that may be pruned and a file that changed
between admission and execution is still caught.

Nothing here replays a generation POST: a segment that was in flight when the parent stopped is simply the first
segment of the suffix, generated again from its frozen seed and anchor.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any, Final

from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.njr_core_v26 import thaw_json
from src.pipeline.replay_njr_compiler import ReplayIntent, compile_replay_intent
from src.video.sequence_admission import verify_provided_anchors
from src.video.sequence_frames import SequenceFrameError, copy_verified, require_png
from src.video.sequence_ledger import (
    ORIGIN_REUSED,
    FileHasher,
    FileRecord,
    FinalFrame,
    InputAnchor,
    LedgerSegment,
    SequenceLedger,
    SequenceLedgerError,
    read_ledger,
    sha256_of,
    verify_segment_files,
)
from src.video.sequence_plan import (
    STAGE_SVD_NATIVE,
    STAGE_VIDEO_WORKFLOW,
    SequencePlan,
    SequencePlanError,
)

RESUME_KEY: Final = "sequence_resume"
REPLAY_KEY: Final = "sequence_replay_of"
REPLAY_BLOCK_KEYS: Final = frozenset(
    {"parent_job_id", "parent_ledger_path", "parent_ledger_sha256"}
)
SEQUENCE_STAGES_BY_PRIORITY: Final = (STAGE_VIDEO_WORKFLOW, STAGE_SVD_NATIVE)
PLAN_KEY: Final = "sequence_metadata"
RESUME_BLOCK_KEYS: Final = frozenset(
    {"parent_job_id", "parent_ledger_path", "parent_ledger_sha256", "plan_sha256", "from_segment"}
)


class SequenceResumeError(ValueError):
    """The checkpoint cannot be resumed; nothing was dispatched and no job was created."""


def unsafe_paths(segments: Sequence[LedgerSegment], root: Path) -> list[str]:
    """Recorded artifact paths that are not inside ``root`` (a ledger may only name files of its own run)."""

    base = root.resolve()
    problems: list[str] = []
    for segment in segments:
        for record in segment.artifact_files():
            try:
                Path(record.path).resolve().relative_to(base)
            except (ValueError, OSError):
                problems.append(
                    f"segment {segment.index}: {Path(record.path).name} is outside the checkpoint's own run folder"
                )
    return problems


def resume_problems(
    plan: SequencePlan,
    ledger: SequenceLedger,
    from_segment: int,
    *,
    parent_job_id: str | None = None,
    ledger_root: Path | None = None,
    hash_file: FileHasher = sha256_of,
) -> list[str]:
    """Every reason ``ledger`` cannot supply the finished prefix ``0..from_segment-1`` of ``plan`` (empty when it can)."""

    problems: list[str] = []
    if parent_job_id is not None and ledger.job_id != parent_job_id:
        problems.append(
            f"the checkpoint belongs to job {ledger.job_id}, not to the job being resumed ({parent_job_id})"
        )
    if ledger.plan_sha256 != plan.plan_sha256():
        problems.append("the checkpoint was made for a different sequence plan")
    if ledger.sequence_id != plan.sequence_id or ledger.total_segments != len(plan.segments):
        problems.append("the checkpoint describes a different sequence")
    count = len(plan.segments)
    if not 1 <= from_segment < count:
        problems.append(f"cannot resume from segment {from_segment} of a {count}-segment sequence")
        return problems
    if len(ledger.segments) < from_segment:
        problems.append(
            f"the checkpoint finished only {len(ledger.segments)} segment(s), "
            f"so segment {from_segment} cannot be the first one to run"
        )
        return problems
    prefix = ledger.segments[:from_segment]
    for done in prefix:
        wanted = plan.segments[done.index]
        if (done.seed, done.expected_frame_count, done.overlap_frames) != (
            wanted.seed,
            wanted.frame_count,
            wanted.overlap_frames,
        ) or (done.workflow_id, done.workflow_version) != (
            wanted.workflow_id,
            wanted.workflow_version,
        ):
            problems.append(
                f"segment {done.index} in the checkpoint is not the segment this plan describes"
            )
        # A workflow segment's frames are exactly its admitted count; native SVD exports may be interpolated.
        if plan.stage == STAGE_VIDEO_WORKFLOW and done.frame_count != done.expected_frame_count:
            problems.append(f"segment {done.index} in the checkpoint has an unexpected frame count")
    if ledger_root is not None:
        problems.extend(unsafe_paths(prefix, ledger_root))
    if problems:
        return problems
    problems.extend(verify_segment_files(prefix, hash_file=hash_file))
    for done in prefix:
        try:
            require_png(Path(done.final_frame.file.path), label=f"segment {done.index} final frame")
        except SequenceFrameError as exc:
            problems.append(str(exc))
    return problems


def plan_from_njr(njr: NormalizedJobRecord, stage_name: str) -> SequencePlan:
    stage = next((item for item in njr.stage_chain if item.stage_type == stage_name), None)
    raw = None if stage is None else thaw_json(stage.extra).get(PLAN_KEY)
    if not raw:
        raise SequenceResumeError(f"the job has no sequence plan on its {stage_name} stage")
    try:
        return SequencePlan.from_dict(raw)
    except SequencePlanError as exc:
        raise SequenceResumeError(str(exc)) from exc


def load_pinned_ledger(path: str | Path, expected_sha256: str) -> SequenceLedger:
    try:
        return read_ledger(Path(path), expected_sha256=expected_sha256)
    except SequenceLedgerError as exc:
        raise SequenceResumeError(str(exc)) from exc


def copy_prefix(
    ledger: SequenceLedger,
    from_segment: int,
    run_dir: Path,
    *,
    hash_file: FileHasher = sha256_of,
) -> list[LedgerSegment]:
    """Copy the finished prefix's artifacts into ``run_dir`` (verifying every copy) and return its segments, re-pointed.

    Only what the sequence still needs is copied: each segment's clip, its frames (the movie is assembled from frames)
    and its exact final frame. Colour-matched frames are not copied; they are recomputed from the originals.
    """

    base = run_dir / "sequence" / "prefix"
    copied: list[LedgerSegment] = []
    try:
        for segment in ledger.segments[:from_segment]:
            folder = base / f"seg_{segment.index:02d}"

            def clone(record: FileRecord, subfolder: str, folder: Path = folder) -> FileRecord:
                return copy_verified(
                    Path(record.path),
                    folder / subfolder / Path(record.path).name,
                    expected_sha256=record.sha256,
                    hash_file=hash_file,
                )

            final = FinalFrame(
                file=clone(segment.final_frame.file, "final"),
                basis=segment.final_frame.basis,
                detail=dict(segment.final_frame.detail),
            )
            anchor = segment.input_anchor
            if anchor is not None and anchor.from_segment is not None and copied:
                # A carried anchor is the previous segment's final frame: point at this run's verified copy of it.
                previous = copied[anchor.from_segment].final_frame
                anchor = InputAnchor(
                    policy=anchor.policy,
                    basis=anchor.basis,
                    file=previous.file,
                    from_segment=anchor.from_segment,
                )
            copied.append(
                replace(
                    segment,
                    origin=ORIGIN_REUSED,
                    clip=None if segment.clip is None else clone(segment.clip, "clip"),
                    manifest=None
                    if segment.manifest is None
                    else clone(segment.manifest, "manifest"),
                    frames=tuple(clone(record, "frames") for record in segment.frames),
                    color_matched=(),
                    color_match=None,
                    input_anchor=anchor,
                    final_frame=final,
                )
            )
    except SequenceFrameError as exc:
        raise SequenceResumeError(str(exc)) from exc
    return copied


def _with_stage_extra(
    njr: NormalizedJobRecord, stage_name: str, updates: Mapping[str, Any]
) -> NormalizedJobRecord:
    stages = tuple(
        replace(stage, extra={**thaw_json(stage.extra), **updates})
        if stage.stage_type == stage_name
        else stage
        for stage in njr.stage_chain
    )
    config = thaw_json(njr.workload.config)
    if isinstance(config.get(stage_name), Mapping):
        config[stage_name] = {**config[stage_name], **updates}
    return replace(njr, stages=stages, workload=replace(njr.workload, config=config))


def build_resume_njr(
    parent: NormalizedJobRecord,
    *,
    stage_name: str,
    ledger_path: str | Path,
    from_segment: int | None = None,
    hash_file: FileHasher = sha256_of,
    id_fn: Callable[[], str] | None = None,
) -> NormalizedJobRecord:
    """A new NJR (parent lineage) that resumes ``parent`` from ``from_segment`` (default: the first unfinished segment).

    Raises ``SequenceResumeError`` before creating anything when the checkpoint is tampered with, missing a file,
    made for another plan, or an authored anchor of the suffix changed.
    """

    plan = plan_from_njr(parent, stage_name)
    ledger_file = Path(ledger_path)
    try:
        ledger_sha = sha256_of(ledger_file)
    except OSError as exc:
        raise SequenceResumeError(f"the sequence ledger is missing: {ledger_file}") from exc
    ledger = load_pinned_ledger(ledger_file, ledger_sha)
    start = len(ledger.segments) if from_segment is None else int(from_segment)
    problems = resume_problems(
        plan,
        ledger,
        start,
        parent_job_id=parent.job_id,
        ledger_root=ledger_file.parent,
        hash_file=hash_file,
    )
    if problems:
        raise SequenceResumeError("; ".join(problems))
    try:
        verify_provided_anchors(plan, hash_file=hash_file, from_segment=start)
    except SequencePlanError as exc:
        raise SequenceResumeError(str(exc)) from exc
    child = compile_replay_intent(ReplayIntent(record=parent), id_fn=id_fn)
    block = {
        "parent_job_id": parent.job_id,
        "parent_ledger_path": str(ledger_file),
        "parent_ledger_sha256": ledger_sha,
        "plan_sha256": plan.plan_sha256(),
        "from_segment": start,
    }
    return _with_stage_extra(child, stage_name, {RESUME_KEY: block})


def sequence_stage_name(njr: NormalizedJobRecord) -> str:
    """The stage of ``njr`` that carries a sequence plan (``video_workflow`` or ``svd_native``)."""

    for name in SEQUENCE_STAGES_BY_PRIORITY:
        stage = next((item for item in njr.stage_chain if item.stage_type == name), None)
        if stage is not None and thaw_json(stage.extra).get(PLAN_KEY):
            return name
    raise SequenceResumeError(
        f"job {njr.job_id} is not a sequence job (its stages carry no sequence plan)"
    )


def find_ledger_path(result: Any) -> str | None:
    """The ``ledger_path`` a finished or failed run recorded in its result metadata (searched, not assumed)."""

    if isinstance(result, Mapping):
        if result.get("ledger_path"):
            return str(result["ledger_path"])
        for value in result.values():
            found = find_ledger_path(value)
            if found:
                return found
    elif isinstance(result, (list, tuple)):
        for value in result:
            found = find_ledger_path(value)
            if found:
                return found
    return None


def build_replay_njr(
    parent: NormalizedJobRecord,
    *,
    stage_name: str,
    ledger_path: str | Path | None = None,
    id_fn: Callable[[], str] | None = None,
) -> NormalizedJobRecord:
    """A full replay: a new NJR (parent lineage) that recomputes EVERY segment from the frozen plan.

    Distinct from a resume: nothing is reused. When the original run's ledger is available (and readable) it is pinned
    so the replay can record whether each recomputed final frame equals the original, as divergence, never a failure."""

    plan_from_njr(parent, stage_name)  # the job must carry a sequence plan
    child = compile_replay_intent(ReplayIntent(record=parent), id_fn=id_fn)
    if ledger_path is None:
        return child
    ledger_file = Path(ledger_path)
    try:
        digest = sha256_of(ledger_file)
    except OSError:
        return child  # no readable reference: the replay still runs, it just has nothing to compare with
    block = {
        "parent_job_id": parent.job_id,
        "parent_ledger_path": str(ledger_file),
        "parent_ledger_sha256": digest,
    }
    return _with_stage_extra(child, stage_name, {REPLAY_KEY: block})


def parse_resume_block(raw: Any) -> dict[str, Any]:
    """The validated ``sequence_resume`` block of a stage config; unknown or missing fields are refused."""

    if not isinstance(raw, Mapping):
        raise SequenceResumeError("sequence_resume must be a mapping")
    extra = sorted(set(raw) - RESUME_BLOCK_KEYS)
    missing = sorted(RESUME_BLOCK_KEYS - set(raw))
    if extra or missing:
        raise SequenceResumeError(f"sequence_resume has unknown fields {extra} or lacks {missing}")
    try:
        return {
            **{key: raw[key] for key in RESUME_BLOCK_KEYS},
            "from_segment": int(raw["from_segment"]),
        }
    except (TypeError, ValueError) as exc:
        raise SequenceResumeError("sequence_resume.from_segment must be a whole number") from exc


__all__ = [
    "PLAN_KEY",
    "REPLAY_BLOCK_KEYS",
    "REPLAY_KEY",
    "RESUME_KEY",
    "SequenceResumeError",
    "build_replay_njr",
    "build_resume_njr",
    "find_ledger_path",
    "sequence_stage_name",
    "copy_prefix",
    "load_pinned_ledger",
    "parse_resume_block",
    "plan_from_njr",
    "resume_problems",
    "unsafe_paths",
]
