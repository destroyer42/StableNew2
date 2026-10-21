"""Read-only workflow readiness on the Video Workflow controller (PR-VID-UX-311).

A mixin so ``VideoWorkflowController`` keeps one surface for the Video Workflow tab while its own module stays small.
It queues nothing and starts or stops no process; the gates live in ``src/video/workflow_preflight.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.video.workflow_preflight import (
    PreflightProbes,
    WorkflowPreflight,
    default_preflight_probes,
    evaluate_workflow_preflight,
)


class VideoPreflightControllerMixin:
    """Requires ``_workflow_registry`` and ``_preflight_probes`` (a probe factory, or ``None`` for the app's)."""

    _workflow_registry: Any
    _preflight_probes: Callable[[], PreflightProbes] | None

    def workflow_preflight(
        self, workflow_id: str, workflow_version: str | None = None
    ) -> WorkflowPreflight:
        """Readiness gates for a workflow, answered before anything is queued.

        Safe to call from a worker thread: it reads host RAM, the driver's GPU memory, the configured launch command
        and, when ComfyUI is already serving, its node list."""

        spec = self._workflow_registry.get(workflow_id, workflow_version)
        return evaluate_workflow_preflight(
            spec, (self._preflight_probes or default_preflight_probes)()
        )
