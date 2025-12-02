import tkinter as tk

import pytest

from src.gui.model_manager_panel_v2 import ModelManagerPanelV2


class DummyAdapter:
    def __init__(self):
        self.model_calls = 0
        self.vae_calls = 0

    def get_model_names(self):
        self.model_calls += 1
        return ["model_a", "model_b"]

    def get_vae_names(self):
        self.vae_calls += 1
        return ["vae_x", "vae_y"]


@pytest.mark.usefixtures("tk_root")
def test_model_panel_refresh_and_selection(tk_root: tk.Tk):
    adapter = DummyAdapter()
    panel = ModelManagerPanelV2(tk_root, adapter=adapter, models=["init_model"], vaes=["init_vae"])

    # initial set/get
    panel.set_selections("init_model", "init_vae")
    selections = panel.get_selections()
    assert selections["model_name"] == "init_model"
    assert selections["vae_name"] == "init_vae"

    # refresh pulls from adapter and updates combos
    panel.refresh_lists()
    assert adapter.model_calls == 1
    assert adapter.vae_calls == 1
    assert "model_a" in panel.model_combo["values"]
    assert "vae_x" in panel.vae_combo["values"]

    # update selection after refresh
    panel.set_selections("model_b", "vae_y")
    refreshed = panel.get_selections()
    assert refreshed["model_name"] == "model_b"
    assert refreshed["vae_name"] == "vae_y"
