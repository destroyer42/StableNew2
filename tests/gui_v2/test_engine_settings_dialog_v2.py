from __future__ import annotations

import tkinter as tk
from pathlib import Path

from src.gui.engine_settings_dialog import EngineSettingsDialog
from src.utils.config import ConfigManager


def _build_dialog(window: tk.Tk, config_manager: ConfigManager) -> EngineSettingsDialog:
    dialog = tk.Toplevel(window)
    frame = EngineSettingsDialog(dialog, config_manager=config_manager)
    frame.pack(fill="both", expand=True)
    return frame


def test_engine_settings_dialog_collects_values(tmp_path: Path, tk_root: tk.Tk) -> None:
    config_manager = ConfigManager(tmp_path / "presets")
    dialog = _build_dialog(tk_root, config_manager)
    dialog._webui_base_url_var.set("http://example.org")
    dialog._webui_autostart_var.set(False)

    values = dialog.collect_values()

    assert values["webui_base_url"] == "http://example.org"
    assert values["webui_autostart_enabled"] is False
    assert "output_dir" in values

    dialog.master.destroy()


def test_engine_settings_dialog_restore_defaults(tmp_path: Path, tk_root: tk.Tk) -> None:
    config_manager = ConfigManager(tmp_path / "presets")
    dialog = _build_dialog(tk_root, config_manager)
    dialog._webui_base_url_var.set("http://custom")
    dialog.restore_defaults()

    defaults = config_manager.get_default_engine_settings()
    assert dialog._webui_base_url_var.get() == defaults["webui_base_url"]

    dialog.master.destroy()
