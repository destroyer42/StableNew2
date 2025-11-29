"""Functional smoke tests for pack config/list buttons and advanced editor tab."""

import tkinter as tk

import pytest

from src.gui.main_window import StableNewGUI
from tests.gui.conftest import pump_events_until


class DummyConfigService:
    def __init__(self):
        self.pack_cfg = {
            "txt2img": {"steps": 42},
            "pipeline": {"loop_count": 3, "images_per_prompt": 2},
        }
        self.lists = {"Favorites": ["PackA", "PackB"]}

    # Presets are unused in these tests but methods are required by the GUI.
    def list_presets(self):
        return []

    def load_preset(self, _name):
        return {}

    def load_pack_config(self, pack: str):
        return self.pack_cfg if pack == "PackA" else {}

    def load_list(self, name: str):
        return self.lists.get(name, [])

    def list_lists(self):
        return list(self.lists.keys())


class TestFunctionalButtons:
    def _prepare_gui(self, tk_root):
        gui = StableNewGUI(root=tk_root)
        gui.config_service = DummyConfigService()
        gui._refresh_list_dropdown()
        try:
            gui.root.update()
        except Exception:
            pass

        listbox = gui.prompt_pack_panel.packs_listbox
        listbox.delete(0, tk.END)
        for name in ["PackA", "PackB", "PackC"]:
            listbox.insert(tk.END, name)
        return gui

    def test_load_pack_config_applies_to_forms(self, tk_root):
        gui = self._prepare_gui(tk_root)
        gui.current_selected_packs = ["PackA"]
        gui._ui_load_pack_config()

        assert gui.config_panel.txt2img_vars["steps"].get() == 42
        assert gui.pipeline_controls_panel.loop_count_var.get() == "3"

    @pytest.mark.timeout(5)
    def test_load_list_selects_packs(self, tk_root, monkeypatch):
        gui = self._prepare_gui(tk_root)

        # Suppress modal dialogs that would otherwise block the test run.
        monkeypatch.setattr(
            "src.gui.main_window.messagebox.showinfo",
            lambda *_, **__: None,
            raising=False,
        )
        monkeypatch.setattr(
            "src.gui.main_window.messagebox.showwarning",
            lambda *_, **__: None,
            raising=False,
        )
        monkeypatch.setattr(
            "src.gui.main_window.messagebox.showerror",
            lambda *_, **__: None,
            raising=False,
        )

        gui.list_combobox.set("Favorites")
        gui._ui_load_list()

        pump_events_until(
            tk_root,
            lambda: gui.prompt_pack_panel.get_selected_packs(),
            timeout=3.0,
        )

        selected = gui.prompt_pack_panel.get_selected_packs()
        assert selected == ["PackA", "PackB"]
        assert gui.ctx.active_list == "Favorites"

    def test_advanced_editor_tab_present(self, tk_root):
        gui = self._prepare_gui(tk_root)
        titles = [gui.center_notebook.tab(t, "text") for t in gui.center_notebook.tabs()]
        assert "Advanced Editor" in titles

    def test_prompt_panel_set_selected_packs_helper(self, tk_root):
        gui = self._prepare_gui(tk_root)
        panel = gui.prompt_pack_panel

        panel.set_selected_packs(["PackB"])

        assert panel.get_selected_packs() == ["PackB"]
