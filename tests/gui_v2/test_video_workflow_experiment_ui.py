"""PR-VID-194: the "Compare one control" section (neutral session + Tk panel).

The neutral session is exercised against the real Video Workflow controller with a fake
JobService; the Tk tests drive the real tab.  No Comfy/WebUI/GPU/network.
"""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from src.controller.video_workflow_controller import VideoWorkflowController
from src.gui.view_contracts.video_experiment_contract import (
    BackgroundWorkRunner,
    VideoExperimentSession,
    WorkOutcome,
)
from src.gui.views.video_workflow_tab_frame_v2 import VideoWorkflowTabFrameV2
from src.video.workflow_catalog_wan_animate2 import (
    WAN_ANIMATE2_CONTROLS_VERSION,
    WAN_ANIMATE2_DRIVE_ID,
)

TI2V_ID = "wan22_ti2v_5b_i2v_v1"


class _JobService:
    def __init__(self) -> None:
        self.calls: list[list[Any]] = []

    def submit_njrs(self, njrs, policy):
        self.calls.append(list(njrs))
        return [f"job-{i}" for i, _ in enumerate(njrs)]


def _files(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "ref.png"
    Image.new("RGB", (48, 80), "navy").save(source)
    clip = tmp_path / "drive.mp4"
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42 fake")
    return source, clip


def _form(tmp_path: Path, **overrides: Any) -> dict[str, Any]:
    _, clip = _files(tmp_path)
    form: dict[str, Any] = {
        "workflow_id": WAN_ANIMATE2_DRIVE_ID,
        "workflow_version": WAN_ANIMATE2_CONTROLS_VERSION,
        "prompt": "a woman in a navy top",
        "negative_prompt": "",
        "pose_video_path": str(clip),
        "experimental_opt_in": True,
        "seed": "5",
        "operator_controls": {"pose_prompt": "steps left", "pose_strength": "1"},
    }
    form.update(overrides)
    return form


def _app(tmp_path: Path):
    service = _JobService()
    app = SimpleNamespace(
        job_service=service,
        output_dir=str(tmp_path / "output"),
        syncs=[],
    )
    app.sync_queue_state_after_direct_submission = lambda: app.syncs.append(threading.get_ident())
    controller = VideoWorkflowController(app_controller=app)
    app.get_video_workflow_controller = lambda: controller
    app.get_video_workflow_specs = controller.list_workflow_specs
    app.build_video_workflow_defaults = controller.build_default_form_state
    app.submit_video_workflow_job = controller.submit_video_workflow_job
    return app, controller, service


def _session(controller) -> VideoExperimentSession:
    session = VideoExperimentSession(
        resolve_baseline=controller.resolve_experiment_baseline,
        build_preview=controller.preview_experiment,
        submit_plan=controller.submit_experiment,
    )
    drive = next(
        r for r in controller.list_workflow_specs() if r["workflow_id"] == WAN_ANIMATE2_DRIVE_ID
    )
    session.apply_controls(drive["operator_controls"])
    session.set_enabled(True)
    return session


# ------------------------------------------------------------------ neutral session


def test_session_is_unavailable_without_declared_controls(tmp_path):
    _, controller, _ = _app(tmp_path)
    session = _session(controller)
    other = next(r for r in controller.list_workflow_specs() if r["workflow_id"] == TI2V_ID)
    session.apply_controls(other["operator_controls"])
    assert session.available is False and session.enabled is False
    assert session.variable_choices == []
    assert session.build_preview("x", {}) is False
    assert not session.preview_valid


def test_variable_choices_are_the_declared_control_labels(tmp_path):
    _, controller, _ = _app(tmp_path)
    session = _session(controller)
    assert session.variable_choices == [
        ("pose_prompt", "Motion Prompt"),
        ("pose_strength", "Pose Strength"),
        ("pose_start_percent", "Pose Start %"),
        ("pose_end_percent", "Pose End %"),
        ("reference_image_strength", "Reference Image Strength"),
    ]


def test_baseline_text_shows_the_resolved_value(tmp_path):
    _, controller, _ = _app(tmp_path)
    session = _session(controller)
    session.select_variable("pose_strength")
    assert session.baseline_text(_form(tmp_path)) == "1"
    session.select_variable("pose_prompt")
    form = _form(tmp_path, operator_controls={"pose_prompt": ""})
    assert session.baseline_text(form) == "a woman in a navy top"  # resolved fallback, not ""
    session.select_variable("pose_end_percent")
    assert session.baseline_text(
        _form(tmp_path, operator_controls={"pose_end_percent": "2"})
    ).startswith("(invalid:")


def test_candidate_rows_are_bounded_to_three(tmp_path):
    _, controller, _ = _app(tmp_path)
    session = _session(controller)
    assert session.candidates == [""]
    assert session.add_candidate() and session.add_candidate()
    assert session.add_candidate() is False and len(session.candidates) == 3
    assert session.remove_candidate(0) and session.remove_candidate(0)
    assert session.remove_candidate(0) is False and len(session.candidates) == 1


def test_preview_states_the_single_change_and_queue_is_one_admission(tmp_path):
    source, _ = _files(tmp_path)
    _, controller, service = _app(tmp_path)
    session = _session(controller)
    session.select_variable("pose_strength")
    session.set_candidate(0, "1.5")
    session.add_candidate()
    session.set_candidate(1, "2")
    form = _form(tmp_path)

    assert session.build_preview(str(source), form) is True
    view = session.preview
    assert view is not None and service.calls == []
    assert view.statement == "Only Pose Strength changes across these jobs."
    assert view.common_seed == "5" and view.experiment_id
    assert view.arms == (
        ("A (baseline)", "Pose Strength = 1"),
        ("B", "Pose Strength = 1.5"),
        ("C", "Pose Strength = 2"),
    )
    fixed = dict(view.fixed)
    assert fixed["Seed"] == "5" and "Frames" in fixed and fixed["pose_prompt"] == "steps left"

    job_ids = session.queue(str(source), form)
    assert job_ids == ["job-0", "job-1", "job-2"]
    assert len(service.calls) == 1 and len(service.calls[0]) == 3
    assert "Queue / History" in session.message and not session.preview_valid


def test_editing_an_execution_field_after_preview_invalidates_it(tmp_path):
    source, _ = _files(tmp_path)
    _, controller, service = _app(tmp_path)
    session = _session(controller)
    session.select_variable("pose_strength")
    session.set_candidate(0, "1.5")
    form = _form(tmp_path)
    assert session.build_preview(str(source), form)

    edits = (
        {**form, "seed": "6"},
        {**form, "prompt": "a different prompt"},
        {**form, "negative_prompt": "blur"},
        {**form, "experimental_opt_in": False},
        {**form, "output_route": "Testing"},
        {**form, "operator_controls": {**form["operator_controls"], "pose_strength": "2"}},
        {**form, "frame_count": 33},
    )
    for edited in edits:
        assert session.build_preview(str(source), form)
        assert session.invalidate_if_changed(str(source), edited) is True
        assert session.queue(str(source), edited) == []
    assert session.build_preview(str(source), form)
    assert session.invalidate_if_changed(str(tmp_path / "other.png"), form) is True  # source edit
    assert service.calls == []


def test_candidate_edit_and_cancel_drop_the_preview_and_submit_nothing(tmp_path):
    source, _ = _files(tmp_path)
    _, controller, service = _app(tmp_path)
    session = _session(controller)
    session.select_variable("pose_strength")
    session.set_candidate(0, "1.5")
    form = _form(tmp_path)
    assert session.build_preview(str(source), form)
    session.set_candidate(0, "1.6")
    assert not session.preview_valid and session.queue(str(source), form) == []

    assert session.build_preview(str(source), form)
    session.cancel_preview()
    assert not session.preview_valid and session.queue(str(source), form) == []
    assert service.calls == []


def test_refused_preview_and_refused_queue_explain_and_queue_nothing(tmp_path):
    source, clip = _files(tmp_path)
    _, controller, service = _app(tmp_path)
    session = _session(controller)
    session.select_variable("pose_strength")
    session.set_candidate(0, "99")
    assert session.build_preview(str(source), _form(tmp_path)) is False
    assert "Preview refused" in session.message and "between 0 and 10" in session.message

    session.set_candidate(0, "1.5")
    form = _form(tmp_path)
    assert session.build_preview(str(source), form)
    clip.write_bytes(clip.read_bytes() + b"x")  # bytes change; the form text is unchanged
    assert session.queue(str(source), form) == []
    assert "changed after it was frozen" in session.message and not session.preview_valid
    assert service.calls == []


# ------------------------------------------------------------------ Tk tab


@pytest.mark.gui
def test_tab_shows_the_section_only_for_workflows_that_declare_controls(tk_root, tmp_path):
    app, _controller, _service = _app(tmp_path)
    tab = VideoWorkflowTabFrameV2(tk_root, app_controller=app, app_state=SimpleNamespace())
    panel = tab.experiment_panel

    tab.workflow_var.set(TI2V_ID)
    tab._refresh_workspace_summary()
    assert not panel.winfo_manager()

    tab.workflow_var.set(WAN_ANIMATE2_DRIVE_ID)
    tab._refresh_workspace_summary()
    assert panel.winfo_manager()
    assert list(panel.variable_combo["values"]) == [
        "Motion Prompt",
        "Pose Strength",
        "Pose Start %",
        "Pose End %",
        "Reference Image Strength",
    ]


class _ManualRunner:
    """Holds worker jobs so a test decides exactly when the 'worker' runs and completes."""

    def __init__(self) -> None:
        self.jobs: list[tuple[str, Any, Any]] = []

    def start(self, name, work, on_done) -> None:
        self.jobs.append((name, work, on_done))

    def drain(self) -> None:
        while self.jobs:
            _name, work, on_done = self.jobs.pop(0)
            on_done(work())


def _ready_tab(tk_root, tmp_path):
    source, clip = _files(tmp_path)
    app, controller, service = _app(tmp_path)
    tab = VideoWorkflowTabFrameV2(tk_root, app_controller=app, app_state=SimpleNamespace())
    tab.workflow_var.set(WAN_ANIMATE2_DRIVE_ID)
    tab._refresh_workspace_summary()
    tab.source_image_var.set(str(source))
    tab.pose_video_var.set(str(clip))
    tab.seed_var.set("11")
    tab._set_text_value(tab.prompt_text, "a woman in a navy top")
    tab.experimental_opt_in_var.set(True)
    panel = tab.experiment_panel
    runner = _ManualRunner()
    panel._runner = runner
    panel.enabled_var.set(True)
    panel._on_toggle()
    panel.variable_var.set("Pose Strength")
    panel._on_variable()
    panel._candidate_widgets[0]._experiment_var.set("1.5")
    return tab, panel, runner, app, controller, service, clip


def _spy_preview(controller, monkeypatch):
    calls: list[int] = []
    original = controller.preview_experiment

    def spy(**kwargs):
        calls.append(threading.get_ident())
        return original(**kwargs)

    monkeypatch.setattr(controller, "preview_experiment", spy)
    return calls


@pytest.mark.gui
def test_tab_preview_queue_and_invalidation_flow(tk_root, tmp_path):
    tab, panel, runner, app, _controller, service, _clip = _ready_tab(tk_root, tmp_path)
    assert panel.baseline_var.get() == "1"

    panel._on_preview()
    runner.drain()
    text = panel.preview_text.get("1.0", "end")
    assert "Only Pose Strength changes across these jobs." in text
    assert "common seed 11" in text and "A (baseline):  Pose Strength = 1" in text
    assert str(panel.queue_button.cget("state")) == "normal"
    assert service.calls == []

    tab.seed_var.set("12")  # any execution edit drops the preview
    assert str(panel.queue_button.cget("state")) == "disabled"
    assert panel.preview_text.get("1.0", "end").strip() == ""

    panel._on_preview()
    runner.drain()
    tab._set_text_value(tab.prompt_text, "changed")
    tab.prompt_text.event_generate("<<Cut>>")
    tab._invalidate_experiment_preview()
    assert str(panel.queue_button.cget("state")) == "disabled"

    tab._set_text_value(tab.prompt_text, "a woman in a navy top")
    panel._on_preview()
    runner.drain()
    tab.experimental_opt_in_var.set(False)  # opt-in is part of the previewed inputs
    assert str(panel.queue_button.cget("state")) == "disabled"
    tab.experimental_opt_in_var.set(True)

    panel._on_preview()
    runner.drain()
    panel._on_queue()
    runner.drain()
    assert len(service.calls) == 1 and len(service.calls[0]) == 2
    assert "Queued 2 experiment jobs" in tab.status_var.get()
    assert app.syncs == [threading.get_ident()]  # queue-state refresh ran on the Tk thread
    assert tab.experimental_opt_in_var.get() is True  # never silently enabled or cleared by it


@pytest.mark.gui
def test_handlers_schedule_work_instead_of_doing_it_on_the_tk_callback(
    tk_root, tmp_path, monkeypatch
):
    tab, panel, runner, _app_stub, controller, service, _clip = _ready_tab(tk_root, tmp_path)
    preview_calls = _spy_preview(controller, monkeypatch)
    admit_calls: list[int] = []
    original_submit = controller.submit_experiment
    monkeypatch.setattr(
        controller,
        "submit_experiment",
        lambda plan: (admit_calls.append(threading.get_ident()), original_submit(plan))[1],
    )

    panel._on_preview()  # the Tk callback returns having only scheduled work
    assert preview_calls == [] and len(runner.jobs) == 1
    assert runner.jobs[0][0].startswith("VideoExperiment-Preview-")
    assert panel.message_var.get() == "Building preview..."
    runner.drain()
    assert len(preview_calls) == 1

    panel._on_queue()
    assert admit_calls == [] and service.calls == [] and len(runner.jobs) == 1
    assert runner.jobs[0][0].startswith("VideoExperiment-Queue-")
    assert panel.message_var.get() == "Queueing experiment..."
    runner.drain()
    assert len(admit_calls) == 1 and len(service.calls) == 1


@pytest.mark.gui
def test_busy_state_blocks_duplicate_preview_and_duplicate_queue(tk_root, tmp_path):
    _tab, panel, runner, _app_stub, _controller, service, _clip = _ready_tab(tk_root, tmp_path)

    panel._on_preview()
    assert str(panel.preview_button.cget("state")) == "disabled"
    panel._on_preview()  # a second click while building schedules nothing
    assert len(runner.jobs) == 1
    runner.drain()
    assert str(panel.preview_button.cget("state")) == "normal"

    panel._on_queue()
    assert str(panel.queue_button.cget("state")) == "disabled"
    assert str(panel.cancel_button.cget("state")) == "disabled"
    panel._on_queue()  # a duplicate click must not become a second admission
    panel._on_preview()
    assert len(runner.jobs) == 1
    runner.drain()
    assert len(service.calls) == 1


@pytest.mark.gui
def test_form_or_candidate_edit_during_preview_discards_the_stale_result(tk_root, tmp_path):
    tab, panel, runner, _app_stub, _controller, service, _clip = _ready_tab(tk_root, tmp_path)

    panel._on_preview()
    tab.seed_var.set("99")  # form edit while the worker is outstanding
    runner.drain()
    assert not panel._session.preview_valid
    assert "changed while the preview was building" in panel.message_var.get()
    assert str(panel.queue_button.cget("state")) == "disabled"

    panel._on_preview()
    panel._candidate_widgets[0]._experiment_var.set("2")  # candidate edit while outstanding
    runner.drain()
    assert not panel._session.preview_valid
    assert str(panel.queue_button.cget("state")) == "disabled"

    panel._on_preview()  # a fresh preview on the current inputs is valid again
    runner.drain()
    assert panel._session.preview_valid and service.calls == []


@pytest.mark.gui
def test_worker_error_is_an_operator_visible_refusal_and_queues_nothing(
    tk_root, tmp_path, monkeypatch
):
    _tab, panel, runner, _app_stub, controller, service, clip = _ready_tab(tk_root, tmp_path)
    panel._candidate_widgets[0]._experiment_var.set("99")
    panel._on_preview()
    runner.drain()
    message = panel.message_var.get()
    assert "Preview refused" in message and "between 0 and 10" in message

    panel._candidate_widgets[0]._experiment_var.set("1.5")
    panel._on_preview()
    runner.drain()
    clip.write_bytes(clip.read_bytes() + b"changed")  # bytes change after the preview
    panel._on_queue()
    runner.drain()
    message = panel.message_var.get()
    assert "Queue refused, nothing was queued" in message
    assert "changed after it was frozen" in message
    assert service.calls == [] and str(panel.queue_button.cget("state")) == "disabled"

    def explode(**_kwargs):
        raise OSError("disk")

    monkeypatch.setattr(controller, "preview_experiment", explode)
    panel._on_preview()
    runner.drain()
    assert "Preview refused: disk" in panel.message_var.get()


@pytest.mark.gui
def test_destroying_the_panel_before_the_worker_completes_is_safe(tk_root, tmp_path):
    tab, panel, runner, _app_stub, _controller, service, _clip = _ready_tab(tk_root, tmp_path)
    panel._on_preview()
    tab.destroy()
    runner.drain()  # completion arrives after teardown: no Tk error, nothing queued
    assert service.calls == []


@pytest.mark.gui
def test_real_worker_thread_completes_on_the_tk_thread(tk_root, tmp_path, monkeypatch):
    import time

    _tab, panel, _runner, _app_stub, _controller, _service, _clip = _ready_tab(tk_root, tmp_path)
    panel._runner = None  # use the real ThreadRegistry worker + TkUiDispatcher marshal
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
    deadline = time.monotonic() + 10
    while session.busy and time.monotonic() < deadline:
        tk_root.update()
        time.sleep(0.01)
    assert session.preview_valid
    assert seen["worker"] != main and seen["finish"] == main


# ------------------------------------------------------------------ neutral concurrency contract


def test_runner_runs_work_off_thread_and_delivers_only_through_the_dispatcher():
    threads: list[threading.Thread] = []
    dispatched: list[Any] = []
    ran: dict[str, int] = {}
    delivered: dict[str, Any] = {}

    def spawn(name, target):
        thread = threading.Thread(target=target, name=name)
        threads.append(thread)
        thread.start()

    def work() -> WorkOutcome:
        ran["w"] = threading.get_ident()
        return WorkOutcome(value=7)

    def done(outcome: WorkOutcome) -> None:
        delivered.update(thread=threading.get_ident(), value=outcome.value)

    runner = BackgroundWorkRunner(spawn=spawn, dispatch=dispatched.append)
    runner.start("t", work, done)
    threads[0].join(5)
    assert ran["w"] != threading.get_ident() and delivered == {}  # nothing delivered yet
    assert len(dispatched) == 1
    dispatched[0]()  # the UI thread drains its queue
    assert delivered == {"thread": threading.get_ident(), "value": 7}


def test_runner_reports_worker_exceptions_and_survives_a_dead_dispatcher():
    delivered: list[WorkOutcome] = []
    queue: list[Any] = []
    runner = BackgroundWorkRunner(spawn=lambda _n, target: target(), dispatch=queue.append)

    def boom() -> WorkOutcome:
        raise RuntimeError("disk gone")

    runner.start("t", boom, delivered.append)
    queue.pop()()
    assert delivered[0].error == "disk gone"

    def dead(_fn):
        raise RuntimeError("root destroyed")

    BackgroundWorkRunner(spawn=lambda _n, target: target(), dispatch=dead).start(
        "t", lambda: WorkOutcome(value=1), delivered.append
    )  # must not raise


def test_session_steps_enforce_busy_staleness_and_single_admission(tmp_path):
    source, _ = _files(tmp_path)
    _, controller, service = _app(tmp_path)
    session = _session(controller)
    session.select_variable("pose_strength")
    session.set_candidate(0, "1.5")
    form = _form(tmp_path)

    work = session.begin_preview(str(source), form)
    assert work is not None and session.busy == "preview"
    assert session.begin_preview(str(source), form) is None  # no second preview while busy
    assert session.begin_queue(str(source), form) is None
    session.set_candidate(0, "1.6")  # candidate edit while the worker is outstanding
    assert session.finish_preview(work, session.run_preview(work), str(source), form) is False
    assert not session.preview_valid and session.busy is None

    work = session.begin_preview(str(source), form)
    outcome = session.run_preview(work)
    assert session.finish_preview(work, outcome, str(source), {**form, "seed": "9"}) is False
    assert not session.preview_valid

    work = session.begin_preview(str(source), form)
    assert session.finish_preview(work, session.run_preview(work), str(source), form) is True
    queue_work = session.begin_queue(str(source), form)
    assert queue_work is not None and session.busy == "queue"
    assert session.begin_queue(str(source), form) is None  # no duplicate admission
    session.cancel_preview()
    assert session.busy == "queue" and service.calls == []
    assert session.finish_queue(queue_work, session.run_queue(queue_work)) == ["job-0", "job-1"]
    assert len(service.calls) == 1 and len(service.calls[0]) == 2  # one call, all arms


def test_preview_worker_gets_a_plain_snapshot_not_the_live_form(tmp_path):
    source, _ = _files(tmp_path)
    _, controller, _service = _app(tmp_path)
    session = _session(controller)
    session.select_variable("pose_strength")
    session.set_candidate(0, "1.5")
    form = _form(tmp_path)
    work = session.begin_preview(str(source), form)
    form["operator_controls"]["pose_strength"] = "7"  # later mutation of the live dict
    form["seed"] = "1"
    assert work.form_data["seed"] == "5"
    assert work.form_data["operator_controls"]["pose_strength"] == "1"


@pytest.mark.gui
def test_normal_queue_button_is_unchanged_when_experiment_mode_is_off(tk_root, tmp_path):
    source, clip = _files(tmp_path)
    app, _controller, service = _app(tmp_path)
    tab = VideoWorkflowTabFrameV2(tk_root, app_controller=app, app_state=SimpleNamespace())
    tab.workflow_var.set(WAN_ANIMATE2_DRIVE_ID)
    tab._refresh_workspace_summary()
    tab.source_image_var.set(str(source))
    tab.pose_video_var.set(str(clip))
    tab._set_text_value(tab.prompt_text, "a woman in a navy top")
    tab.experimental_opt_in_var.set(True)
    assert tab.experiment_panel.enabled_var.get() is False

    import tkinter.messagebox as messagebox

    messagebox.showinfo = lambda *a, **k: None  # type: ignore[assignment]
    tab._on_submit()
    assert len(service.calls) == 1 and len(service.calls[0]) == 1
    assert service.calls[0][0].learning_context is None
