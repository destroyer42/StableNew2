"""PR-VID-BATCH-200: multi-source batch session, Tk panel and Review handoff.

The neutral session runs against the real Video Workflow controller with a fake JobService; the Tk
tests drive the real tab.  No Comfy/WebUI/GPU/network.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from src.controller.video_workflow_controller import VideoWorkflowController
from src.gui.controllers.video_workspace_handoff import (
    route_image_to_video_workflow,
    route_images_to_video_workflow,
)
from src.gui.view_contracts.video_batch_contract import (
    MAX_BATCH_SOURCES,
    VideoBatchSession,
)
from src.gui.view_contracts.video_experiment_contract import WorkOutcome
from src.gui.views.video_workflow_tab_frame_v2 import VideoWorkflowTabFrameV2

TI2V_ID = "wan22_ti2v_5b_i2v_v1"


class _JobService:
    def __init__(self) -> None:
        self.calls: list[list[Any]] = []

    def submit_njrs(self, njrs, policy):
        self.calls.append(list(njrs))
        return [njr.job_id for njr in njrs]


def _images(tmp_path: Path, count: int) -> list[Path]:
    root = tmp_path / "src"
    root.mkdir(parents=True, exist_ok=True)
    paths = []
    for index in range(count):
        path = root / f"img_{index:02d}.png"
        Image.new("RGB", (48 + index, 80), ((index * 9) % 256, 40, 90)).save(path)
        paths.append(path)
    return paths


def _app(tmp_path: Path):
    service = _JobService()
    app = SimpleNamespace(job_service=service, output_dir=str(tmp_path / "output"), syncs=[])
    app.sync_queue_state_after_direct_submission = lambda: app.syncs.append(threading.get_ident())
    controller = VideoWorkflowController(app_controller=app)
    app.get_video_workflow_controller = lambda: controller
    app.get_video_workflow_specs = controller.list_workflow_specs
    app.build_video_workflow_defaults = controller.build_default_form_state
    app.submit_video_workflow_job = controller.submit_video_workflow_job
    return app, controller, service


def _form(**overrides: Any) -> dict[str, Any]:
    form: dict[str, Any] = {
        "workflow_id": TI2V_ID,
        "workflow_version": "1.1.0",
        "prompt": "slow cinematic turn",
        "negative_prompt": "",
        "experimental_opt_in": True,
        "seed": "",
        "frame_count": 33,
    }
    form.update(overrides)
    return form


def _session(controller) -> VideoBatchSession:
    return VideoBatchSession(
        build_preview=controller.preview_batch,
        submit_plan=controller.submit_batch,
        select_sources=controller.select_batch_sources,
        scan_folder=controller.scan_batch_folder,
    )


def _previewed(session: VideoBatchSession, form: dict[str, Any]) -> None:
    work = session.begin_preview(form)
    assert work is not None
    assert session.finish_preview(work, session.run_preview(work), form)


# ------------------------------------------------------------------ neutral session


def test_session_dedupes_reports_and_switches_back_to_single_mode(tmp_path):
    _app_stub, controller, _service = _app(tmp_path)
    session = _session(controller)
    paths = _images(tmp_path, 3)
    assert session.active is False and "Single image mode" in session.source_text

    assert session.choose_files([str(paths[1]), str(paths[0]), str(paths[1])])
    assert [Path(s.path).name for s in session.sources] == ["img_01.png", "img_00.png"]
    assert session.duplicates_omitted == 1 and "1 duplicate path(s) omitted" in session.source_text
    assert session.active and session.origin == "files"

    session.clear()
    assert session.active is False and session.sources == []
    assert "single image mode" in session.message.lower()
    assert session.choose_files([]) is False  # an empty selection changes nothing


def test_oversized_selection_is_kept_whole_and_refused_until_reduced(tmp_path):
    _app_stub, controller, service = _app(tmp_path)
    session = _session(controller)
    paths = _images(tmp_path, MAX_BATCH_SOURCES + 2)
    session.choose_files([str(p) for p in paths])
    assert session.count == 27 and session.over_limit
    assert "Exclude at least 2" in session.source_text

    form = _form()
    _previewed(session, form)
    assert session.preview is not None and not session.preview_valid
    assert "1 to 25" in session.preview.problems[0]
    assert session.begin_queue(form) is None and service.calls == []

    assert session.exclude([25, 26]) == 2  # explicit removal, the operator's choice
    assert session.count == 25 and session.preview is None
    _previewed(session, form)
    assert session.preview_valid


def test_blocked_sources_are_listed_and_must_be_excluded_then_repreviewed(tmp_path):
    _app_stub, controller, service = _app(tmp_path)
    session = _session(controller)
    paths = _images(tmp_path, 4)
    paths[2].write_bytes(b"garbage")
    session.choose_files([str(p) for p in paths])
    form = _form()
    _previewed(session, form)

    view = session.preview
    assert view is not None and view.eligible is False
    assert view.blocked_indices == (2,)
    assert [row.status for row in view.rows] == ["ready", "ready", "blocked", "ready"]
    assert "Unreadable image" in view.rows[2].detail
    assert session.begin_queue(form) is None  # no silent "just the other three"
    assert service.calls == []

    assert session.exclude_blocked() == 1
    assert session.count == 3 and session.preview is None  # a fresh preview is required
    assert session.begin_queue(form) is None
    _previewed(session, form)
    assert session.preview_valid and session.preview.eligible
    ids = session.queue(form)
    assert len(ids) == 3 and len(service.calls) == 1


def test_preview_shows_concrete_seeds_and_queue_never_rerolls_them(tmp_path):
    _app_stub, controller, service = _app(tmp_path)
    session = _session(controller)
    session.choose_files([str(p) for p in _images(tmp_path, 3)])
    form = _form()
    _previewed(session, form)
    view = session.preview
    assert view is not None and view.frozen
    shown = [row.detail.split("seed ")[1].split(";")[0] for row in view.rows]
    assert all(value.isdigit() for value in shown)
    assert any("Seeds" == label for label, _ in view.summary)

    session.invalidate_if_changed(form)  # an unrelated refresh with the same inputs keeps it
    assert session.preview_valid
    session.queue(form)
    queued = [str(n.config["video_workflow"]["seed"]) for n in service.calls[0]]
    assert queued == shown


@pytest.mark.parametrize(
    "edit",
    [
        {"seed": "7"},
        {"prompt": "something else"},
        {"negative_prompt": "blur"},
        {"workflow_version": "1.2.0"},
        {"workflow_id": "wan_animate2_prompt_i2v_v1", "workflow_version": "1.0.0"},
        {"output_route": "Testing"},
        {"frame_count": 17},
        {"experimental_opt_in": False},
    ],
)
def test_any_execution_edit_invalidates_the_preview_and_blocks_queue(tmp_path, edit):
    _app_stub, controller, service = _app(tmp_path)
    session = _session(controller)
    session.choose_files([str(p) for p in _images(tmp_path, 2)])
    form = _form()
    _previewed(session, form)
    edited = {**form, **edit}
    assert session.invalidate_if_changed(edited) is True
    assert session.begin_queue(edited) is None and service.calls == []


def test_a_late_preview_cannot_overwrite_or_reenable_a_newer_edited_session(tmp_path):
    _app_stub, controller, service = _app(tmp_path)
    session = _session(controller)
    paths = _images(tmp_path, 3)
    session.choose_files([str(p) for p in paths])
    form = _form()

    stale = session.begin_preview(form)
    assert stale is not None
    outcome = session.run_preview(stale)  # the worker finishes later...
    session.busy = None  # (the Tk layer would not allow this; model the interleaving directly)
    session.exclude([0])  # ...after the operator already edited the source list
    assert session.finish_preview(stale, outcome, form) is False
    assert session.preview is None and not session.preview_valid
    assert "changed while the preview was building" in session.message
    assert session.begin_queue(form) is None and service.calls == []

    stale = session.begin_preview(form)
    outcome = session.run_preview(stale)
    assert session.finish_preview(stale, outcome, {**form, "seed": "9"}) is False  # form edit
    assert not session.preview_valid


def test_second_queue_click_is_refused_while_the_first_is_outstanding(tmp_path):
    _app_stub, controller, service = _app(tmp_path)
    session = _session(controller)
    session.choose_files([str(p) for p in _images(tmp_path, 2)])
    form = _form()
    _previewed(session, form)

    work = session.begin_queue(form)
    assert work is not None and session.busy == "queue"
    assert session.begin_queue(form) is None  # the double-click
    assert session.begin_preview(form) is None
    assert session.exclude([0]) == 0 and session.count == 2  # no edits mid-admission
    ids = session.finish_queue(work, session.run_queue(work))
    assert len(ids) == 2 and len(service.calls) == 1
    assert "Queue / History" in session.message and session.last_result.batch_id in session.message
    assert session.begin_queue(form) is None  # the preview was consumed


def test_stale_input_at_queue_time_is_a_visible_refusal_with_nothing_queued(tmp_path):
    _app_stub, controller, service = _app(tmp_path)
    session = _session(controller)
    paths = _images(tmp_path, 3)
    session.choose_files([str(p) for p in paths])
    form = _form()
    _previewed(session, form)
    Image.new("RGB", (10, 10), "white").save(paths[1])  # replaced after the preview

    assert session.queue(form) == []
    assert "Queue refused" in session.message and "source image changed" in session.message
    assert session.preview is None and service.calls == []


# ------------------------------------------------------------------ Tk tab


class _ManualRunner:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, Any, Any]] = []

    def start(self, name, work, on_done) -> None:
        self.jobs.append((name, work, on_done))

    def drain(self) -> None:
        while self.jobs:
            _name, work, on_done = self.jobs.pop(0)
            on_done(work())


def _tab(tk_root, tmp_path, count=3):
    app, controller, service = _app(tmp_path)
    tab = VideoWorkflowTabFrameV2(tk_root, app_controller=app, app_state=SimpleNamespace())
    tab.workflow_var.set(TI2V_ID)
    tab._refresh_workspace_summary()
    tab._set_text_value(tab.prompt_text, "slow cinematic turn")
    tab.experimental_opt_in_var.set(True)
    panel = tab.batch_panel
    runner = _ManualRunner()
    panel._runner = runner
    paths = _images(tmp_path, count)
    panel._session.choose_files([str(p) for p in paths])
    panel.refresh()
    return tab, panel, runner, app, controller, service, paths


@pytest.mark.gui
def test_header_strip_stays_compact_and_details_live_in_the_scrolled_body(tk_root, tmp_path):
    app, _controller, _service = _app(tmp_path)
    tab = VideoWorkflowTabFrameV2(tk_root, app_controller=app, app_state=SimpleNamespace())
    tab.pack(fill="both", expand=True)
    tk_root.geometry("1280x800")
    tk_root.update_idletasks()
    panel = tab.batch_panel
    header = tab._header_frame

    def ancestors(widget):
        chain = []
        while widget is not None:
            chain.append(widget)
            widget = widget.master
        return chain

    # The source strip and the primary actions are in the fixed header, not the scrolled body.
    assert tab._body_scroll.inner not in ancestors(panel)
    assert tab._body_scroll.inner in ancestors(panel.details)  # the tall table is scrollable
    assert panel.grid_info() and not panel.details.grid_info()  # single mode: no table
    single_height = header.winfo_reqheight()

    panel._session.choose_files([str(p) for p in _images(tmp_path, 25)])
    panel.refresh()
    tk_root.update_idletasks()
    assert panel.details.grid_info()
    assert panel.preview_button.master is tab._action_bar
    assert panel.queue_button.master is tab._action_bar
    assert panel.preview_button.winfo_manager() == "pack"
    assert panel.queue_button.winfo_manager() == "pack"
    # 25 sources add one summary line to the fixed header; they do not squeeze the form.
    assert header.winfo_reqheight() - single_height < 40


@pytest.mark.gui
def test_batch_mode_disables_single_queue_and_clearing_restores_it(tk_root, tmp_path):
    tab, panel, _runner, _app_stub, _controller, service, _paths = _tab(tk_root, tmp_path)
    assert str(tab.queue_workflow_button.cget("state")) == "disabled"
    assert "batch of 3" in tab.source_summary_var.get()
    assert len(panel.tree.get_children()) == 3
    assert str(panel.queue_button.cget("state")) == "disabled"  # nothing previewed yet

    panel._on_clear()
    assert str(tab.queue_workflow_button.cget("state")) == "normal"
    assert panel.preview_button.winfo_manager() == ""
    assert "Single image mode" in panel.source_var.get()
    assert service.calls == []


@pytest.mark.gui
def test_choosing_a_single_image_returns_to_single_mode(tk_root, tmp_path):
    tab, panel, _runner, *_rest = _tab(tk_root, tmp_path)
    assert panel._session.active
    tab.set_source_image_path(str(_images(tmp_path, 1)[0]))
    assert not panel._session.active
    assert str(tab.queue_workflow_button.cget("state")) == "normal"


@pytest.mark.gui
def test_folder_scan_runs_on_a_worker_and_states_whether_it_is_recursive(
    tk_root, tmp_path, monkeypatch
):
    app, _controller, _service = _app(tmp_path)
    tab = VideoWorkflowTabFrameV2(tk_root, app_controller=app, app_state=SimpleNamespace())
    panel = tab.batch_panel
    runner = _ManualRunner()
    panel._runner = runner
    root = tmp_path / "folder"
    (root / "nested").mkdir(parents=True)
    Image.new("RGB", (16, 16), "red").save(root / "a.png")
    Image.new("RGB", (16, 16), "blue").save(root / "nested" / "b.png")
    monkeypatch.setattr(
        "src.gui.views.video_workflow_batch_panel_v2.filedialog.askdirectory",
        lambda **_kw: str(root),
    )

    panel.recursive_var.set(True)
    panel._on_select_folder()  # the Tk callback only schedules the walk
    assert panel._session.count == 0 and len(runner.jobs) == 1
    assert runner.jobs[0][0].startswith("VideoBatch-Scan-")
    assert "Scanning the folder" in panel.message_var.get()
    assert str(panel.select_folder_button.cget("state")) == "disabled"
    runner.drain()
    assert panel._session.count == 2 and "including subfolders" in panel._session.message

    panel._session.clear()
    panel.recursive_var.set(False)
    panel._on_select_folder()
    runner.drain()
    assert panel._session.count == 1 and "top level only" in panel._session.message


@pytest.mark.gui
def test_choosing_a_single_image_while_a_batch_step_runs_is_refused_not_half_applied(
    tk_root, tmp_path
):
    tab, panel, runner, _app_stub, _controller, _service, _paths = _tab(tk_root, tmp_path)
    panel._on_preview()  # a worker is outstanding
    before = tab.source_image_var.get()
    other = str(_images(tmp_path, 1)[0])
    tab.set_source_image_path(other)
    assert tab.source_image_var.get() == before  # not applied
    assert panel._session.active and "still running" in tab.status_var.get()
    runner.drain()
    tab.set_source_image_path(other)  # idle now: the single image is authoritative again
    assert tab.source_image_var.get() == other and not panel._session.active


@pytest.mark.gui
def test_queue_runs_the_admission_on_a_worker_and_refreshes_on_the_tk_thread(
    tk_root, tmp_path, monkeypatch
):
    tab, panel, _runner, app, _controller, service, _paths = _tab(tk_root, tmp_path)
    panel._runner = None  # real ThreadRegistry worker + TkUiDispatcher marshal
    main = threading.get_ident()
    admitted_on: list[int] = []
    original = service.submit_njrs
    service.submit_njrs = lambda njrs, policy: (
        admitted_on.append(threading.get_ident()),
        original(njrs, policy),
    )[1]
    session = panel._session

    def pump(until) -> None:
        deadline = time.monotonic() + 15
        while until() and time.monotonic() < deadline:
            tk_root.update()
            time.sleep(0.01)

    panel._on_preview()
    pump(lambda: session.busy)
    assert session.preview_valid
    panel._on_queue()
    pump(lambda: session.busy)
    assert len(service.calls) == 1
    assert admitted_on and admitted_on[0] != main  # admission ran off the Tk thread
    assert app.syncs == [main]  # the queue-state refresh ran on it
    assert "Queued 3 video jobs as batch" in tab.status_var.get()


@pytest.mark.gui
def test_preview_and_queue_run_off_the_callback_and_refresh_queue_on_tk(tk_root, tmp_path):
    tab, panel, runner, app, _controller, service, _paths = _tab(tk_root, tmp_path)

    panel._on_preview()  # the Tk callback only schedules the worker
    assert len(runner.jobs) == 1 and runner.jobs[0][0].startswith("VideoBatch-Preview-")
    assert "Preparing sources" in panel.message_var.get()
    assert str(panel.preview_button.cget("state")) == "disabled"
    panel._on_preview()  # duplicate click while building schedules nothing
    assert len(runner.jobs) == 1
    runner.drain()
    assert "Eligible to queue: 3" in panel.preview_text.get("1.0", "end")
    assert str(panel.queue_button.cget("state")) == "normal"
    assert panel.queue_button.cget("text") == "Queue 3 Videos"
    assert service.calls == []

    panel._on_queue()
    assert service.calls == [] and runner.jobs[0][0].startswith("VideoBatch-Queue-")
    assert str(panel.queue_button.cget("state")) == "disabled"
    panel._on_queue()  # double click
    assert len(runner.jobs) == 1
    runner.drain()
    assert len(service.calls) == 1 and len(service.calls[0]) == 3
    assert app.syncs == [threading.get_ident()]  # refreshed on the Tk thread
    assert "Queued 3 video jobs as batch" in tab.status_var.get()
    assert tab.experimental_opt_in_var.get() is True


@pytest.mark.gui
def test_editing_the_form_after_preview_disables_queue(tk_root, tmp_path):
    tab, panel, runner, _app_stub, _controller, service, _paths = _tab(tk_root, tmp_path)
    panel._on_preview()
    runner.drain()
    assert str(panel.queue_button.cget("state")) == "normal"

    tab.seed_var.set("1234")
    assert str(panel.queue_button.cget("state")) == "disabled"
    assert panel.preview_text.get("1.0", "end").strip().startswith("Press Preview Batch")

    panel._on_preview()
    runner.drain()
    tab._set_text_value(tab.prompt_text, "edited")
    tab._invalidate_experiment_preview()  # what the <KeyRelease>/<<Paste>> bindings call
    assert str(panel.queue_button.cget("state")) == "disabled"
    assert service.calls == []


@pytest.mark.gui
def test_blocked_source_row_is_shown_and_excluded_from_the_panel(tk_root, tmp_path):
    tab, panel, runner, _app_stub, _controller, service, paths = _tab(tk_root, tmp_path, count=4)
    paths[1].write_bytes(b"garbage")
    panel._on_preview()
    runner.drain()
    rows = {iid: panel.tree.item(iid, "values") for iid in panel.tree.get_children()}
    assert len(rows) == 4 and rows["1"][1] == "BLOCKED" and "Unreadable image" in rows["1"][2]
    assert str(panel.queue_button.cget("state")) == "disabled"
    assert str(panel.exclude_blocked_button.cget("state")) == "normal"

    panel._on_exclude_blocked()
    assert panel._session.count == 3 and not panel._session.preview_valid
    assert len(panel.tree.get_children()) == 3
    panel._on_preview()
    runner.drain()
    assert str(panel.queue_button.cget("state")) == "normal" and service.calls == []


@pytest.mark.gui
def test_destroying_the_tab_before_the_worker_completes_is_safe(tk_root, tmp_path):
    tab, panel, runner, _app_stub, _controller, service, _paths = _tab(tk_root, tmp_path)
    panel._on_preview()
    tab.destroy()
    runner.drain()  # completion arrives after teardown: no Tk error, nothing queued
    assert service.calls == []


@pytest.mark.gui
def test_real_worker_thread_prepares_off_tk_and_delivers_on_the_tk_thread(
    tk_root, tmp_path, monkeypatch
):
    _tab_obj, panel, _runner, _app_stub, _controller, _service, _paths = _tab(tk_root, tmp_path)
    panel._runner = None  # real ThreadRegistry worker + TkUiDispatcher marshal
    main = threading.get_ident()
    seen: dict[str, int] = {}
    session = panel._session
    original_run, original_finish = session.run_preview, session.finish_preview

    def traced_run(work):
        seen["worker"] = threading.get_ident()
        return original_run(work)

    def traced_finish(*args):
        seen["finish"] = threading.get_ident()
        return original_finish(*args)

    monkeypatch.setattr(session, "run_preview", traced_run)
    monkeypatch.setattr(session, "finish_preview", traced_finish)
    panel._on_preview()
    assert session.busy == "preview"
    deadline = time.monotonic() + 15
    while session.busy and time.monotonic() < deadline:
        tk_root.update()
        time.sleep(0.01)
    assert session.preview_valid
    assert seen["worker"] != main and seen["finish"] == main


@pytest.mark.gui
def test_single_source_state_restoration_is_unchanged_and_batch_is_not_persisted(tk_root, tmp_path):
    tab, panel, _runner, *_rest = _tab(tk_root, tmp_path)
    state = tab.get_video_workflow_state()
    assert "batch" not in repr(state).lower() and "sources" not in state
    single = _images(tmp_path, 1)[0]
    tab.restore_video_workflow_state({**state, "source_image_path": str(single)})
    assert tab.source_image_var.get() == str(single)
    assert panel._session.active  # restoring form fields does not silently drop the batch


# ------------------------------------------------------------------ Review handoff


class _FakeNotebook:
    def __init__(self) -> None:
        self.selected: list[Any] = []

    def select(self, tab) -> None:
        self.selected.append(tab)


@pytest.mark.gui
def test_handoff_transfers_an_ordered_list_without_queueing(tk_root, tmp_path):
    tab, panel, _runner, _app_stub, _controller, service, _paths = _tab(tk_root, tmp_path)
    panel._session.clear()
    window = SimpleNamespace(video_workflow_tab=tab, center_notebook=_FakeNotebook())
    paths = _images(tmp_path, 4)
    chosen = [str(paths[3]), str(paths[1]), str(paths[2])]

    routed = route_images_to_video_workflow(
        main_window=window,
        image_paths=chosen,
        lineage_by_path={chosen[0]: {"source_job_id": "job-x"}},
        status_message="loaded",
    )
    assert routed == chosen
    assert [s.path for s in panel._session.sources] == chosen  # order preserved
    assert dict(panel._session.sources[0].lineage) == {"source_job_id": "job-x"}
    assert window.center_notebook.selected == [tab] and tab.status_var.get() == "loaded"
    assert service.calls == [] and not panel._session.preview_valid


@pytest.mark.gui
def test_handoff_of_one_image_keeps_the_established_single_source_path(tk_root, tmp_path):
    tab, panel, _runner, *_rest = _tab(tk_root, tmp_path)
    window = SimpleNamespace(video_workflow_tab=tab, center_notebook=_FakeNotebook())
    one = str(_images(tmp_path, 1)[0])
    assert route_images_to_video_workflow(main_window=window, image_paths=[one]) == [one]
    assert tab.source_image_var.get() == one and not panel._session.active
    # The pre-existing single-image function behaves exactly as before.
    route_image_to_video_workflow(main_window=window, image_path=one)
    assert tab.source_image_var.get() == one
    with pytest.raises(ValueError):
        route_images_to_video_workflow(main_window=window, image_paths=[])


@pytest.mark.gui
def test_review_sends_only_the_highlighted_rows_in_list_order(tk_root, tmp_path):
    from src.gui.views.review_tab_frame_v2 import ReviewTabFrame

    tab, panel, _runner, *_rest = _tab(tk_root, tmp_path)
    panel._session.clear()
    window = SimpleNamespace(video_workflow_tab=tab, center_notebook=_FakeNotebook())
    app = SimpleNamespace(main_window=window)
    review = ReviewTabFrame(tk_root, app_controller=app)
    paths = _images(tmp_path, 5)
    review._set_selected_images(list(paths))  # five imported; the preview shows row 0

    review.images_list.selection_clear(0, "end")
    review.images_list.selection_set(1)
    review.images_list.selection_set(3, 4)
    review._on_send_selected_to_video_workflow()

    assert [Path(s.path).name for s in panel._session.sources] == [
        "img_01.png",
        "img_03.png",
        "img_04.png",
    ]  # not all five, and not just the previewed image
    assert window.center_notebook.selected == [tab]
    review.destroy()


@pytest.mark.gui
def test_review_with_nothing_highlighted_sends_nothing(tk_root, tmp_path, monkeypatch):
    from src.gui.views.review_tab_frame_v2 import ReviewTabFrame

    tab, panel, _runner, *_rest = _tab(tk_root, tmp_path)
    panel._session.clear()
    window = SimpleNamespace(video_workflow_tab=tab, center_notebook=_FakeNotebook())
    review = ReviewTabFrame(tk_root, app_controller=SimpleNamespace(main_window=window))
    notices: list[str] = []
    monkeypatch.setattr(
        "src.gui.views.review_tab_frame_v2.messagebox.showinfo",
        lambda title, text, **_kw: notices.append(text),
    )
    review._set_selected_images(list(_images(tmp_path, 3)))
    review.images_list.selection_clear(0, "end")
    review._on_send_selected_to_video_workflow()
    assert notices and "Select one or more images" in notices[0]
    assert not panel._session.active and window.center_notebook.selected == []
    review.destroy()


def test_worker_outcome_type_is_shared_with_the_experiment_runner():
    # The batch session deliberately reuses the existing runner contract (no second framework).
    assert WorkOutcome(error="x").error == "x"
