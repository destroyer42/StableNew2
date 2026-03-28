from __future__ import annotations

import tkinter as tk
from pathlib import Path
from unittest.mock import patch

import pytest

from src.gui.engine_settings_dialog import EngineSettingsDialog
from src.services.ui_state_store import UIStateStore
from src.utils.config import ConfigManager
from tests.helpers.gui_harness_v2 import GuiV2Harness


def _make_window_root(root: tk.Tk) -> tk.Toplevel:
    window_root = tk.Toplevel(root)
    window_root.withdraw()
    return window_root


def _write_prompt_packs(base_dir: Path) -> None:
    packs_dir = base_dir / "packs"
    packs_dir.mkdir(parents=True, exist_ok=True)
    (packs_dir / "safe_pack.txt").write_text("sunlit mountains\n", encoding="utf-8")
    (packs_dir / "explicit_pack.txt").write_text("nude portrait\n", encoding="utf-8")


def _open_settings_dialog_frame(root: tk.Toplevel) -> EngineSettingsDialog:
    dialog = next(child for child in root.winfo_children() if isinstance(child, tk.Toplevel))
    return next(child for child in dialog.winfo_children() if isinstance(child, EngineSettingsDialog))


@pytest.mark.gui
def test_main_window_restores_saved_visibility_mode_without_shell_banners(
    tk_root: tk.Tk, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_prompt_packs(tmp_path)
    store = UIStateStore(tmp_path / "ui_state.json")
    store.save_state({"content_visibility": {"mode": "sfw"}})

    with patch("src.gui.main_window_v2.get_ui_state_store", return_value=store):
        root = _make_window_root(tk_root)
        harness = GuiV2Harness(root)
        try:
            root.update()

            assert harness.controller.app_state.content_visibility_mode == "sfw"
            assert not hasattr(harness.window.header_zone, "visibility_button")
            assert "explicit_pack" not in list(harness.window.prompt_tab.pack_listbox.get(0, tk.END))

            queue_panel = getattr(harness.window.pipeline_tab, "queue_panel", None)
            running_job_panel = getattr(harness.window.pipeline_tab, "running_job_panel", None)
            assert queue_panel is not None
            assert running_job_panel is not None
            assert queue_panel.visibility_banner.cget("text") == ""
            assert running_job_panel.visibility_banner.cget("text") == ""
        finally:
            harness.cleanup()
            try:
                root.destroy()
            except Exception:
                pass


@pytest.mark.gui
def test_main_window_persists_visibility_mode_across_cleanup_and_restart(
    tk_root: tk.Tk, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_prompt_packs(tmp_path)
    store = UIStateStore(tmp_path / "ui_state.json")

    with patch("src.gui.main_window_v2.get_ui_state_store", return_value=store):
        first_root = _make_window_root(tk_root)
        first = GuiV2Harness(first_root)
        try:
            first.window.open_engine_settings_dialog(config_manager=ConfigManager(tmp_path / "presets"))
            first_root.update()
            dialog = _open_settings_dialog_frame(first.window.root)
            dialog._webui_base_url_var.set("http://127.0.0.1:7860")
            dialog._content_visibility_mode_var.set("sfw")
            dialog._handle_save()
            first_root.update()
            assert first.controller.app_state.content_visibility_mode == "sfw"
        finally:
            first.cleanup()
            try:
                first_root.destroy()
            except Exception:
                pass

        second_root = _make_window_root(tk_root)
        second = GuiV2Harness(second_root)
        try:
            second_root.update()
            assert second.controller.app_state.content_visibility_mode == "sfw"
            assert not hasattr(second.window.header_zone, "visibility_button")
            assert "explicit_pack" not in list(second.window.prompt_tab.pack_listbox.get(0, tk.END))
        finally:
            second.cleanup()
            try:
                second_root.destroy()
            except Exception:
                pass
