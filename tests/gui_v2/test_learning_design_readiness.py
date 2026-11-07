"""Real-Tk: Build Preview says why it is disabled, and inherited exclusions can be turned off in Learning.

Before this change the panel computed the exact refusal, discarded it, and showed only a fixed hint, so a disabled
Build Preview gave the operator nothing to act on.
"""

from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from src.gui.views.experiment_design_panel import ExperimentDesignPanel
from src.learning import baseline_exclusions as ex
from src.queue.job_repository import JobRepository
from tests.gui_v2.test_learning_guided_workflow_590 import build_tab
from tests.gui_v2.test_lora_composition_design_690 import A, B, pump, resource, select_row
from tests.gui_v2.tk_test_utils import get_shared_tk_root
from tests.learning_v2.test_learning_independent_baseline_650 import PEER, Bench
from tests.learning_v2.test_lora_composition_690 import FIXED, KNIGHT, assets
from tests.learning_v2.test_model_comparison_140 import SDXL


def tk_or_skip():
    root = get_shared_tk_root()
    if root is None:
        pytest.skip("Tk is unavailable")
    return root


@pytest.fixture
def panel(tmp_path):
    """LoRA Composition on the real Design panel over a real LearningController (as in the 690 GUI tests)."""
    root = tk_or_skip()
    bench = Bench(tmp_path)
    bench.controller.app_state = SimpleNamespace(resources={}, content_visibility_mode="nsfw")
    bench.controller._learning_lora_asset_resolver = assets()
    bench.controller.lora_inventory_loader = lambda cancelled: {n: resource(n) for n in (A, B)}
    bench.controller.copy_pipeline_settings("txt2img")
    widget = ExperimentDesignPanel(root, learning_controller=bench.controller, packs_dir=tmp_path)
    widget.prompt_source_var.set("custom")
    widget._choose_lora_composition()
    widget.custom_prompt_text.delete("1.0", "end")
    widget.custom_prompt_text.insert("1.0", KNIGHT + " " + FIXED)
    widget._on_prompt_text_edited()
    yield widget, bench, root
    widget.destroy()
    root.update_idletasks()


@pytest.fixture
def tab(tmp_path):
    root = tk_or_skip()
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    learning_tab, _service = build_tab(root, tmp_path, repository)
    learning_tab.pack(fill="both", expand=True)
    root.update()
    yield learning_tab, root
    learning_tab.destroy()
    repository.close()


def build_state(widget) -> str:
    return str(widget.build_button.cget("state"))


def compare_two(widget, root) -> None:
    frame = widget.lora_composition_frame
    assert pump(root, lambda: bool(frame._rows))
    for name in (A, B):
        select_row(frame, name)
        frame.add_selected()
    frame.operation_var.set("Compare Candidates")


# -- LoRA Composition ---------------------------------------------------------------------------------------------


def test_lora_add_remove_with_two_loras_says_why_and_compare_enables(panel):
    widget, _bench, root = panel
    frame = widget.lora_composition_frame
    assert pump(root, lambda: bool(frame._rows))
    frame.add_empty()
    for name in (A, B):
        select_row(frame, name)
        frame.add_selected()
    assert frame.operation_var.get() == "Add / Remove"
    assert build_state(widget) == "disabled"
    assert "exactly one LoRA" in widget.readiness_reason()
    assert "exactly one LoRA" in widget.readiness_var.get()
    assert (
        "one LoRA at different strengths" in frame.rule_var.get()
    )  # the rule is shown before the trap

    frame.operation_var.set(
        "Compare Candidates"
    )  # selecting the operation alone re-evaluates readiness
    assert "same strength" in frame.rule_var.get()
    assert build_state(widget) == "normal", widget.readiness_reason()
    assert widget.readiness_reason() == "" and widget.readiness_var.get() == ""


def test_the_fixed_optimizer_hint_is_gone_and_only_real_requirements_show(panel):
    widget, _bench, _root = panel
    assert "optimizer" not in widget.model_target_var.get().lower()
    assert "registry-verified SDXL txt2img" in widget.model_target_var.get()


def test_prompt_optimizer_in_the_learning_baseline_can_be_turned_off_in_learning(panel):
    widget, bench, root = panel
    compare_two(widget, root)
    assert build_state(widget) == "normal", widget.readiness_reason()
    bench.state.baseline_draft["config"]["prompt_optimizer"] = {"enabled": True}
    widget._on_baseline_changed()
    editor = widget.baseline_editor
    assert build_state(widget) == "disabled"
    assert "prompt optimizer" in widget.readiness_reason().lower()
    assert "Turn Off for This Study" in widget.readiness_reason()
    assert editor.exclusions_frame.winfo_manager() == "grid"
    assert "Prompt optimizer" in editor.exclusions_var.get()

    pipeline_before = copy.deepcopy(bench.pipeline)
    editor.exclusions_button.invoke()
    root.update()
    assert build_state(widget) == "normal", widget.readiness_reason()
    assert bench.controller.authoring_baseline()["prompt_optimizer"]["enabled"] is False
    assert bench.pipeline == pipeline_before
    assert editor.exclusions_frame.winfo_manager() == ""


def test_baseline_editor_offers_no_exclusion_control_for_an_ordinary_sweep(tmp_path):
    root = tk_or_skip()
    bench = Bench(tmp_path)
    bench.pipeline["prompt_optimizer"] = {"enabled": True}
    bench.controller.copy_pipeline_settings("txt2img")
    widget = ExperimentDesignPanel(root, learning_controller=bench.controller, packs_dir=tmp_path)
    try:
        widget.baseline_editor.refresh()
        assert widget.baseline_editor.exclusions_frame.winfo_manager() == ""
    finally:
        widget.destroy()


# -- Prompt x Model Matrix ----------------------------------------------------------------------------------------


@pytest.fixture
def matrix(tmp_path):
    root = tk_or_skip()
    bench = Bench(tmp_path, resources={"models": [SDXL, PEER]})
    bench.controller.copy_pipeline_settings("txt2img")
    widget = ExperimentDesignPanel(root, learning_controller=bench.controller, packs_dir=tmp_path)
    widget.study_type_var.set("Prompt x Model Matrix")
    widget._on_study_type_changed()
    widget.prompt_source_var.set("custom")
    widget._on_prompt_source_changed()
    root.update()
    yield widget, bench, root
    widget.destroy()
    root.update_idletasks()


def type_prompt(widget, text: str) -> None:
    widget.custom_prompt_text.delete("1.0", "end")
    widget.custom_prompt_text.insert("1.0", text)
    widget._on_prompt_text_edited()  # the <KeyRelease> handler


def test_matrix_slots_follow_the_prompt_and_the_count_follows_the_models(matrix):
    widget, _bench, root = matrix
    frame = widget.matrix_frame
    assert "[[slot_name]]" in frame.instructions_var.get()
    type_prompt(widget, "portrait of a [[subject]] in a forest")
    assert tuple(frame.slot_box.cget("values")) == ("subject",)
    assert frame.slot_var.get() == "subject"  # no Refresh Named Slots press needed
    for value in ("knight", "wizard"):
        frame.value_var.set(value)
        frame.add()
    assert build_state(widget) == "disabled"
    assert "models" in widget.readiness_reason()
    for name in list(widget.choice_vars)[:2]:
        widget.choice_vars[name].set(True)
    root.update()
    assert frame.count_var.get().startswith("2 prompts x 2 models = 4 cells")
    assert build_state(widget) == "normal", widget.readiness_reason()

    type_prompt(widget, "portrait of a [[subject]] in a [[place]]")
    assert (
        frame.slot_var.get() == "subject"
    )  # the chosen slot survives an edit that still contains it
    assert build_state(widget) == "disabled"
    assert "fixed value" in widget.readiness_reason()


def test_matrix_without_a_named_slot_explains_the_missing_slot(matrix):
    widget, _bench, root = matrix
    type_prompt(widget, "portrait of a knight in a forest")
    frame = widget.matrix_frame
    for value in ("knight", "wizard"):
        frame.value_var.set(value)
        frame.add()
    for name in list(widget.choice_vars)[:2]:
        widget.choice_vars[name].set(True)
    root.update()
    assert build_state(widget) == "disabled"
    assert "named slot" in widget.readiness_reason()


def test_matrix_inherited_hires_is_reported_before_preview_and_cleared_in_learning(matrix):
    widget, bench, root = matrix
    bench.state.baseline_draft["config"]["txt2img"]["enable_hr"] = True
    widget._on_baseline_changed()
    type_prompt(widget, "portrait of a [[subject]]")
    frame = widget.matrix_frame
    for value in ("knight", "wizard"):
        frame.value_var.set(value)
        frame.add()
    for name in list(widget.choice_vars)[:2]:
        widget.choice_vars[name].set(True)
    root.update()
    assert build_state(widget) == "disabled"
    assert "hires fix" in widget.readiness_reason()
    editor = widget.baseline_editor
    assert "Hires fix" in editor.exclusions_var.get()
    editor.exclusions_button.invoke()
    root.update()
    assert build_state(widget) == "normal", widget.readiness_reason()
    assert bench.controller.baseline_exclusions(ex.MATRIX) == []


# -- guide bar ----------------------------------------------------------------------------------------------------


def test_the_guide_bar_shows_the_panels_reason_instead_of_a_generic_line(tab):
    tab, root = tab
    panel = tab.experiment_panel
    panel.study_type_var.set("Prompt x Model Matrix")
    panel._on_study_type_changed()
    root.update()
    tab._refresh_guide(force=True)
    reason = panel.readiness_reason()
    assert reason and str(panel.build_button.cget("state")) == "disabled"
    assert str(tab.workflow_bar.primary_button.cget("text")) == "Build Preview"
    assert tab.workflow_bar.notice_var.get().startswith(reason)
    assert "Complete the design" not in tab.workflow_bar.notice_var.get()
