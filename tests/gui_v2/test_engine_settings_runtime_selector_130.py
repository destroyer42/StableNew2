"""PR-RUNTIME-WEBUI-LIFECYCLE-130: Engine Settings exposes the Forge-default / A1111-rollback choice.

One application-level selector, persisted through the existing settings authority, restart-required. The endpoint
shown is the existing identity-aware resolver's answer; the dialog never pins an endpoint that would follow the
wrong runtime later, never rewrites an unchanged selection, and fails closed on an invalid persisted identity.
"""

from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from unittest import mock

import pytest

from src.api.webui_runtime_identity import (
    A1111_DEFAULT_BASE_URL,
    resolve_configured_webui_runtime_identity,
    resolve_effective_webui_base_url,
)
from src.gui.engine_settings_dialog import EngineSettingsDialog
from src.utils.config import ConfigManager

FORGE_URL = "http://127.0.0.1:7871"


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


def _dialog(tk_root: tk.Tk, manager: ConfigManager, **kwargs) -> EngineSettingsDialog:
    window = tk.Toplevel(tk_root)
    frame = EngineSettingsDialog(window, config_manager=manager, **kwargs)
    frame.pack(fill="both", expand=True)
    return frame


def test_missing_identity_selects_the_forge_default_and_shows_the_forge_endpoint(tmp_path, tk_root):
    dialog = _dialog(tk_root, _manager(tmp_path))

    assert dialog.selected_runtime() == "default"
    assert dialog._webui_base_url_var.get() == FORGE_URL
    assert FORGE_URL in dialog.effective_endpoint_text()
    dialog.master.destroy()


def test_persisted_a1111_rollback_is_shown_with_the_a1111_endpoint(tmp_path, tk_root):
    dialog = _dialog(tk_root, _manager(tmp_path, webui_runtime_identity="a1111_webui"))

    assert dialog.selected_runtime() == "a1111_webui"
    assert dialog._webui_base_url_var.get() == A1111_DEFAULT_BASE_URL
    dialog.master.destroy()


def test_selecting_a1111_persists_the_explicit_rollback_identity(tmp_path, tk_root):
    manager = _manager(tmp_path)
    dialog = _dialog(tk_root, manager)

    dialog.set_runtime("a1111_webui")
    values = dialog.collect_values()
    manager.update_settings(values)

    assert values["webui_runtime_identity"] == "a1111_webui"
    assert resolve_configured_webui_runtime_identity(manager.load_settings()) == "a1111_webui"
    assert manager.load_settings()["webui_base_url"] == A1111_DEFAULT_BASE_URL
    dialog.master.destroy()


def test_selecting_the_default_persists_blank_identity_and_never_pins_an_endpoint(tmp_path, tk_root):
    manager = _manager(tmp_path, webui_runtime_identity="a1111_webui")
    dialog = _dialog(tk_root, manager)

    dialog.set_runtime("default")
    values = dialog.collect_values()
    manager.update_settings(values)

    assert values["webui_runtime_identity"] == ""
    # The Forge endpoint is not persisted as an explicit URL, so a later A1111 selection cannot inherit 7871.
    assert values["webui_base_url"] == A1111_DEFAULT_BASE_URL
    assert manager.load_settings()["webui_base_url"] == FORGE_URL
    manager.update_settings({"webui_runtime_identity": "a1111_webui"})
    assert manager.load_settings()["webui_base_url"] == A1111_DEFAULT_BASE_URL
    dialog.master.destroy()


def test_an_unchanged_selection_never_rewrites_the_persisted_identity(tmp_path, tk_root, monkeypatch):
    monkeypatch.setenv("STABLENEW_WEBUI_RUNTIME_IDENTITY", "a1111_webui")  # effective a1111 via environment only
    manager = _manager(tmp_path)
    dialog = _dialog(tk_root, manager)

    assert dialog.selected_runtime() == "a1111_webui"
    assert "webui_runtime_identity" not in dialog.collect_values()
    dialog.master.destroy()


def test_an_explicit_forge_identity_is_preserved_when_the_default_stays_selected(tmp_path, tk_root):
    dialog = _dialog(tk_root, _manager(tmp_path, webui_runtime_identity="forge_webui"))

    assert dialog.selected_runtime() == "default"
    assert "webui_runtime_identity" not in dialog.collect_values()
    dialog.master.destroy()


def test_a_custom_endpoint_is_preserved_and_not_overwritten_by_a_runtime_switch(tmp_path, tk_root):
    dialog = _dialog(tk_root, _manager(tmp_path))
    dialog._webui_base_url_var.set("http://192.168.1.50:9999")

    dialog.set_runtime("a1111_webui")

    assert dialog._webui_base_url_var.get() == "http://192.168.1.50:9999"
    assert dialog.collect_values()["webui_base_url"] == "http://192.168.1.50:9999"
    dialog.master.destroy()


def test_switching_runtime_moves_an_identity_default_endpoint_with_it(tmp_path, tk_root):
    dialog = _dialog(tk_root, _manager(tmp_path))
    assert dialog._webui_base_url_var.get() == FORGE_URL

    dialog.set_runtime("a1111_webui")
    assert dialog._webui_base_url_var.get() == A1111_DEFAULT_BASE_URL

    dialog.set_runtime("default")
    assert dialog._webui_base_url_var.get() == FORGE_URL
    dialog.master.destroy()


def test_effective_endpoint_text_comes_from_the_existing_resolver(tmp_path, tk_root):
    dialog = _dialog(tk_root, _manager(tmp_path))
    dialog.set_runtime("a1111_webui")

    expected = resolve_effective_webui_base_url(
        {"webui_runtime_identity": "a1111_webui", "webui_base_url": dialog._webui_base_url_var.get()}
    )

    assert expected in dialog.effective_endpoint_text()
    dialog.master.destroy()


def test_an_invalid_persisted_identity_fails_closed_and_blocks_saving(tmp_path, tk_root, monkeypatch):
    warn = mock.Mock()
    monkeypatch.setattr("src.gui.engine_settings_dialog.messagebox.showwarning", warn)
    saved = []
    dialog = _dialog(
        tk_root, _manager(tmp_path, webui_runtime_identity="bogus_runtime"), on_save=saved.append
    )

    assert dialog.selected_runtime() == ""  # neither runtime is silently selected
    assert "bogus_runtime" in dialog.runtime_notice_text()
    dialog._handle_save()

    warn.assert_called_once()
    assert saved == []
    dialog.set_runtime("default")
    assert dialog.collect_values()["webui_runtime_identity"] == ""  # an explicit choice repairs it
    dialog.master.destroy()


def test_restart_is_required_when_the_choice_differs_from_the_running_runtime(tmp_path, tk_root):
    dialog = _dialog(tk_root, _manager(tmp_path), running_runtime_identity="forge_webui")
    assert dialog.restart_required() is False

    dialog.set_runtime("a1111_webui")

    assert dialog.restart_required() is True
    assert "restart" in dialog.runtime_notice_text().lower()
    dialog.set_runtime("default")
    assert dialog.restart_required() is False
    dialog.master.destroy()


def test_saving_a_changed_runtime_tells_the_operator_a_restart_is_required(tmp_path, tk_root, monkeypatch):
    info = mock.Mock()
    monkeypatch.setattr("src.gui.engine_settings_dialog.messagebox.showinfo", info)
    saved = []
    dialog = _dialog(
        tk_root, _manager(tmp_path), running_runtime_identity="forge_webui", on_save=saved.append
    )
    dialog.set_runtime("a1111_webui")

    dialog._handle_save()

    assert saved and saved[0]["webui_runtime_identity"] == "a1111_webui"
    info.assert_called_once()
    assert "restart" in str(info.call_args).lower()


def test_saving_an_unchanged_runtime_shows_no_restart_notice(tmp_path, tk_root, monkeypatch):
    info = mock.Mock()
    monkeypatch.setattr("src.gui.engine_settings_dialog.messagebox.showinfo", info)
    dialog = _dialog(
        tk_root, _manager(tmp_path), running_runtime_identity="forge_webui", on_save=lambda _v: None
    )

    dialog._handle_save()

    info.assert_not_called()


def test_restore_defaults_selects_the_default_runtime_and_keeps_the_default_endpoint_value(tmp_path, tk_root):
    manager = _manager(tmp_path, webui_runtime_identity="a1111_webui")
    dialog = _dialog(tk_root, manager)

    dialog.restore_defaults()

    assert dialog.selected_runtime() == "default"
    assert dialog._webui_base_url_var.get() == manager.get_default_engine_settings()["webui_base_url"]
    assert FORGE_URL in dialog.effective_endpoint_text()  # the resolver still reports the real endpoint
    dialog.master.destroy()
