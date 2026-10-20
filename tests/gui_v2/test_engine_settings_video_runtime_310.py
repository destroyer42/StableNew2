"""PR-VID-UX-310: Engine Settings > Video runtime (ComfyUI) configures the launch command explicitly.

The managed installation is selected, or the required flags added, only by an operator click. The dialog
writes the Comfy keys only when they changed and says a restart applies them; it never starts, stops or
adopts a ComfyUI.
"""

from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from unittest import mock

import pytest

from src.gui.engine_settings_dialog import EngineSettingsDialog
from src.utils.config import ConfigManager
from src.video.managed_comfy_runtime import (
    ManagedComfyDetection,
    build_managed_launch_command,
    load_managed_comfy_contract,
)

CONTRACT = load_managed_comfy_contract()
DESKTOP_COMMAND = [
    "E:/desktop/.venv/Scripts/python.exe",
    "E:/desktop/ComfyUI/main.py",
    "--port",
    "8000",
    "--disable-auto-launch",
]


@pytest.fixture(autouse=True)
def _no_identity_environment(monkeypatch):
    monkeypatch.delenv("STABLENEW_WEBUI_RUNTIME_IDENTITY", raising=False)
    monkeypatch.delenv("STABLENEW_WEBUI_BASE_URL", raising=False)


def _manager(tmp_path: Path, **settings) -> ConfigManager:
    presets = tmp_path / "presets"
    presets.mkdir(parents=True, exist_ok=True)
    if settings:
        (presets / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    return ConfigManager(presets_dir=presets, packs_dir=tmp_path / "packs")


def _found(tmp_path: Path):
    def detector(contract, port):
        install = tmp_path / "managed" / contract.install_dir_name
        runtime = tmp_path / "runtime"
        return ManagedComfyDetection(
            contract=contract,
            install_dir=install,
            runtime_dir=runtime,
            problems=(),
            command=tuple(
                build_managed_launch_command(
                    contract, install_dir=install, runtime_dir=runtime, port=port
                )
            ),
            workdir=str(install / "source"),
            base_url=f"http://127.0.0.1:{port}",
        )

    return detector


def _missing(contract, port):
    return ManagedComfyDetection(
        contract=contract,
        install_dir=Path("C:/nowhere"),
        runtime_dir=Path("C:/nowhere/runtime"),
        problems=("no managed ComfyUI v0.38.0 installation at C:/nowhere",),
    )


def _dialog(tk_root, manager, detector=None) -> EngineSettingsDialog:
    window = tk.Toplevel(tk_root)
    frame = EngineSettingsDialog(
        window,
        config_manager=manager,
        managed_comfy_contract=CONTRACT,
        managed_comfy_detector=detector or _missing,
    )
    frame.pack(fill="both", expand=True)
    return frame


def test_desktop_command_without_the_flag_is_reported_and_fixable(tmp_path, tk_root):
    dialog = _dialog(
        tk_root,
        _manager(tmp_path, comfy_command=DESKTOP_COMMAND, comfy_base_url="http://127.0.0.1:8000"),
    )
    try:
        status = dialog.comfy_status_text()
        assert "Custom ComfyUI command" in status
        assert "--disable-pinned-memory" in status
        assert dialog.add_comfy_flags_button.instate(["!disabled"])

        dialog.add_required_comfy_flags()

        assert dialog.comfy_command() == [*DESKTOP_COMMAND, "--disable-pinned-memory"]
        assert "All required launch flags are present" in dialog.comfy_status_text()
        assert dialog.add_comfy_flags_button.instate(["disabled"])
        values = dialog.collect_values()
        assert values["comfy_command"] == [*DESKTOP_COMMAND, "--disable-pinned-memory"]
        assert values["comfy_base_url"] == "http://127.0.0.1:8000"
    finally:
        dialog.master.destroy()


def test_use_managed_install_selects_the_detected_installation(tmp_path, tk_root):
    dialog = _dialog(
        tk_root,
        _manager(tmp_path, comfy_command=DESKTOP_COMMAND, comfy_base_url="http://127.0.0.1:8000"),
        detector=_found(tmp_path),
    )
    try:
        assert dialog.use_managed_comfy_install() is True
        command = dialog.comfy_command()
        assert command[command.index("--port") + 1] == "8000"  # keeps the configured port
        assert "Managed ComfyUI" in dialog.comfy_status_text()
        values = dialog.collect_values()
        assert values["comfy_command"] == command
        assert values["comfy_workdir"].endswith("source")
        assert values["comfy_base_url"] == "http://127.0.0.1:8000"
    finally:
        dialog.master.destroy()


def test_missing_managed_installation_changes_nothing_and_explains(tmp_path, tk_root):
    dialog = _dialog(tk_root, _manager(tmp_path, comfy_command=DESKTOP_COMMAND))
    try:
        with mock.patch("src.gui.engine_settings_dialog.messagebox.showwarning") as warn:
            assert dialog.use_managed_comfy_install() is False
        assert "no managed ComfyUI" in warn.call_args.args[1]
        assert dialog.comfy_command() == DESKTOP_COMMAND
        assert "comfy_command" not in dialog.collect_values()
    finally:
        dialog.master.destroy()


def test_unchanged_comfy_settings_are_never_rewritten(tmp_path, tk_root):
    dialog = _dialog(tk_root, _manager(tmp_path, comfy_command=DESKTOP_COMMAND))
    try:
        assert dialog.comfy_settings_changed() is False
        values = dialog.collect_values()
        for key in ("comfy_command", "comfy_workdir", "comfy_base_url"):
            assert key not in values
    finally:
        dialog.master.destroy()


def test_no_command_explains_external_only_and_clear_round_trips(tmp_path, tk_root):
    dialog = _dialog(tk_root, _manager(tmp_path, comfy_command=DESKTOP_COMMAND))
    try:
        dialog.clear_comfy_command()
        assert dialog.comfy_command() == []
        assert "No launch command" in dialog.comfy_status_text()
        assert dialog.add_comfy_flags_button.instate(["disabled"])
        assert dialog.clear_comfy_command_button.instate(["disabled"])
        values = dialog.collect_values()
        assert values["comfy_command"] == [] and values["comfy_workdir"] == ""
    finally:
        dialog.master.destroy()


def test_save_persists_the_change_and_says_a_restart_applies_it(tmp_path, tk_root):
    manager = _manager(
        tmp_path, comfy_command=DESKTOP_COMMAND, comfy_base_url="http://127.0.0.1:8000"
    )
    saved: list[dict] = []
    window = tk.Toplevel(tk_root)
    dialog = EngineSettingsDialog(
        window,
        config_manager=manager,
        managed_comfy_contract=CONTRACT,
        managed_comfy_detector=_missing,
        on_save=saved.append,
    )
    dialog.pack()
    dialog.add_required_comfy_flags()
    with mock.patch("src.gui.engine_settings_dialog.messagebox.showinfo") as info:
        dialog._handle_save()
    assert saved and saved[0]["comfy_command"][-1] == "--disable-pinned-memory"
    assert any("Restart StableNew" in call.args[1] for call in info.call_args_list)


def test_unreadable_contract_disables_managed_actions(tmp_path, tk_root, monkeypatch):
    from src.gui import engine_settings_dialog as module
    from src.video.managed_comfy_runtime import ManagedComfyContractError

    def _broken():
        raise ManagedComfyContractError("cannot read manifest")

    monkeypatch.setattr(module, "load_managed_comfy_contract", _broken)
    window = tk.Toplevel(tk_root)
    dialog = EngineSettingsDialog(
        window, config_manager=_manager(tmp_path, comfy_command=DESKTOP_COMMAND)
    )
    try:
        assert "contract unavailable" in dialog.comfy_status_text()
        assert dialog.use_managed_comfy_button.instate(["disabled"])
        assert dialog.use_managed_comfy_install() is False
    finally:
        window.destroy()
