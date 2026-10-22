from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from src.controller.ports.default_runtime_ports import DefaultWorkflowRegistryPort
from src.controller.ports.runtime_ports import WorkflowRegistryPort
from src.controller.submission_policy_v26 import SubmissionPolicy
from src.controller.video_eval_controller import VideoEvalControllerMixin
from src.controller.video_preflight_controller import VideoPreflightControllerMixin
from src.controller.video_recent_outputs_controller import VideoRecentOutputsControllerMixin
from src.state.output_routing import OUTPUT_ROUTE_REPROCESS
from src.video.driving_video_inspection import inspect_driving_video as _inspect_video
from src.video.motion_source_preparation import prepare_for_form
from src.video.video_workflow_batch import (
    BatchAdmissionResult,
    BatchPlan,
    BatchSource,
    SourceSelection,
    VideoWorkflowBatchService,
    scan_folder,
    select_sources,
)
from src.video.video_workflow_experiment import (
    ExperimentAdmissionResult,
    ExperimentPlan,
    VideoWorkflowExperimentService,
)
from src.video.video_workflow_intent import (
    EXPERIMENTAL_OPT_IN_FIELD,
    form_visibility,
)
from src.video.video_workflow_njr_builder import VideoWorkflowNjrBuilder
from src.video.workflow_controls import operator_controls_projection
from src.video.workflow_frame_count import frame_count_projection
from src.video.workflow_motion_guidance import motion_readiness_projection
from src.video.workflow_picker import recommended_workflow_id
from src.video.workflow_preflight import PreflightProbes
from src.video.workflow_registry import latest_spec_per_workflow
from src.video.workflow_source_preparation import preview_declared_workflow_source


class VideoWorkflowController(
    VideoEvalControllerMixin, VideoPreflightControllerMixin, VideoRecentOutputsControllerMixin
):
    """Queue-backed controller surface for workflow-driven video jobs."""

    def __init__(
        self,
        *,
        app_controller,
        workflow_registry: WorkflowRegistryPort | None = None,
        preflight_probes: Callable[[], PreflightProbes] | None = None,
    ) -> None:
        self._app_controller = app_controller
        self._preflight_probes = preflight_probes
        self._workflow_registry = workflow_registry or DefaultWorkflowRegistryPort()
        self._njr_builder = VideoWorkflowNjrBuilder(
            workflow_registry=self._workflow_registry,
            output_dir_provider=lambda: getattr(self._app_controller, "output_dir", None),
        )
        self._experiments = VideoWorkflowExperimentService(self._njr_builder)
        self._batches = VideoWorkflowBatchService(self._njr_builder)

    def list_workflow_specs(self) -> list[dict[str, Any]]:
        specs = latest_spec_per_workflow(
            list(self._workflow_registry.list_specs_for_backend("comfy"))
        )
        records: list[dict[str, Any]] = []
        for spec in specs:
            records.append(
                {
                    "workflow_id": spec.workflow_id,
                    "workflow_version": spec.workflow_version,
                    "backend_id": spec.backend_id,
                    "display_name": spec.display_name,
                    "description": spec.description,
                    "governance_state": spec.governance_state,
                    "pinned_revision": spec.pinned_revision,
                    "capability_tags": list(spec.capability_tags),
                    "dependency_specs": [
                        dependency.to_dict() for dependency in spec.dependency_specs
                    ],
                    "experimental": bool(getattr(spec, "is_experimental", False)),
                    "required_inputs": list(getattr(spec, "required_input_names", ())),
                    "accepted_controls": list(getattr(spec, "accepted_controls", ())),
                    "form_visibility": form_visibility(spec),
                    "frame_count": frame_count_projection(spec),
                    "operator_controls": operator_controls_projection(spec),
                    "motion_readiness": motion_readiness_projection(spec),
                    "operator_projection": dict(
                        (getattr(spec, "backend_defaults", None) or {}).get("operator_projection")
                        or {}
                    ),
                }
            )
        return records

    def build_default_form_state(self) -> dict[str, Any]:
        specs = self.list_workflow_specs()
        # An approved workflow, never an experimental one.
        recommended = recommended_workflow_id(specs)
        default_workflow = next(
            (spec for spec in specs if spec["workflow_id"] == recommended),
            specs[0] if specs else {},
        )
        return {
            "workflow_id": str(default_workflow.get("workflow_id") or ""),
            "workflow_version": str(default_workflow.get("workflow_version") or ""),
            "end_anchor_path": "",
            "mid_anchor_paths": [],
            "pose_video_path": "",
            "prompt": "",
            "negative_prompt": "",
            "motion_profile": "gentle",
            "seed": "",
            "frame_count": "",  # empty means the selected workflow's declared default
            "camera_intent": {
                "preset": "none",
                "strength": 0.35,
            },
            "controlnet": {
                "model": "depth",
                "weight": 1.0,
                "guidance_start": 0.0,
                "guidance_end": 1.0,
            },
            "depth_input": {
                "mode": "none",
                "path": "",
            },
            "output_route": OUTPUT_ROUTE_REPROCESS,
            EXPERIMENTAL_OPT_IN_FIELD: False,  # never defaulted on, never persisted globally
            "continuity_pack_id": "",
            "continuity_pack_name": "",
            "continuity_pack_summary": None,
        }

    def validate_source_image(self, path: str | Path) -> tuple[bool, str | None]:
        return self._njr_builder.validate_source_image(path)

    def validate_form_data(self, form_data: dict[str, Any]) -> tuple[bool, str | None]:
        return self._njr_builder.validate_form_data(form_data)

    def _job_service(self) -> Any:
        job_service = getattr(self._app_controller, "job_service", None)
        if job_service is None:
            raise RuntimeError("App controller is missing job_service")
        return job_service

    def submit_video_workflow_job(
        self,
        *,
        source_image_path: str | Path,
        form_data: dict[str, Any],
    ) -> str:
        # Trusted parent ids a handoff (Make Video from History or Review) supplied; never part of the form.
        lineage = form_data.pop("source_lineage", None)
        frozen = self._njr_builder.freeze_inputs(source_image_path, form_data)
        built = self._njr_builder.build_job(
            form_data, frozen, lineage=lineage if isinstance(lineage, Mapping) else None
        )
        job_ids = self._job_service().submit_njrs([built.njr], SubmissionPolicy())
        if not job_ids:
            raise RuntimeError("Failed to enqueue video workflow job")
        form_data["_stable_new_submission_projection"] = {
            "job_id": job_ids[0],
            "seed": built.seed,
            "frame_count": built.frame_count,
            "source_preparation": dict(built.source_preparation),
        }
        return job_ids[0]

    # ---------------------------------------------------------------- one-variable experiments

    def resolve_experiment_baseline(self, form_data: dict[str, Any], variable_name: str) -> Any:
        """The current resolved effective value of one declared control."""

        return self._experiments.resolve_variable(form_data, variable_name)

    def preview_experiment(
        self,
        *,
        source_image_path: str | Path,
        form_data: dict[str, Any],
        variable_name: str,
        candidates: Sequence[Any],
    ) -> ExperimentPlan:
        """Freeze one baseline and build every arm's NJR; nothing is queued."""

        return self._experiments.preview(
            str(source_image_path), form_data, variable_name, candidates
        )

    def submit_experiment(self, plan: ExperimentPlan) -> ExperimentAdmissionResult:
        """Admit a previewed experiment through ONE ``JobService.submit_njrs`` call.

        Safe to call from a worker thread: it only verifies frozen files and submits.  The caller
        refreshes GUI-visible queue state afterwards, on the UI thread."""

        return self._experiments.admit(plan, self._job_service())

    # ---------------------------------------------------------------- multi-source batches

    @staticmethod
    def select_batch_sources(
        paths: Sequence[str | Path],
        lineage_by_path: Mapping[str, Mapping[str, str]] | None = None,
        *,
        review_origin: bool = False,
    ) -> SourceSelection:
        """Order-preserving, duplicate-free source list (nothing is read or queued)."""

        return select_sources(paths, lineage_by_path, review_origin=review_origin)

    @staticmethod
    def scan_batch_folder(folder: str | Path, *, recursive: bool = True) -> SourceSelection:
        return scan_folder(folder, recursive=recursive)

    def preview_batch(
        self,
        *,
        sources: Sequence[BatchSource],
        form_data: dict[str, Any],
        duplicates_omitted: int = 0,
    ) -> BatchPlan:
        """Assess every source and, only when all are accepted, prepare and freeze the batch.

        Worker-thread safe: it reads files and writes only StableNew-owned prepared sources."""

        return self._batches.preview(form_data, sources, duplicates_omitted=duplicates_omitted)

    def submit_batch(self, plan: BatchPlan) -> BatchAdmissionResult:
        """Admit a previewed batch through ONE ``JobService.submit_njrs`` call (worker-safe; the
        caller refreshes GUI-visible queue state afterwards, on the UI thread)."""

        return self._batches.admit(plan, self._job_service())

    # ---------------------------------------------------------------- motion-source readiness

    @staticmethod
    def preview_motion_source(path: str | Path, policy: Mapping[str, Any]) -> Any:
        """Exact prepared pixels and crop geometry; writes nothing (worker-thread safe)."""

        return preview_declared_workflow_source(source_path=path, policy=policy)

    @staticmethod
    def inspect_driving_video(video_path: str | Path, cancel: Any = None) -> Any:
        """Bounded, read-only probe plus small preview frames (worker-thread safe)."""

        return _inspect_video(video_path, cancel=cancel)

    def prepare_motion_source(self, form: Any, request: Any, cancel: Any = None) -> Any:
        """Prepare the form's driving clip for its workflow (worker-thread safe)."""

        builder = self._njr_builder
        return prepare_for_form(builder.spec_for(form), form, request, builder.output_dir(), cancel)
