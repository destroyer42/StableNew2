"""PR-IMG-COMFY-381: Engine Settings exposes the Forge/ComfyUI default for new still images.

Persisted through the existing ``ConfigManager`` path, applied to new jobs at once (no restart prompt), written only when
changed, and fail-closed on an unknown persisted value.
"""

from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path

import pytest

from src.gui.engine_settings_dialog import EngineSettingsDialog
from src.utils.config import ConfigManager


@pytest.fixture(autouse=True)
def _no_identity_environment(monkeypatch):
    monkeypatch.delenv("STABLENEW_WEBUI_RUNTIME_IDENTITY", raising=False)
    monkeypatch.delenv("STABLENEW_WEBUI_BASE_URL", raising=False)


def _manager(tmp_path: Path, **settings) -> ConfigManager:
    manager = ConfigManager(presets_dir=tmp_path / "presets", packs_dir=tmp_path / "packs")
    if settings:
        (tmp_path / "presets" / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
        manager = ConfigManager(presets_dir=tmp_path / "presets", packs_dir=tmp_path / "packs")
    return manager


def _dialog(tk_root: tk.Tk, manager: ConfigManager) -> EngineSettingsDialog:
    window = tk.Toplevel(tk_root)
    frame = EngineSettingsDialog(window, config_manager=manager)
    frame.pack(fill="both", expand=True)
    return frame


def test_the_default_is_forge_and_nothing_is_written_when_unchanged(tmp_path, tk_root):
    dialog = _dialog(tk_root, _manager(tmp_path))

    assert dialog.selected_image_backend() == "webui"
    assert "image_backend_default" not in dialog.collect_values()
    dialog.master.destroy()


def test_choosing_comfyui_persists_through_the_config_manager_and_reopens_selected(
    tmp_path, tk_root
):
    manager = _manager(tmp_path)
    dialog = _dialog(tk_root, manager)

    dialog.set_image_backend("comfyui")
    values = dialog.collect_values()
    assert manager.update_settings(values)
    dialog.master.destroy()

    assert values["image_backend_default"] == "comfyui"
    assert not dialog.restart_required()  # no restart for this key
    reopened = _dialog(tk_root, _manager(tmp_path))
    assert reopened.selected_image_backend() == "comfyui"
    # The WebUI runtime selection is independent and untouched.
    assert (
        reopened.selected_runtime() == "default"
        and "webui_runtime_identity" not in reopened.collect_values()
    )
    reopened.master.destroy()


def test_choosing_forge_again_persists_the_webui_value(tmp_path, tk_root):
    manager = _manager(tmp_path, image_backend_default="comfyui")
    dialog = _dialog(tk_root, manager)

    assert dialog.selected_image_backend() == "comfyui"
    dialog.set_image_backend("webui")
    values = dialog.collect_values()
    manager.update_settings(values)

    assert values["image_backend_default"] == "webui"
    assert manager.load_settings()["image_backend_default"] == "webui"
    dialog.master.destroy()


def test_an_unknown_persisted_value_selects_neither_backend_and_is_never_written_back(
    tmp_path, tk_root
):
    dialog = _dialog(tk_root, _manager(tmp_path, image_backend_default="elsewhere"))

    assert dialog.selected_image_backend() == ""
    assert "image_backend_default" not in dialog.collect_values()
    dialog.set_image_backend("comfyui")
    assert dialog.collect_values()["image_backend_default"] == "comfyui"
    dialog.master.destroy()


def test_restore_defaults_selects_forge(tmp_path, tk_root):
    dialog = _dialog(tk_root, _manager(tmp_path, image_backend_default="comfyui"))

    dialog.restore_defaults()

    assert dialog.selected_image_backend() == "webui"
    dialog.master.destroy()
