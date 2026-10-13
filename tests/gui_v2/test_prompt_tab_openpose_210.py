"""PR-IMG-CNET-210: the Prompt tab carries one OpenPose declaration per slot through editing, save/load and preview."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.assets import AssetRegistry
from src.assets.compatibility import CompatibilityProfile, CompatibilityStatus, ModelFamily
from src.conditioning.openpose import new_declaration
from src.gui.views.prompt_tab_frame_v2 import PromptTabFrame
from src.gui_v2.model_policy_projection import project_model_controls
from src.image_backends import model_policy as mp
from tests.conditioning.openpose_fixtures_210 import (
    make_library,
    png_bytes,
    write_controlnet_weights,
)

pytestmark = pytest.mark.gui

SDXL = "juggernaut.safetensors"
KLEIN = "flux-2-klein-4b-fp8.safetensors"
CN = "xinsir_openpose_sdxl"
_SDXL_EVIDENCE = CompatibilityProfile(CompatibilityStatus.RESOLVED, ModelFamily.SDXL, ())


def _lookup(name: str):
    return {SDXL: _SDXL_EVIDENCE}.get(name)


def _projection(model: str, backend: str = "forge_webui"):
    return project_model_controls(
        mp.resolve_model_policy(model, family_lookup=_lookup), backend, model_name=model
    )


def _immediate(work, done) -> None:
    try:
        result, error = work(), None
    except Exception as exc:  # noqa: BLE001
        result, error = None, exc
    done(result, error)


@pytest.fixture
def tab(tk_root, tmp_path: Path):
    webui = tmp_path / "webui"
    make_library(
        webui,
        {"Standing/relaxed.png": png_bytes(128, 192), "Walking/forward.png": png_bytes(160, 224, (9, 9, 9))},
    )
    write_controlnet_weights(webui / "models" / "ControlNet" / f"{CN}.safetensors", "sdxl")
    frame = PromptTabFrame(tk_root, packs_dir=tmp_path / "packs")
    picker = frame.openpose_picker
    picker._registry_factory = lambda: AssetRegistry(webui, cache_path=tmp_path / "cache" / "registry.json")
    picker._registry = None
    picker._runner = _immediate
    picker.refresh_library()
    frame.workspace_state.new_pack("Pose", slot_count=3)
    frame._refresh_editor()
    yield frame
    frame.destroy()


def _choose(frame: PromptTabFrame, row: int) -> None:
    picker = frame.openpose_picker
    picker.listbox.selection_clear(0, "end")
    picker.listbox.selection_set(row)
    picker._on_list_select()


def test_choosing_a_pose_persists_it_on_the_current_slot_and_marks_the_pack_modified(tab) -> None:
    frame = tab
    frame.workspace_state.dirty = False

    _choose(frame, 0)

    slot = frame.workspace_state.get_slot(0)
    assert slot.openpose["asset"] == "Standing/relaxed.png" and slot.openpose["model"] == CN
    assert frame.workspace_state.dirty is True
    assert "modified" in frame.pack_name_label.cget("text")


def test_each_slot_keeps_and_shows_its_own_pose(tab) -> None:
    frame = tab
    _choose(frame, 0)  # slot 0 -> Standing
    frame.workspace_state.set_current_slot_index(1)
    frame._refresh_editor()
    assert frame.openpose_picker.get_declaration() is None  # a fresh slot starts with no conditioning

    _choose(frame, 1)  # slot 1 -> Walking
    frame.workspace_state.set_current_slot_index(0)
    frame._refresh_editor()

    assert frame.openpose_picker.get_declaration()["asset"] == "Standing/relaxed.png"
    assert frame.workspace_state.get_slot(1).openpose["asset"] == "Walking/forward.png"


def test_switching_slots_is_a_programmatic_load_and_never_dirties_the_pack(tab) -> None:
    frame = tab
    _choose(frame, 0)
    frame.workspace_state.dirty = False

    frame.workspace_state.set_current_slot_index(1)
    frame._refresh_editor()
    frame.workspace_state.set_current_slot_index(0)
    frame._refresh_editor()

    assert frame.workspace_state.dirty is False
    assert frame.workspace_state.get_slot(0).openpose["asset"] == "Standing/relaxed.png"


def test_save_and_reload_round_trip_through_the_native_pack(tab, tmp_path: Path) -> None:
    frame = tab
    _choose(frame, 0)
    frame.openpose_picker.weight_var.set("0.75")
    frame.openpose_picker._on_number_changed()
    path = tmp_path / "packs" / "pose.json"
    frame.workspace_state.save_current_pack_as(path)

    saved = json.loads(path.read_text(encoding="utf-8"))["pack_data"]["slots"][0]["controlnet_openpose"]
    assert saved["asset"] == "Standing/relaxed.png" and saved["weight"] == 0.75 and saved["contract"] == "openpose.v1"

    frame.workspace_state.load_pack(path)
    frame._refresh_editor()
    assert frame.openpose_picker.get_declaration() == saved
    assert frame.workspace_state.dirty is False


def test_removing_the_pose_removes_it_from_the_saved_pack(tab, tmp_path: Path) -> None:
    frame = tab
    frame.workspace_state.set_slot_text(0, "a person")
    _choose(frame, 0)
    path = tmp_path / "packs" / "pose.json"
    frame.workspace_state.save_current_pack_as(path)
    assert "controlnet_openpose" in json.loads(path.read_text(encoding="utf-8"))["pack_data"]["slots"][0]

    frame.openpose_picker._on_remove()
    frame.workspace_state.save_current_pack()

    assert "controlnet_openpose" not in json.loads(path.read_text(encoding="utf-8"))["pack_data"]["slots"][0]


def test_copying_a_slot_copies_its_pose_independently(tab) -> None:
    frame = tab
    _choose(frame, 0)

    frame.workspace_state.copy_slot(0)
    frame.workspace_state.get_slot(1).openpose["weight"] = 0.3

    assert frame.workspace_state.get_slot(0).openpose["weight"] == 1.0
    assert frame.workspace_state.get_slot(1).openpose["asset"] == "Standing/relaxed.png"


def test_a_model_switch_updates_the_target_without_touching_the_selection(tab) -> None:
    frame = tab
    _choose(frame, 0)
    saved = frame.openpose_picker.get_declaration()

    frame.on_model_projection(_projection(SDXL))
    assert "can run OpenPose" in frame.openpose_picker.summary_var.get() or "Ready" in frame.openpose_picker.summary_var.get()

    frame.on_model_projection(_projection(KLEIN))
    assert "does not support ControlNet" in frame.openpose_picker.notes_var.get()
    assert frame.openpose_picker.get_declaration() == saved
    assert frame.workspace_state.get_slot(0).openpose == saved

    frame.on_model_projection(_projection(SDXL, backend="a1111_webui"))
    assert "Forge" in frame.openpose_picker.notes_var.get()
    assert frame.workspace_state.get_slot(0).openpose == saved


def test_the_preview_shows_the_effective_pose_model_and_settings(tab) -> None:
    frame = tab
    frame.on_model_projection(_projection(SDXL))
    _choose(frame, 0)

    text = frame.meta_text.get("1.0", "end")

    assert "CONTROLNET OPENPOSE" in text
    assert "Pose image: Standing/relaxed.png" in text
    assert f"ControlNet model: {CN}" in text
    assert "Weight 1, guidance 0-1" in text and "Preprocessor: None" in text
    assert "will be sent to Forge as one ControlNet unit" in text


def test_the_preview_says_why_an_unsupported_target_will_not_run_it(tab) -> None:
    frame = tab
    _choose(frame, 0)
    frame.on_model_projection(_projection(KLEIN))

    text = frame.meta_text.get("1.0", "end")

    assert "Status: will not run as saved" in text and "does not support ControlNet" in text


def test_slots_without_conditioning_have_no_openpose_preview_section(tab) -> None:
    frame = tab

    assert "CONTROLNET OPENPOSE" not in frame.meta_text.get("1.0", "end")


def test_a_pack_loaded_with_a_hand_written_declaration_is_shown(tab, tmp_path: Path) -> None:
    frame = tab
    path = tmp_path / "packs" / "handwritten.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "schema_version": 1,
        "pack_data": {
            "name": "handwritten",
            "slots": [
                {
                    "index": 0,
                    "text": "a person",
                    "negative": "",
                    "controlnet_openpose": new_declaration("Walking/forward.png", model=CN),
                }
            ],
            "matrix": {"enabled": False, "mode": "fanout", "limit": 8, "slots": []},
        },
        "preset_data": {},
    }
    path.write_text(json.dumps(document), encoding="utf-8")

    frame.workspace_state.load_pack(path)
    frame.workspace_state.set_current_slot_index(0)
    frame._refresh_editor()

    assert frame.openpose_picker.get_declaration()["asset"] == "Walking/forward.png"
    assert frame.openpose_picker.selected_var.get() == "Walking/forward.png"


def test_the_preview_redacts_a_flagged_pose_name_in_sfw_mode(tab) -> None:
    frame = tab
    frame.on_model_projection(_projection(KLEIN))  # not executable: the status lines name the image when it is missing
    frame.workspace_state.set_slot_openpose(0, new_declaration("Gone/nude pose.png", model=CN))
    frame._refresh_editor()
    frame.on_content_visibility_mode_changed("sfw")

    text = frame.meta_text.get("1.0", "end")

    assert "CONTROLNET OPENPOSE" in text
    assert "nude" not in text.lower().replace("hidden in sfw", "")
