"""PR-IMG-MODELS-154B T37-T48: native telemetry providers (fake libraries), cadence, slow providers and failed writes.

No real counter, library, GPU or process is touched except the explicitly opt-in Windows read-only smoke at the end.
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from tools.qualification.img154 import evidence as ev
from tools.qualification.img154.core import GIB, MIB
from tools.qualification.img154.monitor import MonitorConfig, SafetyMonitor
from tools.qualification.img154b import sampler as sp

BASE = 1000.0


class Clock:
    def __init__(self, start=BASE):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def utc_of(clock):
    return (
        lambda: f"2026-01-01T00:{int(clock.now - BASE) // 60 % 60:02d}:{int(clock.now - BASE) % 60:02d}+00:00"
    )


class FakeProvider:
    def __init__(
        self, name, fields, values=None, status=None, *, raises=None, block=None, delay=0.0
    ):
        self.name, self.fields = name, tuple(fields)
        self.values = values or {}
        self.status = status
        self.raises, self.block, self.delay = raises, block, delay
        self.calls = 0

    def read(self):
        self.calls += 1
        if self.block is not None:
            self.block.wait(10)
        if self.delay:
            time.sleep(self.delay)
        if self.raises is not None:
            raise self.raises
        status = self.status or dict.fromkeys(self.fields, sp.OK)
        return sp.ProviderReading(dict(self.values), dict(status), f"fake {self.name}")


GOOD_MEMORY = {
    "commit_total_bytes": 10 * GIB,
    "commit_limit_bytes": 50 * GIB,
    "commit_headroom_bytes": 40 * GIB,
    "ram_available_bytes": 22 * GIB,
}
GOOD_GPU = {
    "vram_used_bytes": 2 * GIB,
    "vram_total_bytes": 12 * GIB,
    "gpu_temperature_c": 45.0,
    "gpu_utilization_percent": 3.0,
    "gpu_board_power_w": 30.0,
    "gpu_device_present": True,
}
GOOD_PDH = {"shared_vram_bytes": 0.3 * GIB, "hard_pages_input_per_s": 4.0}
GOOD_TREE = {"forge_tree_working_set_bytes": 1 * GIB, "forge_tree_private_bytes": 2 * GIB}


def providers(**overrides):
    base = {
        "memory": FakeProvider("windows_memory", sp.NativeMemoryProvider.fields, GOOD_MEMORY),
        "gpu": FakeProvider("nvml", sp.NvmlProvider.fields, GOOD_GPU),
        "pdh": FakeProvider("windows_pdh", sp.PdhProvider.fields, GOOD_PDH),
        "tree": FakeProvider("owned_process_tree", sp.ProcessTreeProvider.fields, GOOD_TREE),
    }
    base.update(overrides)
    return list(base.values())


def make_sampler(tmp_path, provider_list=None, *, clock=None, config=None, writer=None, **kwargs):
    clock = clock or Clock()
    monitor = SafetyMonitor(MonitorConfig(shared_baseline_bytes=0.3 * GIB), clock=clock)
    monitor.begin_observation()
    writer = writer or ev.DurableJsonlWriter(
        tmp_path / "samples.jsonl",
        max_bytes=4 * MIB,
        max_files=3,
        sync=lambda fd: None,
        redact=False,
    )
    sampler = sp.TelemetrySampler(
        provider_list if provider_list is not None else providers(),
        monitor,
        writer,
        mono=clock,
        utc=utc_of(clock),
        config=config or sp.SamplerConfig(provider_timeout_s=1.0),
        **kwargs,
    )
    return sampler, clock, writer


def records_of(tmp_path):
    recorded, torn, corrupt = ev.read_jsonl(tmp_path / "samples.jsonl")
    assert (torn, corrupt) == (False, 0)
    return recorded


# --- T37: counter precision and device identity --------------------------------------------------------------------------


def test_t37_commit_and_ram_are_exact_integer_bytes_not_rounded_gigabytes():
    commit_total = 12_345_678_901
    commit_limit = 53_431_050_241
    available = 17_179_869_233
    reader = lambda: SimpleNamespace(  # noqa: E731
        commit_total_gb=commit_total / GIB,
        commit_limit_gb=commit_limit / GIB,
        physical_available_gb=available / GIB,
    )
    reading = sp.NativeMemoryProvider(reader).read()
    assert reading.values["commit_total_bytes"] == commit_total
    assert reading.values["commit_limit_bytes"] == commit_limit
    assert reading.values["commit_headroom_bytes"] == commit_limit - commit_total
    assert reading.values["ram_available_bytes"] == available
    assert all(isinstance(v, int) for v in reading.values.values())
    assert set(reading.status.values()) == {"ok"}


class FakeNvml:
    """The NVML C API as a Python object: functions fill the ``ctypes.byref`` argument and return an NVML status."""

    def __init__(self, devices, *, memory_code=0, lost=False, fail=()):
        self.devices = devices  # list of (name, uuid, used, total, temp, util, power_mw)
        self.memory_code = memory_code
        self.lost = lost
        self.fail = set(fail)
        self.initialized = 0

    def nvmlInit_v2(self):
        self.initialized += 1
        return 0

    def nvmlDeviceGetCount_v2(self, ref):
        ref._obj.value = len(self.devices)
        return 0

    def nvmlDeviceGetHandleByIndex_v2(self, index, ref):
        ref._obj.value = index + 1  # non-zero fake handle
        return 0

    def _device(self, handle):
        return self.devices[(handle.value if hasattr(handle, "value") else handle) - 1]

    def nvmlDeviceGetName(self, handle, buffer, size):
        buffer.value = self._device(handle)[0].encode()
        return 0

    def nvmlDeviceGetUUID(self, handle, buffer, size):
        buffer.value = self._device(handle)[1].encode()
        return 0

    def nvmlDeviceGetMemoryInfo(self, handle, ref):
        if self.lost:
            return sp.NVML_ERROR_GPU_IS_LOST
        if self.memory_code or "memory" in self.fail:
            return self.memory_code or 999
        device = self._device(handle)
        ref._obj.used, ref._obj.total = device[2], device[3]
        ref._obj.free = device[3] - device[2]
        return 0

    def nvmlDeviceGetTemperature(self, handle, sensor, ref):
        if "temperature" in self.fail:
            return 999
        ref._obj.value = self._device(handle)[4]
        return 0

    def nvmlDeviceGetUtilizationRates(self, handle, ref):
        if "utilization" in self.fail:
            return 999
        ref._obj.gpu = self._device(handle)[5]
        return 0

    def nvmlDeviceGetPowerUsage(self, handle, ref):
        if "power" in self.fail:
            return 3  # not supported
        ref._obj.value = self._device(handle)[6]
        return 0


DEVICE = ("NVIDIA GeForce RTX 4070 Ti", "GPU-aaaa-bbbb-cccc", 2 * GIB, 12 * GIB, 41, 7, 33_500)


def test_t38_nvml_selects_exactly_one_device_and_reports_a_digest_not_the_uuid():
    provider = sp.NvmlProvider(FakeNvml([("Intel UHD", "GPU-x", 0, 0, 0, 0, 0), DEVICE]))
    reading = provider.read()
    assert (
        reading.values["vram_used_bytes"] == 2 * GIB
        and reading.values["vram_total_bytes"] == 12 * GIB
    )
    assert (
        reading.values["gpu_temperature_c"] == 41.0
        and reading.values["gpu_utilization_percent"] == 7.0
    )
    assert (
        reading.values["gpu_board_power_w"] == 33.5 and reading.values["gpu_device_present"] is True
    )
    assert set(reading.status.values()) == {"ok"}
    assert provider.device_name == DEVICE[0]
    assert (
        provider.device_id
        and "GPU-aaaa" not in provider.device_id
        and len(provider.device_id) == 16
    )
    again = sp.NvmlProvider(FakeNvml([DEVICE])).read
    assert again().values["gpu_device_present"] is True  # same board, same identity digest
    same = sp.NvmlProvider(FakeNvml([DEVICE]))
    same.read()
    assert same.device_id == provider.device_id


@pytest.mark.parametrize(
    "devices",
    [
        [],
        [("Intel UHD", "GPU-x", 0, 0, 0, 0, 0)],
        [DEVICE, ("NVIDIA GeForce RTX 4070 Ti", "GPU-2", 0, 12 * GIB, 0, 0, 0)],
    ],
)
def test_t38_zero_or_several_matching_devices_is_unavailable_never_a_guess(devices):
    provider = sp.NvmlProvider(FakeNvml(devices))
    with pytest.raises(sp.ProviderUnavailable):
        provider.read()


def test_t38_a_lost_gpu_is_a_real_observation_and_other_failures_are_errors_not_zero():
    lost = sp.NvmlProvider(FakeNvml([DEVICE], lost=True)).read()
    assert lost.values["gpu_device_present"] is False and lost.status["gpu_device_present"] == "ok"
    assert lost.values["vram_used_bytes"] is None and lost.status["vram_used_bytes"] == "error"
    broken = sp.NvmlProvider(FakeNvml([DEVICE], fail=("memory", "temperature", "power"))).read()
    assert broken.values["vram_used_bytes"] is None and broken.status["vram_used_bytes"] == "error"
    assert (
        broken.values["gpu_device_present"] is None
        and broken.status["gpu_device_present"] == "error"
    )
    assert (
        broken.values["gpu_temperature_c"] is None and broken.status["gpu_temperature_c"] == "error"
    )
    assert broken.values["gpu_board_power_w"] is None
    assert broken.status["gpu_utilization_percent"] == "ok"


def test_t38_a_missing_driver_library_is_unavailable(monkeypatch):
    monkeypatch.setattr(sp.os.path, "isfile", lambda path: False)
    with pytest.raises(sp.ProviderUnavailable):
        sp.NvmlProvider().read()


def test_t39_the_gpu_adapter_is_selected_by_vendor_and_dedicated_memory_never_summed():
    igpu = sp.AdapterInfo("0x00000000_0x0000a001", 0x8086, 128 * MIB, "Intel")
    gpu = sp.AdapterInfo(
        "0x00000000_0x0000b002", sp.NVIDIA_VENDOR_ID, 12 * GIB - 200 * MIB, "NVIDIA"
    )
    basic = sp.AdapterInfo("0x00000000_0x0000c003", 0x1414, 0, "Basic Render")
    assert sp.select_gpu_adapter([igpu, gpu, basic], 12 * GIB).luid == gpu.luid
    second = sp.AdapterInfo("0x00000000_0x0000d004", sp.NVIDIA_VENDOR_ID, 8 * GIB, "NVIDIA other")
    assert (
        sp.select_gpu_adapter([gpu, second], 12 * GIB).luid == gpu.luid
    )  # disambiguated by dedicated memory
    with pytest.raises(sp.ProviderUnavailable):
        sp.select_gpu_adapter([igpu, basic], 12 * GIB)  # no NVIDIA adapter
    twin = sp.AdapterInfo(
        "0x00000000_0x0000e005", sp.NVIDIA_VENDOR_ID, 12 * GIB - 200 * MIB, "NVIDIA twin"
    )
    with pytest.raises(sp.ProviderUnavailable):
        sp.select_gpu_adapter([gpu, twin], 12 * GIB)  # cannot tell them apart: refuse, do not guess


class FakePdh:
    def __init__(self, shared, pages):
        self.shared, self.pages = shared, pages
        self.paths, self.collects, self.closed = [], 0, False

    def add(self, path):
        self.paths.append(path)

    def collect(self):
        self.collects += 1

    def values(self, path):
        return dict(self.shared if "Shared Usage" in path else self.pages)

    def close(self):
        self.closed = True


def test_t40_shared_memory_is_the_mapped_adapters_only_and_the_rate_counter_is_hard_faults():
    luid = "0x00000000_0x0000b002"
    shared = {
        f"luid_{luid}_phys_0": float(512 * MIB),
        "luid_0x00000000_0x0000a001_phys_0": float(
            9 * GIB
        ),  # another adapter: must not be included
    }
    pdh = FakePdh(shared, {"": 31.5})
    provider = sp.PdhProvider(luid, query_factory=lambda: pdh)
    reading = provider.read()
    assert (
        reading.values["shared_vram_bytes"] == 512 * MIB
        and reading.status["shared_vram_bytes"] == "ok"
    )
    assert reading.values["hard_pages_input_per_s"] == 31.5
    assert any("Pages Input/sec" in p for p in pdh.paths) and not any(
        "Page Faults" in p for p in pdh.paths
    )
    assert pdh.collects == 2  # one baseline collection, one per read
    provider.close()
    assert pdh.closed


def test_t40_adapter_instances_that_share_a_luid_are_one_adapter_and_a_missing_adapter_is_not_zero():
    luid = "0x00000000_0x0000b002"
    both = FakePdh({f"luid_{luid}_phys_0": 100.0, f"luid_{luid}_phys_1": 50.0}, {"": 1.0})
    assert (
        sp.PdhProvider(luid, query_factory=lambda: both).read().values["shared_vram_bytes"] == 150
    )
    absent = FakePdh({"luid_0x00000000_0x0000a001_phys_0": 7.0}, {"": 1.0})
    reading = sp.PdhProvider(luid, query_factory=lambda: absent).read()
    assert (
        reading.values["shared_vram_bytes"] is None
        and reading.status["shared_vram_bytes"] == "error"
    )
    nothing = FakePdh({}, {})
    reading = sp.PdhProvider(luid, query_factory=lambda: nothing).read()
    assert reading.status == {"shared_vram_bytes": "missing", "hard_pages_input_per_s": "missing"}


def test_t41_process_tree_memory_counts_only_the_named_pids_and_reports_partial_trees():
    memory = {
        10: SimpleNamespace(working_set_gb=1.0, private_usage_gb=2.0),
        11: SimpleNamespace(working_set_gb=0.5, private_usage_gb=1.5),
        999: SimpleNamespace(working_set_gb=40.0, private_usage_gb=40.0),  # a foreign process
    }
    provider = sp.ProcessTreeProvider(lambda: [10, 11, 12], reader=lambda pid: memory.get(pid))
    reading = provider.read()
    assert reading.values["forge_tree_working_set_bytes"] == int(1.5 * GIB)
    assert reading.values["forge_tree_private_bytes"] == int(3.5 * GIB)
    assert "2/3" in reading.detail  # pid 12 exited: a partial tree is disclosed
    none = sp.ProcessTreeProvider(lambda: [], reader=lambda pid: None).read()
    assert set(none.status.values()) == {"not_applicable"}
    unreadable = sp.ProcessTreeProvider(lambda: [10], reader=lambda pid: None).read()
    assert set(unreadable.status.values()) == {"missing"}


# --- T42: one sample ----------------------------------------------------------------------------------------------------


def test_t42_a_sample_is_a_complete_timestamped_sequenced_persisted_record(tmp_path):
    stage = lambda: sp.StageInfo("denoise", "forge_api")  # noqa: E731
    sampler, clock, _ = make_sampler(
        tmp_path, stage=stage, endpoint=lambda: "responding", owner=lambda: {"pid": 10}
    )
    first = sampler.sample_once()
    clock.advance(1.0)
    second = sampler.sample_once()
    assert (first["sample_seq"], second["sample_seq"]) == (1, 2)
    assert second["mono_s"] - first["mono_s"] == pytest.approx(1.0)
    assert first["values"]["commit_headroom_bytes"] == 40 * GIB
    assert first["values"]["shared_vram_bytes"] == pytest.approx(0.3 * GIB)
    assert first["status"]["vram_used_bytes"] == "ok"
    assert first["stage"] == "denoise" and first["stage_source"] == "forge_api"
    assert first["endpoint"] == "responding" and first["owner"] == {"pid": 10}
    assert first["latency_ms"] >= 0
    assert first["monitor"]["latched"] == "NONE"
    on_disk = records_of(tmp_path)
    assert [r["kind"] for r in on_disk] == ["sample", "sample"]
    assert [r["sample_seq"] for r in on_disk] == [1, 2]
    assert [r["seq"] for r in on_disk] == [
        1,
        2,
    ]  # the durable stream sequence, independent of the sample sequence
    assert sampler.halt is None and not sampler.halt_event.is_set()


def test_t42_a_failing_provider_is_a_visible_error_never_zero_and_the_others_still_report(tmp_path):
    bad = FakeProvider("nvml", sp.NvmlProvider.fields, raises=ProviderError("driver"))
    sampler, _, _ = make_sampler(tmp_path, providers(gpu=bad))
    record = sampler.sample_once()
    assert record["values"]["vram_used_bytes"] is None
    assert (
        record["status"]["vram_used_bytes"] == "error"
        and record["status"]["gpu_device_present"] == "error"
    )
    assert record["status"]["commit_headroom_bytes"] == "ok"


class ProviderError(RuntimeError):
    pass


def test_t42_a_provider_reporting_a_non_ok_field_never_leaks_a_value(tmp_path):
    odd = FakeProvider(
        "windows_pdh",
        sp.PdhProvider.fields,
        {"shared_vram_bytes": 123, "hard_pages_input_per_s": 5.0},
        {"shared_vram_bytes": "error", "hard_pages_input_per_s": "ok"},
    )
    sampler, _, _ = make_sampler(tmp_path, providers(pdh=odd))
    record = sampler.sample_once()
    assert (
        record["values"]["shared_vram_bytes"] is None
        and record["status"]["shared_vram_bytes"] == "error"
    )
    assert record["values"]["hard_pages_input_per_s"] == 5.0


def test_t43_a_slow_provider_cannot_delay_the_tick_and_is_never_called_concurrently_with_itself(
    tmp_path,
):
    release = threading.Event()
    slow = FakeProvider("nvml", sp.NvmlProvider.fields, GOOD_GPU, block=release)
    sampler, clock, _ = make_sampler(
        tmp_path, providers(gpu=slow), config=sp.SamplerConfig(provider_timeout_s=0.1)
    )
    started = time.monotonic()
    first = sampler.sample_once()
    elapsed = time.monotonic() - started
    assert elapsed < 2.0
    assert (
        first["status"]["vram_used_bytes"] == "slow" and first["values"]["vram_used_bytes"] is None
    )
    clock.advance(1.0)
    second = sampler.sample_once()
    assert second["status"]["vram_used_bytes"] == "stuck"
    assert slow.calls == 1  # single flight: the busy provider was not called again
    assert second["status"]["commit_headroom_bytes"] == "ok"
    release.set()
    time.sleep(0.2)
    clock.advance(1.0)
    third = sampler.sample_once()
    assert third["status"]["vram_used_bytes"] == "ok"
    sampler.stop()


def test_t44_slow_cadence_providers_are_polled_at_most_once_per_interval(tmp_path):
    seen = []

    def observe():
        seen.append(1)
        return ()

    sampler, clock, _ = make_sampler(
        tmp_path,
        [*providers(), sp.FaultEventProvider(observe)],
        config=sp.SamplerConfig(provider_timeout_s=1.0, slow_interval_s=15.0),
    )
    for _ in range(10):
        sampler.sample_once()
        time.sleep(0.02)
        clock.advance(1.0)
    assert len(seen) == 1
    clock.advance(6.0)
    sampler.sample_once()
    time.sleep(0.1)
    assert len(seen) == 2


def test_t44_a_new_fault_record_in_the_stream_latches_cannot_verify_and_halts(tmp_path):
    state = {"events": ()}
    sampler, clock, _ = make_sampler(
        tmp_path,
        [*providers(), sp.FaultEventProvider(lambda: state["events"])],
        config=sp.SamplerConfig(provider_timeout_s=1.0, slow_interval_s=1.0),
    )
    sampler.sample_once()
    assert sampler.halt is None
    state["events"] = ("whea:9001",)
    clock.advance(2.0)
    sampler.sample_once()  # the slow-cadence query is submitted; it never delays the tick
    time.sleep(0.2)
    clock.advance(1.0)
    sampler.sample_once()  # its late result is harvested on the next tick
    assert sampler.halt is not None and sampler.halt.action == "CANNOT_VERIFY_SAFE_STATE"
    assert sampler.halt_event.is_set()
    assert any(c.startswith("GPU_FAULT_EVENT") for c in sampler.halt.codes)
    kinds = [r["kind"] for r in records_of(tmp_path)]
    assert "transition" in kinds  # significant transitions are persisted immediately


# --- T45: monitor integration --------------------------------------------------------------------------------------------


def test_t45_a_resource_violation_becomes_a_halt_with_the_trigger_and_last_readings(tmp_path):
    low = FakeProvider(
        "windows_memory",
        sp.NativeMemoryProvider.fields,
        {**GOOD_MEMORY, "commit_headroom_bytes": 3 * GIB},
    )
    sampler, clock, _ = make_sampler(tmp_path, providers(memory=low))
    sampler.sample_once()
    clock.advance(1.0)
    sampler.sample_once()
    assert sampler.halt is not None and sampler.halt.action == "REQUEST_OWNER_STOP"
    assert sampler.halt.first_trigger == "COMMIT_HEADROOM_BELOW_FLOOR"
    assert sampler.halt.last_values["commit_headroom_bytes"] == 3 * GIB
    assert sampler.halt.as_dict()["utc"].startswith("2026-")


def test_t45_missing_vram_for_more_than_ten_seconds_escalates_to_cannot_verify(tmp_path):
    broken = FakeProvider(
        "nvml",
        sp.NvmlProvider.fields,
        dict.fromkeys(sp.NvmlProvider.fields),
        dict.fromkeys(sp.NvmlProvider.fields, "error"),
    )
    sampler, clock, _ = make_sampler(tmp_path, providers(gpu=broken))
    for _ in range(14):
        sampler.sample_once()
        clock.advance(1.0)
    assert sampler.halt is not None and sampler.halt.action == "CANNOT_VERIFY_SAFE_STATE"


def test_t45_a_backwards_monotonic_clock_is_a_harness_fault(tmp_path):
    sampler, clock, _ = make_sampler(tmp_path)
    sampler.sample_once()
    clock.advance(-5.0)
    sampler.sample_once()
    assert sampler.halt is not None and sampler.halt.action == "HARNESS_FAULT"


def test_t45_the_watchdog_detects_a_sampler_that_stopped_producing_samples(tmp_path):
    sampler, clock, _ = make_sampler(tmp_path)
    sampler.sample_once()
    clock.advance(1.0)
    sampler.watchdog_tick()
    assert sampler.halt is None
    clock.advance(10.0)  # no sample for ten seconds: the sampler thread is not delivering
    sampler.watchdog_tick()
    assert sampler.halt is not None and sampler.halt.action == "CANNOT_VERIFY_SAFE_STATE"


# --- T46: failed writes --------------------------------------------------------------------------------------------------


def test_t46_repeated_write_failures_halt_the_run_as_a_harness_fault(tmp_path):
    class BrokenWriter:
        def append(self, record):
            raise OSError("disk full")

    sampler, clock, _ = make_sampler(tmp_path, writer=BrokenWriter())
    for _ in range(3):
        sampler.sample_once()
        clock.advance(1.0)
    assert sampler.harness_fault == "EVIDENCE_WRITE_FAILED"
    assert sampler.halt_event.is_set()
    assert sampler.records_written == 0


def test_t46_a_single_write_failure_is_tolerated_and_counted(tmp_path):
    state = {"n": 0}
    real = ev.DurableJsonlWriter(tmp_path / "samples.jsonl", sync=lambda fd: None, redact=False)

    class FlakyWriter:
        def append(self, record):
            state["n"] += 1
            if state["n"] == 2:
                raise OSError("transient")
            return real.append(record)

    sampler, clock, _ = make_sampler(tmp_path, writer=FlakyWriter())
    for _ in range(4):
        sampler.sample_once()
        clock.advance(1.0)
    assert sampler.harness_fault is None
    assert sampler.records_written == 3


# --- T47: the loop -------------------------------------------------------------------------------------------------------


def test_t47_the_loop_keeps_a_monotonic_cadence_and_never_bursts_to_catch_up(tmp_path):
    waits = []
    clock = Clock()
    sampler_holder = {}

    def sleep_until(seconds):
        waits.append(seconds)
        clock.advance(seconds)
        if len(waits) == 3:
            clock.advance(5.0)  # the next tick starts late: an overrun
        if len(waits) >= 6:
            sampler_holder["s"]._stop.set()

    sampler, _, _ = make_sampler(tmp_path, clock=clock, sleep_until=sleep_until)
    sampler_holder["s"] = sampler
    sampler.start()
    sampler._thread.join(5)
    assert not sampler._thread.is_alive()
    assert all(0.0 <= w <= 1.0 + 1e-9 for w in waits)
    assert sampler.overruns >= 1
    recorded = [r for r in records_of(tmp_path) if r["kind"] == "sample"]
    assert [r["sample_seq"] for r in recorded] == list(range(1, len(recorded) + 1))
    stream_seq = [r["seq"] for r in records_of(tmp_path)]
    assert stream_seq == list(
        range(1, len(stream_seq) + 1)
    )  # headers and transitions advance it; nothing is lost
    with pytest.raises(RuntimeError):
        sampler.start()


def test_t47_a_crashing_loop_is_reported_not_silent(tmp_path):
    class ExplodingMonitorWriter:
        def append(self, record):
            raise AssertionError("unexpected")  # not an OSError: the loop itself fails

    sampler, _, _ = make_sampler(tmp_path, writer=ExplodingMonitorWriter())
    sampler.start()
    sampler._thread.join(5)
    assert sampler.harness_fault and sampler.harness_fault.startswith("SAMPLER_LOOP_")
    assert sampler.halt_event.is_set()


# --- T48: opt-in native smoke --------------------------------------------------------------------------------------------


@pytest.mark.skipif(
    sys.platform != "win32" or os.environ.get("STABLENEW_IMG154B_NATIVE_SMOKE") != "1",
    reason="opt-in Windows read-only native-counter smoke (set STABLENEW_IMG154B_NATIVE_SMOKE=1)",
)
def test_t48_native_providers_read_this_host_without_side_effects():
    memory = sp.NativeMemoryProvider().read()
    assert memory.values["commit_limit_bytes"] > memory.values["commit_total_bytes"] > 0
    nvml = sp.NvmlProvider()
    gpu = nvml.read()
    assert gpu.values["vram_total_bytes"] and nvml.device_id
    adapters = sp.enumerate_dxgi_adapters()
    adapter = sp.select_gpu_adapter(adapters, int(gpu.values["vram_total_bytes"]))
    pdh = sp.PdhProvider(adapter.luid)
    pdh.read()
    time.sleep(1.1)
    reading = pdh.read()
    pdh.close()
    assert reading.status["shared_vram_bytes"] == "ok"
    assert ctypes is not None


def test_t44_a_slow_cadence_provider_never_delays_the_tick_even_when_it_is_very_slow(tmp_path):
    release = threading.Event()

    def observe():
        release.wait(10)
        return ("whea:1",)

    sampler, clock, _ = make_sampler(
        tmp_path,
        [*providers(), sp.FaultEventProvider(observe)],
        config=sp.SamplerConfig(provider_timeout_s=0.1, slow_interval_s=1.0),
    )
    started = time.monotonic()
    for _ in range(3):
        record = sampler.sample_once()
        clock.advance(1.0)
    assert time.monotonic() - started < 2.0  # no tick waited for the stuck query
    assert record["status"]["commit_headroom_bytes"] == "ok"
    assert sampler.halt is None  # nothing was observed yet: absence of a report is not a report
    release.set()
    sampler.stop()


# --- T49-T52: independent-review findings -------------------------------------------------------------------------------


def test_t49_the_pdh_item_structure_is_defined_once_and_never_reassigned_per_instance():
    import ast
    from pathlib import Path

    assert [name for name, _ in sp._PdhItem._fields_] == ["name", "status", "value"]
    assert ctypes.sizeof(sp._PdhItem) == (24 if ctypes.sizeof(ctypes.c_void_p) == 8 else 16)
    tree = ast.parse(Path(sp.__file__).read_text(encoding="utf-8"))
    for function in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        for node in ast.walk(function):
            targets = node.targets if isinstance(node, ast.Assign) else []
            for target in targets:
                assert not (isinstance(target, ast.Attribute) and target.attr == "_fields_"), (
                    function.name
                )
    # a ctypes structure's _fields_ is final: re-assigning it on a second instance raised AttributeError in a real run
    with pytest.raises(AttributeError):
        sp._PdhItem._fields_ = []


@pytest.mark.skipif(
    sys.platform != "win32" or os.environ.get("STABLENEW_IMG154B_NATIVE_SMOKE") != "1",
    reason="opt-in Windows read-only native-counter smoke (set STABLENEW_IMG154B_NATIVE_SMOKE=1)",
)
def test_t49_two_native_pdh_queries_can_coexist_in_one_process():
    first, second = sp._PdhQuery(), sp._PdhQuery()
    for query in (first, second):
        query.add(sp.PdhProvider.PAGES)
        query.collect()
        query.close()


def test_t50_provider_threads_are_daemons_so_a_hung_native_call_cannot_hold_the_interpreter(
    tmp_path,
):
    release = threading.Event()
    hung = FakeProvider("nvml", sp.NvmlProvider.fields, GOOD_GPU, block=release)
    sampler, _, _ = make_sampler(
        tmp_path, providers(gpu=hung), config=sp.SamplerConfig(provider_timeout_s=0.05)
    )
    sampler.sample_once()
    workers = [t for t in threading.enumerate() if t.name == "img154b-nvml"]
    assert workers and all(t.daemon for t in workers)
    release.set()


def test_t51_the_clean_streak_counts_complete_samples_and_resets_on_any_gap_or_latch(tmp_path):
    flaky_status = {"shared_vram_bytes": "ok"}
    pdh = FakeProvider("windows_pdh", sp.PdhProvider.fields, GOOD_PDH, flaky_status)
    sampler, clock, _ = make_sampler(tmp_path, providers(pdh=pdh))
    for expected in (1, 2, 3):
        sampler.sample_once()
        clock.advance(1.0)
        assert sampler.clean_streak == expected
    flaky_status["shared_vram_bytes"] = "missing"  # one incomplete essential field
    sampler.sample_once()
    clock.advance(1.0)
    assert sampler.clean_streak == 0
    flaky_status["shared_vram_bytes"] = "ok"
    sampler.sample_once()
    assert sampler.clean_streak == 1


def test_t51_a_latched_stop_is_never_clean(tmp_path):
    low = FakeProvider(
        "windows_memory",
        sp.NativeMemoryProvider.fields,
        {**GOOD_MEMORY, "commit_headroom_bytes": 3 * GIB},
    )
    sampler, clock, _ = make_sampler(tmp_path, providers(memory=low))
    for _ in range(4):
        sampler.sample_once()
        clock.advance(1.0)
    assert sampler.halt is not None and sampler.clean_streak == 0


def test_t52_nvml_is_initialized_exactly_once_under_concurrent_first_use():
    class SlowNvml(FakeNvml):
        def nvmlInit_v2(self):
            time.sleep(0.05)  # widen the race window
            return super().nvmlInit_v2()

    library = SlowNvml([DEVICE])
    provider = sp.NvmlProvider(library)
    results: list[str] = []
    errors: list[Exception] = []

    def use():
        try:
            results.append(provider.identify())
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=use) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    assert errors == [] and len(set(results)) == 1 and len(results) == 6
    assert library.initialized == 1
