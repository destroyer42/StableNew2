"""LoRA Composition authoring, discovery lifecycle and visibility on the existing Learning Design surface."""

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.assets.compatibility import (
    CompatibilityProfile,
    CompatibilityStatus,
    EvidenceConfidence,
    FamilyEvidence,
    ModelFamily,
)
from src.assets.registry import AssetRecord
from src.gui.views.experiment_design_panel import ExperimentDesignPanel
from src.utils.lora_scanner import LoRAResource
from tests.gui_v2.tk_test_utils import get_shared_tk_root
from tests.learning_v2.test_learning_independent_baseline_650 import Bench
from tests.learning_v2.test_lora_composition_690 import FIXED, KNIGHT, A, B, assets


def resource(name: str, family=ModelFamily.SDXL, *, nsfw=False) -> LoRAResource:
    evidence = (
        FamilyEvidence(
            family, "embedded_metadata:ss_base_model_version", "sdxl", EvidenceConfidence.METADATA
        ),
    )
    record = AssetRecord(
        "ab" * 32,
        (),
        {},
        None,
        compatibility=CompatibilityProfile(CompatibilityStatus.RESOLVED, family, evidence),
    )
    return LoRAResource(
        name, Path(f"{name}.safetensors"), 1, [], "none", record=record, visibility={"nsfw": nsfw}
    )


def pump(root, until, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root.update()
        if until():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def panel(tmp_path):
    root = get_shared_tk_root()
    if root is None:
        pytest.skip("Tk is unavailable")
    bench = Bench(tmp_path)
    bench.controller.app_state = SimpleNamespace(resources={}, content_visibility_mode="nsfw")
    bench.controller._learning_lora_asset_resolver = assets()
    bench.controller.lora_inventory_loader = lambda cancelled: {
        n: resource(n) for n in (A, B, "BetterThanWords", "Other-Family")
    } | {"Other-Family": resource("Other-Family", ModelFamily.SD1)}
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


def select_row(frame, name):
    index = next(i for i, row in enumerate(frame._rows) if row.name == name)
    frame.inventory_list.selection_clear(0, "end")
    frame.inventory_list.selection_set(index)


def test_installed_inventory_loads_off_the_tk_thread_and_marks_status(panel):
    widget, _bench, root = panel
    frame = widget.lora_composition_frame
    assert widget.variable_var.get() == "LoRA Composition"
    assert pump(root, lambda: bool(frame._rows))
    rows = {row.name: row for row in frame._rows}
    assert rows[A].selectable and "family evidence matches" in rows[A].label
    assert rows["BetterThanWords"].fixed and not rows["BetterThanWords"].selectable
    assert not rows["Other-Family"].selectable and "Incompatible" in rows["Other-Family"].label
    assert "BetterThanWords @ 0.55" in frame.fixed_list.get(0, "end")


def test_candidates_are_deliberate_ordered_and_preview_freezes(panel):
    widget, bench, root = panel
    frame = widget.lora_composition_frame
    assert pump(root, lambda: bool(frame._rows))
    assert frame.spec()["candidates"] == []  # nothing is preselected from the inventory
    frame.add_empty()
    for name in (A, B):
        select_row(frame, name)
        frame.add_selected()
    assert [c["name"] for c in frame.spec()["candidates"]] == [None, A, B]
    assert "3 candidates" in widget.estimate_var.get()
    frame.candidate_list.selection_set(2)
    frame.move(-1)
    assert [c["name"] for c in frame.spec()["candidates"]] == [None, B, A]
    frame.operation_var.set("Compare Candidates")
    widget._on_build_preview()
    snapshot = bench.state.current_experiment.execution_snapshot_json
    assert snapshot and not widget.preview_is_stale() and not bench.service.submit_njrs.called
    frame.add_empty()
    assert widget.preview_is_stale()
    assert not bench.service.submit_njrs.called


def test_unusable_inventory_rows_cannot_be_added(panel):
    widget, _bench, root = panel
    frame = widget.lora_composition_frame
    assert pump(root, lambda: bool(frame._rows))
    select_row(frame, "Other-Family")
    frame.add_selected()
    select_row(frame, "BetterThanWords")
    frame.add_selected()
    assert frame.spec()["candidates"] == [] and "usable" in frame.detail_var.get()


def test_stale_discovery_cannot_change_a_newer_selection_and_destroy_disposes(tmp_path):
    root = get_shared_tk_root()
    if root is None:
        pytest.skip("Tk is unavailable")
    from src.gui.views.lora_composition_design_frame import LoraCompositionDesignFrame

    gate = threading.Event()
    calls = []

    def loader(cancelled):
        calls.append(1)
        gate.wait(2)
        return {A: resource(A)}

    frame = LoraCompositionDesignFrame(
        root,
        prompt=lambda: KNIGHT,
        changed=lambda: None,
        visible=lambda: True,
        family=lambda: "sdxl",
        mode=lambda: "nsfw",
        loader=loader,
    )
    frame.refresh_inventory()
    frame.invalidate()  # model/experiment changed while discovery was in flight
    gate.set()
    pump(root, lambda: False, 0.4)
    assert frame._resources == {} and "Discovering" in frame.status_var.get()
    frame.destroy()
    frame.refresh_inventory()  # a destroyed frame never starts or publishes work
    assert len(calls) == 1 and frame._closed


def test_hidden_names_are_masked_and_unlisted_baseline_names_are_not_revealed(panel):
    widget, bench, root = panel
    frame = widget.lora_composition_frame
    assert pump(root, lambda: bool(frame._rows))
    widget.custom_prompt_text.delete("1.0", "end")
    widget.custom_prompt_text.insert("1.0", KNIGHT + " <lora:SecretName:0.4>")
    widget._on_prompt_text_edited()
    bench.controller.app_state.content_visibility_mode = "sfw"
    widget._on_comparison_visibility_changed()
    shown = " ".join(frame.fixed_list.get(0, "end")) + " ".join(frame.original_box.cget("values"))
    assert "SecretName" not in shown and "LoRA 1" in shown
    assert frame.negative_entry.cget("show")


def test_restore_reopens_the_frozen_design_in_order(panel):
    widget, bench, root = panel
    frame = widget.lora_composition_frame
    assert pump(root, lambda: bool(frame._rows))
    frame.add_empty()
    select_row(frame, A)
    frame.add_selected()
    frame.operation_var.set("Compare Candidates")
    widget._on_build_preview()
    experiment = bench.state.current_experiment
    frame._candidates.clear()
    widget.restore_state(experiment)
    assert [c["name"] for c in frame.spec()["candidates"]] == [None, A]
    assert frame.spec()["operation"] == "compare"


def test_strength_sweep_controls_remain_for_controlled_variable(panel):
    widget, _bench, _root = panel
    widget.study_type_var.set("Controlled Variable")
    widget._on_study_type_changed()
    assert widget.lora_composition_frame.winfo_manager() == ""
    widget.variable_var.set("LoRA Strength")
    widget._on_variable_changed()
    assert widget.lora_frame.winfo_manager() == "grid"


@pytest.mark.parametrize("scaling", [1.0, 2.0])
def test_composition_controls_have_scroll_access_at_compact_and_high_dpi(tmp_path, scaling):
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
        panel._choose_lora_composition()
        root.update_idletasks()
        frame = panel.lora_composition_frame
        assert frame.winfo_manager() == "grid"
        assert tab.experiment_scroll._vsb.winfo_manager() == "grid"
        assert frame.winfo_reqwidth() <= 500
        for widget in (
            frame.candidate_list,
            frame.inventory_list,
            frame.negative_entry,
            frame.operation_box,
        ):
            assert widget.winfo_exists()
    finally:
        if tab is not None:
            tab.destroy()
        root.tk.call("tk", "scaling", original_scaling)
        root.withdraw()
        repository.close()


def test_discovery_runs_off_the_tk_thread_and_fixed_slots_reach_the_spec(tmp_path):
    root = get_shared_tk_root()
    if root is None:
        pytest.skip("Tk is unavailable")
    from src.gui.views.lora_composition_design_frame import LoraCompositionDesignFrame

    threads, delivered = [], []

    def loader(cancelled):
        threads.append(threading.get_ident())
        return {A: resource(A)}

    frame = LoraCompositionDesignFrame(
        root,
        prompt=lambda: KNIGHT,
        changed=lambda: None,
        visible=lambda: True,
        family=lambda: "sdxl",
        mode=lambda: "nsfw",
        loader=loader,
        inventory_listener=delivered.append,
    )
    try:
        frame.refresh_inventory()
        assert pump(root, lambda: bool(delivered))
        assert threads and threads[0] != threading.get_ident()
        assert set(delivered[0]) == {A}
        frame.slots_var.set("place=forest, mood = calm")
        assert frame.spec()["fixed_slots"] == {"place": "forest", "mood": "calm"}
    finally:
        frame.destroy()
