"""PR-VID-UX-313/314 test harness: the production Video Workflow controller behind recording doubles.

``make_app`` wires the real ``VideoWorkflowController`` (real NJR builder, real workflow catalog) to a
``RecordingJobService`` standing in for ``JobService.submit_njrs`` so a test can assert exactly what crosses
the canonical submission boundary.  ``HandoffApp`` borrows the production ``AppController`` handoff methods
(unbound, by name) so the Make Video entry points run the real routing code without constructing the whole
application.  Nothing here starts Comfy, a model, a GPU, a WebUI or a network call.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from PIL import Image

from src.controller.app_controller import AppController
from src.controller.submission_policy_v26 import SubmissionPolicy
from src.controller.video_workflow_controller import VideoWorkflowController

TI2V_ID = "wan22_ti2v_5b_i2v_v1"
ANIMATE2_ID = "wan_animate2_drive_i2v_v1"


class FakeNotebook:
    def __init__(self) -> None:
        self.selected: list[Any] = []

    def select(self, tab: Any) -> None:
        self.selected.append(tab)


class RecordingJobService:
    """Stands in for ``JobService.submit_njrs``; optionally persists into a real repository."""

    def __init__(self, repository: Any = None, *, refuse: Exception | None = None) -> None:
        self.calls: list[tuple[list[Any], Any]] = []
        self.history_store = repository
        self._refuse = refuse

    def submit_njrs(self, njrs: list[Any], policy: Any) -> list[str]:
        if self._refuse is not None:
            raise self._refuse
        self.calls.append((list(njrs), policy))
        return [f"job-{len(self.calls)}-{index}" for index, _ in enumerate(njrs)]

    @property
    def submitted(self) -> list[Any]:
        return [njr for njrs, _policy in self.calls for njr in njrs]


def make_image(path: Path, size: tuple[int, int] = (64, 96), color: str = "navy") -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return str(path)


def make_app(tmp_path: Path, *, repository: Any = None, refuse: Exception | None = None):
    service = RecordingJobService(repository, refuse=refuse)
    app = SimpleNamespace(job_service=service, output_dir=str(tmp_path / "output"))
    app.sync_queue_state_after_direct_submission = lambda: None
    controller = VideoWorkflowController(app_controller=app)
    app.get_video_workflow_controller = lambda: controller
    app.get_video_workflow_specs = controller.list_workflow_specs
    app.build_video_workflow_defaults = controller.build_default_form_state
    app.submit_video_workflow_job = controller.submit_video_workflow_job
    return app, controller, service


_BORROWED = (
    "send_image_to_video_workflow",
    "send_image_to_svd",
    "send_history_job_image_to_video_workflow",
    "send_history_job_image_to_svd",
    "_require_main_window",
    "_get_history_entry_by_job_id",
    "_get_history_image_path",
    "_get_history_video_bundle",
    "_iter_history_image_candidates",
    "_extract_history_result_metadata",
    "_extract_video_artifact_summary",
)


class HandoffApp:
    """The production handoff methods of ``AppController`` over a fake main window and history."""

    def __init__(self, main_window: Any, history_items: list[Any] | None = None) -> None:
        self.main_window = main_window
        self.app_state = SimpleNamespace(history_items=list(history_items or []))
        self.log: list[str] = []

    def _append_log(self, message: str) -> None:
        self.log.append(message)


for _name in _BORROWED:  # keep staticmethods as staticmethods
    setattr(HandoffApp, _name, AppController.__dict__[_name])


def make_window(tab: Any, **extra: Any) -> SimpleNamespace:
    return SimpleNamespace(
        video_workflow_tab=tab, center_notebook=FakeNotebook(), pipeline_tab=object(), **extra
    )


def admit_policy_is_default(policy: Any) -> bool:
    return isinstance(policy, SubmissionPolicy)


__all__ = [
    "ANIMATE2_ID",
    "TI2V_ID",
    "FakeNotebook",
    "HandoffApp",
    "RecordingJobService",
    "admit_policy_is_default",
    "make_app",
    "make_image",
    "make_window",
]
