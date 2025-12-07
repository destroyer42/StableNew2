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

    def poll(self) -> None:
        return None

    def wait(self, timeout: float | None = None) -> None:  # noqa: ARG003 - signature compatibility
        return None

    def terminate(self) -> None:
        pass

    def kill(self) -> None:
        pass


class _DummyThread:
    def __init__(self, *args, **kwargs) -> None:  # noqa: ARG002 - signature compatibility
        pass

    def start(self) -> None:
        pass


@pytest.mark.gui
def test_webui_launch_emits_proc_log(monkeypatch) -> None:
    monkeypatch.setattr("threading.Thread", _DummyThread)
    monkeypatch.setattr(
        "src.api.webui_process_manager.subprocess.Popen",
        lambda *args, **kwargs: _DummyProcess(),
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
        entries = list(window.gui_log_handler.get_entries())
        assert any("[PROC] launch" in entry["message"] for entry in entries)
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
        name="python",
        cmdline=("python", "example.py"),
        cwd="/tmp",
        create_time=0.0,
        env_markers=("STABLENEW_RUN_ID=abc",),
    )
    monkeypatch.setattr(
        pipeline_tab_frame_v2,
        "iter_stablenew_like_processes",
        lambda: [sample],
    )
    pipeline_tab._run_process_inspector()

    log_text = window.bottom_zone.log_text.get("1.0", "end")
    assert "[PROC] inspector" in log_text

    entries = list(window.gui_log_handler.get_entries())
    assert any("[PROC] inspector" in entry["message"] for entry in entries)

    try:
        root.destroy()
    except Exception:
        pass
