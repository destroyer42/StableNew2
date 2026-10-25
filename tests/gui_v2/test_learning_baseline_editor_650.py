"""Real-Tk coverage of the Learning baseline editor inside the guided Design step (PR-LEARN-STAGE-650).

Nothing starts generation; the Pipeline is a plain dict and the only submission seam is a recording fake.
"""

from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from src.learning import baseline_authoring as authoring
from src.learning.guided_workflow import STEP_DESIGN, STEP_PREVIEW
from src.queue.job_repository import JobRepository
from tests.gui_v2.test_learning_guided_workflow_590 import (
    build_tab,
    click_primary,
    design_cfg_sweep,
    primary_enabled,
)
from tests.gui_v2.tk_test_utils import get_shared_tk_root
from tests.learning_v2.test_model_comparison_140 import SDXL, baseline

PEER = "peer.safetensors"


@pytest.fixture
def root():
    shared = get_shared_tk_root()
    if shared is None:
        pytest.skip("No display available for Tkinter tests")
    return shared


@pytest.fixture
def tab_env(root, tmp_path):
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    tab, service = build_tab(root, tmp_path, repository)
    pipeline = {"config": baseline()}
    tab.learning_controller._get_baseline_config = lambda: copy.deepcopy(pipeline["config"])
    tab.pack(fill="both", expand=True)
    root.update()
    yield SimpleNamespace(tab=tab, service=service, pipeline=pipeline, panel=tab.experiment_panel)
    tab.destroy()
    repository.close()


def editor_of(env):
    editor = env.panel.baseline_editor
    editor.rebuild()
    return editor


def test_s01_design_step_shows_an_editable_baseline_seeded_once_with_its_origin(tab_env):
    editor = editor_of(tab_env)
    controller = tab_env.tab.learning_controller
    controller.ensure_baseline("txt2img")
    editor.refresh()
    assert editor.origin_var.get().startswith("Baseline: Copied from Pipeline")
    assert editor._vars["steps"].get() == "30"
    assert editor._vars["model"].get() == SDXL
    assert str(editor.copy_button.cget("state")) == "normal"


def test_s02_s03_s04_edits_stay_in_learning_and_pipeline_changes_stay_out(tab_env):
    editor = editor_of(tab_env)
    controller = tab_env.tab.learning_controller
    controller.ensure_baseline("txt2img")
    editor.refresh()
    editor._vars["steps"].set("12")
    assert controller.authoring_baseline()["txt2img"]["steps"] == 12
    assert (
        tab_env.pipeline["config"]["txt2img"]["steps"] == 30
    )  # Learning never writes the Pipeline
    assert "changed in Learning" in editor.origin_var.get()

    tab_env.pipeline["config"]["txt2img"].update(steps=99, sampler_name="Euler")
    editor.refresh()
    assert editor._vars["steps"].get() == "12"
    assert editor._vars["sampler_name"].get() == "DPM++ 2M"


def test_explicit_copy_replaces_only_the_editable_baseline_after_confirmation(tab_env):
    editor = editor_of(tab_env)
    controller = tab_env.tab.learning_controller
    controller.ensure_baseline("txt2img")
    editor.refresh()
    editor._vars["steps"].set("12")
    tab_env.pipeline["config"]["txt2img"]["steps"] = 44
    assert editor.copy_from_pipeline(confirmed=False) is False
    assert controller.authoring_baseline()["txt2img"]["steps"] == 12
    assert editor.copy_from_pipeline(confirmed=True) is True
    assert controller.authoring_baseline()["txt2img"]["steps"] == 44
    assert controller.baseline_authoring_record()["origin"] == authoring.ORIGIN_PIPELINE_COPY
    assert controller.baseline_authoring_record()["edited"] == []


def test_s06_s44_resource_refresh_keeps_the_selection_and_reports_it(tab_env, root):
    editor = editor_of(tab_env)
    controller = tab_env.tab.learning_controller
    controller.ensure_baseline("txt2img")
    controller.app_state = SimpleNamespace(
        resources={"models": [SDXL, PEER], "samplers": ["DPM++ 2M"], "schedulers": ["Karras"]}
    )
    editor.refresh()
    assert list(editor._widgets["model"].cget("values")) == [SDXL, PEER]
    assert editor.problems() == []

    controller.app_state = SimpleNamespace(
        resources={"models": [PEER], "samplers": ["DPM++ 2M"], "schedulers": ["Karras"]}
    )
    editor.refresh()
    root.update()
    assert editor._vars["model"].get() == SDXL  # never silently replaced
    assert any("not available" in problem for problem in editor.problems())
    assert "Still needed" in editor.problems_var.get()
    assert not tab_env.panel._baseline_blockers() == []


def test_s16_editing_the_baseline_after_preview_marks_the_preview_stale(tab_env, root):
    tab, panel = tab_env.tab, tab_env.panel
    design_cfg_sweep(panel)
    click_primary(tab, root)
    assert not panel.preview_is_stale()
    snapshot = tab.learning_controller.learning_state.current_experiment.execution_snapshot_json

    tab._on_step_selected(STEP_DESIGN)
    editor_of(tab_env)._vars["steps"].set("11")
    root.update()
    assert panel.preview_is_stale()
    tab._on_step_selected(STEP_PREVIEW)
    assert not primary_enabled(tab)
    assert "Preview out of date" in tab.workflow_bar.status_var.get()
    assert panel.request_run() == 0
    assert tab_env.service.calls == []
    assert (
        tab.learning_controller.learning_state.current_experiment.execution_snapshot_json
        == snapshot
    )


def test_s17_pipeline_changes_after_preview_leave_the_preview_current(tab_env, root):
    tab, panel = tab_env.tab, tab_env.panel
    design_cfg_sweep(panel)
    click_primary(tab, root)
    tab_env.pipeline["config"]["txt2img"].update(steps=5, model=PEER, sampler_name="Euler")
    root.update()
    assert not panel.preview_is_stale()
    assert tab_env.service.calls == []


def test_s08_the_swept_variable_owns_its_baseline_control(tab_env):
    panel = tab_env.panel
    editor = editor_of(tab_env)
    tab_env.tab.learning_controller.ensure_baseline("txt2img")
    panel.variable_var.set("CFG Scale")
    panel._on_variable_changed()
    editor.refresh()
    assert str(editor._widgets["cfg_scale"].cget("state")) == "disabled"
    assert "sweep" in editor._notes["cfg_scale"].get()
    assert str(editor._widgets["steps"].cget("state")) != "disabled"


@pytest.mark.parametrize("stage", ["img2img", "adetailer", "upscale"])
def test_the_editor_exposes_each_stages_own_settings(tab_env, stage):
    panel = tab_env.panel
    tab_env.tab.learning_controller.ensure_baseline(stage)
    panel.stage_var.set(stage)
    panel._on_stage_changed()
    editor = panel.baseline_editor
    assert set(editor._vars) == {spec.name for spec in authoring.fields_for_stage(stage)}


def test_s45_the_baseline_and_primary_action_are_reachable_in_a_compact_window(root, tmp_path):
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    tab, _service = build_tab(root, tmp_path, repository)
    try:
        root.geometry("1366x768")
        tab.place(x=0, y=0, width=1366, height=720)
        root.deiconify()
        root.update()
        panel = tab.experiment_panel
        assert panel.baseline_section.winfo_manager() == "grid"
        assert panel.baseline_editor.winfo_manager() == "grid"
        assert tab.experiment_scroll._vsb.winfo_manager() == "grid"
        assert tab.workflow_bar.primary_button.winfo_ismapped()
        assert panel.baseline_editor.copy_button.winfo_exists()
    finally:
        tab.destroy()
        root.withdraw()
        repository.close()
