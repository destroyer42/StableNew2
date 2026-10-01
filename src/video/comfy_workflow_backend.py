from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Callable, Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from src.pipeline.artifact_contract import artifact_manifest_payload
from src.services.runtime_transition_service import (
    RUNTIME_COMFY,
    RuntimeTransitionCoordinator,
    RuntimeTransitionError,
)
from src.video.comfy_api_client import ComfyApiClient
from src.video.comfy_dependency_probe import ComfyDependencyProbe
from src.video.comfy_healthcheck import wait_for_comfy_ready
from src.video.comfy_process_manager import (
    ComfyProcessManager,
    build_default_comfy_process_config,
    get_global_comfy_process_manager,
)
from src.video.container_metadata import write_video_container_metadata
from src.video.depth_map_resolver import DepthMapResolver
from src.video.motion.secondary_motion_provenance import extract_secondary_motion_summary
from src.video.motion.secondary_motion_video_reencode import apply_secondary_motion_to_video
from src.video.video_artifact_helpers import build_video_artifact_bundle
from src.video.video_backend_types import (
    CONTROL_CAMERA_INTENT,
    CONTROL_CONTROL_VIDEO,
    CONTROL_END_ANCHOR,
    CONTROL_MID_ANCHORS,
    CONTROL_NEGATIVE_PROMPT,
    CONTROL_POSE_VIDEO,
    CONTROL_PROMPT_TEXT,
    CONTROL_SOURCE_IMAGE,
    CONTROL_START_ANCHOR,
    VIDEO_TASK_IMAGE_TO_VIDEO,
    VideoBackendCapabilities,
    VideoExecutionRequest,
    VideoExecutionResult,
)
from src.video.workflow_compiler import WorkflowCompiler
from src.video.workflow_frame_count import frame_count_policy, parse_frame_count
from src.video.workflow_readiness import WorkflowResourceReadiness
from src.video.workflow_registry import WorkflowRegistry, build_default_workflow_registry


def _release_owned_runtime_after_job(spec: Any) -> bool:
    policy = (getattr(spec, "backend_defaults", None) or {}).get("runtime_policy")
    return isinstance(policy, Mapping) and policy.get("release_owned_runtime_after_job") is True


def _is_generated_output(descriptor: Mapping[str, Any]) -> bool:
    """Only files a workflow *produced* are artifacts.  Comfy also reports previews of inputs
    (for example ``LoadVideo`` echoes its source clip as ``type: input``) and temp previews;
    neither is a generated result."""

    return str(descriptor.get("type") or "output") == "output"


def _required_launch_flags(spec: Any) -> tuple[str, ...]:
    policy = (getattr(spec, "backend_defaults", None) or {}).get("runtime_policy")
    if not isinstance(policy, Mapping):
        return ()
    return tuple(str(flag) for flag in policy.get("required_launch_flags") or () if str(flag))


# (node class, input) pairs whose value is a local file the Comfy server must hold in its input
# directory.  The file is uploaded as a copy through the Comfy API; the source is never modified.
_UPLOADED_FILE_INPUTS = {("LoadImage", "image"), ("LoadVideo", "file")}


def _driving_video_provenance(stage_config: Mapping[str, Any]) -> dict[str, Any]:
    path = str(stage_config.get("pose_video_path") or "").strip()
    if not path:
        return {}
    return {"pose_video": {"path": path, "sha256": stage_config.get("pose_video_sha256")}}


def _file_sha256(path: Any) -> str | None:
    try:
        return hashlib.sha256(Path(str(path)).read_bytes()).hexdigest()
    except (OSError, TypeError, ValueError):
        return None


def _control_provenance(
    spec: Any, request: Any, stage_config: Mapping[str, Any]
) -> dict[str, Any]:
    """Frozen workflow controls plus one self-contained record a later Learning package can read.

    Emitted only for jobs that carry operator controls or a driving video (data-driven, not by
    workflow name).  It restates what the immutable job already froze -- nothing is re-derived.
    """

    controls = stage_config.get("operator_controls")
    driving = _driving_video_provenance(stage_config)
    if not controls and not driving:
        return {}
    identity = _mapping_dict((getattr(spec, "backend_defaults", None) or {}).get("provenance"))
    record: dict[str, Any] = {
        "workflow": {
            "workflow_id": spec.workflow_id,
            "workflow_version": spec.workflow_version,
            "pinned_revision": spec.pinned_revision,
            "qualified_graph_sha256": identity.get("qualified_graph_sha256"),
            "comfyui_version": identity.get("comfyui_version"),
            "comfyui_revision": identity.get("comfyui_revision"),
        },
        "source_image": {
            "path": str(request.input_image_path) if request.input_image_path else None,
            "sha256": _file_sha256(request.input_image_path) if request.input_image_path else None,
        },
        "prompt": request.prompt,
        "negative_prompt": request.negative_prompt,
        "seed": stage_config.get("seed"),
        "operator_controls": dict(controls) if isinstance(controls, Mapping) else {},
        **driving,
    }
    result: dict[str, Any] = {"control_record": record}
    if isinstance(controls, Mapping) and controls:
        result["operator_controls"] = dict(controls)
    return result


def _length_provenance(spec: Any, stage_config: Mapping[str, Any]) -> dict[str, Any]:
    """Frozen frame count and declared FPS for a variable-length workflow (else empty)."""

    policy = frame_count_policy(spec)
    if policy is None or stage_config.get("frame_count") in (None, ""):
        return {}
    frame_count = int(stage_config["frame_count"])
    return {
        "frame_count": frame_count,
        "fps": policy["fps"],
        "approximate_seconds": round(frame_count / policy["fps"], 1),
    }


def _format_missing_dependency_message(spec: Any, dependency_result: Any) -> str:
    missing_entries: list[str] = []
    spec_by_id = {dependency.dependency_id: dependency for dependency in spec.dependency_specs}
    for dependency_id in dependency_result.missing_required:
        dependency = spec_by_id.get(dependency_id)
        if dependency is None:
            missing_entries.append(str(dependency_id))
            continue
        description = str(dependency.description or dependency.locator or "").strip()
        if description:
            missing_entries.append(f"{dependency_id} ({description})")
        else:
            missing_entries.append(str(dependency_id))
    missing_text = ", ".join(missing_entries) if missing_entries else "unknown"
    return (
        f"Workflow '{spec.workflow_id}' missing required Comfy dependencies: {missing_text}. "
        "Install the required workflow nodes/models for this workflow and restart ComfyUI before running the video_workflow stage."
    )


def _build_missing_runtime_message(base_url: str, reason: Exception | None = None) -> str:
    message = (
        "ComfyUI is not running and StableNew has no managed ComfyUI launch configuration. "
        f"Tried base URL '{base_url}'. Configure ComfyUI in Engine Settings so presets/settings.json "
        "contains a valid comfy_command and comfy_workdir, or start ComfyUI manually before running "
        "the video_workflow stage."
    )
    if reason is not None:
        message = f"{message} Last probe error: {reason}"
    return message


def _dedupe_paths(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped


def _mapping_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _contains_locator(payload: Any, locator: str) -> bool:
    needle = str(locator or "").strip().lower()
    if not needle:
        return False
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            if needle in str(key).lower() or _contains_locator(value, needle):
                return True
        return False
    if isinstance(payload, (list, tuple, set)):
        return any(_contains_locator(item, needle) for item in payload)
    return needle in str(payload).lower()


def _has_model_inventory(payload: Any) -> bool:
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            normalized = str(key or "").strip().lower()
            if normalized in {"models", "checkpoints", "loras", "vae"}:
                return True
            if _has_model_inventory(value):
                return True
        return False
    if isinstance(payload, (list, tuple, set)):
        return any(_has_model_inventory(item) for item in payload)
    return False


# While a queued prompt is confirmed alive on the Comfy server, the backend reports bounded
# execution liveness at most this often.  It must stay well below the runner-stall watchdog
# interval (SystemWatchdogV2.RUNNER_STALL_S) and is only ever emitted inside the backend's own
# execution wait (`history_timeout`), so it can never suppress a stall past that bound.
_LIVENESS_REPORT_INTERVAL_S = 5.0


def _prompt_is_live(client: Any, prompt_id: str) -> bool:
    """True only when the Comfy server itself still lists the prompt as running or pending.

    A merely responsive endpoint is not evidence of execution: a prompt that is in neither the
    live queue nor the history is not alive, and an unreachable server raises or times out.
    """

    try:
        queue = client.get_queue()
    except Exception:
        return False
    if not isinstance(queue, Mapping):
        return False
    for key in ("queue_running", "queue_pending"):
        for item in queue.get(key) or ():
            if isinstance(item, (list, tuple)) and len(item) > 1 and str(item[1]) == prompt_id:
                return True
    return False


def _history_entry_from_payload(
    payload: Mapping[str, Any], prompt_id: str
) -> dict[str, Any] | None:
    if "outputs" in payload:
        return dict(payload)
    prompt_key = str(prompt_id or "").strip()
    if prompt_key and prompt_key in payload and isinstance(payload[prompt_key], Mapping):
        return dict(payload[prompt_key])
    return None


def _history_ready(entry: Mapping[str, Any]) -> bool:
    outputs = entry.get("outputs")
    if isinstance(outputs, Mapping) and outputs:
        return True
    status = entry.get("status")
    if isinstance(status, Mapping):
        if status.get("completed") is True:
            return True
        status_str = str(status.get("status_str") or "").strip().lower()
        if status_str in {"success", "completed", "done"}:
            return True
    return False


class ComfyWorkflowVideoBackend:
    backend_id = "comfy"
    capabilities = VideoBackendCapabilities(
        backend_id=backend_id,
        stage_types=("video_workflow",),
        tasks=(VIDEO_TASK_IMAGE_TO_VIDEO,),
        controls=(
            CONTROL_SOURCE_IMAGE,
            CONTROL_PROMPT_TEXT,
            CONTROL_NEGATIVE_PROMPT,
            CONTROL_START_ANCHOR,
            CONTROL_END_ANCHOR,
            CONTROL_MID_ANCHORS,
            CONTROL_CONTROL_VIDEO,
            CONTROL_POSE_VIDEO,
            CONTROL_CAMERA_INTENT,
        ),
        required_controls=(CONTROL_SOURCE_IMAGE,),
    )

    def __init__(
        self,
        *,
        workflow_registry: WorkflowRegistry | None = None,
        compiler: WorkflowCompiler | None = None,
        client: ComfyApiClient | None = None,
        dependency_probe: ComfyDependencyProbe | None = None,
        depth_map_resolver: DepthMapResolver | None = None,
        process_manager: ComfyProcessManager | None = None,
        readiness: WorkflowResourceReadiness | None = None,
        transition: RuntimeTransitionCoordinator | None = None,
        base_url: str = "http://127.0.0.1:8188",
        history_poll_interval: float = 0.5,
        history_timeout: float = 120.0,
    ) -> None:
        self._workflow_registry = workflow_registry or build_default_workflow_registry()
        self._compiler = compiler or WorkflowCompiler()
        self._client = client
        self._dependency_probe = dependency_probe
        self._depth_map_resolver = depth_map_resolver or DepthMapResolver()
        self._readiness = readiness or WorkflowResourceReadiness()
        self._transition = transition or RuntimeTransitionCoordinator()
        self._process_manager = process_manager
        self._managed_process_manager: ComfyProcessManager | None = None
        self._base_url = str(base_url or "http://127.0.0.1:8188").rstrip("/")
        self._history_poll_interval = max(history_poll_interval, 0.1)
        self._history_timeout = max(history_timeout, 5.0)

    def validate_workflow(self, request: VideoExecutionRequest) -> None:
        """Fail before dispatch when the explicit workflow is unknown, not approved, or does not
        declare a requested control.  Never selects or substitutes a workflow."""

        stage_config = dict(request.stage_config or {})
        workflow_id = str(request.workflow_id or stage_config.get("workflow_id") or "").strip()
        if not workflow_id:
            raise ValueError("video workflow requests require an explicit workflow_id")
        version = str(request.workflow_version or stage_config.get("workflow_version") or "")
        spec = self._workflow_registry.get(
            workflow_id,
            version.strip() or None,
            allow_experimental=bool(request.experimental_opt_in),
        )
        missing = sorted(set(request.requested_controls) - set(spec.accepted_controls))
        if missing:
            raise ValueError(
                f"workflow '{spec.workflow_id}' v{spec.workflow_version} does not declare "
                f"requested controls {missing}"
            )

    def execute(self, pipeline: Any, request: VideoExecutionRequest) -> VideoExecutionResult | None:
        stage_config = deepcopy(dict(request.stage_config or {}))
        request.stage_config = stage_config
        workflow_id = str(
            request.workflow_id or stage_config.get("workflow_id") or stage_config.get("id") or ""
        ).strip()
        workflow_version = (
            str(
                request.workflow_version
                or stage_config.get("workflow_version")
                or stage_config.get("version")
                or ""
            ).strip()
            or None
        )
        if not workflow_id:
            raise ValueError("video_workflow stage requires workflow_id")

        # Governance first: an unknown/disabled/un-opted-in workflow never starts a runtime.
        spec = self._workflow_registry.get(
            workflow_id, workflow_version, allow_experimental=bool(request.experimental_opt_in)
        )
        if spec.backend_id != self.backend_id:
            raise ValueError(
                f"Workflow '{spec.workflow_id}' is registered for backend '{spec.backend_id}', "
                f"not '{self.backend_id}'"
            )
        # An illegal frozen length fails before any runtime is started or dispatched.
        if frame_count_policy(spec) is not None:
            parse_frame_count(spec, stage_config.get("frame_count"))
        # A declared launch requirement (e.g. the qualified pinned-memory-off policy) must be
        # provable from StableNew's own managed launch configuration before anything starts.
        self._verify_required_launch_flags(spec)

        if not _release_owned_runtime_after_job(spec):
            return self._execute_on_runtime(pipeline, request, spec, stage_config, workflow_id)

        # Declared runtime policy: once this job has touched the managed runtime, release the
        # process StableNew owns on every exit path (success, failure, or interruption) so the
        # next queued job starts from a fresh runtime.  An external or unowned Comfy is never
        # stopped.  BaseException, so an interrupt cannot leave a resident runtime behind; the
        # original exception always propagates unchanged.
        try:
            result = self._execute_on_runtime(pipeline, request, spec, stage_config, workflow_id)
        except BaseException:
            self._release_owned_runtime()
            raise
        release = self._release_owned_runtime()
        if result is not None:
            result.backend_metadata["runtime_release"] = dict(release)
            result.diagnostic_payload["runtime_release"] = dict(release)
        return result

    def _execute_on_runtime(
        self,
        pipeline: Any,
        request: VideoExecutionRequest,
        spec: Any,
        stage_config: dict[str, Any],
        workflow_id: str,
    ) -> VideoExecutionResult | None:
        # Release conflicting StableNew-owned runtime residency (owned A1111, cached SVD state)
        # before Comfy starts/serves; never touches an external runtime.  See PR-RUNTIME-100.
        transition = self._transition.prepare_for(RUNTIME_COMFY)
        if not transition.ready:
            raise RuntimeTransitionError(transition)

        runtime_base_url = self._ensure_runtime_ready()
        client = self._client or ComfyApiClient(base_url=runtime_base_url)

        object_info = client.get_object_info()
        probe = self._dependency_probe or ComfyDependencyProbe(client)
        dependency_result = probe.probe_workflow(spec, object_info=object_info)
        if not dependency_result.ready:
            raise RuntimeError(_format_missing_dependency_message(spec, dependency_result))

        # Bounded, observe-only resource readiness (workflows that declare a policy): a failing
        # check fails the job before anything is queued; nothing is stopped or restarted.
        readiness = None
        if self._readiness.policy_for(spec) is not None:
            readiness = self._readiness.evaluate(spec, system_stats=client.get_system_stats())
            if not readiness.ready:
                raise RuntimeError(
                    f"Workflow '{spec.workflow_id}' is not resource-ready: {readiness.message}"
                )

        conditioning = self._resolve_conditioning_inputs(
            spec=spec,
            request=request,
            object_info=object_info,
        )

        compiled = self._compiler.compile(spec, request)
        queue_payload = self._build_queue_payload(
            compiled,
            request,
            client=client,
            object_info=object_info,
        )
        queue_response = client.queue_prompt(queue_payload)
        prompt_id = str(queue_response.get("prompt_id") or "").strip()
        if not prompt_id:
            raise RuntimeError("Comfy queue response did not include prompt_id")

        history_entry = self._wait_for_history_entry(
            client,
            prompt_id=prompt_id,
            report_liveness=self._liveness_reporter(pipeline, request),
            timeout=self._history_timeout_for(spec),
        )
        if str(spec.backend_defaults.get("output_transport") or "") == "comfy_view":
            history_entry = self._localize_comfy_outputs(
                client, history_entry, Path(request.output_dir)
            )
        resolved_outputs = self._resolve_output_paths(
            history_entry=history_entry,
            compiled_outputs=compiled.compiled_outputs,
        )
        secondary_motion_block = (
            stage_config.get("secondary_motion")
            if isinstance(stage_config.get("secondary_motion"), dict)
            else None
        )
        if (
            isinstance(secondary_motion_block, dict)
            and secondary_motion_block.get("enabled")
            and resolved_outputs.get("video_path")
        ):
            motion_result = apply_secondary_motion_to_video(
                video_path=str(resolved_outputs["video_path"]),
                output_dir=request.output_dir,
                runtime_block=secondary_motion_block,
                fps=int(stage_config.get("fps") or stage_config.get("video_fps") or 8),
            )
            motion_summary = motion_result.get(
                "secondary_motion_summary"
            ) or extract_secondary_motion_summary(motion_result)
            resolved_outputs.update(
                {
                    "secondary_motion_source_video_path": str(
                        motion_result.get("source_video_path")
                        or resolved_outputs.get("video_path")
                        or ""
                    ),
                    "secondary_motion": motion_result["secondary_motion"],
                    "secondary_motion_summary": motion_summary,
                }
            )
            if motion_summary.get("status") == "applied":
                resolved_outputs.update(
                    {
                        "primary_path": motion_result["primary_path"],
                        "output_paths": list(motion_result["output_paths"]),
                        "video_path": motion_result["video_path"],
                        "video_paths": list(motion_result["video_paths"]),
                        "frame_paths": list(motion_result["frame_paths"]),
                        "thumbnail_path": motion_result["thumbnail_path"],
                    }
                )
        primary_path = resolved_outputs["primary_path"]
        output_paths = resolved_outputs["output_paths"]
        if not primary_path or not output_paths:
            raise RuntimeError(
                f"Workflow '{workflow_id}' completed without discoverable output artifacts"
            )

        length_provenance = _length_provenance(spec, stage_config)
        runtime_policy = _mapping_dict(spec.backend_defaults.get("runtime_policy"))
        provenance_extra: dict[str, Any] = {
            **length_provenance,
            **_driving_video_provenance(stage_config),
            **_control_provenance(spec, request, stage_config),
        }
        if runtime_policy:
            provenance_extra["runtime_policy"] = runtime_policy
        manifest_path = self._write_manifest(
            request=request,
            prompt_id=prompt_id,
            spec=spec,
            compiled=compiled.to_dict(),
            dependency_probe=dependency_result.to_dict(),
            queue_response=queue_response,
            history_entry=history_entry,
            resolved_outputs=resolved_outputs,
            conditioning=conditioning,
            provenance_extra=provenance_extra,
        )
        metadata_payload = {
            "stage": request.stage_name,
            "backend_id": self.backend_id,
            "job_id": request.job_id,
            "run_id": Path(request.output_dir).name,
            "title": request.image_name
            or Path(str(resolved_outputs["primary_path"] or "video")).stem,
            "prompt": request.prompt,
            "negative_prompt": request.negative_prompt,
            "source_image_path": str(request.input_image_path)
            if request.input_image_path
            else None,
            "end_anchor_path": str(request.end_anchor_path) if request.end_anchor_path else None,
            "mid_anchor_paths": [str(path) for path in request.mid_anchor_paths or []],
            "motion_profile": request.motion_profile,
            "workflow_id": spec.workflow_id,
            "workflow_version": spec.workflow_version,
            "conditioning": dict(conditioning),
            "manifest_path": str(manifest_path),
            "output_paths": list(resolved_outputs["output_paths"]),
            "video_paths": list(resolved_outputs["video_paths"]),
            "gif_paths": list(resolved_outputs["gif_paths"]),
            "frame_path_count": len(resolved_outputs["frame_paths"]),
            "thumbnail_path": resolved_outputs["thumbnail_path"],
            "compiled_inputs": dict(compiled.compiled_inputs),
            "config": {
                "stage_config": stage_config,
                "compiled_inputs": dict(compiled.compiled_inputs),
                "compiled_outputs": dict(compiled.compiled_outputs),
                "compiler_metadata": dict(compiled.compiler_metadata),
            },
            "artifact": artifact_manifest_payload(
                stage=request.stage_name,
                image_or_output_path=primary_path,
                manifest_path=manifest_path,
                output_paths=output_paths,
                thumbnail_path=resolved_outputs["thumbnail_path"],
                input_image_path=request.input_image_path,
                artifact_type="video",
            ),
        }
        source_preparation = _mapping_dict(stage_config.get("source_preparation"))
        if source_preparation:
            metadata_payload["source_preparation"] = source_preparation
        metadata_payload.update(provenance_extra)
        if resolved_outputs.get("secondary_motion"):
            metadata_payload["secondary_motion"] = dict(resolved_outputs["secondary_motion"])
            metadata_payload["secondary_motion_summary"] = dict(
                resolved_outputs.get("secondary_motion_summary") or {}
            )
            metadata_payload["secondary_motion_source_video_path"] = resolved_outputs.get(
                "secondary_motion_source_video_path"
            )
        for candidate_path in [
            *resolved_outputs["video_paths"],
            *resolved_outputs["gif_paths"],
        ]:
            write_video_container_metadata(candidate_path, metadata_payload)
        raw_result = {
            "path": primary_path,
            "output_path": primary_path,
            "output_paths": list(output_paths),
            "video_path": resolved_outputs["video_path"],
            "video_paths": list(resolved_outputs["video_paths"]),
            "gif_path": resolved_outputs["gif_path"],
            "gif_paths": list(resolved_outputs["gif_paths"]),
            "frame_paths": list(resolved_outputs["frame_paths"]),
            "frame_path_count": len(resolved_outputs["frame_paths"]),
            "thumbnail_path": resolved_outputs["thumbnail_path"],
            "manifest_path": str(manifest_path),
            "manifest_paths": [str(manifest_path)],
            "count": len(output_paths),
            "source_image_path": str(request.input_image_path)
            if request.input_image_path
            else None,
            "workflow_id": spec.workflow_id,
            "workflow_version": spec.workflow_version,
            "prompt_id": prompt_id,
            "dependency_probe": dependency_result.to_dict(),
            "compiled_workflow": compiled.to_dict(),
            "conditioning": dict(conditioning),
            "secondary_motion": dict(resolved_outputs.get("secondary_motion") or {}),
            "secondary_motion_summary": dict(
                resolved_outputs.get("secondary_motion_summary") or {}
            ),
            "secondary_motion_source_video_path": resolved_outputs.get(
                "secondary_motion_source_video_path"
            ),
            "artifact": artifact_manifest_payload(
                stage=request.stage_name,
                image_or_output_path=primary_path,
                manifest_path=manifest_path,
                output_paths=output_paths,
                thumbnail_path=resolved_outputs["thumbnail_path"],
                input_image_path=request.input_image_path,
                artifact_type="video",
            ),
            "handoff_bundle": build_video_artifact_bundle(
                stage=request.stage_name,
                backend_id=self.backend_id,
                primary_path=primary_path,
                output_paths=list(output_paths),
                video_paths=list(resolved_outputs["video_paths"]),
                gif_paths=list(resolved_outputs["gif_paths"]),
                frame_paths=list(resolved_outputs["frame_paths"]),
                manifest_path=str(manifest_path),
                manifest_paths=[str(manifest_path)],
                thumbnail_path=resolved_outputs["thumbnail_path"],
                source_image_path=str(request.input_image_path)
                if request.input_image_path
                else None,
            ),
        }
        if source_preparation:
            raw_result["source_preparation"] = source_preparation
        raw_result.update(provenance_extra)
        return VideoExecutionResult.from_stage_result(
            backend_id=self.backend_id,
            stage_name=request.stage_name,
            result=raw_result,
            backend_metadata={
                "backend_id": self.backend_id,
                "workflow_id": spec.workflow_id,
                "workflow_version": spec.workflow_version,
                "prompt_id": prompt_id,
                "compiled_inputs": dict(compiled.compiled_inputs),
                "compiled_outputs": dict(compiled.compiled_outputs),
                "conditioning": dict(conditioning),
                **provenance_extra,
            },
            diagnostic_payload={
                "queue_response": dict(queue_response),
                "dependency_probe": dependency_result.to_dict(),
                "resource_readiness": readiness.to_dict() if readiness is not None else None,
                "history_summary": {
                    "has_outputs": bool(history_entry.get("outputs")),
                    "prompt_id": prompt_id,
                },
            },
            replay_manifest_fragment={
                "backend_id": self.backend_id,
                "stage_name": request.stage_name,
                "workflow_id": spec.workflow_id,
                "workflow_version": spec.workflow_version,
                "prompt_id": prompt_id,
                "manifest_path": str(manifest_path),
                "dependency_snapshot": dict(compiled.dependency_snapshot),
                "compiled_inputs": dict(compiled.compiled_inputs),
                "conditioning": dict(conditioning),
                "secondary_motion": dict(resolved_outputs.get("secondary_motion") or {}),
                "secondary_motion_summary": dict(
                    resolved_outputs.get("secondary_motion_summary") or {}
                ),
                "secondary_motion_source_video_path": resolved_outputs.get(
                    "secondary_motion_source_video_path"
                ),
                **length_provenance,
            },
        )

    def _resolve_conditioning_inputs(
        self,
        *,
        spec: Any,
        request: VideoExecutionRequest,
        object_info: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        stage_config = _mapping_dict(request.stage_config)
        camera_intent = _mapping_dict(stage_config.get("camera_intent"))
        controlnet = _mapping_dict(stage_config.get("controlnet"))
        depth_input = _mapping_dict(stage_config.get("depth_input"))

        requires_depth_map = any(
            binding.source_field == "stage_config.depth_input.resolved_path"
            for binding in spec.input_bindings
        )
        if not requires_depth_map:
            return {
                "camera_intent": camera_intent,
                "controlnet": controlnet,
                "depth_input": depth_input,
            }

        selected_controlnet_model = str(controlnet.get("model") or "depth").strip() or "depth"
        controlnet.setdefault("model", selected_controlnet_model)
        self._ensure_controlnet_model_available(
            spec=spec,
            controlnet_model=selected_controlnet_model,
            object_info=object_info,
        )
        depth_resolution = self._depth_map_resolver.resolve(
            source_image_path=request.input_image_path,
            depth_input=depth_input,
            output_dir=request.output_dir,
        )
        depth_input.update(depth_resolution.to_stage_config())
        stage_config["camera_intent"] = camera_intent
        stage_config["controlnet"] = controlnet
        stage_config["depth_input"] = depth_input
        request.stage_config = stage_config
        return {
            "camera_intent": camera_intent,
            "controlnet": controlnet,
            "depth_input": depth_input,
        }

    def _ensure_controlnet_model_available(
        self,
        *,
        spec: Any,
        controlnet_model: str,
        object_info: Mapping[str, Any] | None = None,
    ) -> None:
        payload = dict(object_info or {})
        if not payload or not _has_model_inventory(payload):
            return
        locator = str(controlnet_model or "").strip() or "depth"
        if _contains_locator(payload, locator):
            return
        raise RuntimeError(
            f"Workflow '{spec.workflow_id}' missing required Comfy ControlNet model/checkpoint '{locator}'. "
            "Install the required ControlNet model, refresh ComfyUI model inventory, and restart ComfyUI before running the conditioned video_workflow stage."
        )

    def execute_segment(
        self,
        pipeline: Any,
        request: VideoExecutionRequest,
        *,
        segment_index: int,
        segment_id: str,
        carry_forward_policy: str,
    ) -> VideoExecutionResult | None:
        """Execute one segment of a multi-segment sequence.

        Delegates to ``execute`` and stamps segment provenance into the
        result's ``raw_result`` and ``backend_metadata`` dicts so that
        callers can identify which segment produced each artifact.
        """
        result = self.execute(pipeline, request)
        if result is None:
            return None
        result.raw_result["segment_index"] = segment_index
        result.raw_result["segment_id"] = segment_id
        result.raw_result["carry_forward_policy"] = carry_forward_policy
        result.backend_metadata["segment_index"] = segment_index
        result.backend_metadata["segment_id"] = segment_id
        result.backend_metadata["carry_forward_policy"] = carry_forward_policy
        return result

    def _resolve_process_manager(self) -> ComfyProcessManager | None:
        return (
            self._process_manager
            or self._managed_process_manager
            or get_global_comfy_process_manager()
        )

    def _verify_required_launch_flags(self, spec: Any) -> None:
        """Refuse unless the StableNew-managed ComfyUI command carries every declared flag.

        The command checked is the one StableNew launches (the resolved manager's, or the default
        managed configuration's).  A runtime StableNew does not launch cannot have its flags
        verified, so it is refused rather than assumed; nothing is started, stopped or changed.
        """

        required = _required_launch_flags(spec)
        if not required:
            return
        manager = self._resolve_process_manager()
        config = getattr(manager, "_config", None) if manager is not None else None
        if config is None and manager is None:
            config = build_default_comfy_process_config()
        command = list(getattr(config, "command", None) or [])
        if not command:
            raise RuntimeError(
                f"Workflow '{spec.workflow_id}' requires a StableNew-managed ComfyUI launched with "
                f"{' '.join(required)}; no managed launch configuration is available and an "
                "external runtime's launch flags cannot be verified. Configure comfy_command in "
                "Engine Settings."
            )
        missing = [flag for flag in required if flag not in command]
        if missing:
            raise RuntimeError(
                f"Workflow '{spec.workflow_id}' requires the managed ComfyUI to be launched with "
                f"{' '.join(missing)}, which the configured comfy_command does not include. Add "
                "it to comfy_command in Engine Settings; StableNew will not rewrite it for you."
            )

    def _release_owned_runtime(self) -> dict[str, Any]:
        """Stop the managed Comfy only when StableNew owns its process; report what happened.

        ``ComfyProcessManager.stop()`` is the only release authority.  A manager that does not own
        its process (an external or adopted-by-nobody runtime) is not even asked to stop.  Never
        raises: a release problem is reported, not allowed to mask the job's own outcome.
        """

        manager = self._resolve_process_manager()
        if manager is None:
            return {"policy": "release_owned_runtime_after_job", "ownership": "none", "released": False}
        try:
            owned = bool(manager.owns_process)
            pid = manager.pid
        except Exception as exc:  # noqa: BLE001 - an unreadable owner is never stopped
            return {
                "policy": "release_owned_runtime_after_job",
                "ownership": "unknown",
                "released": False,
                "error": f"{type(exc).__name__}: {exc}"[:300],
            }
        if not owned:
            return {
                "policy": "release_owned_runtime_after_job",
                "ownership": "not_owned",
                "released": False,
            }
        try:
            manager.stop()
            released = not bool(manager.is_running())
        except Exception as exc:  # noqa: BLE001 - report; never escalate to other processes
            return {
                "policy": "release_owned_runtime_after_job",
                "ownership": "owned",
                "pid": pid,
                "released": False,
                "error": f"{type(exc).__name__}: {exc}"[:300],
            }
        return {
            "policy": "release_owned_runtime_after_job",
            "ownership": "owned",
            "pid": pid,
            "released": released,
        }

    def _ensure_runtime_ready(self) -> str:
        manager = self._resolve_process_manager()
        if manager is not None and self._process_manager is None:
            # Keep one owner object across release/relaunch cycles: after a per-job release the
            # same manager relaunches (and re-registers itself), so the app's exit cleanup and
            # runtime transitions keep tracking the process StableNew owns.
            self._managed_process_manager = manager
        if manager is None:
            if self._client is not None:
                wait_for_comfy_ready(self._base_url, timeout=15.0, poll_interval=0.5)
                return self._base_url
            default_config = build_default_comfy_process_config()
            if default_config is not None:
                manager = ComfyProcessManager(default_config)
                self._managed_process_manager = manager
            else:
                try:
                    wait_for_comfy_ready(self._base_url, timeout=15.0, poll_interval=0.5)
                    return self._base_url
                except Exception as exc:
                    raise RuntimeError(_build_missing_runtime_message(self._base_url, exc)) from exc
        if manager is not None:
            if not manager.ensure_running():
                raise RuntimeError("Managed ComfyUI process failed to become healthy")
            base_url = str(getattr(getattr(manager, "_config", None), "base_url", "") or "").strip()
            return base_url or self._base_url
        wait_for_comfy_ready(self._base_url, timeout=15.0, poll_interval=0.5)
        return self._base_url

    def _build_queue_payload(
        self,
        compiled: Any,
        request: VideoExecutionRequest,
        *,
        client: ComfyApiClient,
        object_info: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        backend_payload = dict(compiled.backend_payload or {})
        prompt_payload = backend_payload.get("prompt")
        if not isinstance(prompt_payload, Mapping) or not prompt_payload:
            raise RuntimeError(
                f"Workflow '{compiled.workflow_id}' compiled without a queueable Comfy prompt payload"
            )
        stage_config = request.stage_config or {}
        if stage_config.get("pose_video_path"):
            self._verify_driving_video_source(
                stage_config["pose_video_path"],
                str(stage_config.get("pose_video_sha256") or ""),
            )
        prompt_payload = self._normalize_prompt_payload_for_comfy(
            prompt_payload,
            client=client,
            object_info=object_info,
        )
        extra_data = {
            "workflow_id": compiled.workflow_id,
            "workflow_version": compiled.workflow_version,
            "backend_id": compiled.backend_id,
            "compiled_inputs": dict(compiled.compiled_inputs),
            "compiled_outputs": dict(compiled.compiled_outputs),
            "compiler_metadata": dict(compiled.compiler_metadata),
        }
        return {
            "prompt": dict(prompt_payload),
            "client_id": str(request.job_id or f"stablenew-{uuid.uuid4().hex}"),
            "extra_data": extra_data,
        }

    def _normalize_prompt_payload_for_comfy(
        self,
        prompt_payload: Mapping[str, Any],
        *,
        client: ComfyApiClient,
        object_info: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        prompt = deepcopy(dict(prompt_payload))
        info = dict(object_info or {})
        uploaded_cache: dict[str, str] = {}

        for node_id, node_payload in prompt.items():
            if not isinstance(node_payload, Mapping):
                continue
            class_type = str(node_payload.get("class_type") or "").strip()
            inputs = node_payload.get("inputs")
            if not class_type or not isinstance(inputs, Mapping):
                continue

            schema = info.get(class_type) or {}
            schema_input = schema.get("input") if isinstance(schema, Mapping) else {}
            required = schema_input.get("required") if isinstance(schema_input, Mapping) else {}
            optional = schema_input.get("optional") if isinstance(schema_input, Mapping) else {}
            hidden = schema_input.get("hidden") if isinstance(schema_input, Mapping) else {}
            input_specs: dict[str, Any] = {}
            if isinstance(required, Mapping):
                input_specs.update(required)
            if isinstance(optional, Mapping):
                input_specs.update(optional)
            if isinstance(hidden, Mapping):
                input_specs.update(hidden)

            normalized_inputs = dict(inputs)
            for input_name, raw_value in inputs.items():
                if self._is_comfy_link_value(raw_value):
                    continue
                if (class_type, input_name) in _UPLOADED_FILE_INPUTS:
                    normalized_inputs[input_name] = self._upload_image_for_load_image(
                        client,
                        raw_value,
                        uploaded_cache,
                    )
                    continue
                declared_type = self._extract_declared_input_type(input_specs.get(input_name))
                normalized_inputs[input_name] = self._coerce_comfy_input_value(
                    raw_value, declared_type
                )
            prompt[node_id] = {
                **dict(node_payload),
                "inputs": normalized_inputs,
            }

        return prompt

    @staticmethod
    def _verify_driving_video_source(raw_value: Any, expected_sha256: str) -> None:
        """Reject a queued driving clip changed since admission before uploading it."""

        path = Path(str(raw_value or "")).expanduser()
        if not expected_sha256 or not path.is_file():
            raise ValueError("Driving video or its admission hash is missing at dispatch")
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected_sha256:
            raise ValueError(f"Driving video changed since queue admission: {path}")

    @staticmethod
    def _is_comfy_link_value(value: Any) -> bool:
        return (
            isinstance(value, list)
            and len(value) == 2
            and isinstance(value[0], str)
            and isinstance(value[1], int)
        )

    @staticmethod
    def _extract_declared_input_type(spec: Any) -> str:
        if isinstance(spec, list) and spec:
            first = spec[0]
            if isinstance(first, str):
                return first
            if isinstance(first, list):
                return "ENUM"
        if isinstance(spec, str):
            return spec
        return ""

    @staticmethod
    def _coerce_comfy_input_value(value: Any, declared_type: str) -> Any:
        if declared_type == "STRING":
            if isinstance(value, str):
                return value
            if isinstance(value, (list, dict)):
                return json.dumps(value)
            return "" if value is None else str(value)
        return value

    @staticmethod
    def _upload_image_for_load_image(
        client: ComfyApiClient,
        raw_value: Any,
        uploaded_cache: dict[str, str],
    ) -> Any:
        path_text = str(raw_value or "").strip()
        if not path_text:
            return raw_value
        path = Path(path_text).expanduser()
        if not path.is_absolute():
            return path_text
        cache_key = str(path.resolve()) if path.exists() else str(path)
        if cache_key in uploaded_cache:
            return uploaded_cache[cache_key]
        uploaded = client.upload_image(path)
        name = str(uploaded.get("name") or path.name).strip()
        subfolder = str(uploaded.get("subfolder") or "").strip().strip("/\\")
        relative_name = f"{subfolder}/{name}" if subfolder else name
        uploaded_cache[cache_key] = relative_name
        return relative_name

    @staticmethod
    def _liveness_reporter(
        pipeline: Any, request: VideoExecutionRequest
    ) -> Callable[[float], None] | None:
        """Bind execution liveness to the runner-owned job through the existing runtime-status path.

        This is *not* generation progress: no percentage or step count is invented (the status
        merge keeps whatever was last real).  Only the elapsed time of a prompt the Comfy server
        confirms is still running is reported, as a change in the job's ``stage_detail``.
        """

        emit = getattr(pipeline, "_emit_status_update", None)
        job_id = str(getattr(request, "job_id", "") or "").strip()
        if not callable(emit) or not job_id:
            return None

        def _report(elapsed_s: float) -> None:
            # Best-effort observability: a failed status emit must never abort the generation wait.
            try:
                emit(
                    {
                        "job_id": job_id,
                        "current_stage": request.stage_name,
                        "stage_detail": f"comfy executing ({int(elapsed_s)}s)",
                    }
                )
            except Exception:
                pass

        return _report

    def _history_timeout_for(self, spec: Any) -> float:
        """A workflow may declare a longer generation wait than the backend default (long
        generations would otherwise be abandoned while Comfy is still producing them)."""

        declared = (getattr(spec, "backend_defaults", None) or {}).get("history_timeout_seconds")
        try:
            return max(self._history_timeout, float(declared or 0))
        except (TypeError, ValueError):
            return self._history_timeout

    def _wait_for_history_entry(
        self,
        client: ComfyApiClient,
        *,
        prompt_id: str,
        report_liveness: Callable[[float], None] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        started = time.time()
        deadline = started + (timeout if timeout is not None else self._history_timeout)
        last_report: float | None = None
        last_payload: dict[str, Any] | None = None
        while time.time() < deadline:
            payload = client.get_history(prompt_id)
            last_payload = dict(payload or {})
            entry = _history_entry_from_payload(last_payload, prompt_id)
            if entry and _history_ready(entry):
                return entry
            now = time.time()
            if (
                report_liveness is not None
                and (last_report is None or now - last_report >= _LIVENESS_REPORT_INTERVAL_S)
                and (entry is not None or _prompt_is_live(client, prompt_id))
            ):
                last_report = now
                report_liveness(now - started)
            time.sleep(self._history_poll_interval)
        raise TimeoutError(
            f"Timed out waiting for Comfy workflow history for prompt_id '{prompt_id}'"
        )

    @staticmethod
    def _localize_comfy_outputs(
        client: ComfyApiClient, history_entry: Mapping[str, Any], output_dir: Path
    ) -> dict[str, Any]:
        """Fetch Comfy-side outputs into the StableNew run directory (which stays the artifact
        authority) and point the history descriptors at the local copies."""

        localized = deepcopy(dict(history_entry))
        outputs = localized.get("outputs")
        if not isinstance(outputs, dict):
            return localized
        for node_payload in outputs.values():
            if not isinstance(node_payload, dict):
                continue
            for key in ("gifs", "videos", "images"):
                descriptors = node_payload.get(key)
                if not isinstance(descriptors, list):
                    continue
                for descriptor in descriptors:
                    if not isinstance(descriptor, dict) or not descriptor.get("filename"):
                        continue
                    if not _is_generated_output(descriptor):
                        continue
                    name = str(descriptor["filename"])
                    local = client.download_view(
                        name,
                        output_dir / Path(name).name,
                        subfolder=str(descriptor.get("subfolder") or ""),
                        file_type=str(descriptor.get("type") or "output"),
                    )
                    # Absolute, so a relative run directory is never joined onto itself.
                    descriptor["filename"] = str(Path(local).resolve())
                    descriptor["subfolder"] = ""
        return localized

    def _resolve_output_paths(
        self,
        *,
        history_entry: Mapping[str, Any],
        compiled_outputs: Mapping[str, Any],
    ) -> dict[str, Any]:
        output_dir = Path(str(compiled_outputs.get("output_dir") or "")).expanduser()
        filenames: list[str] = []
        outputs = history_entry.get("outputs")
        if isinstance(outputs, Mapping):
            for node_payload in outputs.values():
                if not isinstance(node_payload, Mapping):
                    continue
                for key in ("gifs", "videos", "images"):
                    descriptors = node_payload.get(key)
                    if not isinstance(descriptors, list):
                        continue
                    for descriptor in descriptors:
                        if not isinstance(descriptor, Mapping) or not _is_generated_output(
                            descriptor
                        ):
                            continue
                        resolved = self._resolve_descriptor_path(descriptor, output_dir)
                        if resolved:
                            filenames.append(resolved)

        discovered_paths = _dedupe_paths(filenames)
        if not discovered_paths and output_dir:
            output_name = str(compiled_outputs.get("output_name") or "").strip()
            if output_name:
                discovered_paths = _dedupe_paths(
                    [
                        str(path)
                        for path in sorted(output_dir.glob(f"{output_name}*"))
                        if path.is_file()
                    ]
                )

        video_paths = [
            path
            for path in discovered_paths
            if Path(path).suffix.lower() in {".mp4", ".mov", ".webm", ".mkv"}
        ]
        gif_paths = [path for path in discovered_paths if Path(path).suffix.lower() == ".gif"]
        frame_paths = [
            path
            for path in discovered_paths
            if Path(path).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
        ]
        output_paths = video_paths + gif_paths if (video_paths or gif_paths) else frame_paths
        primary_path = next(iter(video_paths or gif_paths or frame_paths or output_paths), None)
        thumbnail_path = next(iter(frame_paths), None)
        return {
            "primary_path": primary_path,
            "output_paths": output_paths,
            "video_path": next(iter(video_paths), None),
            "video_paths": video_paths,
            "gif_path": next(iter(gif_paths), None),
            "gif_paths": gif_paths,
            "frame_paths": frame_paths,
            "thumbnail_path": thumbnail_path,
        }

    def _resolve_descriptor_path(
        self,
        descriptor: Mapping[str, Any],
        output_dir: Path,
    ) -> str | None:
        filename = str(descriptor.get("filename") or "").strip()
        if not filename:
            return None
        candidate = Path(filename)
        if candidate.is_absolute():
            return str(candidate)
        subfolder = str(descriptor.get("subfolder") or "").strip()
        if output_dir:
            resolved = output_dir / subfolder / filename if subfolder else output_dir / filename
            return str(resolved)
        return str(candidate)

    def _write_manifest(
        self,
        *,
        request: VideoExecutionRequest,
        prompt_id: str,
        spec: Any,
        compiled: dict[str, Any],
        dependency_probe: dict[str, Any],
        queue_response: Mapping[str, Any],
        history_entry: Mapping[str, Any],
        resolved_outputs: Mapping[str, Any],
        conditioning: Mapping[str, Any],
        provenance_extra: Mapping[str, Any] | None = None,
    ) -> Path:
        output_dir = Path(request.output_dir)
        manifest_dir = output_dir / "manifests"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_stem = Path(str(resolved_outputs["primary_path"])).stem
        manifest_path = manifest_dir / f"{manifest_stem}.json"
        payload = {
            "schema_version": "1.0",
            "backend_id": self.backend_id,
            "workflow_id": spec.workflow_id,
            "workflow_version": spec.workflow_version,
            "prompt_id": prompt_id,
            "source_image_path": str(request.input_image_path)
            if request.input_image_path
            else None,
            "start_anchor_path": str(request.input_image_path)
            if request.input_image_path
            else None,
            "end_anchor_path": str(request.end_anchor_path) if request.end_anchor_path else None,
            "mid_anchor_paths": [str(path) for path in request.mid_anchor_paths or []],
            "prompt": request.prompt,
            "negative_prompt": request.negative_prompt,
            "motion_profile": request.motion_profile,
            "conditioning": dict(conditioning),
            "output_paths": list(resolved_outputs["output_paths"]),
            "video_path": resolved_outputs["video_path"],
            "video_paths": list(resolved_outputs["video_paths"]),
            "gif_path": resolved_outputs["gif_path"],
            "gif_paths": list(resolved_outputs["gif_paths"]),
            "frame_paths": list(resolved_outputs["frame_paths"]),
            "frame_path_count": len(resolved_outputs["frame_paths"]),
            "thumbnail_path": resolved_outputs["thumbnail_path"],
            "manifest_paths": [str(manifest_path)],
            "count": len(resolved_outputs["output_paths"]),
            "compiled_workflow": compiled,
            "dependency_probe": dependency_probe,
            "queue_response": dict(queue_response),
            "history_entry": dict(history_entry),
            "artifact": artifact_manifest_payload(
                stage=request.stage_name,
                image_or_output_path=str(resolved_outputs["primary_path"]),
                manifest_path=manifest_path,
                output_paths=list(resolved_outputs["output_paths"]),
                thumbnail_path=resolved_outputs["thumbnail_path"],
                input_image_path=request.input_image_path,
                artifact_type="video",
            ),
        }
        if resolved_outputs.get("secondary_motion"):
            payload["secondary_motion"] = dict(resolved_outputs["secondary_motion"])
            payload["secondary_motion_summary"] = dict(
                resolved_outputs.get("secondary_motion_summary") or {}
            )
            payload["secondary_motion_source_video_path"] = resolved_outputs.get(
                "secondary_motion_source_video_path"
            )
        payload.update(dict(provenance_extra or {}))
        manifest_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return manifest_path


__all__ = ["ComfyWorkflowVideoBackend"]
