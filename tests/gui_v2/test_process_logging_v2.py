"""GUI-level tests for the Phase 0 process logging helpers."""

from __future__ import annotations

import io

import pytest

from src.api.webui_process_manager import WebUIProcessConfig, WebUIProcessManager
from src.app_factory import build_v2_app
from src.gui.views import pipeline_tab_frame_v2
from src.utils import process_inspector_v2


class _DummyProcess:
    def __init__(self) -> None:
        self.pid = 12345
        self.stdout = io.BytesIO(b"")
        self.stderr = io.BytesIO(b"")
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int | None:  # noqa: ARG002 - signature compatibility
        return self.returncode

    # A real process exits once terminated/killed; without this the manager's stop path polls its
    # full graceful-exit window (10 s) during app teardown.
    def terminate(self) -> None:
        self.returncode = 0

    def kill(self) -> None:
        self.returncode = -9


class _DummyThread:
    def __init__(self, *args, **kwargs) -> None:  # noqa: ARG002 - signature compatibility
        self.daemon = bool(kwargs.get("daemon", False))
        self._alive = False

    def start(self) -> None:
        self._alive = True

    def is_alive(self) -> bool:
        return self._alive

    def join(self, timeout: float | None = None) -> None:  # noqa: ARG002 - signature compatibility
        self._alive = False


@pytest.mark.gui
def test_webui_launch_emits_proc_log(monkeypatch) -> None:
    monkeypatch.setattr("threading.Thread", _DummyThread)
    monkeypatch.setattr(
        "src.api.webui_process_manager.subprocess.Popen",
        lambda *args, **kwargs: _DummyProcess(),
    )

    # Hermetic launch: no loopback probe for a running StableNew GUI (a closed port costs ~1 s on
    # Windows and a live GUI would change the outcome) and no probe of the WebUI port at startup.
    monkeypatch.setattr(
        "src.utils.single_instance.SingleInstanceLock.is_gui_running",
        staticmethod(lambda *args, **kwargs: True),
    )
    monkeypatch.setattr(
        "src.controller.webui_connection_controller.WebUIConnectionController.is_port_listening",
        lambda self, *args, **kwargs: False,
    )

    config = WebUIProcessConfig(command=["python", "-m", "http.server"], working_dir=".")
    manager = WebUIProcessManager(config)
    monkeypatch.setattr(manager, "check_health", lambda: False)

    try:
        root, _, controller, window = build_v2_app(webui_manager=manager)
    except Exception as exc:  # pragma: no cover - Tk unavailable
        pytest.skip(f"Tkinter not available: {exc}")
        return

    try:
        controller.on_launch_webui_clicked()
        window.app_state.flush_now()
        root.update()
        entries = list(window.gui_log_handler.get_entries())
        log_text = window.bottom_zone.log_text.get("1.0", "end")
        assert "[webui] Launch requested by user." in log_text
        assert any(
            (
                "[webui] Launch requested by user." in entry["message"]
                or "WebUI launch profile resolved" in entry["message"]
            )
            for entry in entries
        )
    finally:
        try:
            root.destroy()
        except Exception:
            pass


@pytest.mark.gui
def test_process_inspector_shortcut_logs(monkeypatch) -> None:
    try:
        root, _, controller, window = build_v2_app()
    except Exception as exc:  # pragma: no cover - Tk unavailable
        pytest.skip(f"Tkinter not available: {exc}")
        return

    pipeline_tab = window.pipeline_tab
    sample = process_inspector_v2.ProcessInfo(
        pid=99,
        parent_pid=12,
        name="python",
        cmdline=("python", "example.py"),
        cwd="/tmp",
        create_time=0.0,
        rss_mb=128.0,
        env_markers=("STABLENEW_RUN_ID=abc",),
    )
    monkeypatch.setattr(
        pipeline_tab_frame_v2,
        "iter_stablenew_like_processes",
        lambda: [sample],
    )
    pipeline_tab._run_process_inspector()
    window.app_state.flush_now()
    root.update()

    log_text = window.bottom_zone.log_text.get("1.0", "end")
    assert "[PROC] inspector" in log_text

    entries = list(window.gui_log_handler.get_entries())
    assert any("[PROC] inspector" in entry["message"] for entry in entries)

    try:
        root.destroy()
    except Exception:
        pass
