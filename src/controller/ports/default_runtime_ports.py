"""Default controller-owned adapters for image and video runtime ports."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.api.client import SDWebUIClient
from src.api.forge_client import ForgeWebUIClient
from src.api.webui_runtime_identity import (
    FORGE_WEBUI_IDENTITY,
    effective_webui_base_url,
    load_backend_settings,
    normalize_webui_runtime_identity,
    resolve_configured_webui_runtime_identity,
)
from src.pipeline.pipeline_runner import PipelineRunner
from src.video.workflow_registry import WorkflowRegistry, build_default_workflow_registry


class DefaultImageRuntimePorts:
    """Build StableNew's concrete image runtime client and runner.

    The WebUI-family client is chosen once, from the configured runtime identity
    (``webui_runtime_identity``: managed Forge ``forge_webui`` when unset, the product default, or an
    explicit ``a1111_webui`` rollback; an unrecognized or unreadable configuration raises instead of
    selecting either). A1111 and Forge occupy one runtime slot, so there is exactly one client per
    configured runtime; the client is never swapped under a ``Pipeline`` between jobs, and a job whose
    backend identity does not match the connected endpoint (for example a historical A1111 replay while
    Forge is configured) is rejected before dispatch by the runtime identity guard. There is no fallback.
    """

    def __init__(self, *, runtime_identity: str | None = None) -> None:
        self._runtime_identity = runtime_identity

    @staticmethod
    def base_url() -> str:
        """The endpoint of the configured runtime: the explicit setting, else the identity default (Forge 7871)."""

        return effective_webui_base_url()

    def _configured_identity(self) -> str:
        if self._runtime_identity is not None:
            return normalize_webui_runtime_identity(self._runtime_identity)
        return resolve_configured_webui_runtime_identity(load_backend_settings())

    def create_client(self, *, base_url: str) -> SDWebUIClient:
        if self._configured_identity() == FORGE_WEBUI_IDENTITY:
            return ForgeWebUIClient(base_url=base_url)
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
        # Producers offer approved AND experimental workflows (never disabled); offering is not
        # authorization: experimental execution needs the job's explicit opt-in.
        return list(self._registry.list_offerable_specs(backend_id))

    def get(self, workflow_id: str, workflow_version: str | None = None) -> Any:
        return self._registry.get_offerable(workflow_id, workflow_version)


__all__ = ["DefaultImageRuntimePorts", "DefaultWorkflowRegistryPort"]
