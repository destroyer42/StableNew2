"""PR-RUNTIME-QUEUE-150: Pipeline-tab Queue pause/resume/send control truth.

Real ``PipelineTabFrame`` + ``QueuePanelV2`` + ``AppController`` (the controller the live tab hands to the Queue
panel) + ``JobService`` + temporary SQLite ``JobQueue``. Only the job callable is fake. The operator journey is
driven through the real buttons: Pause -> the SAME button again must Resume (not Pause twice) -> Send Job runs
exactly the top job through the normal JobService path.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

import pytest

from src.controller.app_controller import AppController
from src.controller.job_service import JobService
from src.gui.app_state_v2 import AppStateV2
from src.gui.gui_invoker import GuiInvoker
from src.gui.views.pipeline_tab_frame_v2 import PipelineTabFrame
from src.queue.job_model import JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.utils.config import ConfigManager
from tests.helpers.fake_pipeline_runner import FakePipelineRunner
from tests.helpers.njr_factory import make_queue_job

pytestmark = pytest.mark.gui

DEADLINE = 10.0


class _Window:
    """The slice of MainWindowV2 that AppController.set_main_window needs, marshalling like the real window."""

    root = None

    def __init__(self, app_state: AppStateV2, invoker: GuiInvoker) -> None:
        self.app_state = app_state
        self._invoker = invoker

    def run_in_main_thread(self, callback: Callable[[], None]) -> None:
        self._invoker.invoke(callback)

    def run_in_main_thread_later(self, delay_ms: int, callback: Callable[[], None]) -> None:
        self._invoker.invoke_later(delay_ms, callback)

    @staticmethod
    def connect_controller(_controller: object) -> None:
        return None


class _Stack:
    def __init__(self, tk_root, tmp_path: Path, monkeypatch, *, auto_run: bool) -> None:
        self.root = tk_root
        # Map-state gating of hot surfaces is covered by its own tests; it is orthogonal to control truth.
        monkeypatch.setattr(PipelineTabFrame, "_surface_is_visible", staticmethod(lambda _w: True))
        self.repository = JobRepository(tmp_path / "jobs.sqlite3")
        self.queue = JobQueue(repository=self.repository)
        self.executed: list[str] = []

        def execute(job):
            self.executed.append(job.job_id)
            return {"success": True, "variants": []}

        self.service = JobService(self.queue, run_callable=execute, require_normalized_records=True)
        self.app_state = AppStateV2()
        self.app_state.auto_run_queue = auto_run
        # Worker-thread callbacks reach widgets only through the Tk pump, exactly as in the running app.
        self.invoker = GuiInvoker(tk_root)
        self.controller = AppController(
            main_window=None,
            threaded=False,
            ui_scheduler=self.invoker.invoke,
            pipeline_runner=FakePipelineRunner(),
            job_service=self.service,
            config_manager=ConfigManager(presets_dir=tmp_path / "presets"),
        )
        self.controller.load_packs = lambda: None  # type: ignore[method-assign]
        self.controller._update_status = lambda *_a, **_k: None  # type: ignore[method-assign]
        self.controller.set_main_window(_Window(self.app_state, self.invoker))
        self.service.auto_run_enabled = auto_run
        self.tab = PipelineTabFrame(
            tk_root,
            app_state=self.app_state,
            app_controller=self.controller,
            pipeline_controller=self.controller.pipeline_controller,
        )
        self.tab.pack(fill="both", expand=True)
        self.panel = self.tab.queue_panel
        self.pump()

    def enqueue(self, *job_ids: str) -> None:
        for job_id in job_ids:
            self.service.enqueue(make_queue_job(job_id))
        self.controller._refresh_app_state_queue()
        self.settle(lambda: len(self.app_state.queue_jobs) == len(job_ids))

    def pump(self) -> None:
        """Run Tk's event loop, including the coalesced hot-surface flush the real tab schedules."""
        for _ in range(5):
            self.root.update_idletasks()
            self.root.update()
            time.sleep(0.01)

    def settle(self, predicate: Callable[[], bool], *, timeout: float = DEADLINE) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.pump()
            if predicate():
                return
        self.pump()
        assert predicate(), "condition did not settle before the deadline"

    def queued_ids(self) -> list[str]:
        return [job.job_id for job in self.queue.list_jobs(JobStatus.QUEUED)]

    def durable_paused(self) -> bool:
        return bool(self.repository.get_setting("queue_paused", False))

    def close(self) -> None:
        self.service.stop()
        self.invoker.dispose()
        self.repository.close()


@pytest.fixture
def stack_factory(tk_root, tmp_path, monkeypatch):
    stacks: list[_Stack] = []

    def build(*, auto_run: bool) -> _Stack:
        stack = _Stack(tk_root, tmp_path, monkeypatch, auto_run=auto_run)
        stacks.append(stack)
        return stack

    yield build
    for stack in stacks:
        stack.close()


def test_pause_then_same_button_resumes_then_send_job_runs_exactly_top_job(stack_factory) -> None:
    stack = stack_factory(auto_run=False)
    stack.enqueue("job-a", "job-b")
    panel = stack.panel

    # Initial: unpaused, Pause Queue offered, Send Job legal, nothing dispatched.
    assert stack.durable_paused() is False
    assert panel.pause_resume_button.cget("text") == "Pause Queue"
    assert panel.send_job_button.instate(["!disabled"])

    # Action 1: Pause.
    panel.pause_resume_button.invoke()
    stack.pump()
    assert stack.durable_paused() is True  # the real queue paused ...
    assert stack.queue.is_paused() is True
    assert stack.app_state.is_queue_paused is True  # ... and AppState knows ...
    stack.settle(lambda: panel.pause_resume_button.cget("text") == "Resume Queue")  # ... so the panel must learn
    assert panel.send_job_button.instate(["disabled"])
    assert stack.queued_ids() == ["job-a", "job-b"]
    assert stack.executed == []

    # Action 2: the SAME button must now Resume, not Pause again.
    panel.pause_resume_button.invoke()
    stack.pump()
    assert stack.durable_paused() is False  # Resume reached the queue, not a second Pause
    assert stack.queue.is_paused() is False
    assert stack.app_state.is_queue_paused is False
    stack.settle(lambda: panel.pause_resume_button.cget("text") == "Pause Queue")
    assert panel.send_job_button.instate(["!disabled"])
    assert stack.queued_ids() == ["job-a", "job-b"]
    assert stack.executed == []  # Auto-run is OFF: Resume must not dispatch anything.

    # Action 3: Send Job dispatches exactly the top queued job through JobService.
    panel.send_job_button.invoke()
    stack.settle(lambda: stack.executed == ["job-a"])
    stack.settle(lambda: stack.repository.get_job("job-a").status is JobStatus.COMPLETED)
    stack.settle(lambda: not stack.service.runner.is_running())
    assert stack.executed == ["job-a"]
    assert stack.queued_ids() == ["job-b"]


def test_resume_with_auto_run_on_restores_the_job_service_worker_lifecycle(stack_factory) -> None:
    stack = stack_factory(auto_run=True)
    panel = stack.panel

    panel.pause_resume_button.invoke()
    stack.pump()
    assert stack.durable_paused() is True
    assert stack.app_state.is_queue_paused is True
    stack.settle(lambda: panel.pause_resume_button.cget("text") == "Resume Queue")
    stack.enqueue("job-a")
    assert stack.executed == []
    assert stack.queued_ids() == ["job-a"]

    panel.pause_resume_button.invoke()  # Resume: normal JobService semantics restart the worker (Auto-run ON)

    stack.settle(lambda: stack.executed == ["job-a"])
    assert stack.durable_paused() is False
    assert stack.app_state.is_queue_paused is False
    stack.settle(lambda: panel.pause_resume_button.cget("text") == "Pause Queue")
