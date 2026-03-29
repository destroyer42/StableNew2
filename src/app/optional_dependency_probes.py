from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from src.video.comfy_dependency_probe import ComfyDependencyProbe
from src.video.svd_capabilities import get_svd_postprocess_capabilities
from src.video.workflow_registry import build_default_workflow_registry


OPTIONAL_DEPENDENCY_SCHEMA_V1 = "stablenew.optional-dependencies.v1"


@dataclass(frozen=True, slots=True)
class OptionalDependencyCapability:
    capability_id: str
    available: bool
    status: str
    detail: str
    source: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class OptionalDependencySnapshot:
    schema: str = OPTIONAL_DEPENDENCY_SCHEMA_V1
    capabilities: dict[str, OptionalDependencyCapability] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "capabilities": {
                capability_id: capability.to_dict()
                for capability_id, capability in sorted(self.capabilities.items())
            },
        }


def build_optional_dependency_snapshot(
    *,
    comfy_object_info: dict[str, Any] | None = None,
    comfy_client: Any | None = None,
    svd_config: Any | None = None,
) -> OptionalDependencySnapshot:
    capabilities: dict[str, OptionalDependencyCapability] = {}

    registry = build_default_workflow_registry()
    for spec in registry.list_specs_for_backend("comfy"):
        capability_id = f"workflow:{spec.workflow_id}@{spec.workflow_version}"
        if comfy_object_info is None and comfy_client is None:
            capabilities[capability_id] = OptionalDependencyCapability(
                capability_id=capability_id,
                available=False,
                status="unknown",
                detail="Comfy object info unavailable during startup probe",
                source="comfy",
                metadata={"workflow_id": spec.workflow_id, "workflow_version": spec.workflow_version},
            )
            continue
        try:
            result = ComfyDependencyProbe(client=comfy_client).probe_workflow(
                spec,
                object_info=comfy_object_info,
            )
            capabilities[capability_id] = OptionalDependencyCapability(
                capability_id=capability_id,
                available=result.ready,
                status="ready" if result.ready else "missing",
                detail=(
                    "Dependencies satisfied"
                    if result.ready
                    else "Missing required dependencies: " + ", ".join(result.missing_required)
                ),
                source="comfy",
                metadata=result.to_dict(),
            )
        except Exception as exc:
            capabilities[capability_id] = OptionalDependencyCapability(
                capability_id=capability_id,
                available=False,
                status="error",
                detail=str(exc),
                source="comfy",
                metadata={"workflow_id": spec.workflow_id, "workflow_version": spec.workflow_version},
            )

    for key, capability in get_svd_postprocess_capabilities(svd_config).items():
        capability_id = f"svd:{key}"
        capabilities[capability_id] = OptionalDependencyCapability(
            capability_id=capability_id,
            available=capability.available,
            status=capability.status,
            detail=capability.detail,
            source="svd",
            metadata=capability.to_dict(),
        )

    return OptionalDependencySnapshot(capabilities=capabilities)


__all__ = [
    "OPTIONAL_DEPENDENCY_SCHEMA_V1",
    "OptionalDependencyCapability",
    "OptionalDependencySnapshot",
    "build_optional_dependency_snapshot",
]
