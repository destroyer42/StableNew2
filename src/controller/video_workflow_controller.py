from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from src.controller.ports.default_runtime_ports import DefaultWorkflowRegistryPort
from src.controller.ports.runtime_ports import WorkflowRegistryPort
from src.controller.submission_policy_v26 import SubmissionPolicy
from src.state.output_routing import OUTPUT_ROUTE_REPROCESS
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


class VideoWorkflowController:
    """Queue-backed controller surface for workflow-driven video jobs."""

    def __init__(
        self,
        *,
        app_controller,
        workflow_registry: WorkflowRegistryPort | None = None,
    ) -> None:
        self._app_controller = app_controller
        self._workflow_registry = workflow_registry or DefaultWorkflowRegistryPort()
        self._njr_builder = VideoWorkflowNjrBuilder(
            workflow_registry=self._workflow_registry,
            output_dir_provider=lambda: getattr(self._app_controller, "output_dir", None),
        )
        self._experiments = VideoWorkflowExperimentService(self._njr_builder)

    @staticmethod
    def _version_key(version: str) -> tuple[Any, ...]:
        parts = []
        for part in str(version or "").split("."):
            parts.append((0, int(part)) if part.isdigit() else (1, part))
        return tuple(parts)

    def _latest_per_workflow(self, specs: list[Any]) -> list[Any]:
        """One selectable entry per workflow: its newest registered version.  Older versions stay
        registered so existing jobs replay against their exact pinned revision."""

        latest: dict[str, Any] = {}
        for spec in specs:
            current = latest.get(spec.workflow_id)
            if current is None or self._version_key(spec.workflow_version) > self._version_key(
                current.workflow_version
            ):
                latest[spec.workflow_id] = spec
        return [latest[workflow_id] for workflow_id in sorted(latest)]

    def list_workflow_specs(self) -> list[dict[str, Any]]:
        specs = self._latest_per_workflow(
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
                    "operator_projection": self._mapping_dict(
                        (getattr(spec, "backend_defaults", None) or {}).get("operator_projection")
                    ),
                }
            )
        return records

    def build_default_form_state(self) -> dict[str, Any]:
        specs = self.list_workflow_specs()
        default_workflow = specs[0] if specs else {}
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

    @staticmethod
    def _mapping_dict(value: Any) -> dict[str, Any]:
        if isinstance(value, Mapping):
            return dict(value)
        return {}

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
        frozen = self._njr_builder.freeze_inputs(source_image_path, form_data)
        built = self._njr_builder.build_job(form_data, frozen)
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
        """Admit a previewed experiment through ONE ``JobService.submit_njrs`` call."""

        result = self._experiments.admit(plan, self._job_service())
        sync = getattr(self._app_controller, "sync_queue_state_after_direct_submission", None)
        if callable(sync):
            sync()
        return result
