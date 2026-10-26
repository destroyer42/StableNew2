"""Embedding experiment authoring, discovery lifecycle and visibility on the existing Learning Design surface."""

import threading
import time
from types import SimpleNamespace

import pytest

from src.gui.views.experiment_design_panel import ExperimentDesignPanel
from src.learning import embedding_experiment as ee
from src.learning.embedding_inventory import STRUCTURE_SDXL, EmbeddingResource
from tests.gui_v2.tk_test_utils import get_shared_tk_root
from tests.learning_v2.test_embedding_experiment_700 import KNIGHT, A, B, assets, sha
from tests.learning_v2.test_learning_independent_baseline_650 import Bench

SECRET = "SecretStyle"


def resource(name: str, *, suitability="sdxl", structure=STRUCTURE_SDXL, fmt=".safetensors"):
    return EmbeddingResource(name, sha(name), fmt, 1, structure, suitability, 8)


def inventory(cancelled):
    return {
        A: resource(A),
        B: resource(B),
        SECRET: resource(SECRET),
        "DetailBoost": resource("DetailBoost"),
        "bad_hands": resource("bad_hands"),
        "OldPickle": resource("OldPickle", fmt=".pt", structure="", suitability=""),
        "Sd15Only": resource("Sd15Only", suitability="sd15", structure="sd15_clip_l"),
    }


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
    bench.controller._learning_embedding_asset_resolver = assets()
    bench.controller.embedding_inventory_loader = inventory
    bench.controller.copy_pipeline_settings("txt2img")
    widget = ExperimentDesignPanel(root, learning_controller=bench.controller, packs_dir=tmp_path)
    widget.prompt_source_var.set("custom")
    widget._choose_embedding()
    widget.custom_prompt_text.delete("1.0", "end")
    widget.custom_prompt_text.insert("1.0", KNIGHT)
    widget._on_prompt_text_edited()
    yield widget, bench, root
    widget.destroy()
    root.update_idletasks()


def select_row(frame, name):
    index = next(i for i, row in enumerate(frame._rows) if row.name == name)
    frame.inventory_list.selection_clear(0, "end")
    frame.inventory_list.selection_set(index)


def test_installed_inventory_loads_off_the_tk_thread_and_marks_status(panel):
    widget, bench, root = panel
    frame = widget.embedding_frame
    assert widget.variable_var.get() == "Embedding"
    assert pump(root, lambda: bool(frame._rows))
    rows = {row.name: row for row in frame._rows}
    assert rows[A].selectable and "structure verified" in rows[A].label
    assert not rows["OldPickle"].selectable and "unverified" in rows["OldPickle"].label.lower()
    assert not rows["Sd15Only"].selectable and "Incompatible" in rows["Sd15Only"].label
    assert set(bench.controller.embedding_inventory) == set(
        inventory(None)
    )  # Preview/Run identity evidence
    assert frame.fixed_list.get(0, "end") == ("No fixed embeddings",)


def test_candidates_are_deliberate_ordered_and_preview_freezes(panel):
    widget, bench, root = panel
    frame = widget.embedding_frame
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
    frame.operation_var.set("Identity")
    widget._on_build_preview()
    snapshot = bench.state.current_experiment.execution_snapshot_json
    assert snapshot and not widget.preview_is_stale() and not bench.service.submit_njrs.called
    assert frame.spec()["channel"] == ee.POSITIVE
    frame.add_empty()
    assert widget.preview_is_stale()
    assert not bench.service.submit_njrs.called


def test_weight_candidates_use_the_weight_entry_and_reject_out_of_range(panel):
    widget, _bench, root = panel
    frame = widget.embedding_frame
    assert pump(root, lambda: bool(frame._rows))
    frame.operation_var.set("Weight")
    select_row(frame, A)
    for text in ("0.6", "1.3"):
        frame.weight_var.set(text)
        frame.add_selected()
    frame.weight_var.set("1.9")
    frame.add_selected()
    assert "between 0 and" in frame.detail_var.get()
    frame.weight_var.set("loud")
    frame.add_selected()
    assert [c["weight"] for c in frame.spec()["candidates"]] == [0.6, 1.3]
    assert frame.validation_error(1) == ""
    assert "two to eight" in frame.validation_error(4) or "one to three" in frame.validation_error(
        4
    )


def test_channel_choice_is_part_of_the_spec_and_resets_the_original(panel):
    widget, _bench, _root = panel
    frame = widget.embedding_frame
    frame.channel_var.set("Negative prompt")
    frame._on_channel_changed()
    assert frame.spec()["channel"] == ee.NEGATIVE and frame.spec()["original"] is None


def test_unusable_inventory_rows_cannot_be_added(panel):
    widget, _bench, root = panel
    frame = widget.embedding_frame
    assert pump(root, lambda: bool(frame._rows))
    for name in ("Sd15Only", "OldPickle"):
        select_row(frame, name)
        frame.add_selected()
    assert frame.spec()["candidates"] == [] and "usable" in frame.detail_var.get()


def test_native_pack_row_embeddings_are_shown_fixed_and_the_original_can_be_designated(
    panel, monkeypatch
):
    widget, _bench, root = panel
    frame = widget.embedding_frame
    assert pump(root, lambda: bool(frame._rows))
    slot = SimpleNamespace(
        positive_embeddings=["DetailBoost", [A, 0.8]], negative_embeddings=["bad_hands"]
    )
    monkeypatch.setattr(
        widget, "_get_selected_prompt_payload", lambda: {"slot": slot, "prompt_text": KNIGHT}
    )
    widget.prompt_source_var.set("pack")
    frame.sync_baseline()
    shown = " | ".join(frame.fixed_list.get(0, "end"))
    assert (
        "DetailBoost @ 1 (Positive prompt)" in shown and "bad_hands @ 1 (Negative prompt)" in shown
    )
    assert f"{A} @ 0.8" in shown
    assert A in frame.original_box.cget("values")
    frame.original_var.set(A)
    frame._render()
    assert frame.spec()["original"] == A
    assert A not in " | ".join(
        frame.fixed_list.get(0, "end")
    )  # the tested position is no longer fixed
    rows = {row.name: row for row in frame._rows}
    assert rows["DetailBoost"].fixed and not rows["DetailBoost"].selectable


def test_stale_discovery_cannot_change_a_newer_selection_and_destroy_disposes(tmp_path):
    root = get_shared_tk_root()
    if root is None:
        pytest.skip("Tk is unavailable")
    from src.gui.views.embedding_experiment_design_frame import EmbeddingExperimentDesignFrame

    gate = threading.Event()
    calls = []

    def loader(cancelled):
        calls.append(1)
        gate.wait(2)
        return {A: resource(A)}

    frame = EmbeddingExperimentDesignFrame(
        root,
        prompt=lambda: KNIGHT,
        changed=lambda: None,
        visible=lambda: True,
        family=lambda: "sdxl",
        fixed=lambda: {},
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


def test_discovery_failure_reports_without_leaking_exception_text(tmp_path):
    root = get_shared_tk_root()
    if root is None:
        pytest.skip("Tk is unavailable")
    from src.gui.views.embedding_experiment_design_frame import EmbeddingExperimentDesignFrame

    def loader(cancelled):
        raise OSError(r"C:\private\path\embeddings denied")

    frame = EmbeddingExperimentDesignFrame(
        root,
        prompt=lambda: "",
        changed=lambda: None,
        visible=lambda: True,
        family=lambda: "sdxl",
        fixed=lambda: {},
        loader=loader,
    )
    try:
        frame.refresh_inventory()
        assert pump(root, lambda: "failed" in frame.status_var.get())
        assert "private" not in frame.status_var.get() and "unverified" in frame.status_var.get()
    finally:
        frame.destroy()


def test_hidden_names_are_masked_and_the_search_box_cannot_probe_them(panel, monkeypatch):
    widget, bench, root = panel
    frame = widget.embedding_frame
    assert pump(root, lambda: bool(frame._rows))
    slot = SimpleNamespace(positive_embeddings=[SECRET], negative_embeddings=[])
    monkeypatch.setattr(
        widget, "_get_selected_prompt_payload", lambda: {"slot": slot, "prompt_text": KNIGHT}
    )
    widget.prompt_source_var.set("pack")
    frame.sync_baseline()
    bench.controller.app_state.content_visibility_mode = "sfw"
    widget._on_comparison_visibility_changed()
    frame.query_var.set("secret")
    shown = " ".join(frame.fixed_list.get(0, "end")) + " ".join(frame.original_box.cget("values"))
    listed = " ".join(frame.inventory_list.get(0, "end"))
    assert SECRET not in shown + listed and A not in listed and "Embedding 1" in shown
    assert len(frame._rows) == len(inventory(None))  # the hidden query filtered nothing
    assert frame.negative_entry.cget("show")


def test_restore_reopens_the_frozen_design_in_order(panel):
    widget, bench, root = panel
    frame = widget.embedding_frame
    assert pump(root, lambda: bool(frame._rows))
    frame.operation_var.set("Presence")
    frame.add_empty()
    select_row(frame, A)
    frame.add_selected()
    frame.channel_var.set("Negative prompt")
    widget._on_build_preview()
    experiment = bench.state.current_experiment
    frame._candidates.clear()
    frame.channel_var.set("Positive prompt")
    widget.restore_state(experiment)
    assert [c["name"] for c in frame.spec()["candidates"]] == [None, A]
    assert frame.spec()["operation"] == "presence" and frame.spec()["channel"] == "negative"


def test_signature_changes_with_every_design_input(panel):
    widget, _bench, root = panel
    frame = widget.embedding_frame
    assert pump(root, lambda: bool(frame._rows))
    seen = {frame.signature()}
    frame.add_empty()
    seen.add(frame.signature())
    frame.operation_var.set("Weight")
    seen.add(frame.signature())
    frame.channel_var.set("Negative prompt")
    seen.add(frame.signature())
    frame.slots_var.set("place=forest")
    seen.add(frame.signature())
    assert len(seen) == 5


def test_other_studies_do_not_show_the_embedding_frame(panel):
    widget, _bench, _root = panel
    assert widget.embedding_frame.winfo_manager() == "grid"
    widget.study_type_var.set("Controlled Variable")
    widget._on_study_type_changed()
    assert widget.embedding_frame.winfo_manager() == ""
    widget.study_type_var.set("LoRA Composition")
    widget._on_study_type_changed()
    assert (
        widget.embedding_frame.winfo_manager() == ""
        and widget.lora_composition_frame.winfo_manager() == "grid"
    )


@pytest.mark.parametrize("scaling", [1.0, 2.0])
def test_embedding_controls_have_scroll_access_at_compact_and_high_dpi(tmp_path, scaling):
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
        panel._choose_embedding()
        root.update_idletasks()
        frame = panel.embedding_frame
        assert frame.winfo_manager() == "grid"
        assert tab.experiment_scroll._vsb.winfo_manager() == "grid"
        assert frame.winfo_reqwidth() <= 500
        for widget in (
            frame.candidate_list,
            frame.inventory_list,
            frame.negative_entry,
            frame.operation_box,
            frame.channel_box,
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
    from src.gui.views.embedding_experiment_design_frame import EmbeddingExperimentDesignFrame

    threads, delivered = [], []

    def loader(cancelled):
        threads.append(threading.get_ident())
        return {A: resource(A)}

    frame = EmbeddingExperimentDesignFrame(
        root,
        prompt=lambda: KNIGHT,
        changed=lambda: None,
        visible=lambda: True,
        family=lambda: "sdxl",
        fixed=lambda: {},
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
