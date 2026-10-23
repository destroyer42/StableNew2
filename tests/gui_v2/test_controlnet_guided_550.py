"""PR-GUI-UX-550: guided ControlNet authoring over synthetic maps, weights and resources (no Forge, GPU or network)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from src.assets import AssetRegistry
from src.assets.controlnet_structure import ControlNetEvidence, ControlNetModelOption
from src.conditioning.controlnet import CONTRACT, parse_units
from src.conditioning.openpose import new_declaration
from src.conditioning.openpose_catalog import LibraryEntry, LibraryListing
from src.gui.widgets.controlnet_units_panel import ControlNetUnitsPanel
from src.gui_v2 import controlnet_guidance as g
from src.image_backends.model_policy import EVIDENCE_REGISTRY
from src.utils.thread_registry import ThreadRegistry
from tests.conditioning.openpose_fixtures_210 import (
    make_library,
    png_bytes,
    write_controlnet_weights,
)
from tests.gui_v2 import test_prompt_tab_openpose_210 as legacy_ui
from tests.integration.test_pr_img_cnet_220 import declaration

pytestmark = pytest.mark.gui

POSE_MODEL = "xinsir_openpose_sdxl"
DEPTH_MODEL = "diffusers_xl_depth_full"
CANNY_MODEL = "diffusers_xl_canny_full"
MAPS = {
    "Standing/relaxed.png": png_bytes(128, 192),
    "Walking/forward.png": png_bytes(160, 224, (9, 9, 9)),
    "Depth/room.png": png_bytes(200, 100, (50, 60, 70)),
    "Poses/nude standing.png": png_bytes(64, 64),
}


def _immediate(work, done) -> None:
    try:
        result, error = work(), None
    except Exception as exc:  # noqa: BLE001
        result, error = None, exc
    done(result, error)


@pytest.fixture
def webui(tmp_path: Path) -> Path:
    root = tmp_path / "webui"
    make_library(root, MAPS)
    for name in (POSE_MODEL, DEPTH_MODEL, CANNY_MODEL):
        write_controlnet_weights(root / "models" / "ControlNet" / f"{name}.safetensors", "sdxl")
    return root


@pytest.fixture
def changes() -> list[int]:
    return []


@pytest.fixture
def panel(tk_root, webui, tmp_path, changes, monkeypatch):
    # Resource refresh is exercised through the real worker seam, run inline so the test stays deterministic.
    monkeypatch.setattr(ThreadRegistry, "spawn", lambda self, **kwargs: kwargs["target"]())
    registry = lambda: AssetRegistry(webui, cache_path=tmp_path / "cache" / "registry.json")  # noqa: E731
    widget = ControlNetUnitsPanel(
        tk_root,
        on_change_callback=lambda: changes.append(1),
        registry_factory=registry,
        runner=_immediate,
        confirm=lambda _title, _message: True,
        lazy=False,
    )
    widget.pack()
    yield widget
    widget.destroy()


def _refresh(panel: ControlNetUnitsPanel) -> None:
    panel.refresh_library()
    panel.after_cancel(panel._poll)
    panel._drain()
    assert panel._loaded


def _units(panel: ControlNetUnitsPanel) -> list[dict[str, Any]]:
    return panel.get_declaration()["units"]


def _pick(panel: ControlNetUnitsPanel, identity: str) -> None:
    browser = panel.browser
    browser.search_var.set("")
    row = browser.visible_identities().index(identity)
    browser.listbox.selection_clear(0, "end")
    browser.listbox.selection_set(row)
    browser._on_list_select()


# ------------------------------------------------------------------ A. guided authoring


@pytest.mark.parametrize(
    ("modality", "label"),
    [
        ("openpose", "Pose / Body Position"),
        ("canny", "Edges / Structure"),
        ("depth", "Depth / Spatial Layout"),
    ],
)
def test_each_purpose_button_adds_a_unit_with_the_established_id_and_canonical_defaults(
    panel, changes, modality, label
):
    assert panel.add_buttons[modality].cget("text") == label
    panel.add_buttons[modality].invoke()
    (unit,) = _units(panel)
    assert unit == g.new_unit(modality)
    assert panel.modality_label_var.get() == label and panel.variables["modality"].get() == modality
    assert changes == [1]
    assert panel.get_declaration()["contract"] == CONTRACT
    assert "no reference map chosen yet" in panel.status_var.get()
    assert (
        "kept until you remove it" not in panel.status_var.get()
    )  # a new unit awaiting a map is not "broken"


def test_two_unit_limit_is_enforced_and_third_button_press_does_nothing(panel, changes):
    panel.add_buttons["openpose"].invoke()
    panel.add_buttons["depth"].invoke()
    assert [u["modality"] for u in _units(panel)] == ["openpose", "depth"]
    assert all(str(b.cget("state")) == "disabled" for b in panel.add_buttons.values())
    before = panel.get_declaration()
    panel.add_unit("canny")
    assert panel.get_declaration() == before and changes == [1, 1]


def test_editing_one_unit_never_touches_the_other_and_selection_does_not_reset_values(
    panel, changes
):
    panel.set_declaration(declaration("openpose", "depth"))
    first = copy.deepcopy(_units(panel)[0])
    panel.unit_combo.current(1)
    panel._select()
    assert changes == []  # inspecting is not editing
    panel.variables["weight"].set("0.8")
    panel.variables["resize_mode"].set("Just Resize")
    panel._edit()
    units = _units(panel)
    assert units[0] == first
    assert (units[1]["weight"], units[1]["resize_mode"]) == (0.8, "Just Resize")
    panel.unit_combo.current(0)
    panel._select()
    assert panel.variables["weight"].get() == str(first["weight"])
    assert changes == [1]


def test_reordering_carries_each_units_map_model_and_settings_together(panel):
    raw = declaration("openpose", "depth")
    raw["units"][1]["weight"] = 0.8
    raw["units"][0]["enabled"] = False
    panel.set_declaration(raw)
    panel.unit_buttons["Move down"].invoke()
    moved = _units(panel)
    assert moved == [raw["units"][1], raw["units"][0]]
    assert panel.unit_combo.current() == 1
    panel.unit_buttons["Move up"].invoke()
    assert _units(panel) == raw["units"]
    assert str(panel.unit_buttons["Move up"].cget("state")) == "disabled"


def test_enabling_and_disabling_a_unit_keeps_its_whole_declaration(panel, changes):
    raw = declaration("canny", "depth")
    panel.set_declaration(raw)
    panel.enabled_var.set(False)
    panel._edit()
    disabled = _units(panel)[0]
    assert disabled["enabled"] is False
    assert {k: v for k, v in disabled.items() if k != "enabled"} == {
        k: v for k, v in raw["units"][0].items() if k != "enabled"
    }
    assert "disabled" in panel.summary_var.get().splitlines()[0]
    assert "disabled; kept in the pack and not sent" in panel.status_var.get().splitlines()[0]
    assert changes == [1]


def test_unit_removal_is_an_explicit_button_press(panel, changes):
    panel.set_declaration(declaration("canny", "depth"))
    panel.unit_buttons["Remove"].invoke()
    assert [u["modality"] for u in _units(panel)] == ["depth"]
    panel.unit_buttons["Remove"].invoke()
    assert panel.get_declaration() is None and changes == [1, 1]


def test_a_focus_change_without_an_edit_never_dirties_the_pack(panel, changes):
    panel.set_declaration(declaration("canny"))
    for _ in range(3):
        panel._edit()  # what FocusOut / Return do when nothing was typed
    panel.variables["weight"].set("1")  # "1" is the stored 1.0
    panel._edit()
    assert changes == []


def test_invalid_input_is_refused_with_a_reason_and_the_saved_value_returns(panel, changes):
    panel.set_declaration(declaration("canny"))
    saved = panel.get_declaration()
    for key, text, reason in (
        ("weight", "strong", "must be a number"),
        ("weight", "3", "between 0 and 2"),
        ("guidance_start", "1.5", "between 0 and 1"),
        ("guidance_start", "1", "lower than"),
    ):
        panel.variables[key].set(text)
        panel._edit()
        assert reason in panel.notice_var.get() and "not applied" in panel.notice_var.get()
        assert panel.get_declaration() == saved
        assert panel.variables[key].get() == str(saved["units"][0][key])
    assert changes == []


def test_malformed_saved_values_stay_visible_until_the_operator_corrects_them(panel, changes):
    raw = declaration("canny")
    raw["units"][0]["weight"] = "heavy"
    panel.set_declaration(raw)
    assert panel.variables["weight"].get() == "heavy"
    assert panel.status_var.get().startswith("Cannot execute:")
    panel.variables["control_mode"].set("ControlNet is more important")
    panel._edit()  # editing another field leaves the bad value exactly as saved
    assert _units(panel)[0]["weight"] == "heavy"
    panel.variables["weight"].set("0.7")
    panel._edit()
    assert _units(panel)[0]["weight"] == 0.7
    assert not panel.status_var.get().startswith("Cannot execute: ControlNet unit 1: weight")


def test_advanced_controls_are_collapsed_by_default_and_open_for_customised_units(panel):
    panel.add_unit("canny")
    assert panel.advanced_open is False and not panel.advanced.winfo_manager()
    panel.toggle_advanced()
    assert panel.advanced.winfo_manager() == "grid"
    panel.set_declaration(declaration("openpose"))
    panel.set_declaration(None)
    raw = declaration("depth")
    raw["units"][0]["guidance_end"] = 0.6
    panel.set_declaration(raw)
    assert panel.advanced_open is True
    assert "Higher values generally emphasize" in g.STRENGTH_HELP


def test_changing_the_purpose_of_a_unit_never_substitutes_its_model(panel, changes):
    raw = declaration("openpose")
    panel.set_declaration(raw)
    panel.modality_label_var.set("Depth / Spatial Layout")
    panel._on_modality_chosen()
    unit = _units(panel)[0]
    assert unit["modality"] == "depth" and unit["model"] == raw["units"][0]["model"]
    assert changes == [1]


# ------------------------------------------------------------------ B. reference-map selection


def test_the_library_is_listed_searchable_and_a_pick_stores_the_relative_identity(panel, changes):
    panel.add_unit("openpose")
    changes.clear()
    _refresh(panel)
    assert changes == []  # a refresh is a projection
    assert panel.browser.visible_identities()[:2] == ["Depth/room.png", "Poses/nude standing.png"]
    panel.browser.search_var.set("walk forw")
    assert panel.browser.visible_identities() == ["Walking/forward.png"]
    _pick(panel, "Walking/forward.png")
    assert _units(panel)[0]["asset"] == "Walking/forward.png"
    assert panel.variables["asset"].get() == "Walking/forward.png"
    assert changes == [1]
    _pick(panel, "Walking/forward.png")  # re-picking the same map is not an edit
    assert changes == [1]


def test_selection_and_the_saved_unit_survive_refresh_and_never_dirty(panel, changes):
    raw = declaration("openpose", "depth")
    panel.set_declaration(raw)
    _refresh(panel)
    _refresh(panel)
    assert panel.get_declaration() == raw and changes == []
    assert panel.browser.listbox.curselection() == (
        panel.browser.visible_identities().index("Standing/relaxed.png"),
    )


def test_a_saved_missing_map_stays_visible_and_is_reported(panel, changes):
    raw = declaration("canny")
    raw["units"][0]["asset"] = "Gone/vanished.png"
    panel.set_declaration(raw)
    _refresh(panel)
    assert panel.get_declaration() == raw and changes == []
    assert panel.variables["asset"].get() == "Gone/vanished.png"
    assert "reference map 'Gone/vanished.png' is missing" in panel.status_var.get()
    assert "Missing or unreadable image" in panel.browser.thumbnail_label.cget("text")


def test_a_selected_map_gets_a_bounded_thumbnail_and_facts(panel):
    panel.add_unit("openpose")
    _refresh(panel)
    _pick(panel, "Walking/forward.png")
    browser = panel.browser
    assert browser._photo is not None
    assert max(browser._photo.width(), browser._photo.height()) <= 160
    assert browser.facts_var.get().startswith("160x224")
    assert browser.identity_var.get() == "Walking/forward.png"


def test_a_corrupt_or_unsupported_map_fails_safely(panel, webui):
    (webui / "models" / "OpenPose" / "broken.png").write_bytes(b"this is not an image")
    panel.add_unit("openpose")
    _refresh(panel)
    _pick(panel, "broken.png")
    assert _units(panel)[0]["asset"] == "broken.png"
    assert panel.browser.thumbnail_label.cget("text") == "Missing or unreadable image"
    assert panel.browser._photo is None


@pytest.mark.parametrize(
    "asset", ["../escape.png", "C:/Windows/evil.png", "/etc/passwd.png", "Standing/../x.png"]
)
def test_path_traversal_and_absolute_assets_are_refused_by_the_existing_validation(panel, asset):
    raw = declaration("canny")
    raw["units"][0]["asset"] = asset
    panel.set_declaration(raw)
    _refresh(panel)
    assert panel.get_declaration() == raw  # preserved, never normalised away
    assert panel.status_var.get().startswith("Cannot execute:")
    assert (
        panel.browser.thumbnail_label.cget("text") == "Missing or unreadable image"
    )  # the bounded reader refused it


def test_a_stale_thumbnail_result_never_replaces_a_newer_selection(tk_root, webui, tmp_path):
    pending: list[tuple[Any, Any]] = []
    from src.gui.widgets.reference_map_browser import ReferenceMapBrowser

    browser = ReferenceMapBrowser(
        tk_root,
        on_select=lambda _identity: None,
        registry_factory=lambda: AssetRegistry(webui, cache_path=tmp_path / "c.json"),
        runner=lambda work, done: pending.append((work, done)),
        lazy=False,
    )
    try:
        browser.set_selection("Standing/relaxed.png")
        browser.set_selection("Walking/forward.png")
        assert len(pending) == 2
        (work_a, done_a), (work_b, done_b) = pending
        done_b(work_b(), None)
        assert browser.facts_var.get().startswith("160x224")
        done_a(work_a(), None)  # arrives late
        assert (
            browser.facts_var.get().startswith("160x224")
            and browser.identity_var.get() == "Walking/forward.png"
        )
        browser.set_selection("")  # clearing supersedes anything still in flight
        browser.set_selection("Depth/room.png")
        stale = pending[-1]
        browser.set_selection("")
        stale[1](stale[0](), None)
        assert browser._photo is None and browser.identity_var.get() == ""
    finally:
        browser.destroy()


def test_a_preview_finishing_after_the_editor_closed_is_a_no_op(tk_root, webui, tmp_path):
    from src.gui.widgets.reference_map_browser import ReferenceMapBrowser

    pending: list[tuple[Any, Any]] = []
    browser = ReferenceMapBrowser(
        tk_root,
        on_select=lambda _identity: None,
        registry_factory=lambda: AssetRegistry(webui, cache_path=tmp_path / "c.json"),
        runner=lambda work, done: pending.append((work, done)),
        lazy=False,
    )
    browser.set_selection("Standing/relaxed.png")
    work, done = pending[0]
    result = work()
    browser.destroy()
    done(result, None)  # must not raise or touch a destroyed widget


def test_nothing_is_scanned_or_read_until_the_editor_is_shown(
    tk_root, webui, tmp_path, monkeypatch
):
    spawned: list[Any] = []
    monkeypatch.setattr(
        ThreadRegistry, "spawn", lambda self, **kwargs: spawned.append(kwargs["target"])
    )
    ran: list[int] = []
    widget = ControlNetUnitsPanel(
        tk_root,
        registry_factory=lambda: AssetRegistry(webui, cache_path=tmp_path / "c.json"),
        runner=lambda work, done: ran.append(1),
    )
    try:
        widget.set_declaration(declaration("openpose"))
        assert spawned == [] and ran == []
        assert "when this tab is shown" in widget.browser.empty_var.get()
        widget.browser._mapped = lambda: True  # type: ignore[method-assign]
        widget.browser._maybe_load()
        assert ran == [1]
        widget._on_first_map()
        widget._on_first_map()  # the first display scans once
        assert len(spawned) == 1
    finally:
        widget.destroy()


def test_an_empty_or_missing_library_explains_the_supported_workflow(
    tk_root, tmp_path, monkeypatch
):
    monkeypatch.setattr(ThreadRegistry, "spawn", lambda self, **kwargs: kwargs["target"]())
    empty_root = tmp_path / "empty-webui"
    empty_root.mkdir()
    widget = ControlNetUnitsPanel(
        tk_root,
        registry_factory=lambda: AssetRegistry(empty_root, cache_path=tmp_path / "c.json"),
        runner=_immediate,
        lazy=False,
    )
    try:
        widget.add_unit("depth")
        _refresh(widget)
        text = widget.browser.empty_var.get()
        assert (
            "pre-rendered OpenPose, Canny, or Depth reference image" in text
            and "models/OpenPose" in text
        )
        assert "does not exist" in text
        assert "does not prepare or generate" in text
    finally:
        widget.destroy()


def test_sfw_mode_redacts_flagged_names_everywhere_and_loads_no_hidden_thumbnail(panel, changes):
    raw = declaration("canny")
    raw["units"][0]["asset"] = "Poses/nude standing.png"
    panel.set_declaration(raw)
    _refresh(panel)
    panel.set_content_visibility_mode("sfw")
    assert "Poses/nude standing.png" not in panel.browser.visible_identities()
    shown = " ".join(
        [
            panel.variables["asset"].get(),
            panel.browser.identity_var.get(),
            panel.browser.thumbnail_label.cget("text"),
            panel.status_var.get(),
            panel.summary_var.get(),
        ]
    )
    assert "nude" not in shown and "Hidden" in shown
    assert panel.get_declaration() == raw and changes == []
    panel._edit()  # a redacted field is never written back
    assert panel.get_declaration() == raw


# ------------------------------------------------------------------ C. model choice


def _with_models(panel, *models: ControlNetModelOption) -> None:
    panel._models = list(models)
    panel._loaded = True
    panel._render()


def _evidence(name: str, status: str = "sdxl") -> ControlNetModelOption:
    return ControlNetModelOption(name, ControlNetEvidence(status, "synthetic header"))


def test_a_single_verified_model_is_recommended_but_only_applied_on_request(panel, changes):
    raw = declaration("depth")
    raw["units"][0]["model"] = ""
    panel.set_declaration(raw)
    _with_models(panel, _evidence(POSE_MODEL), _evidence(DEPTH_MODEL))
    assert "Recommended: diffusers_xl_depth_full" in panel.model_hint_var.get()
    assert str(panel.use_recommended_button.cget("state")) == "normal"
    assert _units(panel)[0]["model"] == "" and changes == []  # offered, never applied
    assert list(panel.model_combo.cget("values"))[0] == DEPTH_MODEL  # compatible choices first
    panel.use_recommended_button.invoke()
    assert _units(panel)[0]["model"] == DEPTH_MODEL and changes == [1]
    assert str(panel.use_recommended_button.cget("state")) == "disabled"


def test_a_saved_model_is_never_replaced_by_the_recommendation(panel, changes):
    raw = declaration("depth")
    raw["units"][0]["model"] = "my_other_depth"
    panel.set_declaration(raw)
    _with_models(panel, _evidence(DEPTH_MODEL))
    assert panel.variables["model"].get() == "my_other_depth"
    assert "is not installed in models/ControlNet" in panel.status_var.get()
    assert panel.get_declaration() == raw and changes == []


def test_no_verified_model_explains_the_requirement_without_downloading(panel):
    panel.set_declaration(declaration("canny"))
    _with_models(panel, _evidence(POSE_MODEL), _evidence(CANNY_MODEL, "unverified"))
    hint = panel.model_hint_var.get()
    assert "No installed ControlNet weight is verified" in hint and "never downloads" in hint
    assert str(panel.use_recommended_button.cget("state")) == "disabled"


def test_readiness_follows_the_target_without_editing_the_declaration(panel, changes):
    class Target:
        def __init__(self, executable, evidence=EVIDENCE_REGISTRY):
            self.executable, self.evidence = executable, evidence

    raw = declaration("openpose", "depth")
    panel.set_declaration(raw)
    panel._listing = LibraryListing(
        entries=tuple(
            LibraryEntry(i, 1, "") for i in ("Standing/relaxed.png", "Walking/forward.png")
        ),
        configured=True,
        folder_exists=True,
    )
    _with_models(panel, _evidence(POSE_MODEL), _evidence(DEPTH_MODEL))
    panel.set_target(Target(True))
    assert panel.status_var.get().count("Local resources compatible") == 2
    panel.set_target(Target(False))
    assert panel.status_var.get().count("Cannot execute") == 2
    panel.set_target(Target(True))
    assert panel.status_var.get().count("Local resources compatible") == 2
    assert panel.get_declaration() == raw and changes == []


# ------------------------------------------------------------------ D. legacy OpenPose compatibility


@pytest.fixture
def tab(tk_root, tmp_path):
    yield from legacy_ui.tab.__wrapped__(tk_root, tmp_path)


def _legacy() -> dict:
    return new_declaration("Standing/relaxed.png", model=POSE_MODEL)


def test_a_legacy_declaration_loads_unchanged_and_blocks_new_units_until_switched(tab):
    frame = tab
    legacy = _legacy()
    frame.workspace_state.set_slot_openpose(0, legacy)
    frame.workspace_state.dirty = False
    frame._refresh_editor()
    picker = frame.controlnet_picker
    assert picker.legacy_frame.winfo_manager() == "grid"
    assert (
        "legacy OpenPose" in picker.legacy_var.get() and "cannot coexist" in picker.legacy_var.get()
    )
    assert all(str(button.cget("state")) == "disabled" for button in picker.add_buttons.values())
    assert picker.get_declaration() is None
    assert frame.openpose_picker.get_declaration() == legacy
    assert "legacy OpenPose" in picker.status_var.get()
    picker.add_unit("canny")  # even a direct call cannot start a second declaration
    assert picker.get_declaration() is None
    for index in (1, 0):  # tab/slot navigation never migrates or clears it
        frame.workspace_state.set_current_slot_index(index)
        frame._refresh_editor()
    assert frame.workspace_state.get_slot(0).openpose == legacy
    assert frame.workspace_state.get_slot(0).controlnet_units is None
    assert frame.workspace_state.dirty is False


def test_switching_to_ordered_units_needs_confirmation_and_never_converts(tab):
    frame = tab
    legacy = _legacy()
    frame.workspace_state.set_slot_openpose(0, legacy)
    frame._refresh_editor()
    picker = frame.controlnet_picker
    prompts: list[str] = []
    picker._confirm = lambda title, message: prompts.append(message) is None and False
    frame.workspace_state.dirty = False
    picker.replace_legacy_button.invoke()
    assert len(prompts) == 1 and "removes the legacy OpenPose reference" in prompts[0]
    assert "Nothing is converted automatically" in prompts[0]
    assert frame.workspace_state.get_slot(0).openpose == legacy and not frame.workspace_state.dirty
    picker._confirm = lambda title, message: True
    picker.replace_legacy_button.invoke()
    slot = frame.workspace_state.get_slot(0)
    assert slot.openpose is None and slot.controlnet_units is None  # removed, not converted
    assert frame.openpose_picker.get_declaration() is None
    assert frame.workspace_state.dirty is True
    assert picker.legacy_frame.winfo_manager() == ""
    assert all(str(button.cget("state")) == "normal" for button in picker.add_buttons.values())
    picker.add_buttons["depth"].invoke()
    assert frame.workspace_state.get_slot(0).controlnet_units["units"][0]["modality"] == "depth"


def test_a_saved_conflict_stays_visible_and_is_never_rewritten(tab):
    frame = tab
    legacy, units = _legacy(), declaration("canny")
    frame.workspace_state.set_slot_openpose(0, legacy)
    frame.workspace_state.set_slot_controlnet_units(0, units)
    frame.workspace_state.dirty = False
    frame._refresh_editor()
    picker = frame.controlnet_picker
    assert picker.get_declaration() == units and frame.openpose_picker.get_declaration() == legacy
    assert "Preview will refuse this slot" in picker.legacy_var.get()
    assert picker.status_var.get().count("Cannot execute") == 1
    assert "legacy OpenPose declaration is also saved" in picker.status_var.get()
    assert frame.workspace_state.dirty is False


def test_the_legacy_picker_will_not_start_a_second_declaration_beside_ordered_units(tab):
    frame = tab
    frame.controlnet_picker.set_declaration(declaration("canny"))
    frame._on_controlnet_changed()
    frame.workspace_state.dirty = False
    legacy_ui._choose(frame, 0)
    assert frame.openpose_picker.get_declaration() is None
    assert frame.workspace_state.get_slot(0).openpose is None
    assert "ordered ControlNet units" in frame.openpose_picker.notes_var.get()
    frame.controlnet_picker.remove_unit()  # removing the units frees the legacy editor again
    legacy_ui._choose(frame, 0)
    assert frame.workspace_state.get_slot(0).openpose["asset"] == "Standing/relaxed.png"


# ------------------------------------------------------------------ E/H. persistence, slots, reachability


def test_two_guided_units_round_trip_through_the_native_pack_with_a_disabled_unit(tab, tmp_path):
    frame = tab
    frame.workspace_state.set_slot_text(0, "portrait")
    picker = frame.controlnet_picker
    picker.add_buttons["openpose"].invoke()
    picker.add_buttons["depth"].invoke()
    for index, (asset, model, weight) in enumerate(
        (("Standing/relaxed.png", POSE_MODEL, "1"), ("Walking/forward.png", DEPTH_MODEL, "0.8"))
    ):
        picker.unit_combo.current(index)
        picker._select()
        picker.variables["model"].set(model)
        picker.variables["weight"].set(weight)
        picker._edit()
        picker._on_map_picked(asset)
    picker.unit_combo.current(0)
    picker._select()
    picker.enabled_var.set(False)
    picker._edit()
    picker.unit_buttons["Move down"].invoke()
    expected = picker.get_declaration()
    assert [u["modality"] for u in expected["units"]] == ["depth", "openpose"]
    assert expected["units"][1]["enabled"] is False and expected["units"][0]["weight"] == 0.8
    assert frame.workspace_state.get_slot(0).controlnet_units == expected
    path = tmp_path / "packs" / "guided.json"
    frame.workspace_state.save_current_pack_as(path)
    saved = json.loads(path.read_text(encoding="utf-8"))["pack_data"]["slots"][0][
        "controlnet_units"
    ]
    assert saved == expected
    frame.workspace_state.load_pack(path)
    frame._refresh_editor()
    assert picker.get_declaration() == expected and not frame.workspace_state.dirty
    frame.workspace_state.copy_slot(0)
    frame.workspace_state.get_slot(1).controlnet_units["units"][0]["weight"] = 0.1
    assert frame.workspace_state.get_slot(0).controlnet_units == expected
    assert [u.settings.enabled for u in parse_units(expected)] == [True, False]


def test_each_slot_owns_its_edits_and_switching_slots_keeps_working_state(tab):
    frame = tab
    picker = frame.controlnet_picker
    picker.add_buttons["canny"].invoke()
    frame.workspace_state.set_current_slot_index(1)
    frame._refresh_editor()
    assert picker.get_declaration() is None
    picker.add_buttons["depth"].invoke()
    picker.variables["weight"].set("0.4")
    picker._edit()
    frame.workspace_state.set_current_slot_index(0)
    frame._refresh_editor()
    assert [u["modality"] for u in picker.get_declaration()["units"]] == ["canny"]
    assert picker.get_declaration()["units"][0]["weight"] == 1.0
    assert frame.workspace_state.get_slot(1).controlnet_units["units"][0]["weight"] == 0.4
    assert frame.workspace_state.get_slot(2).controlnet_units is None


def test_a_refresh_from_the_prompt_tab_never_dirties_or_rewrites_the_pack(tab):
    frame = tab
    raw = declaration("openpose", "depth")
    frame.workspace_state.set_slot_controlnet_units(0, raw)
    frame._refresh_editor()
    frame.workspace_state.dirty = False
    frame.controlnet_picker.set_declaration(raw)
    frame.controlnet_picker._listing = LibraryListing(error="offline")
    frame.controlnet_picker._loaded = True
    frame.controlnet_picker._render()
    assert "resource refresh failed: offline" in frame.controlnet_picker.status_var.get()
    assert frame.workspace_state.dirty is False
    assert frame.workspace_state.get_slot(0).controlnet_units == raw


def test_every_control_is_reachable_inside_the_scrolling_conditioning_tab(tab):
    frame = tab
    picker = frame.controlnet_picker
    picker.set_declaration(declaration("openpose", "depth"))
    assert str(picker.winfo_parent()).startswith(str(frame.conditioning_scroll.inner))
    required = [
        picker.modality_combo,
        picker.browser.search_entry,
        picker.browser.listbox,
        picker.controls["asset"],
        picker.model_combo,
        picker.use_recommended_button,
        picker.controls["weight"],
        picker.advanced_button,
        picker.enabled_check,
        picker.unit_combo,
        *picker.unit_buttons.values(),
        *picker.add_buttons.values(),
    ]
    for widget in required:
        assert str(widget.cget("takefocus")) != "0"
        node = widget
        while node is not picker:  # every control lives under the panel that the scroll frame hosts
            node = node.master
    picker.toggle_advanced()
    for key in ("guidance_start", "guidance_end", "control_mode", "resize_mode"):
        assert picker.controls[key].winfo_manager() == "grid"
    # Wrapped text follows the available width, so a narrow window never needs horizontal scrolling.
    picker.event_generate("<Configure>", width=300)
    picker.update_idletasks()
    assert all(int(label.cget("wraplength")) <= 520 for label in picker._wrap_labels)
