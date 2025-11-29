"""Tests for config dirty tracking, warnings, and persistence."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path

import pytest

from src.gui.main_window import (
    StableNewGUI,
    disable_gui_test_mode,
    reset_gui_test_mode,
)
from src.utils.preferences import PreferencesManager


class TestUnsavedState:
    def test_pipeline_change_marks_dirty(self, tk_root):
        gui = StableNewGUI(root=tk_root)
        assert gui._config_dirty is False

        gui.pipeline_controls_panel.loop_count_var.set("5")

        assert gui._config_dirty is True

    def test_run_prompt_blocks_when_cancelled(self, tk_root, monkeypatch):
        gui = StableNewGUI(root=tk_root)
        gui._config_dirty = True

        ran = {"called": False}

        def fake_impl():
            ran["called"] = True

        gui._run_full_pipeline_impl = fake_impl

        prompts = {}

        def fake_yesno(title, message):
            prompts["value"] = (title, message)
            return False

        monkeypatch.setattr("tkinter.messagebox.askyesno", fake_yesno)

        disable_gui_test_mode()
        try:
            gui._run_full_pipeline()
        finally:
            reset_gui_test_mode()

        assert ran["called"] is False
        assert prompts["value"][0] == "Unsaved Changes"

    def test_run_prompt_allows_continue(self, tk_root, monkeypatch):
        gui = StableNewGUI(root=tk_root)
        gui._config_dirty = True

        ran = {"called": False}

        def fake_impl():
            ran["called"] = True

        gui._run_full_pipeline_impl = fake_impl

        monkeypatch.setattr("tkinter.messagebox.askyesno", lambda *_: True)

        disable_gui_test_mode()
        try:
            gui._run_full_pipeline()
        finally:
            reset_gui_test_mode()

        assert ran["called"] is True

    def test_preferences_persist_across_launches(self, tmp_path: Path):
        prefs_path = tmp_path / "prefs.json"

        try:
            root1 = tk.Tk()
            root1.withdraw()
        except tk.TclError:
            pytest.skip("Tk not available in headless environment")

        try:
            manager = PreferencesManager(prefs_path)
            gui1 = StableNewGUI(root=root1, preferences=manager)
            gui1.pipeline_controls_panel.loop_count_var.set("9")
            gui1.config_panel.txt2img_vars["model"].set("PersistentModel")
            gui1._autosave_preferences_if_needed(force=True)
        finally:
            try:
                root1.destroy()
            except Exception:
                pass

        try:
            root2 = tk.Tk()
            root2.withdraw()
        except tk.TclError:
            pytest.skip("Tk not available in headless environment")

        try:
            gui2 = StableNewGUI(root=root2, preferences=PreferencesManager(prefs_path))
            assert gui2.pipeline_controls_panel.loop_count_var.get() == "9"
            assert gui2.config_panel.txt2img_vars["model"].get() == "PersistentModel"
        finally:
            try:
                root2.destroy()
            except Exception:
                pass
