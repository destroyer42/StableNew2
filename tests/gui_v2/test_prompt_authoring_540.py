"""GUI-540: guided template, LoRA and Style Consistency authoring on the real Prompt tab (Tk, synthetic data only).

No scan, GPU, WebUI or network: discovery results are injected through the picker's own completion path, and the
Style Consistency catalog is a temporary file.
"""

from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.assets.registry import AssetRegistrySnapshot
from src.controller.content_visibility_resolver import REDACTED_TEXT
from src.gui.prompt_workspace_state import PromptWorkspaceState
from src.gui.views.prompt_tab_frame_v2 import PromptTabFrame
from src.gui_v2.lora_authoring_view import NO_TRIGGER_METADATA
from src.training.style_lora_manager import ResolvedStyleLoRA, StyleLoRAManager
from src.utils.lora_scanner import LoRAResource
from src.utils.prompt_templates import compose_prompt_text, load_prompt_templates
from tests.gui_v2.test_lora_browser_240 import scanner_at, write_adapter
from tests.gui_v2.test_prompt_target_130b import KLEIN, SDXL, _projection, _resolver

ESTABLISHING = "establishing_wide"
EXAMPLES = load_prompt_templates()[ESTABLISHING].example_values


@pytest.fixture
def tab(tk_root: tk.Tk, tmp_path: Path):
    frame = PromptTabFrame(tk_root, packs_dir=tmp_path)
    picker = frame.lora_picker
    if picker._initial_scan is not None:  # never let the real discovery timer run in these tests
        picker.after_cancel(picker._initial_scan)
        picker._initial_scan = None
    frame.target_lora_resolver = _resolver({})
    frame.workspace_state.dirty = False
    yield frame
    frame.destroy()


def _label(frame: PromptTabFrame, template_id: str) -> str:
    return frame._template_id_to_choice[template_id]


def _choose_template(frame: PromptTabFrame, template_id: str) -> None:
    frame.template_choice_var.set(_label(frame, template_id))
    frame._on_template_choice_selected()


def _preview(frame: PromptTabFrame) -> str:
    return frame.template_preview.get("1.0", "end").strip()


def _fields(frame: PromptTabFrame) -> dict[str, str]:
    return {name: variable.get() for name, variable in frame._template_field_vars.items()}


def _resource(name: str, keywords=(), source="none", description="", errors=()) -> LoRAResource:
    return LoRAResource(
        name,
        Path("/unused") / f"{name}.safetensors",
        12,
        list(keywords),
        source,
        description,
        errors=tuple(errors),
    )


def _finish_discovery(
    frame: PromptTabFrame, resources: dict[str, LoRAResource], *, failed: bool = False
) -> None:
    picker = frame.lora_picker
    picker._scan_active = True
    picker._finish_refresh(picker._request_id, resources, failed, AssetRegistrySnapshot(()))


def _install_catalog(frame: PromptTabFrame, tmp_path: Path) -> None:
    catalog = tmp_path / "style_loras.json"
    catalog.write_text(
        json.dumps(
            {
                "styles": [
                    {
                        "style_id": "style_a",
                        "display_name": "Style A",
                        "trigger_phrase": "cinematic grit, soft rim light",
                        "lora_name": "lora_a",
                        "weight": 0.6,
                        "compatible_model_families": ["sdxl"],
                    },
                    {
                        "style_id": "style_b",
                        "display_name": "Style B",
                        "trigger_phrase": "painterly wash",
                        "lora_name": "lora_b",
                        "weight": 0.5,
                        "compatible_model_families": ["sdxl"],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    manager = StyleLoRAManager(catalog_path=catalog, webui_root=None)
    frame._style_lora_manager = manager
    frame._style_definitions = manager.list_styles()
    frame._sync_style_lora_controls_cached()


# --- Cinematic templates -----------------------------------------------------------------------------------------------


def test_the_selector_shows_friendly_labels_and_stores_the_stable_id(tab: PromptTabFrame) -> None:
    shown = list(tab.template_selector.cget("values"))

    assert any(item.startswith("Establishing Wide Shot") for item in shown)
    assert ESTABLISHING not in shown and "over_the_shoulder" not in shown

    _choose_template(tab, "over_the_shoulder")

    assert tab.workspace_state.get_current_template_id() == "over_the_shoulder"
    assert tab.template_selector_var.get() == "over_the_shoulder"
    assert tab.template_choice_var.get().startswith("Over-The-Shoulder")
    assert "dialogue" in tab.template_description_var.get()  # the catalog's own purpose text


def test_choosing_a_template_offers_labelled_editable_examples_and_renders_them(
    tab: PromptTabFrame,
) -> None:
    _choose_template(tab, ESTABLISHING)

    assert _fields(tab) == EXAMPLES
    assert "examples" in tab.template_example_note_var.get().lower()
    assert all(tag.cget("text") == "example" for tag in tab._template_example_tags.values())
    assert _preview(tab) == compose_prompt_text(ESTABLISHING, EXAMPLES, "")
    assert tab.workspace_state.dirty  # a deliberate working-state edit, like any template change

    tab._template_field_vars["scene"].set("a clockwork harbor")
    assert tab._template_example_tags["scene"].cget("text") == ""
    assert tab._template_example_tags["style"].cget("text") == "example"
    assert _preview(tab).startswith("cinematic wide establishing shot of a clockwork harbor")
    assert tab.workspace_state.get_current_template_variables()["scene"] == "a clockwork harbor"


def test_examples_are_not_written_to_disk_until_the_operator_saves(
    tab: PromptTabFrame, tmp_path: Path
) -> None:
    target = tmp_path / "saved_pack.json"
    _choose_template(tab, ESTABLISHING)
    assert not target.exists()

    tab.workspace_state.save_current_pack_as(target)
    reloaded = PromptWorkspaceState()
    reloaded.load_pack(target)
    slot = reloaded.get_slot(0)

    assert slot.template_id == ESTABLISHING and slot.template_variables == EXAMPLES
    assert reloaded.dirty is False


def test_saved_values_are_shown_as_stored_and_never_replaced_by_examples(
    tab: PromptTabFrame,
) -> None:
    tab.workspace_state.set_slot_template(0, ESTABLISHING, {"scene": "my harbor"})
    tab.workspace_state.dirty = False

    tab._refresh_editor()

    assert _fields(tab) == {"scene": "my harbor", "environment": "", "lighting": "", "style": ""}
    assert tab.template_example_note_var.get() == ""
    assert all(tag.cget("text") == "" for tag in tab._template_example_tags.values())
    assert tab.workspace_state.get_current_template_variables() == {"scene": "my harbor"}
    assert tab.workspace_state.dirty is False  # opening/refreshing the editor is not an edit


def test_switching_slots_restores_each_slots_own_template_state(tab: PromptTabFrame) -> None:
    _choose_template(tab, ESTABLISHING)
    tab._template_field_vars["scene"].set("slot one scene")
    tab.workspace_state.set_current_slot_index(1)
    tab._refresh_editor()
    assert (
        tab.template_selector_var.get() == "" and tab.template_choice_var.get() == "(No template)"
    )

    _choose_template(tab, "aerial_reveal")
    tab.workspace_state.set_current_slot_index(0)
    tab._refresh_editor()

    assert tab.template_selector_var.get() == ESTABLISHING
    assert _fields(tab)["scene"] == "slot one scene"
    assert tab.workspace_state.get_slot(1).template_id == "aerial_reveal"
    assert tab._template_seeded == {}  # examples are never re-applied by navigation


def test_changing_template_keeps_typed_text_and_seeds_only_empty_fields(
    tab: PromptTabFrame,
) -> None:
    _choose_template(tab, ESTABLISHING)
    tab._template_field_vars["scene"].set("typed by hand")

    _choose_template(tab, "aerial_reveal")

    fields = _fields(tab)
    assert fields["scene"] == "typed by hand"
    assert fields["mood"] == load_prompt_templates()["aerial_reveal"].example_values["mood"]
    assert tab._template_example_tags["scene"].cget("text") == ""
    assert tab._template_example_tags["mood"].cget("text") == "example"


def test_the_preview_follows_freeform_text_and_the_canonical_composition(
    tab: PromptTabFrame,
) -> None:
    _choose_template(tab, ESTABLISHING)
    tab.editor.insert("1.0", "rain on the cobblestones")
    tab._on_editor_modified()

    expected = compose_prompt_text(ESTABLISHING, EXAMPLES, "rain on the cobblestones")
    assert _preview(tab) == expected == tab.workspace_state.get_current_prompt_text()
    assert "Freeform text adds: rain on the cobblestones" in tab.template_breakdown_var.get()
    assert "Template adds:" in tab.template_breakdown_var.get()
    assert (
        tab.editor.get("1.0", "end").strip() == "rain on the cobblestones"
    )  # the editor holds only freeform text


def test_clearing_a_template_marks_the_pack_modified_and_keeps_freeform_text(
    tab: PromptTabFrame,
) -> None:
    tab.workspace_state.set_slot_text(0, "kept freeform")
    _choose_template(tab, ESTABLISHING)
    tab.workspace_state.dirty = False

    tab._clear_template_selection()

    assert tab.workspace_state.dirty
    assert tab.workspace_state.get_current_template_id() == ""
    assert _preview(tab) == "kept freeform"
    assert tab.workspace_state.get_current_raw_prompt_text() == "kept freeform"


def test_an_unknown_saved_template_is_kept_visible_and_untouched(
    tab: PromptTabFrame, tmp_path: Path
) -> None:
    tab.workspace_state.set_slot_text(0, "freeform survives")
    tab.workspace_state.set_slot_template(0, "legacy_custom", {"shot": "wide", "mood": "calm"})
    tab.workspace_state.dirty = False

    tab._refresh_editor()
    assert "not in catalog" in tab.template_choice_var.get()
    assert "not in the template catalog" in tab.template_description_var.get()
    assert _preview(tab) == "freeform survives"

    tab._on_template_selection_changed()  # re-selecting it must not wipe its stored values
    assert tab.workspace_state.get_current_template_id() == "legacy_custom"
    assert tab.workspace_state.get_current_template_variables() == {"shot": "wide", "mood": "calm"}
    assert tab.workspace_state.dirty is False

    target = tmp_path / "legacy.json"
    tab.workspace_state.save_current_pack_as(target)
    reloaded = PromptWorkspaceState()
    reloaded.load_pack(target)
    assert reloaded.get_slot(0).template_id == "legacy_custom"
    assert reloaded.get_slot(0).template_variables == {"shot": "wide", "mood": "calm"}


# --- Selected LoRA evidence and trigger insertion ------------------------------------------------------------------------


def _select_loras(
    frame: PromptTabFrame, resources: dict[str, LoRAResource], selected: list[tuple[str, float]]
) -> None:
    frame.workspace_state.set_slot_loras(0, list(selected))
    frame._refresh_editor()
    _finish_discovery(frame, resources)
    frame.workspace_state.dirty = False


def _entry(frame: PromptTabFrame, name: str) -> dict[str, object]:
    return frame.lora_picker._entry_widgets[name]


def _text(frame: PromptTabFrame, name: str, key: str) -> str:
    return str(_entry(frame, name)[key].cget("text"))  # type: ignore[attr-defined]


def test_each_selected_lora_shows_availability_compatibility_and_evidence(
    tab: PromptTabFrame,
) -> None:
    _select_loras(
        tab,
        {
            "civ": _resource("civ", ["sunlit", "film grain"], "civitai"),
            "plain": _resource("plain"),
            "broken": _resource("broken", errors=["Local keyword metadata unavailable"]),
        },
        [("civ", 0.7), ("plain", 0.5), ("broken", 0.4), ("gone", 0.9)],
    )

    assert "Verified local asset reference" in _text(tab, "civ", "inventory_label")
    assert "Civitai info file" in _text(
        tab, "civ", "trigger_label"
    ) and "sunlit, film grain" in _text(tab, "civ", "trigger_label")
    assert "Unknown / unverified" in _text(
        tab, "civ", "compatibility_label"
    )  # no checkpoint evidence: never "compatible"
    assert NO_TRIGGER_METADATA in _text(tab, "plain", "trigger_label")
    assert "could not be read" in _text(tab, "broken", "trigger_label")
    assert "Missing asset" in _text(tab, "gone", "inventory_label")
    assert not _entry(tab, "civ")["insert_button"].instate(["disabled"])  # type: ignore[attr-defined]
    for name in ("plain", "broken", "gone"):
        assert _entry(tab, name)["insert_button"].instate(["disabled"])  # type: ignore[attr-defined]
    assert tab.lora_picker.get_loras() == [
        ("civ", 0.7),
        ("plain", 0.5),
        ("broken", 0.4),
        ("gone", 0.9),
    ]


def test_insert_trigger_words_edits_only_the_current_slot_and_never_saves(
    tab: PromptTabFrame, tmp_path: Path
) -> None:
    tab.workspace_state.set_slot_text(0, "a quiet harbor")
    tab.workspace_state.set_slot_text(1, "other slot")
    tab._refresh_editor()
    _select_loras(
        tab, {"civ": _resource("civ", ["sunlit", "film grain"], "civitai")}, [("civ", 0.7)]
    )
    tab.workspace_state.dirty = False
    before = (tab.workspace_state.get_current_path(), tab.workspace_state.get_slot(1).text)

    tab.lora_picker._insert_trigger_words("civ")

    assert tab.editor.get("1.0", "end").strip() == "a quiet harbor, sunlit, film grain"
    assert tab.workspace_state.get_slot(0).text == "a quiet harbor, sunlit, film grain"
    assert tab.workspace_state.dirty
    assert (tab.workspace_state.get_current_path(), tab.workspace_state.get_slot(1).text) == before
    assert "Slot 1: Inserted 2 trigger word(s)" in tab.lora_picker.insertion_status.get()
    assert tab.lora_picker.get_loras() == [("civ", 0.7)]
    assert not list(tmp_path.glob("*.json"))  # nothing was saved

    tab.lora_picker._insert_trigger_words("civ")  # repeating adds nothing
    assert tab.workspace_state.get_slot(0).text == "a quiet harbor, sunlit, film grain"
    assert "Already in the prompt" in tab.lora_picker.insertion_status.get()


def test_words_already_in_the_template_text_are_not_inserted_again(tab: PromptTabFrame) -> None:
    _choose_template(tab, ESTABLISHING)  # the example style is "cinematic realism"
    _select_loras(
        tab, {"civ": _resource("civ", ["cinematic realism", "sunlit"], "txt")}, [("civ", 0.7)]
    )

    tab.lora_picker._insert_trigger_words("civ")

    assert tab.workspace_state.get_slot(0).text == "sunlit"
    assert "Already in the prompt: cinematic realism" in tab.lora_picker.insertion_status.get()


def test_a_trigger_the_resolver_adds_automatically_is_not_pasted_into_the_prompt(
    tab: PromptTabFrame, monkeypatch
) -> None:
    applied = ResolvedStyleLoRA(
        "style_a", "Style A", "cinematic grit, soft rim light", "lora_a", 0.6
    )
    monkeypatch.setattr(tab, "_cached_style_selection", lambda: (applied, False))
    _select_loras(
        tab, {"civ": _resource("civ", ["Cinematic Grit", "sunlit"], "civitai")}, [("civ", 0.7)]
    )

    tab.lora_picker._insert_trigger_words("civ")

    assert tab.workspace_state.get_slot(0).text == "sunlit"
    assert "Supplied automatically by Style Consistency" in tab.lora_picker.insertion_status.get()


def test_a_lora_without_evidence_offers_nothing_to_insert(tab: PromptTabFrame) -> None:
    _select_loras(tab, {"plain": _resource("plain")}, [("plain", 0.5)])
    tab.workspace_state.dirty = False

    tab.lora_picker._insert_trigger_words("plain")
    tab.lora_picker._insert_trigger_words("never_selected")

    assert tab.workspace_state.get_slot(0).text == "" and not tab.workspace_state.dirty
    assert tab.lora_picker.insertion_status.get() == "No trigger words are available to insert."


def test_a_hidden_lora_and_a_hidden_prompt_expose_no_words_and_accept_no_insertion(
    tab: PromptTabFrame,
) -> None:
    secret = _resource("secret_adapter", ["hidden trigger"], "txt", description="nude")
    _select_loras(tab, {"secret_adapter": secret}, [("secret_adapter", 0.7)])
    tab.lora_picker.insertion_status.set("Slot 1: Inserted 1 trigger word(s): hidden trigger")
    tab.on_content_visibility_mode_changed("sfw")
    assert tab.lora_picker.insertion_status.get() == ""

    for key in ("trigger_label", "compatibility_label", "name_label"):
        text = _text(tab, "secret_adapter", key)
        assert "hidden trigger" not in text and "secret_adapter" not in text
    assert REDACTED_TEXT in _text(tab, "secret_adapter", "trigger_label")
    assert _entry(tab, "secret_adapter")["insert_button"].instate(["disabled"])  # type: ignore[attr-defined]

    tab.workspace_state.dirty = False
    tab.lora_picker._insert_trigger_words("secret_adapter")
    assert tab.workspace_state.get_slot(0).text == "" and not tab.workspace_state.dirty


def test_the_template_preview_is_redacted_for_hidden_content(tab: PromptTabFrame) -> None:
    _choose_template(tab, ESTABLISHING)
    tab._template_field_vars["scene"].set("a nude figure")

    tab.on_content_visibility_mode_changed("sfw")
    tab._refresh_template_preview()

    assert _preview(tab) == REDACTED_TEXT
    assert "nude" not in tab.template_breakdown_var.get()


def test_changing_the_target_updates_advisories_without_rewriting_authored_loras(
    tab: PromptTabFrame, tmp_path: Path
) -> None:
    root, scanner = scanner_at(tmp_path)
    write_adapter(root / "models/Lora/civ.safetensors", {"ss_base_model_version": "flux2_klein_4b"})
    (root / "models/Lora/civ.civitai.info").write_text(json.dumps({"trainedWords": ["sunlit"]}))
    found = scanner.scan_loras(read_only=True)
    _select_loras(tab, found, [("civ", 0.7), ("gone", 0.9)])
    _choose_template(tab, ESTABLISHING)
    tab.workspace_state.dirty = False
    authored = (
        tab.lora_picker.get_loras(),
        tab.workspace_state.get_current_template_variables(),
        tab.workspace_state.get_current_template_id(),
    )

    tab.on_model_projection(_projection(KLEIN))
    klein = _text(tab, "civ", "compatibility_label")
    tab.on_model_projection(_projection(SDXL))
    sdxl = _text(tab, "civ", "compatibility_label")

    assert klein.startswith("Possibly compatible") and "not physically qualified" in klein
    assert sdxl.startswith(
        "Unknown / unverified"
    )  # a different target changes the advisory, never the selection
    assert "Missing asset" in _text(
        tab, "gone", "inventory_label"
    )  # a missing asset stays a missing asset
    assert (
        tab.lora_picker.get_loras(),
        tab.workspace_state.get_current_template_variables(),
        tab.workspace_state.get_current_template_id(),
    ) == authored
    assert tab.workspace_state.dirty is False


# --- Style Consistency -------------------------------------------------------------------------------------------------


def _offered(frame: PromptTabFrame) -> list[str]:
    return [style_id for style_id in frame._style_choice_to_id.values() if style_id]


def test_only_installed_styles_are_offered_until_examples_are_requested(
    tab: PromptTabFrame, tmp_path: Path
) -> None:
    _install_catalog(tab, tmp_path)
    assert _offered(tab) == []
    assert "Checking installed LoRAs" in tab.style_lora_status_var.get()

    _finish_discovery(
        tab, {"lora_a": _resource("lora_a")}
    )  # style A's weight is installed; style B's is not

    assert _offered(tab) == ["style_a"]
    assert tab.style_lora_combo.cget("values") == tuple(tab._style_choice_to_id)
    assert not tab.workspace_state.dirty

    tab.style_show_all_var.set(True)
    tab._sync_style_lora_controls_cached()
    labels = {style_id: label for label, style_id in tab._style_choice_to_id.items() if style_id}
    assert set(labels) == {"style_a", "style_b"}
    assert "example" in labels["style_b"] and "example" not in labels["style_a"]


def test_an_empty_catalog_inventory_explains_itself(tab: PromptTabFrame, tmp_path: Path) -> None:
    _install_catalog(tab, tmp_path)

    _finish_discovery(tab, {})

    assert _offered(tab) == []
    assert "matching installed LoRA" in tab.style_lora_status_var.get()
    assert "Show examples and unavailable styles" in tab.style_lora_status_var.get()


def test_a_saved_unavailable_style_survives_every_refresh_and_unrelated_edits(
    tab: PromptTabFrame, tmp_path: Path
) -> None:
    _install_catalog(tab, tmp_path)
    saved = {"enabled": True, "style_id": "style_b"}
    tab.workspace_state.set_pack_style_lora_config(saved)
    _finish_discovery(tab, {"lora_a": _resource("lora_a")})
    tab.workspace_state.dirty = False

    tab._refresh_editor()
    tab.on_model_projection(_projection(KLEIN))
    tab.on_model_projection(_projection(SDXL))
    tab.style_show_all_var.set(True)
    tab._sync_style_lora_controls_cached()
    tab.style_show_all_var.set(False)
    tab._sync_style_lora_controls_cached()

    assert tab.workspace_state.get_pack_style_lora_config() == saved
    assert "saved" in tab.style_lora_var.get() and "Style B" in tab.style_lora_var.get()
    assert (
        "catalog example" in tab.style_lora_status_var.get()
        and "kept unchanged" in tab.style_lora_status_var.get()
    )
    assert tab.workspace_state.dirty is False

    tab.editor.insert(
        "1.0", "an unrelated edit"
    )  # an ordinary edit elsewhere must not drop the style
    tab._on_editor_modified()
    assert tab.workspace_state.get_pack_style_lora_config() == saved


def test_a_saved_style_missing_from_the_catalog_is_shown_not_replaced(
    tab: PromptTabFrame, tmp_path: Path
) -> None:
    _install_catalog(tab, tmp_path)
    tab.workspace_state.set_pack_style_lora_config({"enabled": True, "style_id": "retired_style"})
    tab.workspace_state.dirty = False

    tab._sync_style_lora_controls()

    assert (
        "retired_style" in tab.style_lora_var.get()
        and "not in the style catalog" in tab.style_lora_var.get()
    )
    assert tab.workspace_state.get_pack_style_lora_config() == {
        "enabled": True,
        "style_id": "retired_style",
    }
    assert tab.workspace_state.dirty is False


def test_discovery_updates_style_availability_but_a_failed_refresh_keeps_the_selection(
    tab: PromptTabFrame, tmp_path: Path
) -> None:
    _install_catalog(tab, tmp_path)
    saved = {"enabled": True, "style_id": "style_a"}
    tab.workspace_state.set_pack_style_lora_config(saved)
    tab._sync_style_lora_controls_cached()
    assert "unverified" in tab.style_lora_var.get()

    _finish_discovery(tab, {"lora_a": _resource("lora_a")})
    assert "installed LoRA found" in tab.style_lora_status_var.get()
    assert _offered(tab) == ["style_a"]

    _finish_discovery(tab, {}, failed=True)
    assert tab.lora_picker.discovered_lora_names() is None
    assert "unverified" in tab.style_lora_var.get()
    assert tab.workspace_state.get_pack_style_lora_config() == saved


def test_choosing_an_installed_style_stores_only_its_id_and_marks_the_pack_modified(
    tab: PromptTabFrame, tmp_path: Path
) -> None:
    _install_catalog(tab, tmp_path)
    _finish_discovery(tab, {"lora_a": _resource("lora_a")})
    tab.workspace_state.dirty = False

    tab.style_lora_var.set(
        next(label for label, style_id in tab._style_choice_to_id.items() if style_id == "style_a")
    )
    tab._on_style_lora_selection_changed()

    assert tab.workspace_state.get_pack_style_lora_config() == {
        "enabled": True,
        "style_id": "style_a",
    }
    assert tab.workspace_state.dirty
    status = tab.style_lora_status_var.get()
    assert (
        "Style A" in status and "Strength" in status and "cinematic grit, soft rim light" in status
    )


def test_a_listener_error_free_close_discards_late_inventory_callbacks(tab: PromptTabFrame) -> None:
    calls: list[int] = []
    tab.lora_picker.inventory_listener = lambda: calls.append(1)

    _finish_discovery(tab, {})
    tab.lora_picker._closed = True
    _finish_discovery(tab, {})

    assert calls == [1]
    tab.lora_picker._closed = False


def test_the_style_status_never_scans_for_target_changes(
    tab: PromptTabFrame, tmp_path: Path, monkeypatch
) -> None:
    _install_catalog(tab, tmp_path)
    tab.workspace_state.set_pack_style_lora_config({"enabled": True, "style_id": "style_a"})
    resolved: list[int] = []
    monkeypatch.setattr(
        tab._style_lora_manager,
        "resolve_selection",
        lambda *a, **k: resolved.append(1) or SimpleNamespace(),
    )

    tab.on_model_projection(_projection(KLEIN))
    _finish_discovery(tab, {"lora_a": _resource("lora_a")})

    assert resolved == []
