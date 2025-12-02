import tkinter as tk

import pytest

from src.gui.output_settings_panel_v2 import OutputSettingsPanelV2


@pytest.mark.usefixtures("tk_root")
def test_output_settings_panel_roundtrip(tk_root: tk.Tk):
    panel = OutputSettingsPanelV2(tk_root)
    panel.output_dir_var.set("out_dir")
    panel.filename_pattern_var.set("file_{index}")
    panel.image_format_var.set("webp")
    panel.batch_size_var.set("3")
    panel.seed_mode_var.set("increment")

    overrides = panel.get_output_overrides()
    assert overrides["output_dir"] == "out_dir"
    assert overrides["filename_pattern"] == "file_{index}"
    assert overrides["image_format"] == "webp"
    assert overrides["batch_size"] == 3
    assert overrides["seed_mode"] == "increment"

    panel.apply_from_overrides({"output_dir": "new_out", "batch_size": 5})
    assert panel.output_dir_var.get() == "new_out"
    assert panel.batch_size_var.get() == "5"
