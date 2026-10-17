from __future__ import annotations

import subprocess

import pytest

from src.utils import process_inspector_v2 as inspector

_BASE = (
    "0, NVIDIA GeForce RTX 4070 Ti, 100, 12282, 9000, 72, 226.89, 285.00, 2820, 10251, P2, 4, 16"
)
_EXTRA = "55, 4, 16, 0x0000000000000001, 0"


def _completed(
    stdout: str = "", stderr: str = "", returncode: int = 0
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["nvidia-smi"], returncode=returncode, stdout=stdout, stderr=stderr
    )


@pytest.fixture
def with_nvidia_smi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inspector.shutil, "which", lambda _name: "nvidia-smi")


def test_query_parses_base_and_additive_fields(monkeypatch, with_nvidia_smi) -> None:
    calls: list[list[str]] = []

    def _run(cmd, **_kwargs):
        calls.append(cmd)
        return _completed(f"{_BASE}, {_EXTRA}\n")

    monkeypatch.setattr(inspector.subprocess, "run", _run)

    result = inspector.query_gpu_survivor_snapshot()

    assert result.status == "ok"
    assert result.detail == ""
    device = result.snapshot["devices"][0]  # type: ignore[index]
    assert device["temperature_c"] == 72.0
    assert device["pcie_link_generation"] == 4
    assert device["utilization_memory_pct"] == 55.0
    assert device["pcie_link_generation_max"] == 4
    assert device["throttle_reasons_active"] == "0x0000000000000001"
    assert device["fan_speed_pct"] == 0.0
    assert len(calls) == 1


def test_query_falls_back_to_base_fields_when_the_driver_rejects_an_additive_field(
    monkeypatch, with_nvidia_smi
) -> None:
    outputs = iter(
        [
            _completed('Field "fan.speed" is not a valid field to query.\n', returncode=2),
            _completed(f"{_BASE}\n"),
        ]
    )
    monkeypatch.setattr(inspector.subprocess, "run", lambda *_a, **_k: next(outputs))

    result = inspector.query_gpu_survivor_snapshot()

    assert result.status == "ok"
    assert result.detail == "base_fields_only"
    device = result.snapshot["devices"][0]  # type: ignore[index]
    assert device["power_draw_w"] == 226.89
    assert "throttle_reasons_active" not in device


def test_query_reports_a_lost_gpu_with_the_driver_message(monkeypatch, with_nvidia_smi) -> None:
    message = (
        "Unable to determine the device handle for GPU0: 0000:01:00.0: GPU is lost.  "
        "Reboot the system to recover this GPU\n"
    )
    monkeypatch.setattr(inspector.subprocess, "run", lambda *_a, **_k: _completed(message))

    result = inspector.query_gpu_survivor_snapshot()

    assert result.snapshot is None
    assert result.status == "gpu_lost"
    assert "GPU is lost" in result.detail


def test_query_distinguishes_timeout_missing_tool_and_other_failures(monkeypatch) -> None:
    monkeypatch.setattr(inspector.shutil, "which", lambda _name: None)
    assert inspector.query_gpu_survivor_snapshot().status == "no_nvidia_smi"

    monkeypatch.setattr(inspector.shutil, "which", lambda _name: "nvidia-smi")

    def _timeout(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="nvidia-smi", timeout=1.0)

    monkeypatch.setattr(inspector.subprocess, "run", _timeout)
    assert inspector.query_gpu_survivor_snapshot().status == "timeout"

    monkeypatch.setattr(
        inspector.subprocess,
        "run",
        lambda *_a, **_k: _completed(stderr="driver exploded", returncode=9),
    )
    other = inspector.query_gpu_survivor_snapshot()
    assert (other.status, other.snapshot) == ("nonzero_exit", None)
    assert "driver exploded" in other.detail

    monkeypatch.setattr(
        inspector.subprocess, "run", lambda *_a, **_k: _completed("No devices were found\n")
    )
    assert inspector.query_gpu_survivor_snapshot().status == "no_devices"


def test_collect_snapshot_keeps_returning_only_the_snapshot(monkeypatch, with_nvidia_smi) -> None:
    monkeypatch.setattr(
        inspector.subprocess, "run", lambda *_a, **_k: _completed(f"{_BASE}, {_EXTRA}\n")
    )
    snapshot = inspector.collect_gpu_survivor_snapshot()
    assert snapshot is not None and snapshot["provider"] == "nvidia-smi"

    monkeypatch.setattr(
        inspector.subprocess, "run", lambda *_a, **_k: _completed("GPU is lost", returncode=0)
    )
    assert inspector.collect_gpu_survivor_snapshot() is None
