"""PR-BATCH-OPS-201: the Tk Batches view over a real service/SQLite, driven through its real widgets."""

from __future__ import annotations

import time
from tkinter import ttk

import pytest

from src.controller.app_controller import AppController
from src.controller.batch_operations_service import build_batch_operations_service
from src.controller.job_service import JobService
from src.gui import batch_operations_panel_v2 as panel_module
from src.gui.app_state_v2 import AppStateV2
from src.gui.batch_operations_panel_v2 import BatchOperationsPanelV2
from src.gui.batch_retry_dialog import BatchRetryDialog
from src.gui.gui_invoker import GuiInvoker
from src.gui.views.pipeline_tab_frame_v2 import PipelineTabFrame
from src.queue.batch_membership import BatchKey, BatchKind
from src.queue.job_model import JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.utils.config import ConfigManager
from src.utils.watchdog_v2 import WatchdogConfig
from tests.gui_v2.test_batch_operations_session_201 import ManualRunner, _evidence
from tests.helpers.batch_ops_201 import (
    admit,
    make_stack,
    review_njr,
    settle_fifo,
    status_of,
    video_njr,
)
from tests.helpers.fake_pipeline_runner import FakePipelineRunner

pytestmark = pytest.mark.gui

VID = BatchKey(BatchKind.VIDEO_WORKFLOW, "vid")


@pytest.fixture
def world(tmp_path):
    stack = make_stack(tmp_path)
    admit(stack, [video_njr(f"v{i:02d}", "vid", i, 10) for i in range(10)])
    admit(stack, [review_njr(f"r{i}", "rev", source_count=6) for i in range(6)])
    settle_fifo(stack, {2: "failed", 4: "failed"}, count=5, results={
        2: _evidence(error_code="connection_error", webui_unavailable=True),
        4: _evidence(error_code="outcome_unknown", request_may_have_executed=True)})
    return stack


@pytest.fixture
def view(tk_root, world, monkeypatch):
    runner = ManualRunner()
    opened = {"folders": [], "review": []}
    panel = BatchOperationsPanelV2(
        tk_root, service=world.operations, runner=runner,
        folder_opener=opened["folders"].append, main_window_provider=lambda: None)
    panel.pack(fill="both", expand=True)
    yield panel, runner, opened
    if panel.winfo_exists():
        panel.destroy()


def _pump(root):
    root.update_idletasks()
    root.update()


def _select_batch(panel, runner, root, key=VID):
    panel.batch_tree.selection_set(key.to_token())
    panel.batch_tree.event_generate("<<TreeviewSelect>>")
    _pump(root)
    runner.drain()
    _pump(root)


def _select_jobs(panel, root, *job_ids):
    panel.job_tree.selection_set(list(job_ids))
    panel.job_tree.event_generate("<<TreeviewSelect>>")
    _pump(root)


# ------------------------------------------------------------------ rendering and selection (26, 27)


def test_the_view_lists_batches_and_shows_progress_from_persisted_state(tk_root, view):
    panel, runner, _ = view
    panel.refresh()
    runner.drain()
    rows = {panel.batch_tree.set(i, "kind"): panel.batch_tree.item(i, "values") for i in panel.batch_tree.get_children()}
    assert set(rows) == {"Video Workflow", "Review"}
    assert rows["Video Workflow"][4] == "10 jobs / 10 sources"
    assert rows["Video Workflow"][3] == "5/10 finished"  # 3 completed + 2 failed
    assert rows["Review"][3] == "0/6 finished"
    _select_batch(panel, runner, tk_root)
    assert len(panel.job_tree.get_children()) == 10
    assert "Queued 5 - Running 0 - Completed 3 - Failed 2" in panel.summary_var.get()
    failed = panel.job_tree.item("v02", "values")
    assert failed[2] == "FAILED" and "Backend unavailable" in failed[3]


def test_selected_jobs_and_batch_remain_selected_across_a_refresh(tk_root, view):
    panel, runner, _ = view
    panel.refresh()
    runner.drain()
    _select_batch(panel, runner, tk_root)
    _select_jobs(panel, tk_root, "v02", "v04")
    panel.refresh()
    runner.drain()
    _pump(tk_root)
    assert set(panel.job_tree.selection()) == {"v02", "v04"}
    assert panel.batch_tree.selection() == (VID.to_token(),)
    assert "Job v04" in panel.detail_text.get("1.0", "end")  # the detail follows the last selected job


def test_filters_drive_the_job_table(tk_root, view):
    panel, runner, _ = view
    panel.refresh()
    runner.drain()
    _select_batch(panel, runner, tk_root)
    panel.status_filter.set("FAILED")
    panel.status_filter.event_generate("<<ComboboxSelected>>")
    _pump(tk_root)
    assert set(panel.job_tree.get_children()) == {"v02", "v04"}
    panel.category_filter.set("Dispatched - outcome unknown")
    panel.category_filter.event_generate("<<ComboboxSelected>>")
    _pump(tk_root)
    assert panel.job_tree.get_children() == ("v04",)
    panel.status_filter.set("All statuses")
    panel.category_filter.set("All failure categories")
    panel.status_filter.event_generate("<<ComboboxSelected>>")
    _pump(tk_root)
    assert len(panel.job_tree.get_children()) == 10


def test_details_show_failure_triage_without_dumping_payloads(tk_root, view):
    panel, runner, _ = view
    panel.refresh()
    runner.drain()
    _select_batch(panel, runner, tk_root)
    _select_jobs(panel, tk_root, "v04")
    text = panel.detail_text.get("1.0", "end")
    assert "Dispatched - outcome unknown" in text and "may have produced output" in text
    assert "Dispatch certainty: unknown" in text and "Job v04" in text
    assert len(text) < 1500


# ------------------------------------------------------------------ buttons are truthful (§3)


def test_buttons_enable_only_when_the_action_is_real_and_explain_when_not(tk_root, view):
    panel, runner, _ = view
    panel.refresh()
    runner.drain()
    assert panel.cancel_button.instate(["disabled"]) and panel.retry_button.instate(["disabled"])
    assert "Select a batch" in panel.cancel_button.tooltip.text
    _select_batch(panel, runner, tk_root)
    assert panel.cancel_button.instate(["!disabled"]) and "5 job(s)" in panel.cancel_button.tooltip.text
    assert panel.retry_button.instate(["disabled"]) and "Select one or more failed" in panel.hint_var.get()
    _select_jobs(panel, tk_root, "v00")
    assert panel.retry_button.instate(["disabled"])
    _select_jobs(panel, tk_root, "v00", "v02")
    assert panel.retry_button.instate(["!disabled"])
    assert panel.review_button.instate(["disabled"]) and panel.folder_button.instate(["disabled"])


def test_cancel_button_confirms_the_exact_queued_count_and_acts_only_when_confirmed(tk_root, view, world, monkeypatch):
    panel, runner, _ = view
    panel.refresh()
    runner.drain()
    _select_batch(panel, runner, tk_root)
    prompts = []
    answers = iter([False, True])

    def ask(title, message, **_):
        prompts.append(message)
        return next(answers)

    monkeypatch.setattr(panel_module.messagebox, "askyesno", ask)
    panel.cancel_button.invoke()
    runner.drain()
    assert "5 job(s) of Video Workflow" in prompts[0] and "5 other job(s)" in prompts[0]
    assert {status_of(world, f"v{i:02d}") for i in range(5, 10)} == {JobStatus.QUEUED}
    panel.cancel_button.invoke()
    runner.drain()
    _pump(tk_root)
    assert {status_of(world, f"v{i:02d}") for i in range(5, 10)} == {JobStatus.CANCELLED}
    assert "Cancelled 5 queued job(s) of Video Workflow" in panel.status_var.get()
    assert "Cancelled 5" in panel.summary_var.get()
    assert panel.cancel_button.instate(["disabled"])  # nothing queued remains


def test_retry_dialog_lists_everything_and_gates_on_each_acknowledgement(tk_root, world):
    from src.controller.batch_operations_service import BatchOperationRefused  # noqa: F401

    plan = world.operations.preflight_retry(VID, ["v02", "v04"])
    dialog = BatchRetryDialog(tk_root, plan)
    try:
        assert set(dialog.rows.get_children()) == {"v02", "v04"}
        assert dialog.submit_button.instate(["disabled"])  # v04 needs its acknowledgement
        assert list(dialog.ack_vars) == ["v04"]
        dialog.submit()  # a disabled submit is inert
        assert dialog.result is None and dialog.winfo_exists()
        dialog.ack_vars["v04"].set(True)
        dialog._sync()
        assert dialog.submit_button.instate(["!disabled"])
        dialog.submit()
        assert dialog.result == ("v04",)
    finally:
        if dialog.winfo_exists():
            dialog.destroy()


def test_retry_dialog_never_enables_submit_for_ineligible_jobs(tk_root, world):
    plan = world.operations.preflight_retry(VID, ["v00", "v02"])
    dialog = BatchRetryDialog(tk_root, plan)
    try:
        assert "Cannot retry" in dialog.rows.item("v00", "values")[2]
        assert "revise the selection" in dialog.notice.cget("text").lower()
        assert dialog.submit_button.instate(["disabled"])
        dialog.cancel()
        assert dialog.result is None
    finally:
        if dialog.winfo_exists():
            dialog.destroy()


def test_retry_button_end_to_end_through_the_dialog(tk_root, view, world, monkeypatch):
    panel, runner, _ = view
    panel.refresh()
    runner.drain()
    _select_batch(panel, runner, tk_root)
    _select_jobs(panel, tk_root, "v02")
    monkeypatch.setattr(BatchRetryDialog, "show", lambda self: (self.submit(), self.result)[1] if (
        self.submit_button.instate(["!disabled"])) else (self.cancel(), self.result)[1])
    before = world.repository.count()
    panel.retry_button.invoke()
    runner.drain()
    _pump(tk_root)
    assert world.repository.count() == before + 1
    assert panel.job_tree.item("v02", "values")[7].endswith("(queued)")  # lineage shown, not double counted
    assert status_of(world, "v02") is JobStatus.FAILED


# ------------------------------------------------------------------ lifecycle (32)


def test_destroying_the_view_with_a_worker_outstanding_is_harmless(tk_root, view):
    panel, runner, _ = view
    panel.refresh()
    outcome, done = runner.run()
    panel.destroy()
    _pump(tk_root)
    done(outcome)  # the late worker completion lands on a dead widget
    assert panel.session._closed is True


def test_the_view_without_a_job_service_says_so_and_stays_inert(tk_root):
    panel = BatchOperationsPanelV2(tk_root, service=None)
    try:
        assert panel.session is None
        assert any("unavailable" in str(c.cget("text")) for c in panel.winfo_children() if isinstance(c, ttk.Label))
        panel.refresh()
        panel.request_refresh_if_visible()
    finally:
        panel.destroy()


def test_automatic_refresh_is_debounced_and_only_while_visible(tk_root, view, monkeypatch):
    panel, runner, _ = view
    clock = {"now": 100.0}
    panel._clock = lambda: clock["now"]
    monkeypatch.setattr(panel, "winfo_ismapped", lambda: False)
    panel.request_refresh_if_visible()
    assert not runner.pending  # not on screen: no repository read
    monkeypatch.setattr(panel, "winfo_ismapped", lambda: True)
    panel.request_refresh_if_visible()
    assert len(runner.pending) == 1
    runner.drain()
    clock["now"] += 0.5
    panel.request_refresh_if_visible()
    assert not runner.pending  # inside the minimum interval
    clock["now"] += 3.0
    panel.request_refresh_if_visible()
    assert len(runner.pending) == 1


# ------------------------------------------------------------------ integration with the real tab (33)


def test_the_real_pipeline_tab_mounts_a_collapsed_batches_view_beside_unchanged_history_and_queue(
    tk_root, tmp_path, monkeypatch
):
    monkeypatch.setattr(PipelineTabFrame, "_surface_is_visible", staticmethod(lambda _w: True))
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    service = JobService(queue, run_callable=lambda job: {"success": True},
                         watchdog_config=WatchdogConfig(enabled=False))
    admit_stack = type("S", (), {"service": service})()
    admit(admit_stack, [video_njr(f"t{i}", "tab", i, 3) for i in range(3)])
    app_state = AppStateV2()
    invoker = GuiInvoker(tk_root)
    controller = AppController(
        main_window=None, threaded=False, ui_scheduler=invoker.invoke,
        pipeline_runner=FakePipelineRunner(), job_service=service,
        config_manager=ConfigManager(presets_dir=tmp_path / "presets"))
    controller.load_packs = lambda: None  # type: ignore[method-assign]
    tab = PipelineTabFrame(tk_root, app_state=app_state, app_controller=controller,
                           pipeline_controller=controller.pipeline_controller)
    tab.pack(fill="both", expand=True)
    try:
        assert tab.queue_panel.pause_resume_button is not None and tab.history_panel is not None
        assert tab.batches_section.is_expanded() is False
        assert "Batches" in tab.batches_section.header_text()
        assert tab.batches_panel.session is not None
        tab.batches_section.set_expanded(True)
        tab.batches_panel.refresh()
        deadline = time.monotonic() + 10
        while not tab.batches_panel.batch_tree.get_children() and time.monotonic() < deadline:
            _pump(tk_root)
            time.sleep(0.02)
        assert tab.batches_panel.batch_tree.get_children() == (BatchKey(BatchKind.VIDEO_WORKFLOW, "tab").to_token(),)
    finally:
        tab.destroy()
        invoker.dispose()
        service.stop()
        repository.close()


def test_a_controller_without_a_real_repository_gets_no_service():
    assert build_batch_operations_service(object()) is None
    assert build_batch_operations_service(None) is None
