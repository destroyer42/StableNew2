from __future__ import annotations

from pathlib import Path
from collections.abc import Mapping
from typing import Any

from src.controller.ports.default_runtime_ports import DefaultWorkflowRegistryPort
from src.controller.ports.runtime_ports import WorkflowRegistryPort
from src.pipeline.job_requests_v2 import PipelineRunMode, PipelineRunRequest, PipelineRunSource
from src.pipeline.reprocess_builder import ReprocessJobBuilder
from src.state.output_routing import (
    OUTPUT_ROUTE_MOVIE_CLIPS,
    OUTPUT_ROUTE_REPROCESS,
    OUTPUT_ROUTE_TESTING,
)
from src.video.continuity_models import normalize_continuity_link

_DEFAULT_OUTPUT_ROUTES = (
    OUTPUT_ROUTE_REPROCESS,
    OUTPUT_ROUTE_MOVIE_CLIPS,
    OUTPUT_ROUTE_TESTING,
)


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

    def list_workflow_specs(self) -> list[dict[str, Any]]:
        specs = self._workflow_registry.list_specs_for_backend("comfy")
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
                    "dependency_specs": [dependency.to_dict() for dependency in spec.dependency_specs],
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
            "prompt": "",
            "negative_prompt": "",
            "motion_profile": "gentle",
            "output_route": OUTPUT_ROUTE_REPROCESS,
            "continuity_pack_id": "",
            "continuity_pack_name": "",
            "continuity_pack_summary": None,
        }

    @staticmethod
    def _continuity_form_supplied(form_data: Mapping[str, Any]) -> bool:
        for key in (
            "continuity_link",
            "continuity_pack",
            "continuity_pack_id",
            "continuity_pack_name",
            "continuity_pack_summary",
        ):
            value = form_data.get(key)
            if value not in (None, "", [], {}):
                return True
        return False

    @staticmethod
    def _build_continuity_link(form_data: Mapping[str, Any]) -> dict[str, Any] | None:
        for key in ("continuity_link", "continuity_pack"):
            link = normalize_continuity_link(form_data.get(key))
            if link:
                return link

        pack_id = str(form_data.get("continuity_pack_id") or "").strip()
        pack_name = str(form_data.get("continuity_pack_name") or "").strip()
        raw_summary = form_data.get("continuity_pack_summary")
        summary = dict(raw_summary) if isinstance(raw_summary, Mapping) else {}
        if pack_name and "display_name" not in summary:
            summary["display_name"] = pack_name
        candidate_pack_id = pack_id or str(summary.get("pack_id") or "").strip()
        if not candidate_pack_id:
            return None
        payload: dict[str, Any] = {"pack_id": candidate_pack_id}
        if summary:
            summary.setdefault("pack_id", candidate_pack_id)
            payload["pack_summary"] = summary
        return normalize_continuity_link(payload)

    def validate_source_image(self, path: str | Path) -> tuple[bool, str | None]:
        source = Path(path)
        if not source.exists() or not source.is_file():
            return False, f"Video workflow source image does not exist: {source}"
        return True, None

    def validate_form_data(self, form_data: dict[str, Any]) -> tuple[bool, str | None]:
        workflow_id = str(form_data.get("workflow_id") or "").strip()
        if not workflow_id:
            return False, "Please select a video workflow."
        workflow_version = str(form_data.get("workflow_version") or "").strip() or None
        try:
            self._workflow_registry.get(workflow_id, workflow_version)
        except Exception as exc:
            return False, str(exc)

        end_anchor = Path(str(form_data.get("end_anchor_path") or "").strip())
        if not end_anchor.exists() or not end_anchor.is_file():
            return False, "Please choose an end anchor image for the video workflow."

        raw_mid_anchors = form_data.get("mid_anchor_paths") or []
        if isinstance(raw_mid_anchors, str):
            raw_mid_anchors = [item.strip() for item in raw_mid_anchors.split(";") if item.strip()]
        for candidate in raw_mid_anchors:
            path = Path(str(candidate or "").strip())
            if not path.exists() or not path.is_file():
                return False, f"Mid anchor image does not exist: {path}"
        if self._continuity_form_supplied(form_data) and self._build_continuity_link(form_data) is None:
            return False, (
                "Continuity pack metadata requires a valid pack_id. Please provide continuity_pack_id or "
                "ensure continuity_pack_summary contains a pack_id."
            )
        return True, None

    def submit_video_workflow_job(
        self,
        *,
        source_image_path: str | Path,
        form_data: dict[str, Any],
    ) -> str:
        valid, reason = self.validate_source_image(source_image_path)
        if not valid:
            raise ValueError(reason or "Video workflow source image is invalid")

        valid, reason = self.validate_form_data(form_data)
        if not valid:
            raise ValueError(reason or "Video workflow configuration is invalid")

        workflow_id = str(form_data.get("workflow_id") or "").strip()
        workflow_version = str(form_data.get("workflow_version") or "").strip() or None
        spec = self._workflow_registry.get(workflow_id, workflow_version)
        end_anchor_path = str(Path(str(form_data.get("end_anchor_path") or "").strip()).expanduser())

        raw_mid_anchors = form_data.get("mid_anchor_paths") or []
        if isinstance(raw_mid_anchors, str):
            raw_mid_anchors = [item.strip() for item in raw_mid_anchors.split(";") if item.strip()]
        mid_anchor_paths = [str(Path(str(item)).expanduser()) for item in raw_mid_anchors if str(item).strip()]

        output_route = str(form_data.get("output_route") or OUTPUT_ROUTE_REPROCESS).strip() or OUTPUT_ROUTE_REPROCESS
        if output_route not in _DEFAULT_OUTPUT_ROUTES:
            output_route = OUTPUT_ROUTE_REPROCESS

        prompt = str(form_data.get("prompt") or "").strip()
        negative_prompt = str(form_data.get("negative_prompt") or "").strip()
        motion_profile = str(form_data.get("motion_profile") or "").strip()
        output_dir = getattr(self._app_controller, "output_dir", None) or "output"
        continuity_link = self._build_continuity_link(form_data)

        config: dict[str, Any] = {
            "video_workflow": {
                "enabled": True,
                "workflow_id": workflow_id,
                "workflow_version": spec.workflow_version,
                "backend_id": spec.backend_id,
                "end_anchor_path": end_anchor_path,
                "mid_anchor_paths": mid_anchor_paths,
                "motion_profile": motion_profile,
                "prompt": prompt,
                "negative_prompt": negative_prompt,
            },
            "pipeline": {
                "output_route": output_route,
                "video_workflow_enabled": True,
            },
        }
        if continuity_link:
            config["metadata"] = {"continuity": dict(continuity_link)}

        extra_metadata = {
            "video_workflow": {
                "workflow_id": workflow_id,
                "workflow_version": spec.workflow_version,
                "display_name": spec.display_name,
                "backend_id": spec.backend_id,
                "output_route": output_route,
            }
        }
        if continuity_link:
            extra_metadata["continuity"] = dict(continuity_link)

        builder = ReprocessJobBuilder()
        njr = builder.build_reprocess_job(
            input_image_paths=[str(Path(source_image_path).expanduser())],
            stages=["video_workflow"],
            config=config,
            output_dir=str(output_dir),
            prompt=prompt,
            negative_prompt=negative_prompt,
            pack_name="Video Workflow",
            source="video_workflow",
            extra_metadata=extra_metadata,
        )
        if continuity_link:
            njr.continuity_link = dict(continuity_link)

        job_service = getattr(self._app_controller, "job_service", None)
        if job_service is None:
            raise RuntimeError("App controller is missing job_service")

        request = PipelineRunRequest(
            prompt_pack_id="video_workflow",
            selected_row_ids=[workflow_id],
            config_snapshot_id=workflow_id,
            run_mode=PipelineRunMode.QUEUE,
            source=PipelineRunSource.ADD_TO_QUEUE,
            requested_job_label=f"Video Workflow: {spec.display_name}",
            explicit_output_dir=str(output_dir),
            tags=["video_workflow", workflow_id],
        )
        job_ids = job_service.enqueue_njrs([njr], request)
        if not job_ids:
            raise RuntimeError("Failed to enqueue video workflow job")
        return job_ids[0]
