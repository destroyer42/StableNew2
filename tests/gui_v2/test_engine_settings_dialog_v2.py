from __future__ import annotations

import tkinter as tk
from pathlib import Path

from src.gui.app_state_v2 import AppStateV2
from src.gui.engine_settings_dialog import EngineSettingsDialog
from src.utils.config import ConfigManager


def _build_dialog(
    window: tk.Tk,
    config_manager: ConfigManager,
    *,
    content_visibility_mode: str = "nsfw",
    on_content_visibility_mode_change=None,
) -> EngineSettingsDialog:
    dialog = tk.Toplevel(window)
    frame = EngineSettingsDialog(
        dialog,
        config_manager=config_manager,
        content_visibility_mode=content_visibility_mode,
        on_content_visibility_mode_change=on_content_visibility_mode_change,
    )
    frame.pack(fill="both", expand=True)
    return frame


def test_engine_settings_dialog_collects_values(tmp_path: Path, tk_root: tk.Tk) -> None:
    config_manager = ConfigManager(tmp_path / "presets")
    dialog = _build_dialog(tk_root, config_manager)
    dialog._webui_base_url_var.set("http://example.org")
    dialog._webui_autostart_var.set(False)
    dialog._prompt_optimizer_vars["enabled"].set(False)

    values = dialog.collect_values()

    assert values["webui_base_url"] == "http://example.org"
    assert values["webui_autostart_enabled"] is False
    assert "output_dir" in values
    assert values["prompt_optimizer"]["enabled"] is False

    dialog.master.destroy()


def test_engine_settings_dialog_restore_defaults(tmp_path: Path, tk_root: tk.Tk) -> None:
    config_manager = ConfigManager(tmp_path / "presets")
    dialog = _build_dialog(tk_root, config_manager)
    dialog._webui_base_url_var.set("http://custom")
    dialog.restore_defaults()

    defaults = config_manager.get_default_engine_settings()
    assert dialog._webui_base_url_var.get() == defaults["webui_base_url"]
    assert dialog._prompt_optimizer_vars["enabled"].get() == bool(defaults["prompt_optimizer"]["enabled"])

    dialog.master.destroy()


def test_engine_settings_dialog_applies_content_visibility_mode_on_save(
    tmp_path: Path, tk_root: tk.Tk
) -> None:
    config_manager = ConfigManager(tmp_path / "presets")
    app_state = AppStateV2()
    dialog = _build_dialog(
        tk_root,
        config_manager,
        content_visibility_mode=app_state.content_visibility_mode,
        on_content_visibility_mode_change=app_state.set_content_visibility_mode,
    )
    dialog._webui_base_url_var.set("http://example.org")
    dialog._content_visibility_mode_var.set("sfw")

    dialog._handle_save()

    assert app_state.content_visibility_mode == "sfw"
