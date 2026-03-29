"""Default controller-owned adapters for image and video runtime ports."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.api.client import SDWebUIClient
from src.pipeline.pipeline_runner import PipelineRunner
from src.video.workflow_registry import WorkflowRegistry, build_default_workflow_registry


class DefaultImageRuntimePorts:
    """Build StableNew's concrete image runtime client and runner."""

    def create_client(self, *, base_url: str) -> SDWebUIClient:
        return SDWebUIClient(base_url=base_url)

    def create_runner(
        self,
        *,
        api_client: Any,
        structured_logger: Any,
        status_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> PipelineRunner:
        return PipelineRunner(
            api_client,
            structured_logger,
            status_callback=status_callback,
        )


class DefaultWorkflowRegistryPort:
    """Expose the canonical workflow registry through a controller-owned port."""

    def __init__(self, registry: WorkflowRegistry | None = None) -> None:
        self._registry = registry or build_default_workflow_registry()

    def list_specs_for_backend(self, backend_id: str) -> list[Any]:
        return list(self._registry.list_specs_for_backend(backend_id))

    def get(self, workflow_id: str, workflow_version: str | None = None) -> Any:
        return self._registry.get(workflow_id, workflow_version)


__all__ = ["DefaultImageRuntimePorts", "DefaultWorkflowRegistryPort"]
