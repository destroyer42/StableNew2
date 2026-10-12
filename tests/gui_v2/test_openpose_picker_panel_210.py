"""PromptPack OpenPose picker (PR-IMG-CNET-210): selection, settings, removal, target state, no data loss.

Headless-safe: the worker ``runner`` is injected synchronously, the registry points at ``tmp_path`` and nothing reaches
a WebUI. The widget never edits the pack itself; it reports its declaration through ``get_declaration``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.assets import AssetRegistry
from src.gui.widgets.openpose_picker_panel import OpenPosePickerPanel
from src.image_backends.openpose_capability import (
    STATUS_UNSUPPORTED,
    STATUS_UNVERIFIED,
    OpenPoseTarget,
)
from tests.conditioning.openpose_fixtures_210 import (
    make_library,
    png_bytes,
    write_controlnet_weights,
)

pytestmark = pytest.mark.gui

CN = "xinsir_openpose_sdxl"


def _immediate(work, done) -> None:
    try:
        result, error = work(), None
    except Exception as exc:  # noqa: BLE001
        result, error = None, exc
    done(result, error)


@pytest.fixture
def library(tmp_path: Path) -> Path:
    make_library(
        tmp_path / "webui",
        {
            "Standing/relaxed.png": png_bytes(128, 192, (10, 20, 30)),
            "Walking/forward.png": png_bytes(160, 224, (40, 50, 60)),
            "Poses/nude standing.png": png_bytes(96, 96, (70, 80, 90)),
        },
    )
    write_controlnet_weights(tmp_path / "webui" / "models" / "ControlNet" / f"{CN}.safetensors", "sdxl")
    write_controlnet_weights(tmp_path / "webui" / "models" / "ControlNet" / "old_sd15_pose.safetensors", "sd15")
    return tmp_path / "webui"


def _panel(tk_root, library: Path, tmp_path: Path, **kwargs: Any) -> tuple[OpenPosePickerPanel, list[int]]:
    changes: list[int] = []
    panel = OpenPosePickerPanel(
        tk_root,
        on_change_callback=lambda: changes.append(1),
        registry_factory=lambda: AssetRegistry(library, cache_path=tmp_path / "cache" / "registry.json"),
        runner=_immediate,
        auto_refresh=False,
        **kwargs,
    )
    panel.pack()
    panel.refresh_library()
    return panel, changes


def _list_items(panel: OpenPosePickerPanel) -> list[str]:
    return list(panel.listbox.get(0, "end"))


def test_refresh_lists_the_library_and_the_installed_controlnet_models(tk_root, library, tmp_path) -> None:
    panel, changes = _panel(tk_root, library, tmp_path)
    try:
        assert _list_items(panel) == ["Poses/nude standing.png", "Standing/relaxed.png", "Walking/forward.png"]
        assert list(panel.model_combo["values"]) == ["old_sd15_pose", CN]
        assert panel.get_declaration() is None and changes == []
        assert "3 pose image(s) available" in panel.summary_var.get()
    finally:
        panel.destroy()


def test_selecting_an_image_creates_a_default_declaration_and_one_change(tk_root, library, tmp_path) -> None:
    panel, changes = _panel(tk_root, library, tmp_path)
    try:
        panel.listbox.selection_set(1)
        panel._on_list_select()

        declaration = panel.get_declaration()
        assert declaration == {
            "contract": "openpose.v1", "enabled": True, "asset": "Standing/relaxed.png", "model": CN,
            "weight": 1.0, "guidance_start": 0.0, "guidance_end": 1.0, "control_mode": "Balanced",
            "resize_mode": "Resize and Fill", "preprocessor": "None",
        }
        assert changes == [1]
        assert panel._photo is not None  # the thumbnail was decoded on the worker and shown
        assert panel.selected_var.get() == "Standing/relaxed.png"
    finally:
        panel.destroy()


def test_search_filters_without_losing_the_selection(tk_root, library, tmp_path) -> None:
    panel, _changes = _panel(tk_root, library, tmp_path)
    try:
        panel.listbox.selection_set(1)
        panel._on_list_select()
        panel.search_var.set("walk")

        assert _list_items(panel) == ["Walking/forward.png"]
        assert panel.get_declaration()["asset"] == "Standing/relaxed.png"  # filtering is not selecting
        panel.search_var.set("")
        assert len(_list_items(panel)) == 3
    finally:
        panel.destroy()


def test_settings_edits_round_trip_into_the_declaration(tk_root, library, tmp_path) -> None:
    panel, changes = _panel(tk_root, library, tmp_path)
    try:
        panel.listbox.selection_set(0)
        panel._on_list_select()
        changes.clear()

        panel.weight_var.set("0.65")
        panel.end_var.set("0.8")
        panel._on_number_changed()
        panel.control_mode_var.set("ControlNet is more important")
        panel.resize_mode_var.set("Crop and Resize")
        panel._on_choice_changed()

        declaration = panel.get_declaration()
        assert (declaration["weight"], declaration["guidance_start"], declaration["guidance_end"]) == (0.65, 0.0, 0.8)
        assert declaration["control_mode"] == "ControlNet is more important"
        assert declaration["resize_mode"] == "Crop and Resize"
        assert len(changes) == 2
    finally:
        panel.destroy()


@pytest.mark.parametrize(("field", "value"), [("weight_var", "9"), ("weight_var", "abc"), ("start_var", "0.9")])
def test_invalid_numbers_are_refused_and_the_saved_values_are_restored(tk_root, library, tmp_path, field, value) -> None:
    panel, changes = _panel(tk_root, library, tmp_path)
    try:
        panel.listbox.selection_set(0)
        panel._on_list_select()
        before = panel.get_declaration()
        changes.clear()

        getattr(panel, field).set(value)
        if field == "start_var":
            panel.end_var.set("0.5")  # start 0.9 >= end 0.5
        panel._on_number_changed()

        assert panel.get_declaration() == before and changes == []
        assert panel.weight_var.get() == "1" and panel.start_var.get() == "0"
    finally:
        panel.destroy()


def test_disabling_keeps_every_setting(tk_root, library, tmp_path) -> None:
    panel, _changes = _panel(tk_root, library, tmp_path)
    try:
        panel.listbox.selection_set(0)
        panel._on_list_select()
        panel.weight_var.set("0.4")
        panel._on_number_changed()

        panel.enable_var.set(False)
        panel._on_enable_toggled()

        declaration = panel.get_declaration()
        assert declaration["enabled"] is False
        assert (declaration["asset"], declaration["weight"], declaration["model"]) == ("Poses/nude standing.png", 0.4, CN)
        assert "switched off" in panel.notes_var.get()
    finally:
        panel.destroy()


def test_remove_clears_the_declaration_and_notifies_once(tk_root, library, tmp_path) -> None:
    panel, changes = _panel(tk_root, library, tmp_path)
    try:
        panel.listbox.selection_set(0)
        panel._on_list_select()
        changes.clear()

        panel._on_remove()

        assert panel.get_declaration() is None and changes == [1]
        assert str(panel.remove_button["state"]) == "disabled"
    finally:
        panel.destroy()


def test_loading_a_declaration_programmatically_never_notifies(tk_root, library, tmp_path) -> None:
    panel, changes = _panel(tk_root, library, tmp_path)
    try:
        saved = {
            "contract": "openpose.v1", "enabled": True, "asset": "Walking/forward.png", "model": CN, "weight": 0.7,
            "guidance_start": 0.1, "guidance_end": 0.9, "control_mode": "Balanced", "resize_mode": "Just Resize",
            "preprocessor": "None",
        }

        panel.set_declaration(saved)

        assert changes == [] and panel.get_declaration() == saved
        assert panel.weight_var.get() == "0.7" and panel.resize_mode_var.get() == "Just Resize"
        assert _list_items(panel)[panel.listbox.curselection()[0]] == "Walking/forward.png"
    finally:
        panel.destroy()


def test_a_missing_image_is_kept_and_clearly_warned(tk_root, library, tmp_path) -> None:
    panel, changes = _panel(tk_root, library, tmp_path)
    try:
        saved = {
            "contract": "openpose.v1", "enabled": True, "asset": "Gone/pose.png", "model": CN, "weight": 1.0,
            "guidance_start": 0.0, "guidance_end": 1.0, "control_mode": "Balanced", "resize_mode": "Resize and Fill",
            "preprocessor": "None",
        }

        panel.set_declaration(saved)

        assert panel.get_declaration() == saved and changes == []
        assert "not in the OpenPose library" in panel.notes_var.get()
        assert panel.listbox.curselection() == ()
    finally:
        panel.destroy()


def test_an_unsupported_target_is_shown_and_the_selection_survives(tk_root, library, tmp_path) -> None:
    panel, changes = _panel(tk_root, library, tmp_path)
    try:
        panel.listbox.selection_set(0)
        panel._on_list_select()
        before = panel.get_declaration()
        changes.clear()

        panel.set_target(
            OpenPoseTarget(STATUS_UNSUPPORTED, "exact_profile", "FLUX.2 Klein does not support ControlNet conditioning.")
        )

        assert panel.get_declaration() == before and changes == []
        assert "does not support ControlNet" in panel.notes_var.get()
        assert "will not run" in panel.summary_var.get()
        assert str(panel.weight_spin["state"]) != "disabled"  # still editable: the choice is preserved, not frozen

        panel.set_target(OpenPoseTarget(STATUS_UNVERIFIED, "unverified_family", "Not identified as SDXL yet."))
        assert "Not identified as SDXL yet." in panel.notes_var.get()
    finally:
        panel.destroy()


def test_a_non_sdxl_controlnet_model_is_flagged(tk_root, library, tmp_path) -> None:
    panel, _changes = _panel(tk_root, library, tmp_path)
    try:
        panel.listbox.selection_set(0)
        panel._on_list_select()
        panel.model_var.set("old_sd15_pose")
        panel._on_model_changed()

        assert panel.get_declaration()["model"] == "old_sd15_pose"
        assert "is not an SDXL model" in panel.notes_var.get()
    finally:
        panel.destroy()


def test_an_invalid_saved_value_is_preserved_until_removed(tk_root, library, tmp_path) -> None:
    panel, changes = _panel(tk_root, library, tmp_path)
    try:
        panel.set_declaration("not-an-object")
        panel.listbox.selection_set(0)
        panel._on_list_select()  # must not overwrite the unreadable value
        panel.weight_var.set("0.5")
        panel._on_number_changed()

        assert panel.get_declaration() == "not-an-object" and changes == []
        assert "not valid and was kept unchanged" in panel.notes_var.get()

        panel._on_remove()
        assert panel.get_declaration() is None and changes == [1]
    finally:
        panel.destroy()


def test_sfw_mode_hides_flagged_names_but_keeps_the_selection(tk_root, library, tmp_path) -> None:
    panel, _changes = _panel(tk_root, library, tmp_path)
    try:
        panel.set_declaration(
            {
                "contract": "openpose.v1", "enabled": True, "asset": "Poses/nude standing.png", "model": CN,
                "weight": 1.0, "guidance_start": 0.0, "guidance_end": 1.0, "control_mode": "Balanced",
                "resize_mode": "Resize and Fill", "preprocessor": "None",
            }
        )
        panel.set_content_visibility_mode("sfw")

        assert "Poses/nude standing.png" not in _list_items(panel)
        assert "Hidden in SFW mode" in panel.selected_var.get()
        assert panel.get_declaration()["asset"] == "Poses/nude standing.png"
    finally:
        panel.destroy()


def test_scan_failure_is_shown_not_raised(tk_root, tmp_path) -> None:
    def broken_registry():
        raise RuntimeError("registry unavailable")

    changes: list[int] = []
    panel = OpenPosePickerPanel(
        tk_root, on_change_callback=lambda: changes.append(1), registry_factory=broken_registry,
        runner=_immediate, auto_refresh=False,
    )
    panel.pack()
    try:
        panel.refresh_library()

        assert "scan failed" in panel.summary_var.get()
        assert panel.get_declaration() is None and changes == []
    finally:
        panel.destroy()
