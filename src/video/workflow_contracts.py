from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


WORKFLOW_CAP_SINGLE_IMAGE_TO_VIDEO = "single_image_to_video"
WORKFLOW_CAP_MULTI_FRAME_ANCHOR_VIDEO = "multi_frame_anchor_video"
WORKFLOW_CAP_SEGMENT_STITCHABLE = "segment_stitchable"
WORKFLOW_CAP_LOCAL_PROCESS_REQUIRED = "local_process_required"

KNOWN_WORKFLOW_CAPABILITY_TAGS = {
    WORKFLOW_CAP_SINGLE_IMAGE_TO_VIDEO,
    WORKFLOW_CAP_MULTI_FRAME_ANCHOR_VIDEO,
    WORKFLOW_CAP_SEGMENT_STITCHABLE,
    WORKFLOW_CAP_LOCAL_PROCESS_REQUIRED,
}


def _normalized_text(value: str) -> str:
    return str(value or "").strip()


def _mapping_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return deepcopy(value)
    return {}


@dataclass(frozen=True, slots=True)
class WorkflowDependencySpec:
    dependency_id: str
    dependency_kind: str
    locator: str
    required: bool = True
    description: str = ""
    version_hint: str = ""

    def __post_init__(self) -> None:
        if not _normalized_text(self.dependency_id):
            raise ValueError("Workflow dependency declarations require a non-empty dependency_id")
        if not _normalized_text(self.dependency_kind):
            raise ValueError("Workflow dependency declarations require a non-empty dependency_kind")
        if not _normalized_text(self.locator):
            raise ValueError("Workflow dependency declarations require a non-empty locator")

    def to_dict(self) -> dict[str, Any]:
        return {
            "dependency_id": self.dependency_id,
            "dependency_kind": self.dependency_kind,
            "locator": self.locator,
            "required": bool(self.required),
            "description": self.description,
            "version_hint": self.version_hint,
        }


@dataclass(frozen=True, slots=True)
class WorkflowInputBinding:
    binding_name: str
    source_field: str
    backend_key: str | None = None
    required: bool = True
    description: str = ""

    def __post_init__(self) -> None:
        if not _normalized_text(self.binding_name):
            raise ValueError("Workflow input bindings require a non-empty binding_name")
        if not _normalized_text(self.source_field):
            raise ValueError("Workflow input bindings require a non-empty source_field")

    def to_dict(self) -> dict[str, Any]:
        return {
            "binding_name": self.binding_name,
            "source_field": self.source_field,
            "backend_key": self.backend_key,
            "required": bool(self.required),
            "description": self.description,
        }


@dataclass(frozen=True, slots=True)
class WorkflowOutputBinding:
    binding_name: str
    source_field: str
    backend_key: str | None = None
    required: bool = False
    artifact_type: str = "video"
    description: str = ""

    def __post_init__(self) -> None:
        if not _normalized_text(self.binding_name):
            raise ValueError("Workflow output bindings require a non-empty binding_name")
        if not _normalized_text(self.source_field):
            raise ValueError("Workflow output bindings require a non-empty source_field")
        if not _normalized_text(self.artifact_type):
            raise ValueError("Workflow output bindings require a non-empty artifact_type")

    def to_dict(self) -> dict[str, Any]:
        return {
            "binding_name": self.binding_name,
            "source_field": self.source_field,
            "backend_key": self.backend_key,
            "required": bool(self.required),
            "artifact_type": self.artifact_type,
            "description": self.description,
        }


@dataclass(frozen=True, slots=True)
class WorkflowSpec:
    workflow_id: str
    workflow_version: str
    backend_id: str
    display_name: str
    description: str = ""
    capability_tags: tuple[str, ...] = ()
    input_bindings: tuple[WorkflowInputBinding, ...] = ()
    output_bindings: tuple[WorkflowOutputBinding, ...] = ()
    dependency_specs: tuple[WorkflowDependencySpec, ...] = ()
    backend_defaults: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not _normalized_text(self.workflow_id):
            raise ValueError("Workflow specs require a non-empty workflow_id")
        if not _normalized_text(self.workflow_version):
            raise ValueError("Workflow specs require a non-empty workflow_version")
        if not _normalized_text(self.backend_id):
            raise ValueError("Workflow specs require a non-empty backend_id")
        if not _normalized_text(self.display_name):
            raise ValueError("Workflow specs require a non-empty display_name")
        if not self.input_bindings:
            raise ValueError("Workflow specs must declare at least one input binding")
        if not self.output_bindings:
            raise ValueError("Workflow specs must declare at least one output binding")
        if not self.dependency_specs:
            raise ValueError("Workflow specs must declare at least one dependency spec")

        unknown_capabilities = sorted(set(self.capability_tags) - KNOWN_WORKFLOW_CAPABILITY_TAGS)
        if unknown_capabilities:
            raise ValueError(
                f"Workflow '{self.workflow_id}' declares unknown capability tags: {unknown_capabilities}"
            )

        input_names = [binding.binding_name for binding in self.input_bindings]
        if len(input_names) != len(set(input_names)):
            raise ValueError(f"Workflow '{self.workflow_id}' declares duplicate input binding names")
        input_backend_keys = [
            binding.backend_key or binding.binding_name for binding in self.input_bindings
        ]
        if len(input_backend_keys) != len(set(input_backend_keys)):
            raise ValueError(f"Workflow '{self.workflow_id}' declares duplicate input backend keys")

        output_names = [binding.binding_name for binding in self.output_bindings]
        if len(output_names) != len(set(output_names)):
            raise ValueError(f"Workflow '{self.workflow_id}' declares duplicate output binding names")
        output_backend_keys = [
            binding.backend_key or binding.binding_name for binding in self.output_bindings
        ]
        if len(output_backend_keys) != len(set(output_backend_keys)):
            raise ValueError(f"Workflow '{self.workflow_id}' declares duplicate output backend keys")

        dependency_ids = [dependency.dependency_id for dependency in self.dependency_specs]
        if len(dependency_ids) != len(set(dependency_ids)):
            raise ValueError(f"Workflow '{self.workflow_id}' declares duplicate dependency ids")

        object.__setattr__(
            self,
            "capability_tags",
            tuple(sorted({_normalized_text(tag) for tag in self.capability_tags if _normalized_text(tag)})),
        )
        object.__setattr__(self, "backend_defaults", _mapping_dict(self.backend_defaults))

    @property
    def registry_key(self) -> tuple[str, str]:
        return (self.workflow_id, self.workflow_version)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "workflow_version": self.workflow_version,
            "backend_id": self.backend_id,
            "display_name": self.display_name,
            "description": self.description,
            "capability_tags": list(self.capability_tags),
            "input_bindings": [binding.to_dict() for binding in self.input_bindings],
            "output_bindings": [binding.to_dict() for binding in self.output_bindings],
            "dependency_specs": [dependency.to_dict() for dependency in self.dependency_specs],
            "backend_defaults": _mapping_dict(self.backend_defaults),
        }


@dataclass(frozen=True, slots=True)
class CompiledWorkflowRequest:
    workflow_id: str
    workflow_version: str
    backend_id: str
    capability_tags: tuple[str, ...]
    compiled_inputs: dict[str, Any] = field(default_factory=dict)
    compiled_outputs: dict[str, Any] = field(default_factory=dict)
    backend_payload: dict[str, Any] = field(default_factory=dict)
    dependency_snapshot: dict[str, Any] = field(default_factory=dict)
    compiler_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "workflow_version": self.workflow_version,
            "backend_id": self.backend_id,
            "capability_tags": list(self.capability_tags),
            "compiled_inputs": _mapping_dict(self.compiled_inputs),
            "compiled_outputs": _mapping_dict(self.compiled_outputs),
            "backend_payload": _mapping_dict(self.backend_payload),
            "dependency_snapshot": _mapping_dict(self.dependency_snapshot),
            "compiler_metadata": _mapping_dict(self.compiler_metadata),
        }


__all__ = [
    "CompiledWorkflowRequest",
    "KNOWN_WORKFLOW_CAPABILITY_TAGS",
    "WORKFLOW_CAP_LOCAL_PROCESS_REQUIRED",
    "WORKFLOW_CAP_MULTI_FRAME_ANCHOR_VIDEO",
    "WORKFLOW_CAP_SEGMENT_STITCHABLE",
    "WORKFLOW_CAP_SINGLE_IMAGE_TO_VIDEO",
    "WorkflowDependencySpec",
    "WorkflowInputBinding",
    "WorkflowOutputBinding",
    "WorkflowSpec",
]
