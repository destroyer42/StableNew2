from __future__ import annotations

import logging
import types

import pytest

from src.utils import debug_shutdown_inspector


def test_log_shutdown_state_records_threads(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("shutdown_inspector_threads")
    caplog.set_level(logging.INFO)
    debug_shutdown_inspector.log_shutdown_state(logger, "thread-check")
    text = caplog.text
    assert "Shutdown inspector (thread-check)" in text
    assert "Thread: name=" in text


def test_log_shutdown_state_reports_child_processes(caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeProcess:
        def children(self, recursive: bool) -> list[object]:
            return []

    fake_psutil = types.SimpleNamespace(Process=lambda pid=None: FakeProcess())
    monkeypatch.setattr(debug_shutdown_inspector, "psutil", fake_psutil)
    logger = logging.getLogger("shutdown_inspector_children")
    caplog.set_level(logging.INFO)
    debug_shutdown_inspector.log_shutdown_state(logger, "child-check")
    assert "Shutdown inspector: no child processes attached." in caplog.text
