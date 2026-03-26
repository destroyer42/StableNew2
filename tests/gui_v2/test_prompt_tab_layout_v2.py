from __future__ import annotations

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