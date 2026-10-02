"""PR-VID-194: the "Compare one control" section (neutral session + Tk panel).

The neutral session is exercised against the real Video Workflow controller with a fake
JobService; the Tk tests drive the real tab.  No Comfy/WebUI/GPU/network.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from src.controller.video_workflow_controller import VideoWorkflowController
from src.gui.view_contracts.video_experiment_contract import VideoExperimentSession
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
    app = SimpleNamespace(job_service=service, output_dir=str(tmp_path / "output"))
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


@pytest.mark.gui
def test_tab_preview_queue_and_invalidation_flow(tk_root, tmp_path):
    source, clip = _files(tmp_path)
    app, _controller, service = _app(tmp_path)
    tab = VideoWorkflowTabFrameV2(tk_root, app_controller=app, app_state=SimpleNamespace())
    tab.workflow_var.set(WAN_ANIMATE2_DRIVE_ID)
    tab._refresh_workspace_summary()
    tab.source_image_var.set(str(source))
    tab.pose_video_var.set(str(clip))
    tab.seed_var.set("11")
    tab._set_text_value(tab.prompt_text, "a woman in a navy top")
    tab.experimental_opt_in_var.set(True)
    panel = tab.experiment_panel

    panel.enabled_var.set(True)
    panel._on_toggle()
    panel.variable_var.set("Pose Strength")
    panel._on_variable()
    assert panel.baseline_var.get() == "1"
    panel._candidate_widgets[0]._experiment_var.set("1.5")

    panel._on_preview()
    text = panel.preview_text.get("1.0", "end")
    assert "Only Pose Strength changes across these jobs." in text
    assert "common seed 11" in text and "A (baseline):  Pose Strength = 1" in text
    assert str(panel.queue_button.cget("state")) == "normal"
    assert service.calls == []

    tab.seed_var.set("12")  # any execution edit drops the preview
    assert str(panel.queue_button.cget("state")) == "disabled"
    assert panel.preview_text.get("1.0", "end").strip() == ""

    panel._on_preview()
    tab._set_text_value(tab.prompt_text, "changed")
    tab.prompt_text.event_generate("<<Cut>>")
    tab._invalidate_experiment_preview()
    assert str(panel.queue_button.cget("state")) == "disabled"

    tab._set_text_value(tab.prompt_text, "a woman in a navy top")
    panel._on_preview()
    tab.experimental_opt_in_var.set(False)  # opt-in is part of the previewed inputs
    assert str(panel.queue_button.cget("state")) == "disabled"
    tab.experimental_opt_in_var.set(True)

    panel._on_preview()
    panel._on_queue()
    assert len(service.calls) == 1 and len(service.calls[0]) == 2
    assert "Queued 2 experiment jobs" in tab.status_var.get()
    assert tab.experimental_opt_in_var.get() is True  # never silently enabled or cleared by it


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
