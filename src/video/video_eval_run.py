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
    frame_count: int | None = None


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
                    )
                )
        return EvalRunPlan(run_id=run_id, suite=suite, jobs=tuple(jobs), errors=tuple(errors))

    def admit(
        self, plan: EvalRunPlan, job_service: Any, *, output_root: str | Path
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
        submit = getattr(job_service, "submit_njrs", None)
        if not callable(submit):
            raise EvalRunRefused("JobService.submit_njrs is unavailable; nothing was queued.")

        run_dir = Path(output_root).expanduser() / EVAL_OUTPUT_FOLDER / plan.run_id
        manifest_path = run_dir / RUN_MANIFEST_NAME
        # The manifest is written first so an admitted run can always be reported; it is removed
        # again if admission fails before any job exists.
        atomic_write_json(manifest_path, build_run_manifest(plan), indent=2, sort_keys=True)
        expected = [job.job_id for job in plan.jobs]
        try:
            submitted = [
                str(job_id)
                for job_id in (submit([job.njr for job in plan.jobs], SubmissionPolicy()) or [])
            ]
        except Exception as exc:
            manifest_path.unlink(missing_ok=True)
            raise EvalRunRefused(f"Queue admission failed; nothing was queued: {exc}") from exc
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


def build_run_manifest(plan: EvalRunPlan) -> dict[str, Any]:
    suite = plan.suite
    return {
        "schema": RUN_SCHEMA,
        "run_id": plan.run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "suite": {
            "suite_id": suite.suite_id,
            "path": str(suite.path),
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
