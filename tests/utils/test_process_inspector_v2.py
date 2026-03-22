"""Tests for the process inspector helpers."""

from __future__ import annotations

import pytest

from src.utils import process_inspector_v2


class _DummyProcess:
    def __init__(self, info: dict[str, object]) -> None:
        self.info = info

    def cmdline(self) -> list[str]:
        return list(self.info.get("cmdline") or [])

    def memory_info(self):
        class _MemInfo:
            def __init__(self, rss: float) -> None:
                self.rss = rss

        rss = float(self.info.get("rss") or 0.0)
        return _MemInfo(rss)

    def environ(self) -> dict[str, str]:
        return dict(self.info.get("environ") or {})


def _require_psutil() -> None:
    if process_inspector_v2.psutil is None:
        pytest.skip("psutil unavailable in this environment")


def test_iter_python_processes_returns_py_only(monkeypatch) -> None:
    _require_psutil()

    python_info = {
        "pid": 42,
        "name": "python.exe",
        "cmdline": ["python", "some_script.py"],
        "cwd": str(process_inspector_v2.REPO_ROOT),
        "create_time": 1.0,
        "rss": 0.0,
        "environ": {"STABLENEW_RUN_ID": "run-1"},
    }
    other_info = {
        "pid": 99,
        "name": "cmd.exe",
        "cmdline": ["cmd", "/C", "echo"],
        "cwd": "C:/Windows",
        "create_time": 2.0,
        "rss": 0.0,
        "environ": {},
    }

    monkeypatch.setattr(
        process_inspector_v2.psutil,
        "process_iter",
        lambda attrs=None: iter([_DummyProcess(python_info), _DummyProcess(other_info)]),
    )

    results = list(process_inspector_v2.iter_python_processes())

    assert len(results) == 1
    result = results[0]
    assert result.pid == 42
    assert "run-1" in result.env_markers[0]


def test_iter_stablenew_like_processes_filters(monkeypatch) -> None:
    python_one = process_inspector_v2.ProcessInfo(
        pid=1,
        parent_pid=None,
        name="python",
        cmdline=("python", "some_script.py"),
        cwd=str(process_inspector_v2.REPO_ROOT),
        create_time=0.0,
        rss_mb=12.0,
        env_markers=(),
    )
    python_two = process_inspector_v2.ProcessInfo(
        pid=2,
        parent_pid=1,
        name="python",
        cmdline=("python", "a1111_upscale_folder.py"),
        cwd="/usr/bin",
        create_time=0.0,
        rss_mb=8.0,
        env_markers=(),
    )

    monkeypatch.setattr(
        process_inspector_v2,
        "iter_python_processes",
        lambda: iter([python_one, python_two]),
    )

    result = list(process_inspector_v2.iter_stablenew_like_processes())

    assert result == [python_one, python_two]


def test_collect_process_risk_snapshot_ignores_single_main_process_high_rss(monkeypatch) -> None:
    main_process = process_inspector_v2.ProcessInfo(
        pid=1,
        parent_pid=None,
        name="python.exe",
        cmdline=("python", "-m", "src.main"),
        cwd=str(process_inspector_v2.REPO_ROOT),
        create_time=0.0,
        rss_mb=1200.0,
        env_markers=(),
    )

    monkeypatch.setattr(
        process_inspector_v2,
        "iter_stablenew_like_processes",
        lambda: iter([main_process]),
    )

    result = process_inspector_v2.collect_process_risk_snapshot()

    assert result["status"] == "normal"
    assert result["main_process_count"] == 1
    assert result["suspicious_processes"] == []


def test_collect_process_risk_snapshot_marks_duplicate_main_processes_critical(monkeypatch) -> None:
    main_a = process_inspector_v2.ProcessInfo(
        pid=1,
        parent_pid=None,
        name="python.exe",
        cmdline=("python", "-m", "src.main"),
        cwd=str(process_inspector_v2.REPO_ROOT),
        create_time=0.0,
        rss_mb=950.0,
        env_markers=(),
    )
    main_b = process_inspector_v2.ProcessInfo(
        pid=2,
        parent_pid=1,
        name="python.exe",
        cmdline=("python", "-m", "src.main"),
        cwd=str(process_inspector_v2.REPO_ROOT),
        create_time=0.0,
        rss_mb=940.0,
        env_markers=(),
    )

    monkeypatch.setattr(
        process_inspector_v2,
        "iter_stablenew_like_processes",
        lambda: iter([main_a, main_b]),
    )

    result = process_inspector_v2.collect_process_risk_snapshot()

    assert result["status"] == "critical"
    assert result["main_process_count"] == 2
    assert len(result["suspicious_processes"]) == 2


def test_collect_process_risk_snapshot_ignores_tiny_duplicate_main_process(monkeypatch) -> None:
    main_a = process_inspector_v2.ProcessInfo(
        pid=1,
        parent_pid=None,
        name="python.exe",
        cmdline=("python", "-m", "src.main"),
        cwd=str(process_inspector_v2.REPO_ROOT),
        create_time=0.0,
        rss_mb=900.0,
        env_markers=(),
    )
    main_b = process_inspector_v2.ProcessInfo(
        pid=2,
        parent_pid=1,
        name="python.exe",
        cmdline=("python", "-m", "src.main"),
        cwd=str(process_inspector_v2.REPO_ROOT),
        create_time=0.0,
        rss_mb=8.0,
        env_markers=(),
    )

    monkeypatch.setattr(
        process_inspector_v2,
        "iter_stablenew_like_processes",
        lambda: iter([main_a, main_b]),
    )

    result = process_inspector_v2.collect_process_risk_snapshot()

    assert result["status"] == "normal"
    assert result["main_process_count"] == 2
    assert result["significant_main_process_count"] == 1
    assert result["suspicious_processes"] == []
