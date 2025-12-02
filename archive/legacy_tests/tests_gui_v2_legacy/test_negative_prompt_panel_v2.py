import tkinter as tk

import pytest

from src.gui.negative_prompt_panel_v2 import NegativePromptPanelV2


@pytest.mark.usefixtures("tk_root")
def test_negative_panel_set_and_get(tk_root: tk.Tk):
    panel = NegativePromptPanelV2(tk_root)
    panel.set_negative_prompt("bad hands, low quality")
    assert panel.get_negative_prompt() == "bad hands, low quality"


@pytest.mark.usefixtures("tk_root")
def test_negative_panel_clear_button(tk_root: tk.Tk):
    panel = NegativePromptPanelV2(tk_root)
    panel.set_negative_prompt("text")
    panel.clear()
    assert panel.get_negative_prompt() == ""
    panel.set_negative_prompt("reset me")
    panel.reset_to_default()
    assert panel.get_negative_prompt() == ""  # default is empty unless configured
