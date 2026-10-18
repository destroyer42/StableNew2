"""WebUI per-launch output logs are bounded (audit E6): repository-anchored, rotated and pruned."""

from __future__ import annotations

import io
import os
import types
from pathlib import Path

import pytest

from src.api import webui_process_manager as wpm
from src.api.webui_process_manager import (
    WebUIProcessConfig,
    WebUIProcessManager,
    clear_global_webui_process_manager,
)


@pytest.fixture(autouse=True)
def _reset_global_webui_manager():
    clear_global_webui_process_manager()
    yield
    clear_global_webui_process_manager()


def _manager_with_streams(stdout: str, stderr: str) -> WebUIProcessManager:
    manager = WebUIProcessManager(WebUIProcessConfig(command=["python", "webui.py"]))
    manager._process = types.SimpleNamespace(stdout=io.StringIO(stdout), stderr=io.StringIO(stderr))
    return manager


def test_log_directory_is_anchored_to_the_repository_not_the_working_directory() -> None:
    # The conftest redirects the module constant under pytest; the production value is what matters here.
    text = Path(wpm.__file__).read_text(encoding="utf-8")
    assert '_WEBUI_LOG_DIR = Path(__file__).resolve().parents[2] / "logs" / "webui"' in text
    assert 'Path("logs") / "webui"' not in text


def test_output_capture_writes_per_launch_logs_and_tails(tmp_path: Path) -> None:
    manager = _manager_with_streams("out one\nout two\n", "err one\n")
    manager._start_output_capture("sess1")
    manager._stdout_thread.join(timeout=5)
    manager._stderr_thread.join(timeout=5)
    manager._stop_output_capture()

    log_dir = wpm._WEBUI_LOG_DIR
    assert (log_dir / "webui_stdout_sess1.log").read_text(encoding="utf-8").splitlines() == [
        "out one",
        "out two",
    ]
    assert (log_dir / "webui_stderr_sess1.log").read_text(encoding="utf-8").splitlines() == [
        "err one"
    ]
    assert list(manager._stdout_tail) == ["out one", "out two"]


def test_output_capture_prunes_old_launch_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    log_dir = wpm._WEBUI_LOG_DIR
    log_dir.mkdir(parents=True)
    for index in range(12):
        for stream in ("stdout", "stderr"):
            path = log_dir / f"webui_{stream}_old{index:02d}.log"
            path.write_text("x", encoding="utf-8")
            os.utime(path, (1_000_000 + index, 1_000_000 + index))
    manager = _manager_with_streams("", "")
    manager._start_output_capture("new")
    manager._stop_output_capture()

    stdout_logs = sorted(p.name for p in log_dir.glob("webui_stdout_*.log"))
    assert len(stdout_logs) <= wpm.WEBUI_LOG_LAUNCHES_KEPT
    assert "webui_stdout_old11.log" in stdout_logs  # the newest survive
    assert "webui_stdout_old00.log" not in stdout_logs
