"""Protocol definitions for controller-owned runtime wiring seams."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class NJRSummaryPort(Protocol):
    """Structural contract for objects that can produce a unified job summary."""

    def to_unified_summary(self) -> Any:
        """Return a unified job summary payload."""
        ...


@runtime_checkable
class NJRUISummaryPort(Protocol):
    """Structural contract for objects that can produce a UI summary."""

    def to_ui_summary(self) -> Any:
        """Return a UI-oriented summary payload."""
        ...


@runtime_checkable
class JobCompletionCallbackPort(Protocol):
    """Structural contract for controllers that accept completion callbacks."""

    def on_job_completed_callback(self, job: Any, result: Any) -> None:
        """Handle a job-completion event."""
        ...


@runtime_checkable
class ImageRuntimePorts(Protocol):
    """StableNew-owned factory seam for image runtime client/runner wiring."""

    def create_client(self, *, base_url: str) -> Any:
        """Create an image runtime client for the specified base URL."""
        ...

    def create_runner(
        self,
        *,
        api_client: Any,
        structured_logger: Any,
        status_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> Any:
        """Create a runner bound to the supplied image runtime client."""
        ...


@runtime_checkable
class WorkflowRegistryPort(Protocol):
    """StableNew-owned port for video workflow lookup and validation."""

    def list_specs_for_backend(self, backend_id: str) -> list[Any]:
        """Return workflow specs for the specified backend."""
        ...

    def get(self, workflow_id: str, workflow_version: str | None = None) -> Any:
        """Return the resolved workflow spec or raise if unknown."""
        ...


__all__ = [
    "ImageRuntimePorts",
    "JobCompletionCallbackPort",
    "NJRSummaryPort",
    "NJRUISummaryPort",
    "WorkflowRegistryPort",
]
