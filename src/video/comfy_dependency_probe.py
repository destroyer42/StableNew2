from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from src.video.comfy_api_client import ComfyApiClient
from src.video.workflow_contracts import WorkflowDependencySpec, WorkflowSpec


def _contains_locator(payload: Any, locator: str) -> bool:
    needle = str(locator or "").strip().lower()
    if not needle:
        return False
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            if needle in str(key).lower() or _contains_locator(value, locator):
                return True
        return False
    if isinstance(payload, (list, tuple, set)):
        return any(_contains_locator(item, locator) for item in payload)
    return needle in str(payload).lower()


@dataclass(frozen=True, slots=True)
class DependencyProbeResult:
    ready: bool
    present: tuple[str, ...] = ()
    missing_required: tuple[str, ...] = ()
    missing_optional: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": bool(self.ready),
            "present": list(self.present),
            "missing_required": list(self.missing_required),
            "missing_optional": list(self.missing_optional),
            "details": dict(self.details or {}),
        }


class ComfyDependencyProbe:
    def __init__(self, client: ComfyApiClient | None = None) -> None:
        self._client = client

    def probe_workflow(
        self,
        spec: WorkflowSpec,
        *,
        object_info: Mapping[str, Any] | None = None,
    ) -> DependencyProbeResult:
        payload: Mapping[str, Any]
        if object_info is not None:
            payload = object_info
        elif self._client is not None:
            payload = self._client.get_object_info()
        else:
            raise ValueError("ComfyDependencyProbe requires a client or explicit object_info payload")

        present: list[str] = []
        missing_required: list[str] = []
        missing_optional: list[str] = []
        details: dict[str, Any] = {}

        for dependency in spec.dependency_specs:
            found = _contains_locator(payload, dependency.locator)
            details[dependency.dependency_id] = {
                "found": found,
                "locator": dependency.locator,
                "dependency_kind": dependency.dependency_kind,
                "required": bool(dependency.required),
            }
            if found:
                present.append(dependency.dependency_id)
            elif dependency.required:
                missing_required.append(dependency.dependency_id)
            else:
                missing_optional.append(dependency.dependency_id)

        return DependencyProbeResult(
            ready=not missing_required,
            present=tuple(sorted(present)),
            missing_required=tuple(sorted(missing_required)),
            missing_optional=tuple(sorted(missing_optional)),
            details=details,
        )


__all__ = ["ComfyDependencyProbe", "DependencyProbeResult"]
