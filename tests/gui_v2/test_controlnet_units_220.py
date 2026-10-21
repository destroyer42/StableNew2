"""Multi-unit authoring and resource refresh preserve independently authored intent."""

from __future__ import annotations

import copy
import json

import pytest

from src.assets import AssetRegistry
from src.assets.controlnet_structure import ControlNetEvidence, ControlNetModelOption
from src.conditioning.openpose_catalog import LibraryEntry, LibraryListing
from src.promptpacks.storage import prompt_pack_rows
from src.utils.thread_registry import ThreadRegistry
from tests.gui_v2 import test_prompt_tab_openpose_210 as legacy_ui
from tests.integration.test_pr_img_cnet_220 import declaration

pytestmark = pytest.mark.gui


@pytest.fixture
def tab(tk_root, tmp_path):
    yield from legacy_ui.tab.__wrapped__(tk_root, tmp_path)


def test_slot_edit_save_reload_clone_and_clear_preserve_units(tab, tmp_path):
    frame = tab
    frame.workspace_state.set_slot_text(0, "portrait")
    raw = declaration("canny", "depth")
    frame.controlnet_picker.set_declaration(raw)
    frame._on_controlnet_changed()
    assert frame.workspace_state.dirty
    assert frame.workspace_state.get_slot(0).controlnet_units == raw
    frame.workspace_state.copy_slot(0)
    frame.workspace_state.get_slot(1).controlnet_units["units"][0]["weight"] = 0.3
    assert frame.workspace_state.get_slot(0).controlnet_units == raw
    path = tmp_path / "packs" / "units.json"
    frame.workspace_state.save_current_pack_as(path)
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["pack_data"]["slots"][0]["controlnet_units"] == raw
    frame.workspace_state.load_pack(path)
    frame._refresh_editor()
    assert frame.controlnet_picker.get_declaration() == raw
    assert not frame.workspace_state.dirty
    frame.controlnet_picker.remove_unit()
    frame.controlnet_picker.remove_unit()
    frame.workspace_state.save_current_pack()
    assert (
        "controlnet_units"
        not in json.loads(path.read_text(encoding="utf-8"))["pack_data"]["slots"][0]
    )


def test_selected_unit_independent_settings_and_order(tab):
    picker = tab.controlnet_picker
    picker.set_declaration(declaration("openpose", "depth"))
    original = picker.get_declaration()["units"][0]
    picker.unit_combo.current(1)
    picker._select()
    picker.variables["weight"].set("0.25")
    picker.variables["guidance_start"].set("0.15")
    picker._edit()
    assert picker.get_declaration()["units"][0] == original
    assert picker.get_declaration()["units"][1]["weight"] == 0.25
    picker.move_up()
    assert [unit["modality"] for unit in picker.get_declaration()["units"]] == ["depth", "openpose"]
    assert picker.get_declaration()["units"][0]["guidance_start"] == 0.15
    picker.add_unit()
    assert len(picker.get_declaration()["units"]) == 2


def test_refresh_runs_off_tk_and_never_rewrites_a_missing_selection(tab, tmp_path, monkeypatch):
    picker = tab.controlnet_picker
    raw = declaration("canny", "depth")
    picker.set_declaration(raw)
    tab._on_controlnet_changed()
    tab.workspace_state.dirty = False
    work = []
    # Patch the class, not the singleton: undoing an instance patch re-installs the old bound method as an
    # instance attribute, which then shadows every later class-level patch of ``spawn`` in the same process.
    monkeypatch.setattr(
        ThreadRegistry, "spawn", lambda self, **kwargs: work.append(kwargs["target"])
    )
    picker._registry_factory = lambda: AssetRegistry(
        tmp_path / "webui", cache_path=tmp_path / "resource-cache.json"
    )
    picker.set_target(legacy_ui._projection("juggernaut.safetensors").openpose)
    picker.refresh_library()
    assert len(work) == 1
    # The worker only produces data, and Tk consumes it later.
    work[0]()
    assert not picker._loaded
    picker.after_cancel(picker._poll)
    picker._drain()
    assert picker._loaded
    assert "Cannot execute" in picker.status_var.get()
    assert picker.get_declaration() == raw
    assert not tab.workspace_state.dirty


def test_local_capability_projection_checks_all_units_and_saved_target(tab):
    picker = tab.controlnet_picker
    picker.set_declaration(declaration("openpose", "depth"))
    picker._listing = LibraryListing(
        entries=(
            LibraryEntry("Standing/relaxed.png", 1, ""),
            LibraryEntry("Walking/forward.png", 1, ""),
        ),
        configured=True,
        folder_exists=True,
    )
    picker._models = [
        ControlNetModelOption(name, ControlNetEvidence("sdxl", "test header"))
        for name in ("xinsir_openpose_sdxl", "diffusers_xl_depth_full")
    ]
    picker._loaded = True
    picker.set_target(legacy_ui._projection("juggernaut.safetensors").openpose)
    assert picker.status_var.get().count("Local resources compatible") == 2
    picker.set_target(legacy_ui._projection("flux-2-klein-4b-fp8.safetensors").openpose)
    assert picker.status_var.get().count("Cannot execute") == 2
    assert picker.get_declaration()["units"][1]["modality"] == "depth"


def test_malformed_declaration_is_preserved_until_explicit_removal(tab):
    picker = tab.controlnet_picker
    raw = {"contract": "unknown", "units": "bad"}
    picker.set_declaration(raw)
    assert picker.get_declaration() == raw
    assert "Cannot execute" in picker.status_var.get()
    picker.add_unit()
    assert picker.get_declaration() == raw
    picker.remove_unit()
    assert picker.get_declaration() is None


def test_unit_rows_are_losslessly_carried_to_compile():
    raw = declaration("canny", "depth")
    doc = {"pack_data": {"slots": [{"index": 0, "text": "portrait", "controlnet_units": raw}]}}
    row = prompt_pack_rows(doc)[0]
    assert row.controlnet_units == raw
    raw["units"].reverse()
    assert row.controlnet_units == declaration("canny", "depth")
    assert copy.deepcopy(row).controlnet_units == row.controlnet_units
