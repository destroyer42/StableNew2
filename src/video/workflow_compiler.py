from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re
from typing import Any

from src.video.video_backend_types import VideoExecutionRequest
from src.video.workflow_contracts import CompiledWorkflowRequest, WorkflowSpec
from src.video.workflow_registry import WorkflowRegistry


def _normalize_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return [_normalize_value(item) for item in value]
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _normalize_value(item) for key, item in value.items()}
    return value


def _is_missing(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _extract_field_value(request: VideoExecutionRequest, source_field: str) -> Any:
    parts = [part for part in str(source_field or "").split(".") if part]
    if not parts:
        return None

    current: Any = request
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
            continue
        if hasattr(current, part):
            current = getattr(current, part)
            continue
        return None
    return _normalize_value(current)


_TEMPLATE_PATTERN = re.compile(r"\{\{\s*([a-zA-Z0-9_.-]+)\s*\}\}")


def _resolve_template_value(context: dict[str, Any], key_path: str) -> Any:
    current: Any = context
    for part in [part for part in str(key_path or "").split(".") if part]:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _render_template_string(template: str, context: dict[str, Any]) -> Any:
    matches = list(_TEMPLATE_PATTERN.finditer(template))
    if not matches:
        return template
    if len(matches) == 1 and matches[0].span() == (0, len(template)):
        return _normalize_value(_resolve_template_value(context, matches[0].group(1)))

    rendered = template
    for match in matches:
        resolved = _resolve_template_value(context, match.group(1))
        replacement = "" if resolved is None else str(_normalize_value(resolved))
        rendered = rendered.replace(match.group(0), replacement)
    return rendered


def _render_template_value(template: Any, context: dict[str, Any]) -> Any:
    if isinstance(template, str):
        return _render_template_string(template, context)
    if isinstance(template, list):
        return [_render_template_value(item, context) for item in template]
    if isinstance(template, dict):
        return {
            str(key): _render_template_value(value, context)
            for key, value in template.items()
        }
    return _normalize_value(template)


class WorkflowCompiler:
    def compile(
        self,
        spec: WorkflowSpec,
        request: VideoExecutionRequest,
    ) -> CompiledWorkflowRequest:
        compiled_inputs: dict[str, Any] = {}
        backend_inputs: dict[str, Any] = {}

        for binding in spec.input_bindings:
            value = _extract_field_value(request, binding.source_field)
            if _is_missing(value):
                if binding.required:
                    raise ValueError(
                        f"Workflow '{spec.workflow_id}' requires input '{binding.binding_name}' "
                        f"from '{binding.source_field}'"
                    )
                continue
            compiled_inputs[binding.binding_name] = value
            backend_inputs[binding.backend_key or binding.binding_name] = value

        compiled_outputs: dict[str, Any] = {}
        backend_outputs: dict[str, Any] = {}
        for binding in spec.output_bindings:
            value = _extract_field_value(request, binding.source_field)
            if _is_missing(value):
                if binding.required:
                    raise ValueError(
                        f"Workflow '{spec.workflow_id}' requires output binding '{binding.binding_name}' "
                        f"from '{binding.source_field}'"
                    )
                continue
            compiled_outputs[binding.binding_name] = value
            backend_outputs[binding.backend_key or binding.binding_name] = value

        payload = deepcopy(spec.backend_defaults)
        payload_inputs = dict(payload.get("inputs") or {})
        payload_outputs = dict(payload.get("outputs") or {})
        payload_inputs.update(backend_inputs)
        payload_outputs.update(backend_outputs)
        payload["workflow_id"] = spec.workflow_id
        payload["workflow_version"] = spec.workflow_version
        payload["backend_id"] = spec.backend_id
        payload["inputs"] = payload_inputs
        payload["outputs"] = payload_outputs

        if request.backend_options:
            payload["backend_options"] = _normalize_value(request.backend_options)
        if request.workflow_inputs:
            payload["workflow_inputs"] = _normalize_value(request.workflow_inputs)
        prompt_template = payload.get("prompt_template")
        if prompt_template:
            payload["prompt"] = _render_template_value(
                prompt_template,
                {
                    "input": deepcopy(compiled_inputs),
                    "output": deepcopy(compiled_outputs),
                    "workflow": {
                        "id": spec.workflow_id,
                        "version": spec.workflow_version,
                        "backend_id": spec.backend_id,
                    },
                    "request": {
                        "job_id": request.job_id,
                        "stage_name": request.stage_name,
                        "image_name": request.image_name,
                    },
                },
            )

        dependency_snapshot = {
            dependency.dependency_id: dependency.to_dict() for dependency in spec.dependency_specs
        }

        return CompiledWorkflowRequest(
            workflow_id=spec.workflow_id,
            workflow_version=spec.workflow_version,
            backend_id=spec.backend_id,
            capability_tags=tuple(spec.capability_tags),
            compiled_inputs=compiled_inputs,
            compiled_outputs=compiled_outputs,
            backend_payload=payload,
            dependency_snapshot=dependency_snapshot,
            compiler_metadata={
                "stage_name": request.stage_name,
                "job_id": request.job_id,
                "request_backend_id": request.backend_id,
            },
        )

    def compile_registered(
        self,
        registry: WorkflowRegistry,
        *,
        workflow_id: str,
        request: VideoExecutionRequest,
        workflow_version: str | None = None,
    ) -> CompiledWorkflowRequest:
        spec = registry.get(workflow_id, workflow_version)
        return self.compile(spec, request)


__all__ = ["WorkflowCompiler"]
