"""D5 (154B): bounded, in-process native telemetry acquisition feeding the PR-154A ``SafetyMonitor``.

Design rules (each one is exercised by a test):

* Windows counters are read by persistent native handles (``GetPerformanceInfo``, NVML, one PDH query, DXGI for the
  adapter map) inside this process. No PowerShell or console tool is launched once per sample.
* One sample is one timestamped, sequence-numbered record with per-field status, provenance and acquisition latency.
  A value that could not be obtained is ``None`` with a non-``ok`` status; it is never zero and never carried forward.
* A slow provider cannot delay the tick: providers run single-flight on a small pool with a per-tick deadline, and a field
  whose provider is still busy is reported ``slow``. The tick cadence is monotonic and never bursts to catch up.
* Records are fsynced one by one by the PR-154A durable writer, so a crash leaves the survivor evidence on disk.
* The sampler never acts on a process. A monitor stop/uncertainty is a latched ``halt`` the coordinator observes.

Phase markers are never fabricated: ``stage`` is whatever the injected stage source states (``unknown`` by default).
"""

from __future__ import annotations

import ctypes
import hashlib
import os
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future, wait
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from tools.qualification.img154.core import GIB, MIB
from tools.qualification.img154.evidence import DurableJsonlWriter
from tools.qualification.img154.monitor import (
    CANNOT_VERIFY_SAFE_STATE,
    HARNESS_FAULT,
    NONE,
    REQUEST_OWNER_STOP,
    SafetyMonitor,
    Sample,
)

OK = "ok"
MISSING = "missing"
ERROR = "error"
SLOW = "slow"
STUCK = "stuck"
NOT_APPLICABLE = "not_applicable"

#: Every field a sample record can carry, with its units. The monitor consumes the first seven.
FIELD_UNITS: Mapping[str, str] = {
    "commit_total_bytes": "bytes",
    "commit_limit_bytes": "bytes",
    "commit_headroom_bytes": "bytes",
    "ram_available_bytes": "bytes",
    "vram_used_bytes": "bytes",
    "vram_total_bytes": "bytes",
    "shared_vram_bytes": "bytes",
    "gpu_temperature_c": "celsius",
    "gpu_utilization_percent": "percent",
    "gpu_board_power_w": "watts",
    "gpu_device_present": "boolean",
    "hard_pages_input_per_s": "pages_per_second",
    "forge_tree_working_set_bytes": "bytes",
    "forge_tree_private_bytes": "bytes",
}
HALT_LEVELS = (REQUEST_OWNER_STOP, CANNOT_VERIFY_SAFE_STATE, HARNESS_FAULT)


class ProviderUnavailable(RuntimeError):
    """A native source cannot be used on this host (missing library, no device, unsupported call)."""


@dataclass(frozen=True)
class ProviderReading:
    """What one provider returned for one tick. ``status`` is per field; absent fields are ``missing``."""

    values: Mapping[str, Any]
    status: Mapping[str, str]
    source: str
    detail: str = ""


class Provider(Protocol):
    name: str
    fields: tuple[str, ...]

    def read(self) -> ProviderReading: ...


# ------------------------------------------------------------------------------------------------------ providers


class NativeMemoryProvider:
    """``GetPerformanceInfo`` commit and physical memory, as exact integer bytes (never ``RAM + pagefile - reserve``)."""

    name = "windows_memory"
    fields: tuple[str, ...] = (
        "commit_total_bytes",
        "commit_limit_bytes",
        "commit_headroom_bytes",
        "ram_available_bytes",
    )

    def __init__(self, reader: Callable[[], Any] | None = None) -> None:
        self._reader = reader

    def _read(self) -> Any:
        if self._reader is None:
            from tools.qualification.vid160c.win_memory import read_system_commit

            self._reader = read_system_commit
        return self._reader()

    def read(self) -> ProviderReading:
        info = self._read()
        total = int(round(info.commit_total_gb * GIB))
        limit = int(round(info.commit_limit_gb * GIB))
        available = int(round(info.physical_available_gb * GIB))
        values = {
            "commit_total_bytes": total,
            "commit_limit_bytes": limit,
            "commit_headroom_bytes": limit - total,
            "ram_available_bytes": available,
        }
        return ProviderReading(
            values,
            dict.fromkeys(values, OK),
            "GetPerformanceInfo (CommitTotal, CommitLimit, PhysicalAvailable x PageSize)",
        )


class _NvmlMemory(ctypes.Structure):
    _fields_ = [
        ("total", ctypes.c_ulonglong),
        ("free", ctypes.c_ulonglong),
        ("used", ctypes.c_ulonglong),
    ]


class _NvmlUtilization(ctypes.Structure):
    _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]


NVML_SUCCESS = 0
NVML_ERROR_GPU_IS_LOST = 15
NVML_TEMPERATURE_GPU = 0


def _nvml_candidates() -> list[str]:
    root = os.environ.get("SystemRoot") or os.environ.get("windir") or r"C:\Windows"
    program = os.environ.get("ProgramFiles") or r"C:\Program Files"
    return [
        os.path.join(root, "System32", "nvml.dll"),
        os.path.join(program, "NVIDIA Corporation", "NVSMI", "nvml.dll"),
    ]


class NvmlProvider:
    """NVML dedicated memory, temperature, utilization and board power for exactly one identified GPU.

    ``device_id`` is a short digest of the board UUID (never the UUID): stable across the run and the boot, usable to prove a
    baseline and a launch reading came from the same GPU. A host with zero or several matching devices is ``ambiguous`` and
    every field is an error, never a guess. A lost GPU is a real observation: ``gpu_device_present`` is ``False``.
    """

    name = "nvml"
    fields: tuple[str, ...] = (
        "vram_used_bytes",
        "vram_total_bytes",
        "gpu_temperature_c",
        "gpu_utilization_percent",
        "gpu_board_power_w",
        "gpu_device_present",
    )

    def __init__(
        self, library: Any | None = None, *, expected_name_fragment: str = "RTX 4070 Ti"
    ) -> None:
        self._lib = library
        self._fragment = expected_name_fragment.lower()
        self._handle: Any = None
        self.device_id: str | None = None
        self.device_name: str | None = None
        self._initialized = False
        self._init_lock = threading.Lock()

    def _load(self) -> Any:
        if self._lib is not None:
            return self._lib
        for path in _nvml_candidates():
            if os.path.isfile(path):
                self._lib = ctypes.WinDLL(path)  # type: ignore[attr-defined,unused-ignore]
                return self._lib
        raise ProviderUnavailable("nvml.dll was not found in the driver locations")

    def _call(self, name: str, *args: Any) -> int:
        return int(getattr(self._load(), name)(*args))

    def _initialize(self) -> None:
        with self._init_lock:
            self._initialize_locked()

    def _initialize_locked(self) -> None:
        if self._initialized:
            return
        if self._call("nvmlInit_v2") != NVML_SUCCESS:
            raise ProviderUnavailable("nvmlInit failed")
        count = ctypes.c_uint(0)
        if self._call("nvmlDeviceGetCount_v2", ctypes.byref(count)) != NVML_SUCCESS:
            raise ProviderUnavailable("nvmlDeviceGetCount failed")
        matches: list[tuple[Any, str, str]] = []
        for index in range(count.value):
            handle = ctypes.c_void_p()
            if (
                self._call("nvmlDeviceGetHandleByIndex_v2", index, ctypes.byref(handle))
                != NVML_SUCCESS
            ):
                continue
            name_buffer = ctypes.create_string_buffer(96)
            uuid_buffer = ctypes.create_string_buffer(96)
            if self._call("nvmlDeviceGetName", handle, name_buffer, 96) != NVML_SUCCESS:
                continue
            if self._call("nvmlDeviceGetUUID", handle, uuid_buffer, 96) != NVML_SUCCESS:
                continue
            name = name_buffer.value.decode("ascii", "replace")
            if self._fragment in name.lower():
                matches.append((handle, name, uuid_buffer.value.decode("ascii", "replace")))
        if len(matches) != 1:
            raise ProviderUnavailable(
                f"{len(matches)} devices match the expected GPU; exactly one is required"
            )
        self._handle, self.device_name, uuid = matches[0]
        self.device_id = hashlib.sha256(uuid.encode("utf-8")).hexdigest()[:16]
        self._initialized = True

    def identify(self) -> str:
        """The boot-stable device digest of the one matching GPU (initializes NVML; raises when it cannot be identified)."""

        self._initialize()
        if not self.device_id:
            raise ProviderUnavailable("the GPU has no identity")
        return self.device_id

    def read(self) -> ProviderReading:
        self._initialize()
        values: dict[str, Any] = {}
        status: dict[str, str] = {}
        memory = _NvmlMemory()
        code = self._call("nvmlDeviceGetMemoryInfo", self._handle, ctypes.byref(memory))
        if code == NVML_ERROR_GPU_IS_LOST:
            values["gpu_device_present"] = False
            status["gpu_device_present"] = OK
            for name in self.fields[:-1]:
                values[name], status[name] = None, ERROR
            return ProviderReading(values, status, "NVML", "the GPU reported as lost")
        if code == NVML_SUCCESS:
            values["vram_used_bytes"], values["vram_total_bytes"] = (
                int(memory.used),
                int(memory.total),
            )
            values["gpu_device_present"] = True
            status.update(vram_used_bytes=OK, vram_total_bytes=OK, gpu_device_present=OK)
        else:
            for name in ("vram_used_bytes", "vram_total_bytes", "gpu_device_present"):
                values[name], status[name] = None, ERROR
        temperature = ctypes.c_uint(0)
        if (
            self._call(
                "nvmlDeviceGetTemperature",
                self._handle,
                NVML_TEMPERATURE_GPU,
                ctypes.byref(temperature),
            )
            == NVML_SUCCESS
        ):
            values["gpu_temperature_c"], status["gpu_temperature_c"] = float(temperature.value), OK
        else:
            values["gpu_temperature_c"], status["gpu_temperature_c"] = None, ERROR
        utilization = _NvmlUtilization()
        if (
            self._call("nvmlDeviceGetUtilizationRates", self._handle, ctypes.byref(utilization))
            == NVML_SUCCESS
        ):
            values["gpu_utilization_percent"], status["gpu_utilization_percent"] = (
                float(utilization.gpu),
                OK,
            )
        else:
            values["gpu_utilization_percent"], status["gpu_utilization_percent"] = None, ERROR
        power = ctypes.c_uint(0)
        if self._call("nvmlDeviceGetPowerUsage", self._handle, ctypes.byref(power)) == NVML_SUCCESS:
            values["gpu_board_power_w"], status["gpu_board_power_w"] = power.value / 1000.0, OK
        else:
            values["gpu_board_power_w"], status["gpu_board_power_w"] = None, ERROR
        return ProviderReading(
            values,
            status,
            "NVML (nvmlDeviceGetMemoryInfo, GetTemperature, GetUtilizationRates, GetPowerUsage)",
        )


@dataclass(frozen=True)
class AdapterInfo:
    luid: str  # "0x<high:08x>_0x<low:08x>" as it appears in the GPU performance-counter instance names
    vendor_id: int
    dedicated_bytes: int
    description: str = ""


def enumerate_dxgi_adapters() -> list[
    AdapterInfo
]:  # pragma: no cover - exercised by the opt-in Windows smoke
    """Read-only DXGI adapter enumeration (LUID, vendor, dedicated memory) via the COM vtable, no device is created."""

    from ctypes import wintypes

    class LUID(ctypes.Structure):
        _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

    class DESC1(ctypes.Structure):
        _fields_ = [
            ("Description", ctypes.c_wchar * 128),
            ("VendorId", ctypes.c_uint),
            ("DeviceId", ctypes.c_uint),
            ("SubSysId", ctypes.c_uint),
            ("Revision", ctypes.c_uint),
            ("DedicatedVideoMemory", ctypes.c_size_t),
            ("DedicatedSystemMemory", ctypes.c_size_t),
            ("SharedSystemMemory", ctypes.c_size_t),
            ("AdapterLuid", LUID),
            ("Flags", ctypes.c_uint),
        ]

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", ctypes.c_ulong),
            ("Data2", ctypes.c_ushort),
            ("Data3", ctypes.c_ushort),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    iid = GUID(
        0x770AAE78,
        0xF26F,
        0x4DBA,
        (ctypes.c_ubyte * 8)(0xA8, 0x29, 0x25, 0x3C, 0x83, 0xD1, 0xB3, 0x87),
    )
    root = os.environ.get("SystemRoot") or r"C:\Windows"
    dxgi = ctypes.WinDLL(os.path.join(root, "System32", "dxgi.dll"))  # type: ignore[attr-defined,unused-ignore]
    factory = ctypes.c_void_p()
    if dxgi.CreateDXGIFactory1(ctypes.byref(iid), ctypes.byref(factory)) != 0 or not factory.value:
        raise ProviderUnavailable("CreateDXGIFactory1 failed")

    def vtable(pointer: ctypes.c_void_p) -> Any:
        return ctypes.cast(
            ctypes.cast(pointer, ctypes.POINTER(ctypes.c_void_p))[0],
            ctypes.POINTER(ctypes.c_void_p),
        )

    def release(pointer: ctypes.c_void_p) -> None:
        ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable(pointer)[2])(pointer)

    enum_adapters1 = ctypes.WINFUNCTYPE(
        ctypes.c_long, ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)
    )(vtable(factory)[12])
    adapters: list[AdapterInfo] = []
    try:
        index = 0
        while True:
            adapter = ctypes.c_void_p()
            if enum_adapters1(factory, index, ctypes.byref(adapter)) != 0:
                break
            try:
                get_desc1 = ctypes.WINFUNCTYPE(
                    ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(DESC1)
                )(vtable(adapter)[10])
                desc = DESC1()
                if get_desc1(adapter, ctypes.byref(desc)) == 0:
                    adapters.append(
                        AdapterInfo(
                            f"0x{desc.AdapterLuid.HighPart & 0xFFFFFFFF:08x}_0x{desc.AdapterLuid.LowPart:08x}",
                            int(desc.VendorId),
                            int(desc.DedicatedVideoMemory),
                            str(desc.Description),
                        )
                    )
            finally:
                release(adapter)
            index += 1
    finally:
        release(factory)
    return adapters


NVIDIA_VENDOR_ID = 0x10DE


def select_gpu_adapter(
    adapters: Sequence[AdapterInfo],
    dedicated_total_bytes: int | None,
    *,
    vendor_id: int = NVIDIA_VENDOR_ID,
) -> AdapterInfo:
    """The one adapter that is the NVML-identified GPU: vendor match, and dedicated memory equal to NVML's total when known.

    Zero or several candidates raise: a shared-memory counter must never be summed across adapters or guessed.
    """

    candidates = [a for a in adapters if a.vendor_id == vendor_id]
    if dedicated_total_bytes:
        # NVML reports the board total and DXGI the addressable dedicated memory: they agree within a few hundred MiB.
        close = [
            a for a in candidates if abs(a.dedicated_bytes - dedicated_total_bytes) <= 512 * MIB
        ]
        if close:
            candidates = close
    if len(candidates) != 1:
        raise ProviderUnavailable(
            f"{len(candidates)} adapters match the identified GPU; exactly one is required"
        )
    return candidates[0]


class PdhProvider:
    """One persistent PDH query: per-adapter ``Shared Usage`` and ``Dedicated Usage`` and ``\\Memory\\Pages Input/sec``.

    ``Pages Input/sec`` counts pages read to resolve HARD faults (not the broader ``Page Faults/sec``); as a rate it needs two
    collections, so its first reading is ``missing``. Adapter instances are matched by LUID to the NVML-identified GPU.
    """

    name = "windows_pdh"
    fields: tuple[str, ...] = ("shared_vram_bytes", "hard_pages_input_per_s")
    SHARED = "\\GPU Adapter Memory(*)\\Shared Usage"
    DEDICATED = "\\GPU Adapter Memory(*)\\Dedicated Usage"
    PAGES = "\\Memory\\Pages Input/sec"

    def __init__(
        self,
        luid: Callable[[], str] | str,
        *,
        query_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._luid = luid
        self._factory = query_factory
        self._query: Any = None

    def _open(self) -> Any:
        if self._query is None:
            self._query = (self._factory or _PdhQuery)()
            for path in (self.SHARED, self.PAGES):
                self._query.add(path)
            self._query.collect()  # establishes the baseline sample for the rate counter
        return self._query

    def close(self) -> None:
        if self._query is not None and hasattr(self._query, "close"):
            self._query.close()
        self._query = None

    def read(self) -> ProviderReading:
        query = self._open()
        query.collect()
        luid = self._luid() if callable(self._luid) else self._luid
        values: dict[str, Any] = {"shared_vram_bytes": None, "hard_pages_input_per_s": None}
        status = {"shared_vram_bytes": MISSING, "hard_pages_input_per_s": MISSING}
        shared = query.values(self.SHARED)
        wanted = [v for k, v in shared.items() if luid.lower() in k.lower()]
        if len(wanted) == 1 and wanted[0] is not None and wanted[0] >= 0:
            values["shared_vram_bytes"], status["shared_vram_bytes"] = int(wanted[0]), OK
        elif len(wanted) > 1:
            # several physical-adapter instances share a LUID: they are one adapter, so the sum is the adapter's usage
            numbers = [v for v in wanted if v is not None and v >= 0]
            if len(numbers) == len(wanted):
                values["shared_vram_bytes"], status["shared_vram_bytes"] = int(sum(numbers)), OK
        elif shared:
            status["shared_vram_bytes"] = ERROR
        pages = query.values(self.PAGES)
        numbers = [v for v in pages.values() if v is not None and v >= 0]
        if len(numbers) == 1:
            values["hard_pages_input_per_s"], status["hard_pages_input_per_s"] = (
                float(numbers[0]),
                OK,
            )
        return ProviderReading(
            values,
            status,
            "PDH \\GPU Adapter Memory(luid)\\Shared Usage; \\Memory\\Pages Input/sec (hard faults)",
        )


class _PdhValue(ctypes.Union):
    _fields_ = [("l", ctypes.c_long), ("d", ctypes.c_double), ("q", ctypes.c_longlong)]


class _PdhItem(ctypes.Structure):
    """``PDH_FMT_COUNTERVALUE_ITEM_W``: name pointer, status, 8-byte value union (24 bytes on x64).

    Defined once at module level: a ctypes structure's ``_fields_`` can be assigned only once, so a per-instance assignment
    made every second ``_PdhQuery`` in a process fail.
    """

    _fields_ = [("name", ctypes.c_wchar_p), ("status", ctypes.c_ulong), ("value", _PdhValue)]


class _PdhQuery:  # pragma: no cover - exercised by the opt-in Windows smoke
    """The minimal native PDH wrapper (English counter names, large/double formatted values, array counters)."""

    PDH_FMT_DOUBLE = 0x00000200
    PDH_FMT_LARGE = 0x00000400
    PDH_MORE_DATA = 0x800007D2

    def __init__(self) -> None:
        root = os.environ.get("SystemRoot") or r"C:\Windows"
        self._pdh = ctypes.WinDLL(os.path.join(root, "System32", "pdh.dll"))  # type: ignore[attr-defined,unused-ignore]
        self._query = ctypes.c_void_p()
        if self._pdh.PdhOpenQueryW(None, 0, ctypes.byref(self._query)) != 0:
            raise ProviderUnavailable("PdhOpenQuery failed")
        self._counters: dict[str, ctypes.c_void_p] = {}

    def add(self, path: str) -> None:
        handle = ctypes.c_void_p()
        if self._pdh.PdhAddEnglishCounterW(self._query, path, 0, ctypes.byref(handle)) != 0:
            raise ProviderUnavailable(f"counter unavailable: {path}")
        self._counters[path] = handle

    def collect(self) -> None:
        if self._pdh.PdhCollectQueryData(self._query) != 0:
            raise ProviderUnavailable("PdhCollectQueryData failed")

    def values(self, path: str) -> dict[str, float | None]:
        handle = self._counters[path]
        double = path.endswith("Pages Input/sec")
        fmt = self.PDH_FMT_DOUBLE if double else self.PDH_FMT_LARGE
        size, count = ctypes.c_ulong(0), ctypes.c_ulong(0)
        code = self._pdh.PdhGetFormattedCounterArrayW(
            handle, fmt, ctypes.byref(size), ctypes.byref(count), None
        )
        if (code & 0xFFFFFFFF) != self.PDH_MORE_DATA:
            return {}
        buffer = ctypes.create_string_buffer(size.value)
        if (
            self._pdh.PdhGetFormattedCounterArrayW(
                handle, fmt, ctypes.byref(size), ctypes.byref(count), buffer
            )
            != 0
        ):
            return {}
        items = ctypes.cast(buffer, ctypes.POINTER(_PdhItem))
        result: dict[str, float | None] = {}
        for index in range(count.value):
            item = items[index]
            if item.status in (0, 0x00000001):
                result[str(item.name)] = float(item.value.d if double else item.value.q)
            else:
                result[str(item.name)] = None
        return result

    def close(self) -> None:
        if self._query:
            self._pdh.PdhCloseQuery(self._query)
            self._query = ctypes.c_void_p()


class ProcessTreeProvider:
    """Resident and private memory of exactly the owned process tree (the pids come from the verified ownership facts)."""

    name = "owned_process_tree"
    fields: tuple[str, ...] = ("forge_tree_working_set_bytes", "forge_tree_private_bytes")

    def __init__(
        self,
        pids: Callable[[], Sequence[int]],
        reader: Callable[[int], Any] | None = None,
    ) -> None:
        self._pids = pids
        self._reader = reader

    def _memory(self, pid: int) -> Any:
        if self._reader is None:
            from tools.qualification.vid160c.win_memory import read_process_memory

            self._reader = read_process_memory
        return self._reader(pid)

    def read(self) -> ProviderReading:
        pids = list(self._pids())
        if not pids:
            values = dict.fromkeys(self.fields)
            return ProviderReading(
                values,
                dict.fromkeys(self.fields, NOT_APPLICABLE),
                "owned process tree",
                "no owned process",
            )
        working = private = 0
        unreadable = 0
        for pid in pids:
            info = self._memory(int(pid))
            if info is None:
                unreadable += 1
                continue
            working += int(round(info.working_set_gb * GIB))
            private += int(round(info.private_usage_gb * GIB))
        if unreadable == len(pids):
            values = dict.fromkeys(self.fields)
            return ProviderReading(
                values,
                dict.fromkeys(self.fields, MISSING),
                "owned process tree",
                "no process readable",
            )
        # a partial tree (an exited child) is still a real, lower-bound reading; the count is recorded
        values = {"forge_tree_working_set_bytes": working, "forge_tree_private_bytes": private}
        return ProviderReading(
            values,
            dict.fromkeys(values, OK),
            "GetProcessMemoryInfo over the owned tree",
            f"{len(pids) - unreadable}/{len(pids)} processes readable",
        )


class FaultEventProvider:
    """Slow-cadence new-fault-record observation (an injected callable; production wraps the 154A snapshot diff)."""

    name = "fault_events"
    fields: tuple[str, ...] = ("fault_events",)

    def __init__(self, observe: Callable[[], Sequence[str]]) -> None:
        self._observe = observe

    def read(self) -> ProviderReading:
        events = tuple(str(item) for item in self._observe())
        return ProviderReading(
            {"fault_events": events}, {"fault_events": OK}, "event-log snapshot diff"
        )


# ------------------------------------------------------------------------------------------------------- sampler

#: The fields whose simultaneous ``ok`` status makes a sample "clean" for the pre-dispatch streak.
ESSENTIAL_FIELDS = (
    "commit_headroom_bytes",
    "ram_available_bytes",
    "vram_used_bytes",
    "vram_total_bytes",
    "shared_vram_bytes",
    "gpu_temperature_c",
    "gpu_device_present",
)


def _submit_daemon(function: Callable[[], ProviderReading], name: str) -> Future[ProviderReading]:
    """Run one provider read on its own DAEMON thread and return a ``Future`` (a pool's workers are not daemons)."""

    future: Future[ProviderReading] = Future()

    def run() -> None:
        try:
            future.set_result(function())
        except BaseException as exc:  # noqa: BLE001 - delivered to the sampler as a failed reading
            future.set_exception(exc)

    threading.Thread(target=run, name=name, daemon=True).start()
    return future


@dataclass(frozen=True)
class StageInfo:
    stage: str = "unknown"
    source: str = "unknown"


@dataclass(frozen=True)
class SamplerConfig:
    interval_s: float = 1.0
    provider_timeout_s: float = 0.75
    #: cadence (seconds) of providers named in ``slow_providers``; they are polled at most this often, never per tick
    slow_interval_s: float = 15.0
    slow_providers: tuple[str, ...] = ("fault_events",)
    write_failure_limit: int = 3


@dataclass
class HaltRecord:
    action: str
    codes: tuple[str, ...]
    first_trigger: str | None
    seq: int | None
    mono_s: float
    utc: str
    last_values: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "codes": list(self.codes),
            "first_trigger": self.first_trigger,
            "seq": self.seq,
            "mono_s": self.mono_s,
            "utc": self.utc,
            "last_values": dict(self.last_values),
        }


class TelemetrySampler:
    def __init__(
        self,
        providers: Sequence[Provider],
        monitor: SafetyMonitor,
        writer: DurableJsonlWriter,
        *,
        mono: Callable[[], float] = time.monotonic,
        utc: Callable[[], str] = lambda: datetime.now(UTC).isoformat(),
        stage: Callable[[], StageInfo] | None = None,
        endpoint: Callable[[], str] | None = None,
        owner: Callable[[], Mapping[str, Any]] | None = None,
        config: SamplerConfig | None = None,
        sleep_until: Callable[[float], bool] | None = None,
    ) -> None:
        self.config = config or SamplerConfig()
        self._providers = list(providers)
        self._monitor = monitor
        self._writer = writer
        self._mono, self._utc = mono, utc
        self._stage = stage or (lambda: StageInfo())
        self._endpoint = endpoint or (lambda: "unknown")
        self._owner = owner or (lambda: {})
        self._lock = threading.Lock()
        self._clean_streak = 0
        self._pending: dict[str, Future[ProviderReading]] = {}
        self._last_slow: dict[str, float] = {}
        self._cached_slow: dict[str, ProviderReading] = {}
        self._seq = 0
        self._write_failures = 0
        self._last_action = NONE
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._sleep_until = sleep_until
        self.halt_event = threading.Event()
        self.halt: HaltRecord | None = None
        self.harness_fault: str | None = None
        self.records_written = 0
        self.overruns = 0
        self.last_values: dict[str, Any] = {}
        self.provenance: dict[str, str] = {}

    # ------------------------------------------------------------------------------------------------ acquisition
    def _collect(self) -> tuple[dict[str, Any], dict[str, str], float]:
        started = self._mono()
        now = started
        values: dict[str, Any] = {}
        status: dict[str, str] = {}
        fast: dict[str, Future[ProviderReading]] = {}
        for provider in self._providers:
            slow = provider.name in self.config.slow_providers
            pending = self._pending.get(provider.name)
            if pending is not None and pending.done():
                self._pending.pop(provider.name, None)
                if slow:
                    # a slow-cadence reading that finished late is still valid evidence (events are cumulative)
                    try:
                        self._cached_slow[provider.name] = pending.result()
                    except Exception as exc:  # noqa: BLE001
                        self.provenance.setdefault(f"{provider.name}:error", type(exc).__name__)
                pending = None
            if slow:
                last = self._last_slow.get(provider.name)
                due = last is None or now - last >= self.config.slow_interval_s
                if due and pending is None:
                    self._pending[provider.name] = _submit_daemon(
                        provider.read, f"img154b-{provider.name}"
                    )
                    self._last_slow[provider.name] = now
                cached = self._cached_slow.get(provider.name)
                if cached is not None:
                    self._apply(provider, cached, values, status)
                else:
                    for name in provider.fields:
                        values[name], status[name] = None, MISSING
                continue
            if pending is not None:
                for name in provider.fields:
                    values[name], status[name] = None, STUCK
                continue
            future = _submit_daemon(provider.read, f"img154b-{provider.name}")
            self._pending[provider.name] = future
            fast[provider.name] = future
        if fast:
            wait(list(fast.values()), timeout=self.config.provider_timeout_s)
        by_name = {p.name: p for p in self._providers}
        for name, future in fast.items():
            provider = by_name[name]
            if not future.done():
                for field_name in provider.fields:
                    values[field_name], status[field_name] = None, SLOW
                continue
            self._pending.pop(name, None)
            try:
                reading = future.result()
            except Exception as exc:  # noqa: BLE001 - a provider failure is a visible non-ok field
                for field_name in provider.fields:
                    values[field_name], status[field_name] = None, ERROR
                self.provenance.setdefault(f"{name}:error", type(exc).__name__)
                continue
            self._apply(provider, reading, values, status)
        return values, status, self._mono() - started

    def _apply(
        self,
        provider: Provider,
        reading: ProviderReading,
        values: dict[str, Any],
        status: dict[str, str],
    ) -> None:
        for name in provider.fields:
            values[name] = reading.values.get(name)
            state = reading.status.get(name, MISSING)
            status[name] = state
            if state != OK and name != "fault_events":
                values[name] = None
            self.provenance.setdefault(name, reading.source)

    def sample_once(self) -> dict[str, Any]:
        """One tick: acquire, evaluate with the monitor, persist. Deterministic with injected clock and providers."""

        started_mono, started_utc = self._mono(), self._utc()
        values, status, latency = self._collect()
        with self._lock:
            self._seq += 1
            seq = self._seq
            stage = self._stage()
            fault = values.get("fault_events") or ()
            sample = Sample(
                seq=seq,
                mono_s=started_mono,
                utc=started_utc,
                ram_available_bytes=_num(values.get("ram_available_bytes")),
                commit_headroom_bytes=_num(values.get("commit_headroom_bytes")),
                vram_used_bytes=_num(values.get("vram_used_bytes")),
                vram_total_bytes=_num(values.get("vram_total_bytes")),
                shared_vram_bytes=_num(values.get("shared_vram_bytes")),
                gpu_temperature_c=_num(values.get("gpu_temperature_c")),
                gpu_device_present=values.get("gpu_device_present")
                if isinstance(values.get("gpu_device_present"), bool)
                else None,
                fault_events=tuple(str(item) for item in fault),
                stage=stage.stage,
                stage_source=stage.source,
                extra={
                    k: values.get(k)
                    for k in (
                        "gpu_utilization_percent",
                        "gpu_board_power_w",
                        "hard_pages_input_per_s",
                        "forge_tree_working_set_bytes",
                        "forge_tree_private_bytes",
                    )
                },
            )
            decision = self._monitor.ingest(sample)
            essential_ok = all(status.get(name) == OK for name in ESSENTIAL_FIELDS)
            self._clean_streak = (
                self._clean_streak + 1
                if essential_ok and decision.latched_action not in HALT_LEVELS
                else 0
            )
            self.last_values = {k: v for k, v in values.items() if k != "fault_events"}
            action = decision.latched_action
            record = {
                "kind": "sample",
                # ``seq`` is reserved for the durable writer's STREAM sequence (it also counts headers and transitions)
                "sample_seq": seq,
                "mono_s": started_mono,
                "utc": started_utc,
                "latency_ms": round(latency * 1000.0, 3),
                "values": {k: v for k, v in values.items() if k in FIELD_UNITS},
                "status": {k: v for k, v in status.items() if k in FIELD_UNITS},
                "fault_events": list(sample.fault_events),
                "stage": stage.stage,
                "stage_source": stage.source,
                "endpoint": self._endpoint(),
                "owner": dict(self._owner()),
                "monitor": {
                    "action": decision.action,
                    "codes": list(decision.codes),
                    "latched": action,
                },
            }
            self._persist(record)
            if action != self._last_action or decision.codes:
                if action != self._last_action:
                    self._persist(
                        {
                            "kind": "transition",
                            "sample_seq": seq,
                            "mono_s": started_mono,
                            "utc": started_utc,
                            "from": self._last_action,
                            "to": action,
                            "codes": list(decision.codes),
                        }
                    )
                self._last_action = action
            if action in HALT_LEVELS and self.halt is None:
                self.halt = HaltRecord(
                    action,
                    decision.codes,
                    decision.first_trigger,
                    seq,
                    started_mono,
                    started_utc,
                    dict(self.last_values),
                )
                self.halt_event.set()
        return record

    def _persist(self, record: Mapping[str, Any]) -> None:
        try:
            self._writer.append(record)
            self.records_written += 1
            self._write_failures = 0
        except (OSError, ValueError, TypeError):
            self._write_failures += 1
            if (
                self._write_failures >= self.config.write_failure_limit
                and self.harness_fault is None
            ):
                self.harness_fault = "EVIDENCE_WRITE_FAILED"
                self.halt_event.set()

    def write_header(self, **facts: Any) -> None:
        """The provenance record: which source produced which field (the field map is also kept in memory)."""

        self._persist(
            {
                "kind": "header",
                "units": dict(FIELD_UNITS),
                "provenance": dict(self.provenance),
                **facts,
            }
        )

    def watchdog_tick(self) -> None:
        """Called from another thread: staleness detection that does not depend on the sampler thread being alive."""

        with self._lock:
            decision = self._monitor.tick()
            action = decision.latched_action
            if action in HALT_LEVELS and self.halt is None:
                self.halt = HaltRecord(
                    action,
                    decision.codes,
                    decision.first_trigger,
                    decision.seq,
                    self._mono(),
                    self._utc(),
                    dict(self.last_values),
                )
                self.halt_event.set()

    @property
    def sample_count(self) -> int:
        return self._seq

    @property
    def clean_streak(self) -> int:
        """Consecutive samples with every essential field ``ok`` and no latched stop or uncertainty."""

        return self._clean_streak

    # --------------------------------------------------------------------------------------------------- thread
    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("the sampler is already running")
        self._monitor.begin_observation()
        self._thread = threading.Thread(target=self._run, name="img154b-sampler", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        interval = self.config.interval_s
        next_tick = self._mono()
        while not self._stop.is_set():
            try:
                self.sample_once()
            except Exception as exc:  # noqa: BLE001 - the loop must never die silently
                self.harness_fault = f"SAMPLER_LOOP_{type(exc).__name__}"
                self.halt_event.set()
                return
            next_tick += interval
            now = self._mono()
            if next_tick <= now:
                self.overruns += 1
                next_tick = now + interval  # never burst to catch up
            self._wait(max(0.0, next_tick - now))

    def _wait(self, seconds: float) -> None:
        if self._sleep_until is not None:
            self._sleep_until(seconds)
        else:
            self._stop.wait(seconds)

    def stop(self, timeout_s: float = 5.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout_s)
        # provider threads are daemons: a native call that never returns cannot hold the interpreter open at exit


def _num(value: object) -> float | None:
    if value is None or isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


# ---------------------------------------------------------------------------------------------- native assembly


def build_native_providers(
    owned_pids: Callable[[], Sequence[int]],
    *,
    fault_events: Callable[[], Sequence[str]] | None = None,
    expected_gpu_name: str = "RTX 4070 Ti",
) -> tuple[list[Provider], NvmlProvider]:
    """The production provider set. Constructing it touches no device; the first ``read`` initializes NVML and PDH."""

    nvml = NvmlProvider(expected_name_fragment=expected_gpu_name)

    def luid() -> str:
        nvml._initialize()
        total = None
        reading = nvml.read()
        if reading.status.get("vram_total_bytes") == OK:
            total = int(reading.values["vram_total_bytes"])
        return select_gpu_adapter(enumerate_dxgi_adapters(), total).luid

    providers: list[Provider] = [
        NativeMemoryProvider(),
        nvml,
        PdhProvider(_cached(luid)),
        ProcessTreeProvider(owned_pids),
    ]
    if fault_events is not None:
        providers.append(FaultEventProvider(fault_events))
    return providers, nvml


def _cached(function: Callable[[], str]) -> Callable[[], str]:
    box: dict[str, str] = {}

    def wrapper() -> str:
        if "value" not in box:
            box["value"] = function()
        return box["value"]

    return wrapper
