"""Video eval suites on the Video Workflow controller (PR-VID-EVAL-320).

A mixin so ``VideoWorkflowController`` keeps one surface for the Video Workflow tab while its own module
stays small. It coordinates only: the NJRs come from the existing builders (``VideoWorkflowNjrBuilder`` and
``SVDController.build_admitted_njr``), admission goes through ``JobService.submit_njrs`` once
(``src/video/video_eval_run.py``), and the report is a post-execution consumer
(``src/video/video_eval_report.py``). Every public method is safe to call from a worker thread.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.video.svd_config import SVDConfig
from src.video.svd_preprocess import read_svd_source_size
from src.video.svd_target import select_svd_target_size
from src.video.video_eval_report import EvalReport, build_eval_report
from src.video.video_eval_run import BuiltEvalJob, EvalAdmission, EvalRunPlan, VideoEvalRunService
from src.video.video_eval_suite import (
    ARM_BACKEND_SVD,
    ARM_BACKEND_WORKFLOW,
    EvalArm,
    EvalCase,
    load_eval_suite,
)
from src.video.video_workflow_njr_builder import VideoWorkflowNjrBuilder


class VideoEvalControllerMixin:
    """Requires ``_app_controller``, ``_njr_builder``, ``_job_service()`` and ``build_default_form_state()``."""

    _app_controller: Any
    _njr_builder: VideoWorkflowNjrBuilder

    def _job_service(self) -> Any:  # provided by the controller
        raise NotImplementedError

    def build_default_form_state(self) -> dict[str, Any]:  # provided by the controller
        raise NotImplementedError

    def _eval_service(self) -> VideoEvalRunService:
        return VideoEvalRunService(
            builders={
                ARM_BACKEND_WORKFLOW: self._build_workflow_eval_job,
                ARM_BACKEND_SVD: self._build_svd_eval_job,
            }
        )

    def preview_eval_run(self, suite_path: str | Path) -> EvalRunPlan:
        """Load a suite and build every (case, arm) NJR; queues nothing."""

        return self._eval_service().plan(load_eval_suite(suite_path))

    def submit_eval_run(self, plan: EvalRunPlan) -> EvalAdmission:
        """Admit a previewed eval run through ONE ``JobService.submit_njrs`` call."""

        output_dir = getattr(self._app_controller, "output_dir", None) or "output"
        return self._eval_service().admit(plan, self._job_service(), output_root=output_dir)

    def build_eval_report(
        self, run_dir: str | Path, *, cancel: Any = None, show_prompts: bool = True
    ) -> EvalReport:
        """Measure an admitted run's finished clips and write its contact sheet."""

        repository = getattr(self._job_service(), "history_store", None)
        if not callable(getattr(repository, "get_job", None)):
            raise RuntimeError("The job history is not available to build an eval report.")
        return build_eval_report(run_dir, repository, cancel=cancel, show_prompts=show_prompts)

    def _build_workflow_eval_job(self, case: EvalCase, arm: EvalArm, seed: int) -> BuiltEvalJob:
        form = self.build_default_form_state()
        form.update(dict(arm.overrides))
        form.update(prompt=case.prompt, negative_prompt=case.negative_prompt, seed=str(seed))
        frozen = self._njr_builder.freeze_inputs(case.image_path, form)
        built = self._njr_builder.build_job(form, frozen)
        return BuiltEvalJob(njr=built.njr, seed=built.seed, frame_count=built.frame_count)

    def _build_svd_eval_job(self, case: EvalCase, arm: EvalArm, seed: int) -> BuiltEvalJob:
        from src.controller.svd_controller import SVDController

        svd = SVDController(app_controller=self._app_controller)
        merged = deep_merge(svd.build_default_config().to_dict(), arm.overrides)
        if "target_width" not in dict(arm.overrides.get("preprocess") or {}):
            width, height = select_svd_target_size(*read_svd_source_size(case.image_path))
            merged.setdefault("preprocess", {}).update(target_width=width, target_height=height)
        merged.setdefault("inference", {})["seed"] = seed
        config = SVDConfig.from_dict(merged)
        njr = svd.build_admitted_njr(source_image_path=case.image_path, config=config)
        return BuiltEvalJob(njr=njr, seed=seed, frame_count=config.inference.num_frames)


def deep_merge(base: Mapping[str, Any], overrides: Mapping[str, Any]) -> dict[str, Any]:
    """``base`` with ``overrides`` applied; nested mappings merge, everything else replaces."""

    merged = dict(base)
    for key, value in overrides.items():
        current = merged.get(key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            merged[key] = deep_merge(current, value)
        else:
            merged[key] = value
    return merged


__all__ = ["VideoEvalControllerMixin", "deep_merge"]
