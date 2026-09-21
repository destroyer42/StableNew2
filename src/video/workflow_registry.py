from __future__ import annotations

from src.video.workflow_catalog import build_builtin_workflow_specs
from src.video.workflow_contracts import WorkflowSpec


class WorkflowRegistry:
    def __init__(self) -> None:
        self._specs: dict[tuple[str, str], WorkflowSpec] = {}
        self._versions_by_id: dict[str, list[str]] = {}

    def register(self, spec: WorkflowSpec) -> None:
        key = spec.registry_key
        if key in self._specs:
            raise ValueError(
                f"Workflow '{spec.workflow_id}' version '{spec.workflow_version}' is already registered"
            )
        self._specs[key] = spec
        versions = self._versions_by_id.setdefault(spec.workflow_id, [])
        versions.append(spec.workflow_version)
        versions.sort()

    @staticmethod
    def _require_runnable(spec: WorkflowSpec, *, allow_experimental: bool = False) -> WorkflowSpec:
        if spec.is_experimental:
            # Experimental workflows run only with an explicit, per-job opt-in carried in the
            # immutable job intent; there is no process-global switch.
            if not allow_experimental:
                raise KeyError(
                    f"Workflow '{spec.workflow_id}' version '{spec.workflow_version}' is "
                    "experimental and requires an explicit experimental opt-in for this job"
                )
        elif spec.governance_state != "approved":
            raise KeyError(
                f"Workflow '{spec.workflow_id}' version '{spec.workflow_version}' is not approved for execution"
            )
        if not spec.pinned_revision:
            raise KeyError(
                f"Workflow '{spec.workflow_id}' version '{spec.workflow_version}' is missing a pinned revision"
            )
        return spec

    def get(
        self,
        workflow_id: str,
        workflow_version: str | None = None,
        *,
        allow_experimental: bool = False,
    ) -> WorkflowSpec:
        workflow_key = str(workflow_id or "").strip()
        if not workflow_key:
            raise KeyError("Workflow lookup requires a non-empty workflow_id")
        if workflow_version is not None:
            key = (workflow_key, str(workflow_version or "").strip())
            if key not in self._specs:
                raise KeyError(
                    f"Workflow '{workflow_key}' version '{workflow_version}' is not registered"
                )
            return self._require_runnable(self._specs[key], allow_experimental=allow_experimental)

        versions = self._versions_by_id.get(workflow_key) or []
        if not versions:
            raise KeyError(f"Workflow '{workflow_key}' is not registered")
        if len(versions) > 1:
            raise KeyError(
                f"Workflow '{workflow_key}' has multiple versions registered; version is required"
            )
        return self._require_runnable(
            self._specs[(workflow_key, versions[0])], allow_experimental=allow_experimental
        )

    def list_workflow_ids(self) -> list[str]:
        return sorted(self._versions_by_id.keys())

    def list_versions(self, workflow_id: str) -> list[str]:
        return list(self._versions_by_id.get(str(workflow_id or "").strip()) or [])

    def list_specs_for_backend(self, backend_id: str) -> list[WorkflowSpec]:
        backend_key = str(backend_id or "").strip()
        return sorted(
            [
                spec
                for spec in self._specs.values()
                if spec.backend_id == backend_key and spec.is_runnable
            ],
            key=lambda spec: (spec.workflow_id, spec.workflow_version),
        )

    def list_offerable_specs(self, backend_id: str) -> list[WorkflowSpec]:
        """Approved and experimental (never disabled) specs, for producers/UI to offer."""

        backend_key = str(backend_id or "").strip()
        return sorted(
            [
                spec
                for spec in self._specs.values()
                if spec.backend_id == backend_key and spec.is_offerable
            ],
            key=lambda spec: (spec.workflow_id, spec.workflow_version),
        )

    def get_offerable(self, workflow_id: str, workflow_version: str | None = None) -> WorkflowSpec:
        """Look a spec up for form validation: experimental allowed, disabled never."""

        return self.get(workflow_id, workflow_version, allow_experimental=True)


def build_default_workflow_registry() -> WorkflowRegistry:
    registry = WorkflowRegistry()
    for spec in build_builtin_workflow_specs():
        registry.register(spec)
    return registry


__all__ = ["WorkflowRegistry", "build_default_workflow_registry"]
