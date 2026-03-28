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
    (packs_dir / "explicit_pack.txt").write_text("nude portrait reference\n", encoding="utf-8")


@pytest.mark.gui
def test_content_visibility_mode_journey_filters_live_and_persists(
    tk_root: tk.Tk, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_prompt_packs(tmp_path)
    store = UIStateStore(tmp_path / "ui_state.json")

    with patch("src.gui.main_window_v2.get_ui_state_store", return_value=store):
        first_root = _make_window_root(tk_root)
        first = GuiV2Harness(first_root)
        try:
            prompt_tab = first.window.prompt_tab
            assert list(prompt_tab.pack_listbox.get(0, tk.END)) == ["explicit_pack", "safe_pack"]
            assert not hasattr(first.window.header_zone, "visibility_button")

            first.window.open_engine_settings_dialog(config_manager=ConfigManager(tmp_path / "presets"))
            first_root.update()
            dialog = next(
                child for child in first.window.root.winfo_children() if isinstance(child, tk.Toplevel)
            )
            panel = next(child for child in dialog.winfo_children() if isinstance(child, EngineSettingsDialog))
            panel._webui_base_url_var.set("http://127.0.0.1:7860")
            panel._content_visibility_mode_var.set("sfw")
            panel._handle_save()
            first_root.update()

            assert first.controller.app_state.content_visibility_mode == "sfw"
            assert list(prompt_tab.pack_listbox.get(0, tk.END)) == ["safe_pack"]

            queue_panel = getattr(first.window.pipeline_tab, "queue_panel", None)
            running_job_panel = getattr(first.window.pipeline_tab, "running_job_panel", None)
            assert queue_panel is not None
            assert running_job_panel is not None
            assert queue_panel.visibility_banner.cget("text") == ""
            assert running_job_panel.visibility_banner.cget("text") == ""
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
            assert list(second.window.prompt_tab.pack_listbox.get(0, tk.END)) == ["safe_pack"]
        finally:
            second.cleanup()
            try:
                second_root.destroy()
            except Exception:
                pass
