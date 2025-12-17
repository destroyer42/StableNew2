import types

import pytest

from src.controller import process_auto_scanner_service as scanner_module
from src.controller.process_auto_scanner_service import (
    ProcessAutoScannerConfig,
    ProcessAutoScannerService,
)


class _FakeProcess:
    def __init__(self, pid: int, name: str, cwd: str, memory_mb: float, create_time: float):
        self.pid = pid
        self._name = name
        self._cwd = cwd
        self._memory_mb = memory_mb
        self._create_time = create_time
        self._terminated = False
        self._killed = False

    def name(self) -> str:
        return self._name

    def cwd(self) -> str:
        return self._cwd

    def create_time(self) -> float:
        return self._create_time

    def memory_info(self) -> types.SimpleNamespace:
        return types.SimpleNamespace(rss=int(self._memory_mb * 1024 * 1024))

    def terminate(self) -> None:
        self._terminated = True

    def kill(self) -> None:
        self._killed = True

    def wait(self, timeout: float | None = None) -> None:
        return


def _make_psutil(processes: list[_FakeProcess]) -> types.SimpleNamespace:
    def iter_proc(attrs=None):
        return iter(processes)

    return types.SimpleNamespace(process_iter=iter_proc)


@pytest.fixture(autouse=True)
def patch_time(monkeypatch):
    monkeypatch.setattr(
        scanner_module, "time", types.SimpleNamespace(time=lambda: 1000.0, sleep=lambda _: None)
    )
    yield


def test_auto_scanner_kills_candidate(monkeypatch):
    fake = _FakeProcess(
        pid=9999,
        name="python.exe",
        cwd="/tmp",
        memory_mb=1500.0,
        create_time=0.0,
    )
    service = ProcessAutoScannerService(
        config=ProcessAutoScannerConfig(idle_threshold_sec=0.0, memory_threshold_mb=100.0),
        start_thread=False,
    )
    monkeypatch.setattr(service, "_psutil", _make_psutil([fake]))
    summary = service.scan_once()
    assert summary.scanned == 1
    assert len(summary.killed) == 1


def test_auto_scanner_respects_protected(monkeypatch):
    fake = _FakeProcess(
        pid=8888,
        name="python.exe",
        cwd="/tmp",
        memory_mb=2000.0,
        create_time=0.0,
    )
    service = ProcessAutoScannerService(
        config=ProcessAutoScannerConfig(idle_threshold_sec=0.0, memory_threshold_mb=100.0),
        protected_pids=lambda: {8888},
        start_thread=False,
    )
    monkeypatch.setattr(service, "_psutil", _make_psutil([fake]))
    summary = service.scan_once()
    assert summary.scanned == 0 or len(summary.killed) == 0
