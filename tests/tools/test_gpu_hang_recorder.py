"""DIAG-GPU-150: the NVML hang recorder, with a scripted fake provider (no GPU, no NVML, no real clock)."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tools.diagnostics import gpu_hang_recorder as ghr
from tools.diagnostics.gpu_hang_recorder import NvmlError, Recorder


class FakeProvider:
    """Answers from a script: each ``tick`` yields the values or the error for every metric."""

    def __init__(self, script: list[dict[str, Any] | NvmlError] | None = None) -> None:
        self.script = list(script or [])
        self.opened = 0
        self.closed = 0
        self.open_errors: list[NvmlError] = []
        self.on_call: Callable[[str | None], None] = lambda _name: None
        self.block = threading.Event()
        self.block_on: str | None = None
        self.throughput_calls = 0
        self._current: dict[str, Any] | NvmlError = {}

    def open(self) -> None:
        self.opened += 1
        if self.open_errors:
            raise self.open_errors.pop(0)

    def close(self) -> None:
        self.closed += 1

    def describe(self) -> dict[str, Any]:
        return {"name": "Fake RTX", "driver_version": "0.0", "pci_bus_id": "0000:01:00.0"}

    def _advance(self) -> None:
        if self.script:
            self._current = self.script.pop(0)

    def metrics(self) -> dict[str, Callable[[], float | int | str]]:
        keys = ("util_gpu_pct", "power_w", "temp_c", "pcie_gen", "pcie_replay", "fan_pct")

        def make(key: str) -> Callable[[], float | int | str]:
            def read() -> float | int | str:
                if key == keys[0]:
                    self._advance()  # one scripted step per sample, taken at the first metric
                self.on_call(f"read_{key}")
                try:
                    if self.block_on == f"read_{key}":
                        self.block.wait(timeout=5)
                    current = self._current
                    if isinstance(current, NvmlError):
                        raise current
                    if key in current.get("fail", {}):
                        raise NvmlError(f"read_{key}", current["fail"][key])
                    return current.get(key, 1)  # type: ignore[no-any-return]
                finally:
                    self.on_call(None)

            return read

        return {key: make(key) for key in keys}

    def pcie_throughput(self) -> dict[str, int]:
        self.throughput_calls += 1
        return {"pcie_tx_kbps": 1, "pcie_rx_kbps": 2}


class ManualClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _recorder(
    tmp_path: Path, provider: FakeProvider, **kwargs: Any
) -> tuple[Recorder, ManualClock, list[int]]:
    clock = ManualClock()
    synced: list[int] = []
    recorder = Recorder(
        provider,
        out_dir=tmp_path,
        interval_ms=50,
        clock=clock,
        sleep=clock.sleep,
        fsync=synced.append,
        host_reader=lambda: {
            "commit_used_mb": 40000,
            "commit_limit_mb": 56000,
            "phys_avail_mb": 5000,
        },
        stamp="20261021T000000Z",
        **kwargs,
    )
    return recorder, clock, synced


def _records(directory: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in sorted(directory.glob("gpu_hang_recorder_*.jsonl")):
        out.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
    return out


def test_header_then_samples_carry_latency_pcie_and_host_state(tmp_path: Path) -> None:
    provider = FakeProvider(
        [{"util_gpu_pct": 97, "pcie_gen": 4, "pcie_replay": 0, "power_w": 244.5}]
    )
    recorder, _clock, synced = _recorder(tmp_path, provider)

    recorder.run(duration_s=0.2)

    records = _records(tmp_path)
    assert records[0]["event"] == "header"
    assert records[0]["schema"] == ghr.SCHEMA and records[0]["interval_ms"] == 50.0
    assert records[0]["device"]["pci_bus_id"] == "0000:01:00.0"
    samples = [r for r in records if "seq" in r and r.get("status")]
    assert len(samples) >= 3
    first = samples[0]
    assert first["status"] == "ok" and first["util_gpu_pct"] == 97 and first["pcie_gen"] == 4
    assert (
        first["pcie_replay"] == 0
        and "read_ms" in first
        and first["host"]["commit_limit_mb"] == 56000
    )
    assert records[-1]["event"] == "stopped"
    assert synced, "records must be fsynced, not only flushed"
    assert provider.opened == 1 and provider.closed == 1


def test_pcie_throughput_is_sampled_at_its_own_slower_rate(tmp_path: Path) -> None:
    provider = FakeProvider([{"util_gpu_pct": 1}])
    recorder, _clock, _ = _recorder(
        tmp_path, provider, pcie_throughput_hz=2.0
    )  # every 10th sample at 20 Hz

    recorder.run(duration_s=1.0)

    samples = [r for r in _records(tmp_path) if r.get("status")]
    with_tp = [r for r in samples if "pcie_tx_kbps" in r]
    assert provider.throughput_calls == len(with_tp) >= 1
    assert len(with_tp) < len(samples) / 4
    off, _c, _ = _recorder(tmp_path / "off", FakeProvider([{}]), pcie_throughput_hz=0)
    off.run(duration_s=0.5)
    assert not any("pcie_tx_kbps" in r for r in _records(tmp_path / "off"))


def test_an_unsupported_metric_is_recorded_without_failing_the_sample(tmp_path: Path) -> None:
    provider = FakeProvider(
        [{"util_gpu_pct": 50, "fail": {"fan_pct": ghr.NVML_ERROR_NOT_SUPPORTED}}]
    )
    recorder, _c, _ = _recorder(tmp_path, provider)

    sample = (
        recorder.sample_once() if recorder.start() is None else {}
    )  # start() opens the provider

    recorder.close()
    assert sample["status"] == "partial"
    assert sample["errors"] == {"fan_pct": ghr.NVML_ERROR_NOT_SUPPORTED}
    assert sample["util_gpu_pct"] == 50 and "lost_code" not in sample


def test_gpu_lost_writes_an_incident_with_the_preceding_window_and_keeps_probing(
    tmp_path: Path,
) -> None:
    lost = NvmlError("nvmlDeviceGetUtilizationRates", ghr.NVML_ERROR_GPU_IS_LOST, "GPU is lost")
    provider = FakeProvider(
        [{"util_gpu_pct": 99, "pcie_replay": 3}] * 5 + [lost, lost, {"util_gpu_pct": 0}]
    )
    recorder, _clock, _ = _recorder(tmp_path, provider)

    recorder.run(duration_s=3.0)

    records = _records(tmp_path)
    events = [r["event"] for r in records if "event" in r]
    assert events.count("gpu_lost") == 1, "one incident per loss, not one per lost sample"
    assert "gpu_back" in events and events[-1] == "stopped"
    incidents = sorted(tmp_path.glob("incident_*.json"))
    assert len(incidents) == 1
    incident = json.loads(incidents[0].read_text(encoding="utf-8"))
    assert (
        incident["trigger"]["status"] == "lost"
        and incident["trigger"]["lost_code"] == ghr.NVML_ERROR_GPU_IS_LOST
    )
    assert len(incident["samples"]) == 5 and all(s["pcie_replay"] == 3 for s in incident["samples"])
    assert incident["host"]["commit_used_mb"] == 40000
    lost_event = next(r for r in records if r.get("event") == "gpu_lost")
    assert lost_event["incident_file"] == incidents[0].name


def test_all_core_metrics_failing_together_is_a_loss_even_without_a_lost_code(
    tmp_path: Path,
) -> None:
    unknown = NvmlError("anything", 999, "Unknown Error")
    provider = FakeProvider([unknown])
    recorder, _c, _ = _recorder(tmp_path, provider)
    recorder.start()

    sample = recorder.sample_once()
    recorder.close()

    assert sample["status"] == "lost" and sample["lost_code"] == 999


def test_a_failed_open_probes_until_the_device_appears(tmp_path: Path) -> None:
    provider = FakeProvider([{"util_gpu_pct": 10}])
    provider.open_errors = [
        NvmlError("nvmlDeviceGetHandleByIndex_v2", ghr.NVML_ERROR_GPU_IS_LOST, "GPU is lost"),
        NvmlError("nvmlDeviceGetHandleByIndex_v2", ghr.NVML_ERROR_GPU_IS_LOST, "GPU is lost"),
    ]
    recorder, _c, _ = _recorder(tmp_path, provider)

    recorder.run(duration_s=5.0)

    records = _records(tmp_path)
    assert records[0]["device"]["open_error_code"] == ghr.NVML_ERROR_GPU_IS_LOST
    assert [r for r in records if r.get("status") == "lost"], (
        "lost records while the device is absent"
    )
    back = [r for r in records if r.get("event") == "gpu_back"]
    assert len(back) == 1 and back[0]["device"]["name"] == "Fake RTX"
    assert any(r.get("status") == "ok" for r in records)
    assert provider.opened == 3


def test_a_slow_read_is_flagged(tmp_path: Path) -> None:
    clock = ManualClock()

    class SlowProvider(FakeProvider):
        def metrics(self) -> dict[str, Callable[[], float | int | str]]:
            base = super().metrics()

            def slow() -> float | int | str:
                clock.now += 0.4  # 400 ms inside the driver
                return base["util_gpu_pct"]()

            return {**base, "util_gpu_pct": slow}

    recorder = Recorder(
        SlowProvider([{}]),
        out_dir=tmp_path,
        clock=clock,
        sleep=clock.sleep,
        fsync=lambda _fd: None,
        host_reader=dict,
        stamp="s",
    )
    recorder.run(duration_s=0.01)

    slow = [r for r in _records(tmp_path) if r.get("event") == "slow_read"]
    assert slow and slow[0]["read_ms"] >= ghr.SLOW_READ_MS


def test_a_blocked_nvml_call_is_named_by_the_watchdog_while_the_sampler_is_stuck(
    tmp_path: Path,
) -> None:
    provider = FakeProvider([{"util_gpu_pct": 5}])
    provider.block_on = "read_power_w"
    recorder = Recorder(
        provider,
        out_dir=tmp_path,
        interval_ms=20,
        fsync=lambda _fd: None,
        host_reader=lambda: {"commit_used_mb": 1},
        stamp="w",
        blocked_after_ms=100,
    )
    worker = threading.Thread(target=lambda: recorder.run(duration_s=0.5), daemon=True)
    worker.start()
    deadline = time.monotonic() + 5.0
    blocked: list[dict[str, Any]] = []
    while time.monotonic() < deadline and not blocked:
        blocked = [r for r in _records(tmp_path) if r.get("event") == "nvml_call_blocked"]
        time.sleep(0.05)
    provider.block.set()
    worker.join(timeout=5)

    assert blocked, "the watchdog must report the hang while the sampling thread is blocked"
    assert blocked[0]["call"] == "read_power_w" and blocked[0]["blocked_ms"] >= 100
    assert blocked[0]["host"]["commit_used_mb"] == 1
    assert not worker.is_alive()


def test_files_rotate_and_old_ones_are_pruned(tmp_path: Path) -> None:
    provider = FakeProvider([{"util_gpu_pct": 1}])
    recorder, _c, _ = _recorder(
        tmp_path, provider, max_file_mb=0.002, keep_files=3
    )  # ~2 KB per file

    recorder.run(duration_s=3.0)

    files = sorted(tmp_path.glob("gpu_hang_recorder_*.jsonl"))
    assert len(files) == 3, "older files are pruned to the retention limit"
    assert files[-1].name.endswith("_001.jsonl") is False
    continued = json.loads(files[-1].read_text(encoding="utf-8").splitlines()[0])
    assert continued["event"] == "header" and continued["continued"] is True


def test_only_one_recorder_may_hold_the_lock(tmp_path: Path) -> None:
    first = ghr.InstanceLock(tmp_path / ".recorder.lock")
    second = ghr.InstanceLock(tmp_path / ".recorder.lock")

    assert first.acquire() is True
    assert second.acquire() is False
    first.release()
    assert second.acquire() is True
    second.release()


def test_interval_is_clamped_to_the_minimum(tmp_path: Path) -> None:
    recorder = Recorder(FakeProvider([{}]), out_dir=tmp_path, interval_ms=1, stamp="c")
    assert recorder._interval_s == pytest.approx(ghr.MIN_INTERVAL_MS / 1000.0)


def test_probe_reports_a_lost_device_and_a_healthy_one() -> None:
    lost = FakeProvider()
    lost.open_errors = [
        NvmlError("nvmlDeviceGetHandleByIndex_v2", ghr.NVML_ERROR_GPU_IS_LOST, "GPU is lost")
    ]
    assert ghr.probe(lost) == 2

    healthy = FakeProvider([{"util_gpu_pct": 1}])
    assert ghr.probe(healthy) == 0 and healthy.closed == 1

    partial = FakeProvider([{"fail": {"fan_pct": ghr.NVML_ERROR_NOT_SUPPORTED}}])
    assert ghr.probe(partial) == 1


def test_the_recorder_is_read_only_and_never_imported_by_the_application() -> None:
    import re

    source = Path(ghr.__file__).read_text(encoding="utf-8")
    assert not re.search(
        r"nvmlDeviceSet|nvmlDeviceReset|nvmlUnitSet|subprocess|taskkill|os\.kill", source
    )
    for path in Path("src").rglob("*.py"):
        assert "gpu_hang_recorder" not in path.read_text(encoding="utf-8", errors="ignore"), path
