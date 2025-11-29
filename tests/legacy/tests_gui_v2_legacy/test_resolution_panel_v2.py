import tkinter as tk

import pytest

from src.gui.resolution_panel_v2 import ResolutionPanelV2


@pytest.mark.usefixtures("tk_root")
def test_resolution_panel_preset_sets_width_height(tk_root: tk.Tk):
    panel = ResolutionPanelV2(tk_root)
    panel.apply_preset("1024x1024")

    assert panel.get_resolution() == (1024, 1024)
    assert panel.get_preset_label() == "1024x1024"


@pytest.mark.usefixtures("tk_root")
def test_resolution_panel_manual_edit_overrides_preset(tk_root: tk.Tk):
    panel = ResolutionPanelV2(tk_root)
    panel.apply_preset("768x768")
    panel.set_resolution(900, 600)

    width, height = panel.get_resolution()
    assert width == 900
    assert height == 600
    assert panel.get_preset_label() == ""
