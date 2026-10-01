from __future__ import annotations

import hashlib
import secrets
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.controller.ports.default_runtime_ports import DefaultWorkflowRegistryPort
from src.controller.ports.runtime_ports import WorkflowRegistryPort
from src.controller.submission_policy_v26 import SubmissionPolicy
from src.pipeline.reprocess_builder import ReprocessJobBuilder
from src.state.output_routing import (
    OUTPUT_ROUTE_MOVIE_CLIPS,
    OUTPUT_ROUTE_REPROCESS,
    OUTPUT_ROUTE_TESTING,
)
from src.video.continuity_models import normalize_continuity_link
from src.video.video_execution_resolver import VIDEO_EXECUTION_KEY
from src.video.video_workflow_intent import (
    EXPERIMENTAL_OPT_IN_FIELD,
    build_video_execution_block,
    capability_errors,
    default_negative_prompt,
    form_visibility,
    mid_anchor_list,
    parse_seed_input,
)
from src.video.workflow_controls import operator_controls_projection, resolve_operator_controls
from src.video.workflow_frame_count import (
    approximate_seconds,
    frame_count_policy,
    frame_count_projection,
    parse_frame_count,
)
from src.video.workflow_source_preparation import prepare_declared_workflow_source

_DRIVING_VIDEO_SUFFIXES = {".mp4", ".webm", ".mov", ".mkv"}
_DEFAULT_OUTPUT_ROUTES = (
    OUTPUT_ROUTE_REPROCESS,
    OUTPUT_ROUTE_MOVIE_CLIPS,
    OUTPUT_ROUTE_TESTING,
)
_VALID_DEPTH_INPUT_MODES = {"none", "auto", "upload"}
_VALID_CAMERA_PRESETS = {
    "none",
    "dolly_in",
    "dolly_out",
    "truck_left",
    "truck_right",
    "orbit_left",
    "orbit_right",
    "tilt_up",
    "tilt_down",
}


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
    def _parse_float(
        value: Any,
        *,
        field_name: str,
        minimum: float | None = None,
        maximum: float | None = None,
    ) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name} must be a number") from exc
        if minimum is not None and parsed < minimum:
            raise ValueError(f"{field_name} must be >= {minimum}")
        if maximum is not None and parsed > maximum:
            raise ValueError(f"{field_name} must be <= {maximum}")
        return parsed

    @staticmethod
    def _mapping_dict(value: Any) -> dict[str, Any]:
        if isinstance(value, Mapping):
            return dict(value)
        return {}

    def _normalize_camera_intent(self, form_data: Mapping[str, Any]) -> dict[str, Any]:
        payload = self._mapping_dict(form_data.get("camera_intent"))
        preset = (
            str(payload.get("preset") or form_data.get("camera_preset") or "none").strip().lower()
            or "none"
        )
        if preset not in _VALID_CAMERA_PRESETS:
            allowed = ", ".join(sorted(_VALID_CAMERA_PRESETS))
            raise ValueError(f"camera_intent.preset must be one of: {allowed}")
        strength_value = payload.get("strength", form_data.get("camera_strength", 0.35))
        strength = self._parse_float(
            strength_value,
            field_name="camera_intent.strength",
            minimum=0.0,
            maximum=1.0,
        )
        return {
            "preset": preset,
            "strength": strength,
        }

    def _normalize_controlnet(self, form_data: Mapping[str, Any]) -> dict[str, Any]:
        payload = self._mapping_dict(form_data.get("controlnet"))
        model = (
            str(payload.get("model") or form_data.get("controlnet_model") or "depth").strip()
            or "depth"
        )
        weight = self._parse_float(
            payload.get("weight", form_data.get("controlnet_weight", 1.0)),
            field_name="controlnet.weight",
            minimum=0.0,
        )
        guidance_start = self._parse_float(
            payload.get("guidance_start", form_data.get("controlnet_guidance_start", 0.0)),
            field_name="controlnet.guidance_start",
            minimum=0.0,
            maximum=1.0,
        )
        guidance_end = self._parse_float(
            payload.get("guidance_end", form_data.get("controlnet_guidance_end", 1.0)),
            field_name="controlnet.guidance_end",
            minimum=0.0,
            maximum=1.0,
        )
        if guidance_end < guidance_start:
            raise ValueError("controlnet.guidance_end must be >= controlnet.guidance_start")
        return {
            "model": model,
            "weight": weight,
            "guidance_start": guidance_start,
            "guidance_end": guidance_end,
        }

    def _normalize_depth_input(self, form_data: Mapping[str, Any]) -> dict[str, Any]:
        payload = self._mapping_dict(form_data.get("depth_input"))
        mode = (
            str(payload.get("mode") or form_data.get("depth_mode") or "none").strip().lower()
            or "none"
        )
        if mode not in _VALID_DEPTH_INPUT_MODES:
            allowed = ", ".join(sorted(_VALID_DEPTH_INPUT_MODES))
            raise ValueError(f"depth_input.mode must be one of: {allowed}")
        path = str(
            payload.get("path") or payload.get("upload_path") or form_data.get("depth_path") or ""
        ).strip()
        return {
            "mode": mode,
            "path": path,
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
            spec = self._workflow_registry.get(workflow_id, workflow_version)
        except Exception as exc:
            return False, str(exc)

        try:
            self._normalize_camera_intent(form_data)
            self._normalize_controlnet(form_data)
            depth_input = self._normalize_depth_input(form_data)
            if "seed" in spec.declared_input_names:
                parse_seed_input(form_data.get("seed"))
            if frame_count_policy(spec) is not None:
                parse_frame_count(spec, form_data.get("frame_count"))
            resolve_operator_controls(spec, form_data)
        except ValueError as exc:
            return False, str(exc)

        # Required inputs, accepted controls and experimental opt-in all come from the spec.
        problems = capability_errors(spec, form_data)
        if problems:
            return False, problems[0]
        end_anchor_text = str(form_data.get("end_anchor_path") or "").strip()
        if end_anchor_text:
            end_anchor = Path(end_anchor_text)
            if not end_anchor.exists() or not end_anchor.is_file():
                return False, f"End anchor image does not exist: {end_anchor}"
        for candidate in mid_anchor_list(form_data.get("mid_anchor_paths")):
            path = Path(candidate)
            if not path.exists() or not path.is_file():
                return False, f"Mid anchor image does not exist: {path}"
        driving_text = str(form_data.get("pose_video_path") or "").strip()
        if driving_text:
            driving = Path(driving_text).expanduser()
            if not driving.exists() or not driving.is_file():
                return False, f"Driving video does not exist: {driving}"
            if driving.suffix.lower() not in _DRIVING_VIDEO_SUFFIXES:
                allowed = ", ".join(sorted(_DRIVING_VIDEO_SUFFIXES))
                return False, f"Driving video must be a video file ({allowed}): {driving}"
        input_bindings = getattr(spec, "input_bindings", ()) or ()
        requires_depth_input = any(
            getattr(binding, "source_field", None) == "stage_config.depth_input.resolved_path"
            for binding in input_bindings
        )
        if requires_depth_input and depth_input["mode"] == "none":
            return False, (
                "The selected conditioned workflow requires depth_input.mode to be 'auto' or 'upload'."
            )
        if depth_input["mode"] == "upload":
            depth_path = Path(depth_input["path"])
            if not depth_path.exists() or not depth_path.is_file():
                return False, f"Depth input image does not exist: {depth_path}"
        if (
            self._continuity_form_supplied(form_data)
            and self._build_continuity_link(form_data) is None
        ):
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
        end_anchor_text = str(form_data.get("end_anchor_path") or "").strip()
        end_anchor_path = str(Path(end_anchor_text).expanduser()) if end_anchor_text else ""
        mid_anchor_paths = mid_anchor_list(form_data.get("mid_anchor_paths"))

        output_route = (
            str(form_data.get("output_route") or OUTPUT_ROUTE_REPROCESS).strip()
            or OUTPUT_ROUTE_REPROCESS
        )
        if output_route not in _DEFAULT_OUTPUT_ROUTES:
            output_route = OUTPUT_ROUTE_REPROCESS

        prompt = str(form_data.get("prompt") or "").strip()
        negative_prompt = str(form_data.get("negative_prompt") or "").strip() or (
            default_negative_prompt(spec) if "negative_prompt" in spec.declared_input_names else ""
        )
        form_with_defaults = {**form_data, "negative_prompt": negative_prompt}
        motion_profile = str(form_data.get("motion_profile") or "").strip()
        camera_intent = self._normalize_camera_intent(form_data)
        controlnet = self._normalize_controlnet(form_data)
        depth_input = self._normalize_depth_input(form_data)
        output_dir = getattr(self._app_controller, "output_dir", None) or "output"
        continuity_link = self._build_continuity_link(form_data)

        workflow_config: dict[str, Any] = {
            "enabled": True,
            "workflow_id": workflow_id,
            "workflow_version": spec.workflow_version,
            "backend_id": spec.backend_id,
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            # Neutral, explicit execution intent (PR-VID-120 contract); the historical
            # stage-owned bridge is not needed for work compiled here.
            VIDEO_EXECUTION_KEY: build_video_execution_block(
                spec, {**form_with_defaults, "camera_intent": camera_intent}
            ),
        }
        declared_inputs = set(spec.declared_input_names)
        if "end_anchor" in declared_inputs:
            workflow_config["end_anchor_path"] = end_anchor_path
        if "mid_anchors" in declared_inputs:
            workflow_config["mid_anchor_paths"] = mid_anchor_paths
        if "motion_profile" in declared_inputs:
            workflow_config["motion_profile"] = motion_profile
        if "camera_preset" in declared_inputs:
            workflow_config["camera_intent"] = camera_intent
        if any(name in declared_inputs for name in ("depth_map", "controlnet_model")):
            workflow_config["controlnet"] = controlnet
            workflow_config["depth_input"] = depth_input
        driving_provenance: dict[str, Any] | None = None
        driving_text = str(form_data.get("pose_video_path") or "").strip()
        if "pose_video" in declared_inputs and driving_text:
            # Frozen by path and content hash: the source file is only ever read (staged by the
            # backend as a copy), and provenance records exactly which clip drove the motion.
            driving_path = Path(driving_text).expanduser().resolve()
            driving_provenance = {
                "path": str(driving_path),
                "sha256": hashlib.sha256(driving_path.read_bytes()).hexdigest(),
            }
            workflow_config["pose_video_path"] = driving_provenance["path"]
            workflow_config["pose_video_sha256"] = driving_provenance["sha256"]

        prepared_source_path = str(Path(source_image_path).expanduser())
        source_preparation: dict[str, Any] | None = None
        backend_defaults = getattr(spec, "backend_defaults", None) or {}
        preparation_policy = backend_defaults.get("source_preparation")
        if isinstance(preparation_policy, Mapping):
            prepared_source = prepare_declared_workflow_source(
                source_path=source_image_path,
                output_root=output_dir,
                policy=preparation_policy,
            )
            source_preparation = prepared_source.to_stage_config()
            workflow_config["source_preparation"] = source_preparation
            prepared_source_path = prepared_source.prepared_image_path

        config: dict[str, Any] = {
            "video_workflow": workflow_config,
            "pipeline": {
                "output_route": output_route,
                "video_workflow_enabled": True,
            },
        }
        frozen_seed: int | None = None
        if "seed" in declared_inputs:
            # Recorded in the immutable job so a replay reproduces the same sampler seed.
            frozen_seed = parse_seed_input(form_data.get("seed"))
            if frozen_seed is None:
                frozen_seed = secrets.randbelow(2**31)
            workflow_config["seed"] = frozen_seed
        frozen_frame_count: int | None = None
        length_policy = frame_count_policy(spec)
        if length_policy is not None:
            # Frozen at admission so the queued job, its artifact and any replay agree on length.
            frozen_frame_count = parse_frame_count(spec, form_data.get("frame_count"))
            workflow_config["frame_count"] = frozen_frame_count
            workflow_config["fps"] = length_policy["fps"]
        # Declared workflow controls (e.g. Animate-2 motion prompt / pose strength) are frozen
        # here, like seed and length; the compiler binds them to the exact graph inputs.
        frozen_controls = resolve_operator_controls(spec, form_data)
        if frozen_controls is not None:
            workflow_config["operator_controls"] = frozen_controls
        if continuity_link:
            config["metadata"] = {"continuity": dict(continuity_link)}

        extra_metadata = {
            "video_workflow": {
                "workflow_id": workflow_id,
                "workflow_version": spec.workflow_version,
                "display_name": spec.display_name,
                "backend_id": spec.backend_id,
                "governance_state": spec.governance_state,
                "experimental_opt_in": config["video_workflow"][VIDEO_EXECUTION_KEY][
                    EXPERIMENTAL_OPT_IN_FIELD
                ],
                "output_route": output_route,
            }
        }
        if "camera_intent" in workflow_config:
            extra_metadata["video_workflow"]["camera_intent"] = camera_intent
        if "controlnet" in workflow_config:
            extra_metadata["video_workflow"]["controlnet"] = controlnet
            extra_metadata["video_workflow"]["depth_input"] = depth_input
        if source_preparation:
            extra_metadata["video_workflow"]["source_preparation"] = dict(source_preparation)
        if frozen_seed is not None:
            extra_metadata["video_workflow"]["seed"] = frozen_seed
        if frozen_controls is not None:
            extra_metadata["video_workflow"]["operator_controls"] = dict(frozen_controls)
        if driving_provenance is not None:
            extra_metadata["video_workflow"]["pose_video"] = dict(driving_provenance)
        if frozen_frame_count is not None and length_policy is not None:
            extra_metadata["video_workflow"].update(
                frame_count=frozen_frame_count,
                fps=length_policy["fps"],
                approximate_seconds=approximate_seconds(frozen_frame_count, length_policy["fps"]),
            )
        if continuity_link:
            extra_metadata["continuity_link"] = dict(continuity_link)

        builder = ReprocessJobBuilder()
        njr = builder.build_reprocess_job(
            input_image_paths=[prepared_source_path],
            stages=["video_workflow"],
            config=config,
            output_dir=str(output_dir),
            prompt=prompt,
            negative_prompt=negative_prompt,
            pack_name="Video Workflow",
            source="video_workflow",
            extra_metadata=extra_metadata,
        )
        job_service = getattr(self._app_controller, "job_service", None)
        if job_service is None:
            raise RuntimeError("App controller is missing job_service")

        job_ids = job_service.submit_njrs([njr], SubmissionPolicy())
        if not job_ids:
            raise RuntimeError("Failed to enqueue video workflow job")
        form_data["_stable_new_submission_projection"] = {
            "job_id": job_ids[0],
            "seed": frozen_seed,
            "frame_count": frozen_frame_count,
            "source_preparation": dict(source_preparation or {}),
        }
        return job_ids[0]
