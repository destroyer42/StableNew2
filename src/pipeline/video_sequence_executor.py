"""Runs the segments of one sequence job (PR-VID-SEQ-330-CORE).

One NJR, one queue row, one ``PipelineRunner.run_njr`` call: the executor is what runs *inside* that call. For each
segment it hands a typed, allow-listed set of overrides to ``run_segment`` (the runner's ``_execute_video_stage`` seam),
establishes the segment's frames and its exact final frame, records the segment in the durable ledger, and only then
dispatches the next. It then assembles the movie from the segments' frames with the ASM-332 engine, inside this same job.

Runtime ownership. Every segment is dispatched with ``hold_runtime=True`` so a StableNew-owned ComfyUI stays warm between
segments. ``release_runtime`` is called exactly once, in ``finally``, on success, failure, cancellation and any
``BaseException``; it goes through the backend's existing ownership interface, which only stops a process StableNew
launched and still owns and never touches an external one. The release never masks the error that ended the sequence.

SQLite keeps every job lifecycle fact. The ledger written here is evidence and a resume source, nothing more.
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from src.controller.runtime_state import CancellationError, CancelToken
from src.video.sequence_admission import verify_plan_source, verify_provided_anchors
from src.video.sequence_assembly import assemble_sequence_frames
from src.video.sequence_frames import (
    ClipDecoder,
    SegmentArtifacts,
    SequenceFrameError,
    collect_segment_artifacts,
    decode_clip_to_frames,
    match_segment_colors,
    require_png,
    require_still,
    trim_overlap,
)
from src.video.sequence_ledger import (
    ANCHOR_BASES,
    LEDGER_FILE_NAME,
    STATE_CANCELLED,
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_INTERRUPTED,
    FileHasher,
    FileRecord,
    InputAnchor,
    LedgerSegment,
    SequenceLedger,
    SequenceLedgerError,
    read_ledger,
    sha256_of,
    write_ledger,
)
from src.video.sequence_plan import (
    ANCHOR_CARRY,
    ANCHOR_PROVIDED,
    ANCHOR_SOURCE,
    STAGE_SVD_NATIVE,
    STAGE_VIDEO_WORKFLOW,
    SegmentSpec,
    SequencePlan,
    SequencePlanError,
)
from src.video.sequence_resume import (
    REPLAY_BLOCK_KEYS,
    REPLAY_KEY,
    SequenceResumeError,
    copy_prefix,
    load_pinned_ledger,
    parse_resume_block,
    resume_problems,
)

logger = logging.getLogger(__name__)

#: The only stage-config paths a segment may override, per stage. Anything else is a planning error, never applied.
ALLOWED_OVERRIDES: dict[str, frozenset[str]] = {
    STAGE_VIDEO_WORKFLOW: frozenset(
        {
            "seed",
            "frame_count",
            "prompt",
            "negative_prompt",
            "workflow_id",
            "workflow_version",
            "video_execution.workflow_id",
            "video_execution.workflow_version",
        }
    ),
    STAGE_SVD_NATIVE: frozenset({"inference.seed", "inference.num_frames", "output.save_frames"}),
}

REPLAY_NOTE = (
    "a full replay recomputes every segment; GPU generation is not guaranteed to be byte-identical, so a "
    "different final frame is recorded as divergence, not as a failure"
)


@dataclass(frozen=True, slots=True)
class SegmentRun:
    """What the runner's segment seam returns: the backend's variant payload and its output paths."""

    raw_result: Mapping[str, Any]
    output_paths: tuple[str, ...] = ()


#: ``(segment, input_image_path, hold_runtime) -> SegmentRun``
SegmentCallback = Callable[[SegmentSpec, str, bool], SegmentRun]


@dataclass(slots=True)
class SequenceOutcome:
    ledger: SequenceLedger
    ledger_path: Path
    ledger_sha256: str
    assembled_path: str | None = None
    assembly_manifest_path: str | None = None
    segment_outputs: list[str] = field(default_factory=list)

    @property
    def output_paths(self) -> list[str]:
        head = [self.assembled_path] if self.assembled_path else []
        return [*head, *self.segment_outputs]


def segment_overrides(plan: SequencePlan, segment: SegmentSpec) -> dict[str, Any]:
    """The nested stage-config overrides for ``segment`` (every path is in ``ALLOWED_OVERRIDES``)."""

    if plan.stage == STAGE_SVD_NATIVE:
        return {
            "inference": {"seed": segment.seed, "num_frames": segment.frame_count},
            # The sequence assembles from frames, so a segment must save them.
            "output": {"save_frames": True},
        }
    return {
        "seed": segment.seed,
        "frame_count": segment.frame_count,
        "prompt": segment.prompt,
        "negative_prompt": segment.negative_prompt,
        "workflow_id": segment.workflow_id,
        "workflow_version": segment.workflow_version,
        "video_execution": {
            "workflow_id": segment.workflow_id,
            "workflow_version": segment.workflow_version,
        },
    }


def _flatten(value: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, item in value.items():
        path = f"{prefix}{key}"
        if isinstance(item, Mapping):
            flat.update(_flatten(item, f"{path}."))
        else:
            flat[path] = item
    return flat


def apply_stage_overrides(
    config: Mapping[str, Any], overrides: Mapping[str, Any], *, stage: str
) -> dict[str, Any]:
    """A copy of ``config`` with ``overrides`` merged in; an override outside the allow-list is refused.

    The frozen NJR is never touched: the runner passes a copy of its stage config through here once per segment."""

    allowed = ALLOWED_OVERRIDES.get(stage)
    if allowed is None:
        raise SequencePlanError(f"stage {stage!r} cannot run as a sequence")
    flat = _flatten(overrides)
    refused = sorted(set(flat) - allowed)
    if refused:
        raise SequencePlanError(
            f"segment override(s) {', '.join(refused)} are not allowed for a {stage} sequence"
        )
    merged: dict[str, Any] = _deep_copy(config)
    for path, value in flat.items():
        cursor = merged
        *parents, leaf = path.split(".")
        for part in parents:
            nxt = cursor.get(part)
            if not isinstance(nxt, dict):
                nxt = {}
                cursor[part] = nxt
            cursor = nxt
        cursor[leaf] = value
    return merged


def _deep_copy(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _deep_copy(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_deep_copy(item) for item in value]
    return value


class VideoSequenceExecutor:
    def __init__(
        self,
        *,
        plan: SequencePlan,
        job_id: str,
        run_dir: Path,
        run_segment: SegmentCallback,
        release_runtime: Callable[[], Mapping[str, Any] | None] | None = None,
        cancel_token: CancelToken | None = None,
        hash_file: FileHasher = sha256_of,
        decode_clip: ClipDecoder | None = None,
        assemble: Callable[..., Any] | None = None,
        on_persist: Callable[[Path, str, SequenceLedger], None] | None = None,
        replay_reference: Mapping[str, Any] | None = None,
    ) -> None:
        self._plan = plan
        self._job_id = job_id
        self._run_dir = run_dir
        self._run_segment = run_segment
        self._release_runtime = release_runtime
        self._cancel_token = cancel_token
        self._hash_file = hash_file
        self._decode_clip = decode_clip or decode_clip_to_frames
        self._assemble = assemble or assemble_sequence_frames
        self._on_persist = on_persist
        self._ledger_path = run_dir / LEDGER_FILE_NAME
        self._ledger = SequenceLedger(
            sequence_id=plan.sequence_id,
            job_id=job_id,
            plan_sha256=plan.plan_sha256(),
            total_segments=len(plan.segments),
            policy_version=plan.policy_version,
        )
        self._ledger_sha = ""
        self._outputs: dict[int, list[str]] = {}
        self._replay_reference = replay_reference
        self._reference_ledger: SequenceLedger | None = None

    # ------------------------------------------------------------------ public

    def execute(
        self, *, source_image_path: str, resume: Mapping[str, Any] | None = None
    ) -> SequenceOutcome:
        outcome: SequenceOutcome | None = None
        try:
            start = self._begin(source_image_path, resume)
            self._persist()
            outcome = self._run_all(source_image_path, start)
        except BaseException as exc:
            self._ledger.state = _terminal_state(exc)
            self._ledger.error = f"{type(exc).__name__}: {exc}"[:1000]
            self._persist_quietly()
            raise
        finally:
            self._release_once()
        assert outcome is not None
        outcome.ledger_sha256 = (
            self._ledger_sha
        )  # the release record was written after the segments
        return outcome

    # ------------------------------------------------------------------ steps

    def _begin(self, source_image_path: str, resume: Mapping[str, Any] | None) -> int:
        block = parse_resume_block(resume) if resume is not None else None
        start = 0 if block is None else int(block["from_segment"])
        # What was queued must still be what is on disk, before anything is dispatched: the frozen source image
        # (when segment 0 has to run) and the authored anchors of the segments that still have to run.
        if start == 0:
            verify_plan_source(self._plan, source_image_path, hash_file=self._hash_file)
        verify_provided_anchors(self._plan, hash_file=self._hash_file, from_segment=start)
        self._load_replay_reference()
        if block is None:
            return 0
        if block["plan_sha256"] != self._plan.plan_sha256():
            raise SequenceResumeError("the resume was made for a different sequence plan")
        parent_path = Path(block["parent_ledger_path"])
        parent = load_pinned_ledger(parent_path, block["parent_ledger_sha256"])
        problems = resume_problems(
            self._plan,
            parent,
            start,
            parent_job_id=str(block["parent_job_id"]),
            ledger_root=parent_path.parent,
            hash_file=self._hash_file,
        )
        if problems:
            raise SequenceResumeError("; ".join(problems))
        self._ledger.segments = copy_prefix(parent, start, self._run_dir, hash_file=self._hash_file)
        self._ledger.parent = {
            "job_id": block["parent_job_id"],
            "ledger_sha256": block["parent_ledger_sha256"],
            "resumed_from_segment": start,
            "reused_segments": list(range(start)),
        }
        return start

    def _load_replay_reference(self) -> None:
        """Open the original run's ledger for comparison; an unavailable reference is recorded, never fatal."""

        reference = self._replay_reference
        if reference is None:
            return
        base: dict[str, Any] = {
            "note": REPLAY_NOTE,
            "reference_job_id": reference.get("parent_job_id"),
            "reference_ledger_sha256": reference.get("parent_ledger_sha256"),
            "compared_segments": [],
            "diverged_segments": [],
        }
        try:
            ledger = read_ledger(
                Path(str(reference.get("parent_ledger_path"))),
                expected_sha256=str(reference.get("parent_ledger_sha256")),
            )
        except SequenceLedgerError as exc:
            self._ledger.replay = {**base, "status": "reference_unavailable", "reason": str(exc)}
            return
        if ledger.plan_sha256 != self._ledger.plan_sha256:
            self._ledger.replay = {
                **base,
                "status": "not_comparable",
                "reason": "the original run was made for a different sequence plan",
            }
            return
        self._reference_ledger = ledger
        self._ledger.replay = {**base, "status": "comparing"}

    def _run_all(self, source_image_path: str, start: int) -> SequenceOutcome:
        for segment in self._plan.segments[start:]:
            self._check_cancel()
            input_path, anchor = self._input_for(segment, source_image_path)
            try:
                # hold_runtime keeps a StableNew-owned Comfy warm; the one release is in ``execute``'s finally.
                run = self._run_segment(segment, input_path, True)
                # A segment that finished is committed whatever happens next (a cancel arriving now must not
                # lose it): the cancel check is the next iteration's, after the ledger holds this segment.
                artifacts = collect_segment_artifacts(
                    run.raw_result,
                    segment_index=segment.index,
                    expected_frame_count=segment.frame_count,
                    run_dir=self._run_dir,
                    decode_clip=self._decode_clip,
                    cancel_token=self._cancel_token,
                )
                self._outputs[segment.index] = [str(item) for item in run.output_paths]
                self._ledger.segments.append(self._record(segment, artifacts, anchor))
                self._compare_with_reference(self._ledger.segments[-1])
                self._persist()  # the segment is durable before the next one dispatches
            except BaseException:
                self._discard_uncommitted(segment)
                raise
        assembled_path = manifest_path = None
        if self._plan.assembly.enabled:
            self._check_cancel()
            assembled_path, manifest_path = self._assemble_movie()
        self._ledger.state = STATE_COMPLETED
        self._persist()
        return SequenceOutcome(
            ledger=self._ledger,
            ledger_path=self._ledger_path,
            ledger_sha256=self._ledger_sha,
            assembled_path=assembled_path,
            assembly_manifest_path=manifest_path,
            segment_outputs=self._segment_outputs(),
        )

    def _input_for(self, segment: SegmentSpec, source_image_path: str) -> tuple[str, InputAnchor]:
        """The image this segment is conditioned on (verified again here) and how it is recorded."""

        if segment.index == 0:
            source = Path(source_image_path)
            return str(source), InputAnchor(
                policy=ANCHOR_SOURCE,
                basis="source",
                file=FileRecord.of(source, hash_file=self._hash_file),
            )
        if segment.anchor_policy == ANCHOR_PROVIDED:
            assert segment.anchor_path is not None
            anchor = Path(segment.anchor_path)
            if not anchor.is_file() or self._hash_file(anchor) != segment.anchor_sha256:
                raise SequencePlanError(
                    f"segment {segment.index} anchor changed since it was queued: {segment.anchor_path}"
                )
            try:
                require_still(anchor, label=f"segment {segment.index} anchor")
            except SequenceFrameError as exc:
                raise SequencePlanError(str(exc)) from exc
            return str(anchor), InputAnchor(
                policy=ANCHOR_PROVIDED,
                basis="provided",
                file=FileRecord.of(anchor, hash_file=self._hash_file),
            )
        if segment.anchor_policy != ANCHOR_CARRY:
            raise SequencePlanError(f"segment {segment.index} has an unusable anchor policy")
        previous = self._ledger.segments[segment.index - 1]
        record = previous.final_frame.file
        carried = Path(record.path)
        if not carried.is_file() or self._hash_file(carried) != record.sha256:
            raise SequencePlanError(
                f"the carried frame of segment {previous.index} is missing or changed; "
                "the next segment is not dispatched"
            )
        try:
            require_png(carried, label=f"the carried frame of segment {previous.index}")
        except SequenceFrameError as exc:
            raise SequencePlanError(f"{exc}; the next segment is not dispatched") from exc
        basis = previous.final_frame.basis
        assert basis in ANCHOR_BASES
        return str(carried), InputAnchor(
            policy=ANCHOR_CARRY, basis=basis, file=record, from_segment=previous.index
        )

    def _record(
        self, segment: SegmentSpec, artifacts: SegmentArtifacts, anchor: InputAnchor
    ) -> LedgerSegment:
        frames = tuple(
            FileRecord.of(frame, hash_file=self._hash_file) for frame in artifacts.frames
        )
        return LedgerSegment(
            index=segment.index,
            seed=segment.seed,
            expected_frame_count=segment.frame_count,
            frame_count=len(frames),
            workflow_id=segment.workflow_id,
            workflow_version=segment.workflow_version,
            input_anchor=anchor,
            overlap_frames=segment.overlap_frames,
            clip=None
            if artifacts.clip is None
            else FileRecord.of(artifacts.clip, hash_file=self._hash_file),
            manifest=None
            if artifacts.manifest is None
            else FileRecord.of(artifacts.manifest, hash_file=self._hash_file),
            final_frame=artifacts.final_frame,
            frames=frames,
            processing={
                **dict(artifacts.processing),
                "fps": self._plan.fps,
                "frame_count_matches_plan": len(frames) == segment.frame_count,
            },
        )

    def _compare_with_reference(self, committed: LedgerSegment) -> None:
        """A full replay's recomputed final frame against the original run's (recorded, never a failure)."""

        reference = self._reference_ledger
        replay = self._ledger.replay
        if reference is None or replay is None or committed.index >= len(reference.segments):
            return
        original = reference.segments[committed.index].final_frame.file.sha256
        recomputed = committed.final_frame.file.sha256
        compared = [*replay["compared_segments"], committed.index]
        diverged = list(replay["diverged_segments"])
        if original != recomputed:
            diverged.append(committed.index)
        self._ledger.replay = {
            **replay,
            "compared_segments": compared,
            "diverged_segments": diverged,
            "segment_final_frames": {
                **dict(replay.get("segment_final_frames") or {}),
                str(committed.index): {
                    "original_sha256": original,
                    "replayed_sha256": recomputed,
                    "identical": original == recomputed,
                },
            },
        }

    def _discard_uncommitted(self, segment: SegmentSpec) -> None:
        """Remove the staging files of a segment that did not commit (nothing a ledger entry refers to)."""

        if any(item.index == segment.index for item in self._ledger.segments):
            return
        name = f"seg_{segment.index:02d}"
        base = self._run_dir / "sequence"
        for folder in (base / "decoded" / name, base / "color_matched" / name):
            shutil.rmtree(folder, ignore_errors=True)
        for leftover in (base / "anchors" / f"{name}_last.png",):
            leftover.unlink(missing_ok=True)
        for leftover in (base / "native").glob(f"{name}_*") if (base / "native").is_dir() else ():
            leftover.unlink(missing_ok=True)

    def _assemble_movie(self) -> tuple[str, str]:
        """Encode the assembly frames (overlap dropped, optionally colour-matched) with the ASM-332 engine."""

        frames: list[Path] = []
        used: list[dict[str, Any]] = []
        reference = Path(self._ledger.segments[0].frames[0].path)
        reference_sha = self._hash_file(reference)
        matching = self._plan.color_match.enabled
        for position, ledger_segment in enumerate(self._ledger.segments):
            spec = self._plan.segments[ledger_segment.index]
            originals = [Path(record.path) for record in ledger_segment.frames]
            kept = trim_overlap(originals, spec.overlap_frames)
            transformed = matching and ledger_segment.index > 0
            if transformed:
                records = match_segment_colors(
                    kept,
                    reference,
                    self._run_dir
                    / "sequence"
                    / "color_matched"
                    / f"seg_{ledger_segment.index:02d}",
                    hash_file=self._hash_file,
                    cancel_token=self._cancel_token,
                )
                kept = [Path(record.path) for record in records]
            else:
                records = []
            self._ledger.segments[position] = replace(
                ledger_segment,
                color_matched=tuple(records),
                color_match=None
                if not matching
                else {
                    "algorithm": self._plan.color_match.algorithm,
                    "reference": self._plan.color_match.reference,
                    "reference_sha256": reference_sha,
                    "transformed": transformed,
                },
            )
            frames.extend(kept)
            used.append(
                {
                    "segment": ledger_segment.index,
                    "origin": ledger_segment.origin,
                    "frames_used": len(kept),
                    "frames_dropped": len(originals) - len(kept),
                    "color_matched": transformed,
                }
            )
        outcome = self._assemble(
            frames,
            self._plan,
            run_dir=self._run_dir,
            job_id=self._job_id,
            cancel_token=self._cancel_token,
        )
        self._ledger.assembly = {
            "output_path": str(outcome.output_path),
            "output_sha256": outcome.output_sha256,
            "manifest_path": str(outcome.manifest_path),
            "total_frames": outcome.timeline.total_frames,
            "fps": outcome.timeline.fps,
            "segments": used,
            "color_match_reference": str(reference) if matching else None,
        }
        return str(outcome.output_path), str(outcome.manifest_path)

    def _segment_outputs(self) -> list[str]:
        ordered: list[str] = []
        for index in sorted(self._outputs):
            ordered.extend(self._outputs[index])
        for ledger_segment in self._ledger.segments:
            if ledger_segment.index not in self._outputs and ledger_segment.clip is not None:
                ordered.append(ledger_segment.clip.path)  # a resumed prefix's copied clip
        return ordered

    # ------------------------------------------------------------------ plumbing

    def _check_cancel(self) -> None:
        if self._cancel_token is not None and self._cancel_token.is_cancelled():
            raise CancellationError("the video sequence was cancelled")

    def _persist(self) -> None:
        self._ledger_sha = write_ledger(self._ledger_path, self._ledger)
        if self._on_persist is not None:
            self._on_persist(self._ledger_path, self._ledger_sha, self._ledger)

    def _persist_quietly(self) -> None:
        try:
            self._persist()
        except Exception:  # noqa: BLE001 - never mask the error that ended the sequence
            logger.exception("could not write the final sequence ledger")

    def _release_once(self) -> None:
        if self._release_runtime is None:
            return
        try:
            release = self._release_runtime()
        except Exception as exc:  # noqa: BLE001 - one attempt; a failed release is recorded, never raised
            logger.exception("sequence-end runtime release failed")
            release = {
                "released": False,
                "error": f"release raised {type(exc).__name__}: {exc}"[:500],
            }
        if release is not None:
            self._ledger.runtime_release = dict(release)
            self._persist_quietly()


def _terminal_state(exc: BaseException) -> str:
    if isinstance(exc, CancellationError):
        return STATE_CANCELLED
    if isinstance(exc, (KeyboardInterrupt, SystemExit, GeneratorExit)):
        return STATE_INTERRUPTED
    return STATE_FAILED


def sequence_artifact_payload(outcome: SequenceOutcome, plan: SequencePlan) -> dict[str, Any]:
    """The run-metadata record of a finished sequence (the shape history and the legacy readers already know)."""

    segments = outcome.ledger.segments
    return {
        "sequence_id": plan.sequence_id,
        "job_id": outcome.ledger.job_id,
        "plan_sha256": outcome.ledger.plan_sha256,
        "total_segments": len(plan.segments),
        "completed_segments": len(segments),
        "is_complete": len(segments) == len(plan.segments),
        "sequence_manifest_path": str(outcome.ledger_path),
        "ledger_path": str(outcome.ledger_path),
        "ledger_sha256": outcome.ledger_sha256,
        "ledger_state": outcome.ledger.state,
        "segment_provenance": [
            {
                "segment_index": segment.index,
                "seed": segment.seed,
                "frame_count": segment.frame_count,
                "origin": segment.origin,
                "primary_output_path": None if segment.clip is None else segment.clip.path,
                "manifest_path": None if segment.manifest is None else segment.manifest.path,
                "final_frame": segment.final_frame.to_dict(),
                "carry_forward_policy": plan.segments[segment.index].anchor_policy,
            }
            for segment in segments
        ],
        "all_output_paths": outcome.output_paths,
        "assembled_video": dict(outcome.ledger.assembly or {}) or None,
        "runtime_release": dict(outcome.ledger.runtime_release or {}) or None,
        "replay": dict(outcome.ledger.replay or {}) or None,
    }


def parse_sequence_plan(sequence_config: Mapping[str, Any], *, stage_name: str) -> SequencePlan:
    """The frozen plan of a stage config's ``sequence_metadata``, validated again at run time.

    A block in the retired pre-SEQ-330 shape (``total_segments``) was never produced by any admission path and cannot
    be executed; it is refused with a readable message, and the record itself stays readable."""

    if "segments" not in sequence_config:
        raise SequencePlanError(
            "this job carries a sequence block from before PR-VID-SEQ-330 (total_segments), which can no longer be "
            "executed; re-admit the sequence so it is frozen as a typed plan"
        )
    plan = SequencePlan.from_dict(sequence_config)
    errors = plan.validate()
    if errors:
        raise SequencePlanError("; ".join(errors))
    if plan.stage != stage_name:
        raise SequencePlanError(
            f"the sequence plan is for {plan.stage} but the job's stage is {stage_name}"
        )
    return plan


def parse_replay_block(raw: Any) -> dict[str, Any] | None:
    """The ``sequence_replay_of`` block of a stage config (``None`` when absent); a malformed one is refused."""

    if raw is None:
        return None
    if not isinstance(raw, Mapping) or set(raw) != REPLAY_BLOCK_KEYS:
        raise SequencePlanError(
            f"{REPLAY_KEY} must name exactly {', '.join(sorted(REPLAY_BLOCK_KEYS))}"
        )
    return {key: raw[key] for key in REPLAY_BLOCK_KEYS}


def run_sequence_stage(
    *,
    runner: Any,
    stage_name: str,
    njr: Any,
    current_stage_paths: list[str],
    sequence_config: Mapping[str, Any],
    run_dir: Path,
    cancel_token: CancelToken | None,
    variants: list[dict[str, Any]],
    metadata: dict[str, Any],
    survivor_telemetry: Any = None,
    hash_file: FileHasher = sha256_of,
) -> list[str]:
    """What ``PipelineRunner._execute_sequence`` does: run the plan's segments inside the one job and return its outputs."""

    from src.video.video_artifact_helpers import build_video_artifact_bundle

    plan = parse_sequence_plan(sequence_config, stage_name=stage_name)
    config_dict = runner._stage_config_dict_for_video(njr, stage_name)
    # Continuity and plan-origin provenance: the NJR's own, else what the plan froze at admission.
    continuity_link = runner._resolve_continuity_link(
        njr, metadata=metadata, sequence_config=sequence_config
    )
    plan_origin = runner._resolve_plan_origin(
        njr, metadata=metadata, sequence_config=sequence_config
    )
    if continuity_link:
        metadata["continuity"] = dict(continuity_link)
    if plan_origin:
        metadata["plan_origin"] = dict(plan_origin)
    resume = config_dict.get("sequence_resume")
    replay = parse_replay_block(config_dict.get(REPLAY_KEY))
    if resume is not None and replay is not None:
        raise SequencePlanError("a job is either a resume or a full replay, never both")
    if not current_stage_paths:
        raise SequencePlanError("a sequence needs the job's source image")

    def run_segment(segment: SegmentSpec, input_path: str, hold: bool) -> SegmentRun:
        sink: list[Any] = []
        capture = (
            {
                "sequence_capture": {
                    "native_final_frame_path": str(
                        run_dir / "sequence" / "native" / f"seg_{segment.index:02d}_native_last.png"
                    )
                }
            }
            if plan.stage == STAGE_SVD_NATIVE
            else None
        )
        paths = runner._execute_video_stage(
            stage_name=stage_name,
            njr=njr,
            current_stage_paths=[input_path],
            prompt=segment.prompt or str(getattr(njr, "positive_prompt", "") or ""),
            negative_prompt=segment.negative_prompt
            or str(getattr(njr, "negative_prompt", "") or ""),
            run_dir=run_dir,
            cancel_token=cancel_token,
            variants=variants,
            metadata=metadata,
            survivor_telemetry=survivor_telemetry,
            stage_config_overrides=segment_overrides(plan, segment),
            request_job_id=f"{njr.job_id}_seg{segment.index:02d}",
            hold_runtime=hold,
            context_extra=capture,
            result_sink=sink,
        )
        if not sink:
            raise RuntimeError(f"segment {segment.index} produced no result")
        return SegmentRun(raw_result=sink[-1].to_variant_payload(), output_paths=tuple(paths))

    def release_runtime() -> Mapping[str, Any] | None:
        intent = runner._video_resolver.build_intent(stage_name, config_dict, has_source_image=True)
        backend = runner._video_resolver.resolve(stage_name, intent)
        release = getattr(backend, "release_for_sequence", None)
        if release is None:
            return None
        released: Mapping[str, Any] = release(
            [
                (item.workflow_id, item.workflow_version)
                for item in plan.segments
                if item.workflow_id
            ]
        )
        return released

    executor = VideoSequenceExecutor(
        plan=plan,
        job_id=str(njr.job_id),
        run_dir=run_dir,
        run_segment=run_segment,
        release_runtime=release_runtime,
        cancel_token=cancel_token,
        hash_file=hash_file,
        replay_reference=replay,
        on_persist=lambda path, sha, ledger: metadata.__setitem__(
            "sequence_artifact",
            {
                "sequence_id": plan.sequence_id,
                "plan_sha256": ledger.plan_sha256,
                "ledger_path": str(path),
                "ledger_sha256": sha,
                "ledger_state": ledger.state,
                "completed_segments": ledger.completed_prefix,
                "next_segment": ledger.next_segment,
                "total_segments": len(plan.segments),
            },
        ),
    )
    outcome = executor.execute(source_image_path=current_stage_paths[0], resume=resume)
    artifact = sequence_artifact_payload(outcome, plan)
    if continuity_link:
        artifact["continuity_link"] = dict(continuity_link)
    if plan_origin:
        artifact["plan_origin"] = dict(plan_origin)
    metadata["sequence_artifact"] = artifact
    if outcome.assembled_path:
        bundle = build_video_artifact_bundle(
            stage=stage_name,
            backend_id=str(metadata.get("video_primary_backend_id") or stage_name),
            primary_path=outcome.assembled_path,
            output_paths=[outcome.assembled_path],
            video_paths=[outcome.assembled_path],
            gif_paths=[],
            frame_paths=[],
            manifest_path=outcome.assembly_manifest_path,
            manifest_paths=[
                path for path in (outcome.assembly_manifest_path, str(outcome.ledger_path)) if path
            ],
            thumbnail_path=None,
            source_image_path=current_stage_paths[0],
        )
        metadata["assembled_video_artifact"] = dict(bundle)
        metadata.setdefault("video_artifacts", {})["assembled_video"] = dict(bundle)
        primary = dict(metadata.get("video_primary_artifact") or {})
        primary.update(
            primary_path=outcome.assembled_path,
            output_paths=outcome.output_paths,
            video_paths=[outcome.assembled_path],
        )
        metadata["video_primary_artifact"] = primary
    return outcome.output_paths


__all__ = [
    "ALLOWED_OVERRIDES",
    "REPLAY_KEY",
    "SegmentCallback",
    "SegmentRun",
    "SequenceOutcome",
    "VideoSequenceExecutor",
    "apply_stage_overrides",
    "parse_replay_block",
    "parse_sequence_plan",
    "run_sequence_stage",
    "segment_overrides",
    "sequence_artifact_payload",
]
