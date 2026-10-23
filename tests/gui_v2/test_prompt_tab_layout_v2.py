from __future__ import annotations

from unittest.mock import Mock

from src.gui.app_state_v2 import AppStateV2
from src.gui.view_contracts.prompt_editor_contract import (
    PROMPT_TAB_CENTER_COLUMN_MIN_WIDTH,
    PROMPT_TAB_LEFT_COLUMN_MIN_WIDTH,
    PROMPT_TAB_RIGHT_COLUMN_MIN_WIDTH,
)
from src.gui.views.prompt_tab_frame_v2 import PromptTabFrame


def test_prompt_tab_uses_shared_column_minimums(tk_root) -> None:
    frame = PromptTabFrame(tk_root)
    try:
        assert frame.columnconfigure(0)["minsize"] == PROMPT_TAB_LEFT_COLUMN_MIN_WIDTH
        assert frame.columnconfigure(1)["minsize"] == PROMPT_TAB_CENTER_COLUMN_MIN_WIDTH
        assert frame.columnconfigure(2)["minsize"] == PROMPT_TAB_RIGHT_COLUMN_MIN_WIDTH

        assert frame.prompts_tab.rowconfigure(1)["minsize"] >= 120
        assert frame.prompts_tab.rowconfigure(4)["minsize"] >= 72
        assert frame.embedding_picker.master is frame.embedding_scroll.inner
        assert frame.lora_picker.master is frame.lora_scroll.inner
    finally:
        frame.destroy()


def test_prompt_tab_defers_visibility_pack_refresh_until_mapped(tk_root) -> None:
    state = AppStateV2()
    frame = PromptTabFrame(tk_root, app_state=state)
    try:
        frame._refresh_pack_list = Mock()

        state.set_content_visibility_mode("sfw")
        state.flush_now()

        frame._refresh_pack_list.assert_not_called()
        assert frame._pending_visibility_refresh is True

        frame._on_map()
        tk_root.update_idletasks()
        tk_root.update()

        frame._refresh_pack_list.assert_called_once()
    finally:
        frame.destroy()


def test_prompt_tab_template_preview_updates_current_prompt(tk_root) -> None:
    frame = PromptTabFrame(tk_root)
    try:
        frame.workspace_state.set_slot_text(0, "rain drifting through the alley")
        frame._refresh_editor()

        frame.template_selector_var.set("establishing_wide")
        frame._on_template_selection_changed()

        frame._template_field_vars["scene"].set("the hero arrival")
        frame._template_field_vars["environment"].set("neon storefronts")
        frame._template_field_vars["lighting"].set("wet reflections")
        frame._template_field_vars["style"].set("cinematic realism")
        tk_root.update_idletasks()

        preview = frame.template_preview.get("1.0", "end").strip()
        editor_text = frame.editor.get("1.0", "end").strip()
        current_prompt = frame.workspace_state.get_current_prompt_text()

        assert "cinematic wide establishing shot of the hero arrival" in preview
        assert "rain drifting through the alley" in preview
        assert editor_text == "rain drifting through the alley"
        assert current_prompt == preview
        assert frame.workspace_state.get_current_template_id() == "establishing_wide"
    finally:
        frame.destroy()


def test_prompt_tab_style_lora_selection_updates_pack_preset_data(tk_root) -> None:
    frame = PromptTabFrame(tk_root)
    try:
        # Catalog entries are examples until an installed LoRA is verified: the primary selector offers none of them.
        assert not [style_id for style_id in frame._style_choice_to_id.values() if style_id]
        frame.style_show_all_var.set(True)
        frame._sync_style_lora_controls_cached()
        style_choices = [
            choice for choice, style_id in frame._style_choice_to_id.items() if style_id
        ]
        assert style_choices

        selected_choice = style_choices[0]
        selected_style_id = frame._style_choice_to_id[selected_choice]
        frame.style_lora_var.set(selected_choice)
        frame._on_style_lora_selection_changed()

        assert frame.workspace_state.get_pack_style_lora_config()["style_id"] == selected_style_id
        assert frame.style_lora_status_var.get()

        frame._clear_style_lora_selection()
        assert frame.workspace_state.get_pack_style_lora_config() == {}
    finally:
        frame.destroy()
