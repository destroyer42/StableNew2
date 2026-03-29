from __future__ import annotations

from unittest.mock import Mock

from src.gui.app_state_v2 import AppStateV2
from src.gui.view_contracts.prompt_editor_contract import (
    PROMPT_PICKER_COLUMN_MIN_WIDTH,
    PROMPT_PICKER_ROW_MIN_HEIGHT,
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

        assert frame.prompts_tab.columnconfigure(0)["minsize"] == PROMPT_PICKER_COLUMN_MIN_WIDTH
        assert frame.prompts_tab.columnconfigure(1)["minsize"] == PROMPT_PICKER_COLUMN_MIN_WIDTH
        assert frame.prompts_tab.rowconfigure(5)["minsize"] == PROMPT_PICKER_ROW_MIN_HEIGHT
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
