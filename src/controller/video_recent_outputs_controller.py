"""Make Video support on the Video Workflow controller (PR-VID-UX-313/314).

A mixin so ``VideoWorkflowController`` keeps one surface for the Video Workflow tab while its own module stays small.
Both calls are read-only: they queue nothing, start no process and write nothing.
"""

from __future__ import annotations

from typing import Any

from src.video.recent_video_outputs import (
    DEFAULT_LIMIT,
    RecentVideoOutput,
    list_recent_video_outputs,
)
from src.video.workflow_picker import recommended_workflow_id


class VideoRecentOutputsControllerMixin:
    """Requires ``list_workflow_specs`` and ``_job_service`` on the host controller."""

    def recommended_workflow_id(self) -> str:
        """The workflow a Make Video handoff preselects: the first approved one, never an experimental one."""

        return recommended_workflow_id(self.list_workflow_specs())  # type: ignore[attr-defined]

    def list_recent_video_outputs(self, limit: int = DEFAULT_LIMIT) -> list[RecentVideoOutput]:
        """Newest playable clips from the canonical repository (read-only; worker-thread safe)."""

        repository: Any = getattr(self._job_service(), "history_store", None)  # type: ignore[attr-defined]
        return list_recent_video_outputs(repository, limit=limit)
