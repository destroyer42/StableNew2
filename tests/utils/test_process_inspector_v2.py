"""Tests for the Phase 0 process inspector helpers."""

from __future__ import annotations

import pytest

from src.utils import process_inspector_v2


class _DummyProcess:
    def __init__(self, info: dict[str, object]) -> None:
        self.info = info


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
        "environ": {"STABLENEW_RUN_ID": "run-1"},
    }
    other_info = {
        "pid": 99,
        "name": "cmd.exe",
        "cmdline": ["cmd", "/C", "echo"],
        "cwd": "C:/Windows",
        "create_time": 2.0,
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
        name="python",
        cmdline=("python", "some_script.py"),
        cwd=str(process_inspector_v2.REPO_ROOT),
        create_time=0.0,
        env_markers=(),
    )
    python_two = process_inspector_v2.ProcessInfo(
        pid=2,
        name="python",
        cmdline=("python", "a1111_upscale_folder.py"),
        cwd="/usr/bin",
        create_time=0.0,
        env_markers=(),
    )

    monkeypatch.setattr(
        process_inspector_v2,
        "iter_python_processes",
        lambda: iter([python_one, python_two]),
    )

    result = list(process_inspector_v2.iter_stablenew_like_processes())

    assert result == [python_one, python_two]
