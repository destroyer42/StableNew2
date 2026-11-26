"""N11: when the managed Forge (WebUI) process dies, StableNew records why, and does not call its own stop a crash."""

from __future__ import annotations

import json
import logging
import time
from unittest import mock

import pytest

from src.api.process_exit_cause import describe_exit_cause
from src.api.webui_process_manager import (
    WebUIProcessConfig,
    WebUIProcessManager,
    clear_global_webui_process_manager,
    describe_startup_exit,
)
from tests.helpers.webui_mocks import DummyProcess


@pytest.fixture(autouse=True)
def _reset_global_webui_manager():
    clear_global_webui_process_manager()
    yield
    clear_global_webui_process_manager()


# -- decoding ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "words"),
    [
        (3221225477, ("0xC0000005", "access violation")),
        (-1073741819, ("0xC0000005", "access violation")),
        (0xC00000FD, ("0xC00000FD", "stack overflow")),
        (0xC0000409, ("0xC0000409", "fast fail")),
        (0xC000013A, ("0xC000013A", "Ctrl+C")),
        (0xC0000017, ("0xC0000017", "out of memory")),
        (0xE06D7363, ("0xE06D7363", "C++ exception")),
        (-9, ("signal 9", "SIGKILL")),
    ],
)
def test_windows_status_codes_and_signals_are_named(code, words):
    text = describe_exit_cause(code)
    for word in words:
        assert word in text


def test_the_last_python_exception_and_cuda_oom_are_named_from_stderr():
    stderr = "\n".join(
        [
            "Traceback (most recent call last):",
            '  File "launch.py", line 5, in <module>',
            "torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 2.00 GiB",
            "Press any key to continue . . .",
        ]
    )
    text = describe_exit_cause(1, stderr_tail=stderr)
    assert "exit code 1" in text
    assert "torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 2.00 GiB" in text

    plain = describe_exit_cause(
        1, stderr_tail="Traceback (most recent call last):\nValueError: bad flag --xformers"
    )
    assert "ValueError: bad flag --xformers" in plain


def test_a_clean_exit_and_an_unknown_code_are_described_plainly():
    assert "exited normally" in describe_exit_cause(0)
    unknown = describe_exit_cause(7)
    assert "exit code 7" in unknown and len(unknown) < 200
    assert describe_exit_cause(None) == ""


def test_the_description_is_one_bounded_line():
    text = describe_exit_cause(1, stderr_tail="RuntimeError: " + "x" * 5000 + "\nmore")
    assert "\n" not in text and len(text) <= 400


# -- the manager ---------------------------------------------------------------------------------------------------


def _manager(monkeypatch, process: DummyProcess) -> WebUIProcessManager:
    monkeypatch.setattr("subprocess.Popen", mock.Mock(return_value=process))
    monkeypatch.setattr(
        "src.api.webui_process_manager.build_process_container", mock.Mock(return_value=mock.Mock())
    )
    manager = WebUIProcessManager(
        WebUIProcessConfig(command=["python", "webui.py"], working_dir=".")
    )
    manager._start_orphan_monitor = mock.Mock()
    manager.start()
    return manager


def test_an_unexpected_exit_is_recorded_with_its_cause_once(monkeypatch, caplog):
    process = DummyProcess(pid=4242)
    manager = _manager(monkeypatch, process)
    manager._stderr_tail.append("torch.OutOfMemoryError: CUDA out of memory.")
    started = time.monotonic()
    process._returncode = 3221225477

    with caplog.at_level(logging.ERROR):
        first = manager.observe_unexpected_exit()
        again = manager.observe_unexpected_exit()

    assert first is not None and again is first
    assert first["pid"] == 4242 and first["exit_code"] == 3221225477
    assert "access violation" in first["exit_cause"] and "CUDA out of memory" in first["exit_cause"]
    records = [
        r
        for r in caplog.records
        if getattr(r, "json_payload", {}).get("event") == "webui_process_exited"
    ]
    assert len(records) == 1 and records[0].levelno == logging.ERROR
    assert records[0].json_payload["exit_cause"] == first["exit_cause"]
    assert manager.get_status()["last_exit_cause"] == first["exit_cause"]
    assert "access violation" in manager.exit_diagnostics()["exit_cause"]
    assert manager.unexpected_exit_since(started) is first
    assert manager.unexpected_exit_since(time.monotonic() + 60) is None
    json.dumps(first)  # a record is plain data


def test_a_deliberate_stop_is_not_reported_as_a_crash(monkeypatch, caplog):
    process = DummyProcess(pid=4343)
    manager = _manager(monkeypatch, process)
    monkeypatch.setattr(manager, "_owned_descendants", lambda _pid: [])

    def terminate():
        process._returncode = 1  # what TerminateProcess reports on Windows

    process.terminate = terminate
    with caplog.at_level(logging.INFO):
        assert manager.stop_webui(grace_seconds=0.2) is True

    assert manager.observe_unexpected_exit() is None
    assert not [
        r
        for r in caplog.records
        if getattr(r, "json_payload", {}).get("event") == "webui_process_exited"
    ]
    assert not [
        r for r in caplog.records if r.levelno >= logging.ERROR and "exited" in r.getMessage()
    ]
    assert manager.get_status()["last_exit_cause"] is None


def test_the_orphan_monitor_reports_a_natural_exit(monkeypatch):
    process = DummyProcess(pid=4444)
    manager = _manager(monkeypatch, process)
    process._returncode = 0xC00000FD
    monkeypatch.setattr(
        "src.utils.single_instance.SingleInstanceLock.is_gui_running", staticmethod(lambda: True)
    )

    manager._orphan_monitor_loop()

    assert "stack overflow" in manager.get_status()["last_exit_cause"]


def test_a_startup_exit_description_names_the_cause():
    text = describe_startup_exit(
        {
            "pid": 1,
            "exit_code": 0xC0000005,
            "runtime_identity": "forge_webui",
            "launch_profile": "default",
            "endpoint": "http://127.0.0.1:7860",
            "exit_cause": describe_exit_cause(0xC0000005),
        }
    )
    assert "access violation" in text
