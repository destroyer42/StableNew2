"""Prompt Slot authoring and lifecycle on the existing Learning Design surface."""

from types import SimpleNamespace

import pytest

from src.gui.views.experiment_design_panel import ExperimentDesignPanel
from tests.gui_v2.tk_test_utils import get_shared_tk_root
from tests.learning_v2.test_learning_independent_baseline_650 import Bench


@pytest.fixture
def panel(tmp_path):
    root = get_shared_tk_root()
    if root is None:
        pytest.skip("Tk is unavailable")
    bench = Bench(tmp_path)
    bench.controller.app_state = SimpleNamespace(resources={}, content_visibility_mode="nsfw")
    bench.controller.copy_pipeline_settings("txt2img")
    widget = ExperimentDesignPanel(root, learning_controller=bench.controller, packs_dir=tmp_path)
    widget.prompt_source_var.set("custom")
    widget._choose_prompt_slot()
    widget.custom_prompt_text.delete("1.0", "end")
    widget.custom_prompt_text.insert("1.0", "A [[expression]] knight")
    widget.prompt_slot_frame.refresh_slots()
    yield widget, bench
    widget.destroy()
    root.update_idletasks()


def test_prompt_slot_is_selectable_and_candidates_reorder(panel):
    widget, _bench = panel
    assert widget.variable_var.get() == "Prompt Slot"
    frame = widget.prompt_slot_frame
    for text in ("calm", "angry", "weary"):
        frame.value_var.set(text)
        frame.add()
    assert frame.spec()["candidates"] == ["calm", "angry", "weary"]
    frame.candidate_list.selection_set(2)
    frame.move(-1)
    assert frame.spec()["candidates"] == ["calm", "weary", "angry"]
    assert "3 candidates" in widget.estimate_var.get()
    frame.remove()
    assert len(frame.spec()["candidates"]) == 2


def test_preview_freezes_and_edit_marks_stale(panel):
    widget, bench = panel
    for text in ("calm", "angry"):
        widget.prompt_slot_frame.value_var.set(text)
        widget.prompt_slot_frame.add()
    widget._on_build_preview()
    assert bench.state.current_experiment.execution_snapshot_json
    assert not widget.preview_is_stale()
    widget.prompt_slot_frame.value_var.set("weary")
    widget.prompt_slot_frame.add()
    assert widget.preview_is_stale()
    assert not bench.service.submit_njrs.called


def test_fixed_slots_explicit_and_text_hidden_on_visibility_change(panel):
    widget, bench = panel
    widget.custom_prompt_text.delete("1.0", "end")
    widget.custom_prompt_text.insert("1.0", "[[expression]] at [[place]]")
    frame = widget.prompt_slot_frame
    frame.refresh_slots()
    frame.slot_var.set("expression")
    frame._fixed_fields()
    for text in ("calm", "angry"):
        frame.value_var.set(text)
        frame.add()
    assert frame.validation_error(1)
    frame._fixed_vars["place"].set("forest")
    assert not frame.validation_error(1)
    bench.controller.app_state.content_visibility_mode = "sfw"
    widget._on_comparison_visibility_changed()
    assert "angry" not in str(frame.candidate_list.get(0, "end"))
    assert frame.value_entry.cget("show")
    assert frame.negative_entry.cget("show")
    assert str(widget.custom_prompt_text.tag_cget("slot_hidden", "elide")) == "1"


def test_keyboard_add_restore_and_destroy(panel):
    widget, bench = panel
    frame = widget.prompt_slot_frame
    for text in ("calm", "angry"):
        frame.value_var.set(text)
        frame.add()
    widget._on_build_preview()
    experiment = bench.state.current_experiment
    experiment.name = "Operator chosen name"
    widget.restore_state(experiment)
    assert widget.name_var.get() == "Operator chosen name"
    assert frame.spec()["candidates"] == ["calm", "angry"]
    assert frame.value_entry.bind("<Return>")
    assert frame.value_entry.cget("takefocus") in ("", "1", 1, "ttk::takefocus")


def test_restored_native_fixed_slots_do_not_depend_on_a_live_pack(panel):
    widget, _bench = panel
    frame = widget.prompt_slot_frame
    widget.custom_prompt_text.delete("1.0", "end")
    frame.load(
        {"slot": "expression", "candidates": ["calm", "angry"], "fixed_slots": {"place": "forest"}},
        frozen_template="[[expression]] at [[place]]",
    )
    assert frame.spec()["fixed_slots"] == {"place": "forest"}
    assert frame.spec()["template"] == "[[expression]] at [[place]]"
    assert not frame.validation_error(1)
    frame.clear_frozen_source()
    assert frame.spec()["template"] == ""


@pytest.mark.parametrize("scaling", [1.0, 2.0])
def test_prompt_slot_controls_have_scroll_access_at_compact_and_high_dpi(tmp_path, scaling):
    from src.queue.job_repository import JobRepository
    from tests.gui_v2.test_learning_guided_workflow_590 import build_tab

    root = get_shared_tk_root()
    if root is None:
        pytest.skip("Tk is unavailable")
    original_scaling = root.tk.call("tk", "scaling")
    repository = JobRepository(tmp_path / "layout.sqlite3")
    tab = None
    try:
        root.tk.call("tk", "scaling", scaling)
        tab, _service = build_tab(root, tmp_path, repository)
        root.geometry("1366x768")
        tab.place(x=0, y=0, width=1366, height=720)
        panel = tab.experiment_panel
        panel._choose_prompt_slot()
        root.update_idletasks()
        assert panel.prompt_slot_frame.winfo_manager() == "grid"
        assert tab.experiment_scroll._vsb.winfo_manager() == "grid"
        assert panel.prompt_slot_frame.winfo_reqwidth() <= 500
        assert panel.prompt_slot_frame.value_entry.winfo_exists()
        assert panel.prompt_slot_frame.negative_entry.winfo_exists()
    finally:
        if tab is not None:
            tab.destroy()
        root.tk.call("tk", "scaling", original_scaling)
        root.withdraw()
        repository.close()
