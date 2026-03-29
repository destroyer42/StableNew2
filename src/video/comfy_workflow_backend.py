from __future__ import annotations

import json
import time
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from src.pipeline.artifact_contract import artifact_manifest_payload
from src.video.video_artifact_helpers import build_video_artifact_bundle
from src.video.container_metadata import write_video_container_metadata
from src.video.comfy_api_client import ComfyApiClient
from src.video.comfy_dependency_probe import ComfyDependencyProbe
from src.video.comfy_healthcheck import wait_for_comfy_ready
from src.video.comfy_process_manager import (
    ComfyProcessManager,
    build_default_comfy_process_config,
    get_global_comfy_process_manager,
)
from src.video.motion.secondary_motion_provenance import extract_secondary_motion_summary
from src.video.motion.secondary_motion_video_reencode import apply_secondary_motion_to_video
from src.video.video_backend_types import (
    VideoBackendCapabilities,
    VideoExecutionRequest,
    VideoExecutionResult,
)
from src.video.workflow_compiler import WorkflowCompiler
from src.video.workflow_registry import WorkflowRegistry, build_default_workflow_registry


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


def _history_entry_from_payload(payload: Mapping[str, Any], prompt_id: str) -> dict[str, Any] | None:
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
        requires_input_image=True,
        supports_prompt_text=True,
        supports_negative_prompt=True,
        supports_multiple_anchors=True,
    )

    def __init__(
        self,
        *,
        workflow_registry: WorkflowRegistry | None = None,
        compiler: WorkflowCompiler | None = None,
        client: ComfyApiClient | None = None,
        dependency_probe: ComfyDependencyProbe | None = None,
        process_manager: ComfyProcessManager | None = None,
        base_url: str = "http://127.0.0.1:8188",
        history_poll_interval: float = 0.5,
        history_timeout: float = 120.0,
    ) -> None:
        self._workflow_registry = workflow_registry or build_default_workflow_registry()
        self._compiler = compiler or WorkflowCompiler()
        self._client = client
        self._dependency_probe = dependency_probe
        self._process_manager = process_manager
        self._managed_process_manager: ComfyProcessManager | None = None
        self._base_url = str(base_url or "http://127.0.0.1:8188").rstrip("/")
        self._history_poll_interval = max(history_poll_interval, 0.1)
        self._history_timeout = max(history_timeout, 5.0)

    def execute(self, pipeline: Any, request: VideoExecutionRequest) -> VideoExecutionResult | None:
        stage_config = dict(request.stage_config or {})
        workflow_id = str(
            request.workflow_id
            or stage_config.get("workflow_id")
            or stage_config.get("id")
            or ""
        ).strip()
        workflow_version = str(
            request.workflow_version
            or stage_config.get("workflow_version")
            or stage_config.get("version")
            or ""
        ).strip() or None
        if not workflow_id:
            raise ValueError("video_workflow stage requires workflow_id")

        runtime_base_url = self._ensure_runtime_ready()
        client = self._client or ComfyApiClient(base_url=runtime_base_url)
        spec = self._workflow_registry.get(workflow_id, workflow_version)
        if spec.backend_id != self.backend_id:
            raise ValueError(
                f"Workflow '{spec.workflow_id}' is registered for backend '{spec.backend_id}', "
                f"not '{self.backend_id}'"
            )

        object_info = client.get_object_info()
        probe = self._dependency_probe or ComfyDependencyProbe(client)
        dependency_result = probe.probe_workflow(spec, object_info=object_info)
        if not dependency_result.ready:
            raise RuntimeError(_format_missing_dependency_message(spec, dependency_result))

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

        history_entry = self._wait_for_history_entry(client, prompt_id=prompt_id)
        resolved_outputs = self._resolve_output_paths(
            history_entry=history_entry,
            compiled_outputs=compiled.compiled_outputs,
        )
        secondary_motion_block = stage_config.get("secondary_motion") if isinstance(stage_config.get("secondary_motion"), dict) else None
        if isinstance(secondary_motion_block, dict) and secondary_motion_block.get("enabled") and resolved_outputs.get("video_path"):
            motion_result = apply_secondary_motion_to_video(
                video_path=str(resolved_outputs["video_path"]),
                output_dir=request.output_dir,
                runtime_block=secondary_motion_block,
                fps=int(stage_config.get("fps") or stage_config.get("video_fps") or 8),
            )
            motion_summary = motion_result.get("secondary_motion_summary") or extract_secondary_motion_summary(motion_result)
            resolved_outputs.update(
                {
                    "secondary_motion_source_video_path": str(
                        motion_result.get("source_video_path") or resolved_outputs.get("video_path") or ""
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

        manifest_path = self._write_manifest(
            request=request,
            prompt_id=prompt_id,
            spec=spec,
            compiled=compiled.to_dict(),
            dependency_probe=dependency_result.to_dict(),
            queue_response=queue_response,
            history_entry=history_entry,
            resolved_outputs=resolved_outputs,
        )
        metadata_payload = {
            "stage": request.stage_name,
            "backend_id": self.backend_id,
            "job_id": request.job_id,
            "run_id": Path(request.output_dir).name,
            "title": request.image_name or Path(str(resolved_outputs["primary_path"] or "video")).stem,
            "prompt": request.prompt,
            "negative_prompt": request.negative_prompt,
            "source_image_path": str(request.input_image_path) if request.input_image_path else None,
            "end_anchor_path": str(request.end_anchor_path) if request.end_anchor_path else None,
            "mid_anchor_paths": [str(path) for path in request.mid_anchor_paths or []],
            "motion_profile": request.motion_profile,
            "workflow_id": spec.workflow_id,
            "workflow_version": spec.workflow_version,
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
        if resolved_outputs.get("secondary_motion"):
            metadata_payload["secondary_motion"] = dict(resolved_outputs["secondary_motion"])
            metadata_payload["secondary_motion_summary"] = dict(resolved_outputs.get("secondary_motion_summary") or {})
            metadata_payload["secondary_motion_source_video_path"] = resolved_outputs.get("secondary_motion_source_video_path")
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
            "source_image_path": str(request.input_image_path) if request.input_image_path else None,
            "workflow_id": spec.workflow_id,
            "workflow_version": spec.workflow_version,
            "prompt_id": prompt_id,
            "dependency_probe": dependency_result.to_dict(),
            "compiled_workflow": compiled.to_dict(),
            "secondary_motion": dict(resolved_outputs.get("secondary_motion") or {}),
            "secondary_motion_summary": dict(resolved_outputs.get("secondary_motion_summary") or {}),
            "secondary_motion_source_video_path": resolved_outputs.get("secondary_motion_source_video_path"),
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
                source_image_path=str(request.input_image_path) if request.input_image_path else None,
            ),
        }
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
            },
            diagnostic_payload={
                "queue_response": dict(queue_response),
                "dependency_probe": dependency_result.to_dict(),
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
                "secondary_motion": dict(resolved_outputs.get("secondary_motion") or {}),
                "secondary_motion_summary": dict(resolved_outputs.get("secondary_motion_summary") or {}),
                "secondary_motion_source_video_path": resolved_outputs.get("secondary_motion_source_video_path"),
            },
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

    def _ensure_runtime_ready(self) -> str:
        manager = (
            self._process_manager
            or self._managed_process_manager
            or get_global_comfy_process_manager()
        )
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
                if class_type == "LoadImage" and input_name == "image":
                    normalized_inputs[input_name] = self._upload_image_for_load_image(
                        client,
                        raw_value,
                        uploaded_cache,
                    )
                    continue
                declared_type = self._extract_declared_input_type(input_specs.get(input_name))
                normalized_inputs[input_name] = self._coerce_comfy_input_value(raw_value, declared_type)
            prompt[node_id] = {
                **dict(node_payload),
                "inputs": normalized_inputs,
            }

        return prompt

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

    def _wait_for_history_entry(
        self,
        client: ComfyApiClient,
        *,
        prompt_id: str,
    ) -> dict[str, Any]:
        deadline = time.time() + self._history_timeout
        last_payload: dict[str, Any] | None = None
        while time.time() < deadline:
            payload = client.get_history(prompt_id)
            last_payload = dict(payload or {})
            entry = _history_entry_from_payload(last_payload, prompt_id)
            if entry and _history_ready(entry):
                return entry
            time.sleep(self._history_poll_interval)
        raise TimeoutError(
            f"Timed out waiting for Comfy workflow history for prompt_id '{prompt_id}'"
        )

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
                        if not isinstance(descriptor, Mapping):
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

        video_paths = [path for path in discovered_paths if Path(path).suffix.lower() in {".mp4", ".mov", ".webm", ".mkv"}]
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
            "source_image_path": str(request.input_image_path) if request.input_image_path else None,
            "start_anchor_path": str(request.input_image_path) if request.input_image_path else None,
            "end_anchor_path": str(request.end_anchor_path) if request.end_anchor_path else None,
            "mid_anchor_paths": [str(path) for path in request.mid_anchor_paths or []],
            "prompt": request.prompt,
            "negative_prompt": request.negative_prompt,
            "motion_profile": request.motion_profile,
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
            payload["secondary_motion_summary"] = dict(resolved_outputs.get("secondary_motion_summary") or {})
            payload["secondary_motion_source_video_path"] = resolved_outputs.get("secondary_motion_source_video_path")
        manifest_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return manifest_path


__all__ = ["ComfyWorkflowVideoBackend"]
