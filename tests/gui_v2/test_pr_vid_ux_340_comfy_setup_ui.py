"""PR-VID-UX-340: the guided ComfyUI setup repair from the Video Workflow tab, and truthful Engine Settings saves.

Real Tk tab against the real controller with injected probes and a manual worker, and the real Engine Settings dialog
with injected launch facts and a fake detector. Nothing launches ComfyUI, probes a host or queues a job; the negative
assertions prove it.
"""

from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

import pytest

from src.controller.app_controller import AppController
from src.gui.engine_settings_dialog import EngineSettingsDialog
from src.gui.main_window_v2 import MainWindowV2
from src.utils.config import ConfigManager
from src.video.comfy_process_manager import ComfyProcessManager
from src.video.comfy_runtime_setup import ComfyLaunchFacts
from src.video.managed_comfy_runtime import (
    ManagedComfyDetection,
    build_managed_launch_command,
    load_managed_comfy_contract,
)
from src.video.workflow_preflight import PreflightProbes
from tests.gui_v2.test_pr_vid_ux_311_runtime_strip import _Probes, _tab

ANIMATE_ID = "wan_animate2_drive_i2v_v1"
PIN = "--disable-pinned-memory"
AUTO = "--disable-auto-launch"
BARE = ("python", "main.py")
GOOD = ("python", "main.py", PIN, AUTO)
CONTRACT = load_managed_comfy_contract()


class _LaunchProbes(_Probes):
    """``_Probes`` plus the launch evidence the real app supplies."""

    def __init__(self) -> None:
        super().__init__()
        self.launch: ComfyLaunchFacts | None = ComfyLaunchFacts(saved_command=GOOD)

    def build(self) -> PreflightProbes:
        probes = super().build()
        return PreflightProbes(**{**probes.__dict__, "launch": self.launch})


@pytest.fixture(autouse=True)
def _nothing_launches(monkeypatch):
    """The repair path must never start, stop or restart a ComfyUI."""

    calls: list[str] = []
    for name in ("start", "stop", "restart", "ensure_running"):
        monkeypatch.setattr(
            ComfyProcessManager, name, lambda *_a, _n=name, **_k: calls.append(_n) or False
        )
    return calls


def _select(tab, workflow_id: str) -> None:
    label = next(k for k, v in tab._workflow_map.items() if v["workflow_id"] == workflow_id)
    tab.workflow_var.set(label)
    tab._refresh_workspace_summary()
    tab.runtime_readiness_strip.request_refresh(force=True)


def _shown(widget) -> bool:
    return bool(widget.winfo_manager())


# --------------------------------------------------------------------------- the strip action


@pytest.mark.gui
def test_a_missing_launch_configuration_shows_fix_setup_and_it_opens_engine_settings(
    tk_root, tmp_path, monkeypatch, _nothing_launches
) -> None:
    probes = _LaunchProbes()
    probes.launch = ComfyLaunchFacts()
    tab, runner = _tab(tk_root, tmp_path, monkeypatch, probes)
    opened: list[dict[str, Any]] = []
    tab.app_controller.on_open_settings = lambda **options: opened.append(options)
    _select(tab, ANIMATE_ID)
    runner.drain()
    strip = tab.runtime_readiness_strip

    assert strip.last_view.repair_available
    assert (
        _shown(strip.fix_setup_button)
        and strip.fix_setup_button.cget("text") == "Fix ComfyUI Setup"
    )
    assert tab.queue_workflow_button.instate(["disabled"])

    strip.fix_setup_button.invoke()

    assert len(opened) == 1 and opened[0]["focus_video_runtime"] is True
    assert "no launch command is configured" in opened[0]["comfy_repair_reason"]
    assert tab.app_controller.job_service.calls == []  # diagnosis queued nothing
    assert _nothing_launches == []  # and started nothing

    runner.drain()
    opened[0][
        "on_closed"
    ]()  # the dialog closed: the strip re-reads, so a saved change shows at once
    assert len(runner.jobs) == 1
    runner.drain()


@pytest.mark.gui
def test_a_resource_blocker_shows_its_reason_and_no_fix_setup(
    tk_root, tmp_path, monkeypatch
) -> None:
    probes = _LaunchProbes()
    probes.ram = 4.0
    tab, runner = _tab(tk_root, tmp_path, monkeypatch, probes)
    runner.drain()
    strip = tab.runtime_readiness_strip

    assert not strip.last_view.repair_available and not _shown(strip.fix_setup_button)
    assert "System RAM" in tab.queue_block_reason_var.get()


@pytest.mark.gui
def test_a_saved_but_unapplied_change_is_a_restart_notice_not_a_fix_or_an_enabled_queue(
    tk_root, tmp_path, monkeypatch
) -> None:
    probes = _LaunchProbes()
    probes.launch = ComfyLaunchFacts(saved_command=GOOD, active_command=BARE)
    tab, runner = _tab(tk_root, tmp_path, monkeypatch, probes)
    _select(tab, ANIMATE_ID)
    tab.experimental_opt_in_var.set(
        True
    )  # the per-job opt-in is satisfied; only the runtime blocks
    tab._refresh_queue_gate()
    runner.drain()
    strip = tab.runtime_readiness_strip

    assert not _shown(strip.fix_setup_button)
    assert "must restart" in strip.notices_var.get() and _shown(strip.notices_label)
    assert tab.queue_workflow_button.instate(
        ["disabled"]
    )  # the active launcher still lacks the flag
    flags = next(row for row in strip.last_view.rows if row.label == "Launch flags")
    assert "not applied" in flags.detail and "Restart StableNew" in flags.fix


@pytest.mark.gui
def test_an_environment_override_is_named_and_no_fix_action_is_offered(
    tk_root, tmp_path, monkeypatch
) -> None:
    probes = _LaunchProbes()
    probes.launch = ComfyLaunchFacts(
        saved_command=GOOD, environment_command=BARE, active_command=BARE
    )
    tab, runner = _tab(tk_root, tmp_path, monkeypatch, probes)
    _select(tab, ANIMATE_ID)
    runner.drain()
    strip = tab.runtime_readiness_strip

    assert "STABLENEW_COMFY_COMMAND" in strip.notices_var.get()
    assert not _shown(strip.fix_setup_button)
    assert any("STABLENEW_COMFY_COMMAND" in row.detail for row in strip.last_view.rows)


@pytest.mark.gui
def test_an_ordinary_workflow_keeps_its_readiness_and_queue_behaviour(
    tk_root, tmp_path, monkeypatch
) -> None:
    probes = _LaunchProbes()
    probes.launch = ComfyLaunchFacts(
        saved_command=BARE, active_command=BARE
    )  # no special flags needed
    tab, runner = _tab(tk_root, tmp_path, monkeypatch, probes)
    runner.drain()
    strip = tab.runtime_readiness_strip

    assert not strip.last_view.repair_available and not _shown(strip.fix_setup_button)
    assert not _shown(strip.notices_label)
    assert tab.queue_workflow_button.instate(["!disabled"])
    assert tab.queue_block_reason_var.get() == ""


@pytest.mark.gui
def test_an_experimental_wan_workflow_still_needs_its_own_opt_in_which_defaults_off(
    tk_root, tmp_path, monkeypatch
) -> None:
    tab, runner = _tab(tk_root, tmp_path, monkeypatch, _LaunchProbes())
    _select(tab, ANIMATE_ID)
    runner.drain()

    assert tab.experimental_opt_in_var.get() is False
    assert tab.queue_workflow_button.instate(["disabled"])
    assert "experimental opt-in" in tab.queue_block_reason_var.get()
    _select(
        tab,
        next(
            v["workflow_id"] for v in tab._workflow_map.values() if v["workflow_id"] != ANIMATE_ID
        ),
    )
    assert tab.experimental_opt_in_var.get() is False  # never carried to another workflow


# --------------------------------------------------------------------------- Engine Settings dialog

DESKTOP = ["E:/desktop/python.exe", "E:/desktop/ComfyUI/main.py", "--port", "8000", AUTO]


def _manager(tmp_path: Path, **settings: Any) -> ConfigManager:
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
        problems=(
            "no managed ComfyUI v0.38.0 installation at C:/nowhere",
            "runtime folder missing: C:/nowhere/runtime/input",
        ),
    )


def _dialog(tk_root, manager, *, detector=_missing, facts=None, on_save=None, on_cancel=None):
    window = tk.Toplevel(tk_root)
    frame = EngineSettingsDialog(
        window,
        config_manager=manager,
        managed_comfy_contract=CONTRACT,
        managed_comfy_detector=detector,
        comfy_launch_facts=(lambda: facts) if facts is not None else (lambda: ComfyLaunchFacts()),
        on_save=on_save,
        on_cancel=on_cancel,
    )
    frame.pack(fill="both", expand=True)
    return frame


def test_the_repair_dialog_says_why_and_focuses_the_available_action(tmp_path, tk_root) -> None:
    dialog = _dialog(tk_root, _manager(tmp_path, comfy_command=DESKTOP))
    try:
        dialog.focus_video_runtime("Launch flags: the configured ComfyUI command is missing --x.")

        text = dialog.comfy_status_text()
        assert text.startswith(
            "Why you are here: Launch flags: the configured ComfyUI command is missing"
        )
        assert "Missing required flags: --disable-pinned-memory" in text
        assert dialog.add_comfy_flags_button.instate(["!disabled"])
    finally:
        dialog.master.destroy()


def test_add_required_flags_is_exactly_once_and_changes_nothing_else(
    tmp_path, tk_root, _nothing_launches
) -> None:
    dialog = _dialog(tk_root, _manager(tmp_path, comfy_command=DESKTOP))
    try:
        dialog.add_required_comfy_flags()
        dialog.add_required_comfy_flags()

        assert dialog.comfy_command() == [*DESKTOP, PIN]
        assert dialog.comfy_command().count(PIN) == 1
        assert _nothing_launches == []
    finally:
        dialog.master.destroy()


def test_a_missing_installation_lists_what_is_missing_inline_and_changes_nothing(
    tmp_path, tk_root
) -> None:
    dialog = _dialog(tk_root, _manager(tmp_path))
    try:
        with mock.patch("src.gui.engine_settings_dialog.messagebox.showwarning"):
            assert dialog.use_managed_comfy_install() is False

        text = dialog.comfy_status_text()
        assert "no managed ComfyUI v0.38.0 installation at C:/nowhere" in text
        assert "runtime folder missing" in text and "managed_comfy_runtime.md" in text
        assert dialog.comfy_command() == [] and not dialog.comfy_settings_changed()
    finally:
        dialog.master.destroy()


def test_use_managed_install_only_stages_the_settings(tmp_path, tk_root, _nothing_launches) -> None:
    manager = _manager(tmp_path, comfy_base_url="http://127.0.0.1:8000")
    dialog = _dialog(tk_root, manager, detector=_found(tmp_path))
    try:
        assert dialog.use_managed_comfy_install() is True
        command = dialog.comfy_command()

        assert command[command.index("--port") + 1] == "8000"
        assert PIN in command and AUTO in command
        assert (
            "comfy_command" not in manager.load_settings()
            or not manager.load_settings()["comfy_command"]
        )
        assert _nothing_launches == []  # staged in the dialog; nothing persisted or launched
    finally:
        dialog.master.destroy()


def test_cancel_persists_nothing_and_claims_no_repair(tmp_path, tk_root) -> None:
    manager = _manager(tmp_path, comfy_command=DESKTOP)
    saved: list[dict] = []
    cancelled: list[bool] = []
    dialog = _dialog(
        tk_root, manager, on_save=saved.append, on_cancel=lambda: cancelled.append(True)
    )
    dialog.add_required_comfy_flags()
    before = (tmp_path / "presets" / "settings.json").read_text(encoding="utf-8")

    with mock.patch("src.gui.engine_settings_dialog.messagebox.showinfo") as info:
        dialog._handle_cancel()

    assert cancelled == [True] and saved == [] and info.call_count == 0
    assert (tmp_path / "presets" / "settings.json").read_text(encoding="utf-8") == before
    assert manager.load_settings()["comfy_command"] == DESKTOP


def test_save_says_restart_required_and_starts_nothing(
    tmp_path, tk_root, _nothing_launches
) -> None:
    saved: list[dict] = []
    dialog = _dialog(tk_root, _manager(tmp_path, comfy_command=DESKTOP), on_save=saved.append)
    dialog.add_required_comfy_flags()

    with (
        mock.patch("src.gui.engine_settings_dialog.messagebox.showinfo") as info,
        mock.patch("src.gui.engine_settings_dialog.messagebox.showerror") as error,
    ):
        dialog._handle_save()

    assert saved[0]["comfy_command"] == [*DESKTOP, PIN]
    assert any("Restart StableNew" in call.args[1] for call in info.call_args_list)
    assert error.call_count == 0 and _nothing_launches == []


def test_save_under_an_environment_override_says_the_saved_command_will_not_be_used(
    tmp_path, tk_root
) -> None:
    facts = ComfyLaunchFacts(saved_command=tuple(DESKTOP), environment_command=BARE)
    dialog = _dialog(
        tk_root, _manager(tmp_path, comfy_command=DESKTOP), facts=facts, on_save=lambda _v: None
    )
    dialog.add_required_comfy_flags()

    with mock.patch("src.gui.engine_settings_dialog.messagebox.showinfo") as info:
        dialog._handle_save()

    message = " ".join(call.args[1] for call in info.call_args_list)
    assert "STABLENEW_COMFY_COMMAND" in message and "outside StableNew" in message


def test_a_failed_save_callback_is_reported_and_the_dialog_stays_open(tmp_path, tk_root) -> None:
    def _fail(_values: dict) -> None:
        raise RuntimeError("Settings could not be written to disk.")

    dialog = _dialog(tk_root, _manager(tmp_path, comfy_command=DESKTOP), on_save=_fail)
    dialog.add_required_comfy_flags()

    with (
        mock.patch("src.gui.engine_settings_dialog.messagebox.showinfo") as info,
        mock.patch("src.gui.engine_settings_dialog.messagebox.showerror") as error,
    ):
        dialog._handle_save()

    try:
        message = dialog._save_error_var.get()
        assert "not saved" in message and "could not be written" in message
        assert error.call_count == 0  # inline and non-modal: nothing blocks waiting for an acknowledgement
        assert info.call_count == 0  # no "restart to apply" claim for a change that was not saved
        assert dialog.master.winfo_exists()
        assert dialog.comfy_command() == [*DESKTOP, PIN]  # the operator's staged edit is kept
    finally:
        dialog.master.destroy()


# --------------------------------------------------------------------------- the save path


class _FailingConfig:
    def update_settings(self, _updates: dict) -> bool:
        return False

    def save_settings(self, *_a: Any, **_k: Any) -> bool:
        raise AssertionError("a failed update must not be followed by a second write")


def test_the_controller_raises_when_settings_cannot_be_persisted() -> None:
    controller = SimpleNamespace(_config_manager=_FailingConfig())

    with pytest.raises(RuntimeError, match="could not be written"):
        AppController.on_settings_saved(controller, {"comfy_command": ["x"]})


def test_the_main_window_does_not_swallow_a_failed_save() -> None:
    destroyed: list[bool] = []
    dialog = SimpleNamespace(destroy=lambda: destroyed.append(True))

    def _boom(_values: dict) -> None:
        raise RuntimeError("disk full")

    window = SimpleNamespace(
        app_state=SimpleNamespace(controller=SimpleNamespace(on_settings_saved=_boom))
    )
    with pytest.raises(RuntimeError, match="disk full"):
        MainWindowV2._handle_settings_saved(window, {"x": 1}, dialog)
    assert destroyed == []  # the dialog is left for the operator to retry or cancel


def test_the_controller_forwards_dialog_options_to_the_one_settings_dialog() -> None:
    calls: list[dict[str, Any]] = []
    window = SimpleNamespace(open_engine_settings_dialog=lambda **kw: calls.append(kw))
    controller = SimpleNamespace(
        _append_log=lambda *_a: None, main_window=window, _config_manager="cm"
    )

    AppController.on_open_settings(controller)
    AppController.on_open_settings(controller, focus_video_runtime=True, comfy_repair_reason="why")

    assert calls == [
        {"config_manager": "cm"},
        {"config_manager": "cm", "focus_video_runtime": True, "comfy_repair_reason": "why"},
    ]
