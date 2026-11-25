"""Plan and admit one video eval run on the canonical path (PR-VID-EVAL-320).

``plan`` turns a suite into one NJR per (case, arm) with the arm's own builder (the Video Workflow NJR
builder or the native SVD controller), all with the suite seed so arms see identical inputs. ``admit``
re-checks the source images and crosses ``JobService.submit_njrs`` exactly once. Eval membership lives in
a run manifest (``stablenew.video-eval-run.v1``) beside the report, never in the NJR: the jobs are
ordinary jobs that replay, retry and appear in History like any other.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.controller.submission_policy_v26 import SubmissionPolicy
from src.utils.atomic_io import atomic_write_json
from src.video.video_eval_motion import MotionFacts, motion_facts_from_njr
from src.video.video_eval_suite import (
    EvalArm,
    EvalCase,
    EvalSuite,
    file_sha256,
)

RUN_SCHEMA = "stablenew.video-eval-run.v1"
RUN_MANIFEST_NAME = "run.json"
EVAL_OUTPUT_FOLDER = "video_eval"


@dataclass(frozen=True)
class BuiltEvalJob:
    """What an arm builder returns for one case."""

    njr: Any
    seed: int | None
    #: For a sequence, the total generated frames across segments.
    frame_count: int | None = None
    #: For a sequence case, each segment's frozen seed (segment 0's is ``seed``); empty for a single clip.
    segment_seeds: tuple[int, ...] = ()


#: ``(case, arm, seed) -> BuiltEvalJob``; raises ``ValueError``/``RuntimeError`` to refuse the case.
EvalJobBuilder = Callable[[EvalCase, EvalArm, int], BuiltEvalJob]


@dataclass(frozen=True)
class EvalJobPlan:
    case_id: str
    arm_id: str
    backend: str
    job_id: str
    seed: int | None
    frame_count: int | None
    njr: Any = field(repr=False, compare=False)
    segment_seeds: tuple[int, ...] = ()
    #: Driving context frozen into the compiled NJR (motion cases only).
    motion: MotionFacts | None = None
    #: ``(label, path, sha256)`` of every input the preview froze; admission re-hashes each one.
    inputs: tuple[tuple[str, str, str], ...] = ()


@dataclass(frozen=True)
class EvalRunPlan:
    run_id: str
    suite: EvalSuite
    jobs: tuple[EvalJobPlan, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def eligible(self) -> bool:
        return not self.errors and len(self.jobs) == self.suite.job_count

    @property
    def experimental_arms(self) -> tuple[str, ...]:
        return tuple(arm.arm_id for arm in self.suite.arms if arm.requests_experimental)

    def summary(self) -> str:
        suite = self.suite
        lines = [
            f"Eval suite {suite.suite_id}: {len(suite.cases)} cases x {len(suite.arms)} arms = "
            f"{suite.job_count} jobs, seed {suite.seed}, baseline arm {suite.baseline_arm_id}."
        ]
        sequences = [case for case in suite.cases if case.is_sequence]
        if sequences:
            segments = sum(len(case.segments) for case in sequences)
            lines.append(
                f"  {len(sequences)} case(s) are multi-segment sequences ({segments} segments per arm, "
                "segment i seeded with the suite seed + i); each runs as one job rated as a whole."
            )
        motion_cases = [case for case in suite.cases if case.motion is not None]
        if motion_cases:
            drivers = {case.motion.driving_sha256 for case in motion_cases if case.motion}
            sources = {case.image_sha256 for case in motion_cases}
            lines.append(
                f"  {len(motion_cases)} case(s) bind a driving-motion reference "
                f"({len(drivers)} distinct driver(s), {len(sources)} distinct source image(s)); "
                "the driver is part of every job and is never dropped."
            )
            lines.extend(f"  - {note}" for note in preparation_disclosures(self.jobs))
        for arm in suite.arms:
            flag = (
                " (experimental workflow, opted in by the suite)"
                if arm.requests_experimental
                else ""
            )
            lines.append(f"  arm {arm.arm_id}: {arm.label} [{arm.backend}]{flag}")
        if self.errors:
            lines.append("Not queueable:")
            lines.extend(f"  - {error}" for error in self.errors)
        return "\n".join(lines)


@dataclass(frozen=True)
class EvalAdmission:
    run_id: str
    run_dir: Path
    manifest_path: Path
    job_ids: tuple[str, ...]


class EvalRunRefused(RuntimeError):
    """Nothing was queued; the message says why."""


def _frozen_inputs(
    case: EvalCase, njr: Any
) -> tuple[MotionFacts | None, tuple[tuple[str, str, str], ...]]:
    """What the compiled NJR really froze for a motion case, checked against the case, plus the hashes to re-verify.

    The NJR is the authority: a driver that is missing from it (a silently dropped reference), a different driver, a
    different motion prompt, or a preparation the case did not ask for refuses the job."""

    binding = case.motion
    if binding is None:
        return None, ()
    facts = motion_facts_from_njr(njr)
    if facts is None:
        raise ValueError(
            "the compiled job carries no driving video; the case's driving reference is never dropped"
        )
    if facts.driver_original_sha256 != binding.driving_sha256:
        raise ValueError("the compiled job froze a different driving video than the case binds")
    if facts.motion_prompt != binding.motion_prompt:
        raise ValueError("the compiled job froze a different motion prompt than the case")
    if facts.frame_count is None or facts.fps is None:
        raise ValueError(
            "the compiled job froze no output length or rate, so its motion cannot be compared"
        )
    if binding.library_asset is not None and (
        facts.library_asset is None
        or facts.library_asset.get("asset_id") != binding.library_asset.get("asset_id")
    ):
        raise ValueError("the compiled job lost the case's Motion Library binding")
    if binding.library_asset is None and facts.library_asset is not None:
        raise ValueError("the compiled job claims a Motion Library asset the case does not bind")
    if (binding.preparation_mode == "workflow_prepared") != facts.prepared:
        raise ValueError(
            "the compiled job's driving preparation differs from the case's request "
            f"({binding.preparation_mode})"
        )
    inputs: list[tuple[str, str, str]] = []
    first = list(getattr(njr, "input_image_paths", ()) or ())
    if first:
        inputs.append(("prepared source image", str(first[0]), file_sha256(Path(str(first[0])))))
    inputs.append(("driving video", facts.driver_original_path, facts.driver_original_sha256))
    if facts.prepared:
        inputs.append(
            ("prepared driving video", facts.driver_effective_path, facts.driver_effective_sha256)
        )
    return facts, tuple(inputs)


def preparation_disclosures(jobs: tuple[EvalJobPlan, ...]) -> list[str]:
    """Plain statements where arms of one case consume different prepared driving derivatives (never hidden)."""

    notes: list[str] = []
    for case_id in dict.fromkeys(job.case_id for job in jobs):
        rows = [job for job in jobs if job.case_id == case_id and job.motion is not None]
        contracts = {
            (
                job.motion.workflow_id,
                job.motion.workflow_version,
                job.motion.frame_count,
                job.motion.ordered_frames_sha256,
            ): job.arm_id
            for job in rows
            if job.motion is not None
        }
        if len(contracts) > 1:
            notes.append(
                f"case {case_id}: arms use {len(contracts)} different driving contracts "
                "(workflow, version, length or prepared frames differ) and are not identical inputs: "
                + "; ".join(
                    f"{arm}={workflow} {version} {frames} frames"
                    for (workflow, version, frames, _digest), arm in contracts.items()
                )
            )
    return notes


class VideoEvalRunService:
    def __init__(self, *, builders: dict[str, EvalJobBuilder]) -> None:
        self._builders = dict(builders)

    def plan(self, suite: EvalSuite) -> EvalRunPlan:
        """Build every (case, arm) NJR, or report every case/arm that cannot be built. All or none."""

        run_id = f"{datetime.now(UTC):%Y%m%d_%H%M%S}_{suite.suite_id}_{uuid.uuid4().hex[:8]}"
        jobs: list[EvalJobPlan] = []
        errors: list[str] = []
        for arm in suite.arms:
            builder = self._builders.get(arm.backend)
            if builder is None:
                errors.append(f"arm {arm.arm_id}: no builder for backend {arm.backend}")
                continue
            for case in suite.cases:
                try:
                    built = builder(case, arm, suite.seed)
                    facts, inputs = _frozen_inputs(case, built.njr)
                except (ValueError, RuntimeError, OSError, KeyError) as exc:
                    errors.append(f"{case.case_id} x {arm.arm_id}: {exc}")
                    continue
                jobs.append(
                    EvalJobPlan(
                        case_id=case.case_id,
                        arm_id=arm.arm_id,
                        backend=arm.backend,
                        job_id=str(built.njr.job_id),
                        seed=built.seed,
                        frame_count=built.frame_count,
                        njr=built.njr,
                        segment_seeds=tuple(built.segment_seeds),
                        motion=facts,
                        inputs=inputs,
                    )
                )
        return EvalRunPlan(run_id=run_id, suite=suite, jobs=tuple(jobs), errors=tuple(errors))

    def admit(
        self,
        plan: EvalRunPlan,
        job_service: Any,
        *,
        output_root: str | Path,
        require_active: Callable[[], None] | None = None,
    ) -> EvalAdmission:
        """Re-verify the source images, write the run manifest, then submit every job once."""

        if not plan.eligible:
            raise EvalRunRefused(
                "This eval run is not queueable; nothing was queued.\n" + plan.summary()
            )
        for case in plan.suite.cases:
            try:
                current = file_sha256(case.image_path)
            except OSError as exc:
                raise EvalRunRefused(
                    f"case {case.case_id}: cannot read {case.image_path}: {exc}"
                ) from exc
            if current != case.image_sha256:
                raise EvalRunRefused(
                    f"case {case.case_id}: {case.image_path.name} changed after the preview; "
                    "preview the suite again. Nothing was queued."
                )
        for job in plan.jobs:
            for label, path, frozen_sha in job.inputs:
                try:
                    current = file_sha256(Path(path))
                except OSError as exc:
                    raise EvalRunRefused(
                        f"{job.case_id} x {job.arm_id}: the {label} is no longer readable ({path}): {exc}. "
                        "Preview the suite again. Nothing was queued."
                    ) from exc
                if current != frozen_sha:
                    raise EvalRunRefused(
                        f"{job.case_id} x {job.arm_id}: the {label} changed after the preview "
                        f"({Path(path).name}); it is not the input that was validated. Preview the suite "
                        "again. Nothing was queued."
                    )
        submit = getattr(job_service, "submit_njrs", None)
        if not callable(submit):
            raise EvalRunRefused("JobService.submit_njrs is unavailable; nothing was queued.")

        run_dir = Path(output_root).expanduser() / EVAL_OUTPUT_FOLDER / plan.run_id
        manifest_path = run_dir / RUN_MANIFEST_NAME
        # The manifest is written first so an admitted run can always be reported; it is removed
        # again if admission fails before any job exists.
        if require_active is not None:
            require_active()
        atomic_write_json(manifest_path, build_run_manifest(plan), indent=2, sort_keys=True)
        expected = [job.job_id for job in plan.jobs]
        try:
            if require_active is not None:
                require_active()
            submitted = [
                str(job_id)
                for job_id in (submit([job.njr for job in plan.jobs], SubmissionPolicy()) or [])
            ]
        except Exception as exc:
            # Native admission is atomic. A notification can still fail after the commit.
            # Keep the manifest whenever the repository confirms admission or is unavailable.
            lookup = getattr(getattr(job_service, "history_store", None), "get_job_entries", None)
            admitted = lookup(expected) if callable(lookup) else {}
            if not admitted:
                manifest_path.unlink(missing_ok=True)
                raise EvalRunRefused(f"Queue admission failed; nothing was queued: {exc}") from exc
            submitted = [job_id for job_id in expected if job_id in admitted]
        if submitted != expected:
            raise EvalRunRefused(
                f"Admission returned {len(submitted)} job id(s) for {len(expected)} eval jobs; "
                f"check Queue / History. The run manifest is kept at {manifest_path}."
            )
        return EvalAdmission(
            run_id=plan.run_id,
            run_dir=run_dir,
            manifest_path=manifest_path,
            job_ids=tuple(submitted),
        )


def _job_motion_record(job: EvalJobPlan) -> dict[str, Any]:
    assert job.motion is not None
    record = job.motion.to_record()
    prepared_source = next(
        (sha for label, _path, sha in job.inputs if label == "prepared source image"), None
    )
    if prepared_source:
        record["prepared_source_sha256"] = prepared_source
    return record


def build_run_manifest(plan: EvalRunPlan) -> dict[str, Any]:
    suite = plan.suite
    return {
        "schema": RUN_SCHEMA,
        "run_id": plan.run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "suite": {
            "suite_id": suite.suite_id,
            "schema": suite.schema,
            "path": str(suite.path) if suite.path is not None else None,
            "sha256": suite.sha256,
            "description": suite.description,
            "seed": suite.seed,
            "baseline_arm": suite.baseline_arm_id,
        },
        "cases": [
            {
                "case_id": case.case_id,
                "image": str(case.image_path),
                "image_sha256": case.image_sha256,
                "prompt": case.prompt,
                "negative_prompt": case.negative_prompt,
                "tags": list(case.tags),
                **(
                    {
                        "segments": [
                            {"prompt": segment.prompt, "frame_count": segment.frame_count}
                            for segment in case.segments
                        ]
                    }
                    if case.is_sequence
                    else {}
                ),
                **({"motion": case.motion.to_record()} if case.motion is not None else {}),
            }
            for case in suite.cases
        ],
        "arms": [
            {
                "arm_id": arm.arm_id,
                "label": arm.label,
                "backend": arm.backend,
                "experimental": arm.requests_experimental,
                "overrides": dict(arm.overrides),
            }
            for arm in suite.arms
        ],
        "jobs": [
            {
                "case_id": job.case_id,
                "arm_id": job.arm_id,
                "backend": job.backend,
                "job_id": job.job_id,
                "seed": job.seed,
                "frame_count": job.frame_count,
                **({"segment_seeds": list(job.segment_seeds)} if job.segment_seeds else {}),
                **({"motion": _job_motion_record(job)} if job.motion is not None else {}),
            }
            for job in plan.jobs
        ],
    }


__all__ = [
    "EVAL_OUTPUT_FOLDER",
    "RUN_MANIFEST_NAME",
    "RUN_SCHEMA",
    "BuiltEvalJob",
    "EvalAdmission",
    "EvalJobBuilder",
    "EvalJobPlan",
    "EvalRunPlan",
    "EvalRunRefused",
    "VideoEvalRunService",
    "build_run_manifest",
]
