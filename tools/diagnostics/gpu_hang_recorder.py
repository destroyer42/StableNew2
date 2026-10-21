"""High-rate, long-lived NVML recorder that pins the instant a GPU stops responding (DIAG-GPU-150).

Why this exists: the application's survivor telemetry spawns ``nvidia-smi`` about every 0.55 s, so a loss is only known to
within one sample and the process spawn itself is a source of NVML init/shutdown churn. This tool is one separate process
that opens NVML once and keeps the handle, samples at 20 Hz by default, and records what the loss itself looks like:

* every sample carries the NVML read latency, so a slowdown before a hang is visible;
* a watchdog thread (no NVML calls) writes ``nvml_call_blocked`` events naming the call that has not returned, so a hang
  is timestamped and attributed even though the sampling thread is stuck inside the driver;
* the PCIe replay counter, current link generation and width, power, clocks, throttle reasons, P-state and host commit
  are recorded every sample (replay-counter growth is the textbook precursor of a marginal link);
* on a device-lost status it writes an ``incident_*.json`` with the preceding seconds, fsyncs it, and keeps probing at 1 Hz
  to log whether the device ever comes back.

It is read-only: NVML queries only, no CUDA context, no GPU control, no queue, runtime or process action. It is not part of
the application and is never imported by it. One instance per machine (an OS file lock enforces this) so two recorders are
never a second polling variable.

    python tools/diagnostics/gpu_hang_recorder.py --probe              # one read of every field, then exit
    python tools/diagnostics/gpu_hang_recorder.py                       # record until Ctrl+C
    python tools/diagnostics/gpu_hang_recorder.py --duration-s 600      # bounded run
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import platform
import sys
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any, Protocol

SCHEMA = "stablenew.gpu-hang-recorder.v1"
TOOL_VERSION = "1"
DEFAULT_INTERVAL_MS = 50
MIN_INTERVAL_MS = 10
DEFAULT_OUT_DIR = "reports/diagnostics/gpu_hang_recorder"
DEFAULT_MAX_FILE_MB = 64
DEFAULT_KEEP_FILES = 12
FSYNC_INTERVAL_S = 0.25
SLOW_READ_MS = 250.0
BLOCKED_AFTER_MS = 300.0
BLOCKED_REPEAT_S = 1.0
LOST_POLL_INTERVAL_S = 1.0
INCIDENT_WINDOW_S = 10.0

# NVML return codes that mean the device (or driver) is gone rather than that one metric is unsupported.
NVML_ERROR_NOT_SUPPORTED = 3
NVML_ERROR_DRIVER_NOT_LOADED = 9
NVML_ERROR_GPU_IS_LOST = 15
NVML_ERROR_RESET_REQUIRED = 16
LOST_CODES = frozenset(
    {NVML_ERROR_DRIVER_NOT_LOADED, NVML_ERROR_GPU_IS_LOST, NVML_ERROR_RESET_REQUIRED}
)
# The metrics a healthy device always answers; if all of them fail together the device is treated as lost.
CORE_METRICS = ("util_gpu_pct", "power_w", "temp_c", "pcie_gen")


class NvmlError(Exception):
    """One NVML call returned a non-zero status."""

    def __init__(self, call: str, code: int, text: str = "") -> None:
        super().__init__(f"{call} -> {code} {text}".strip())
        self.call = call
        self.code = code
        self.text = text


class Provider(Protocol):
    """What the recorder needs from NVML; the real one is ``NvmlProvider``, tests pass a fake."""

    def open(self) -> None: ...
    def close(self) -> None: ...
    def describe(self) -> dict[str, Any]: ...
    def metrics(self) -> dict[str, Callable[[], float | int | str]]: ...
    def pcie_throughput(self) -> dict[str, int]: ...


class HostReader(Protocol):
    def __call__(self) -> dict[str, Any]: ...


# --------------------------------------------------------------------------------------------------------------------
# Real NVML through ctypes (no third-party package)
# --------------------------------------------------------------------------------------------------------------------


class _Utilization(ctypes.Structure):
    _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]


class _Memory(ctypes.Structure):
    _fields_ = [
        ("total", ctypes.c_ulonglong),
        ("free", ctypes.c_ulonglong),
        ("used", ctypes.c_ulonglong),
    ]


class _PciInfo(ctypes.Structure):
    _fields_ = [
        ("busIdLegacy", ctypes.c_char * 16),
        ("domain", ctypes.c_uint),
        ("bus", ctypes.c_uint),
        ("device", ctypes.c_uint),
        ("pciDeviceId", ctypes.c_uint),
        ("pciSubSystemId", ctypes.c_uint),
        ("busId", ctypes.c_char * 32),
    ]


_NVML_CLOCK_GRAPHICS, _NVML_CLOCK_SM, _NVML_CLOCK_MEM, _NVML_CLOCK_VIDEO = 0, 1, 2, 3
_NVML_TEMPERATURE_GPU = 0
_NVML_PCIE_UTIL_TX_BYTES, _NVML_PCIE_UTIL_RX_BYTES = 0, 1


def default_nvml_path() -> str:
    root = os.environ.get("SystemRoot", r"C:\Windows")
    return str(Path(root) / "System32" / "nvml.dll")


class NvmlProvider:
    """Thin ctypes binding. Every call is named so a block or failure can be attributed to it."""

    def __init__(self, *, index: int = 0, library_path: str | None = None) -> None:
        self._index = index
        self._path = library_path or default_nvml_path()
        self._lib: Any = None
        self._handle = ctypes.c_void_p()
        self.on_call: Callable[[str | None], None] = lambda _name: None

    # -- plumbing ------------------------------------------------------------------------------------------------

    def _fn(self, name: str) -> Any:
        return getattr(self._lib, name)

    def _check(self, name: str, code: int) -> None:
        if code != 0:
            raise NvmlError(name, code, self._error_text(code))

    def _error_text(self, code: int) -> str:
        try:
            function = self._fn("nvmlErrorString")
            function.restype = ctypes.c_char_p
            raw = function(code)
            return raw.decode("ascii", "replace") if raw else ""
        except Exception:  # noqa: BLE001 - diagnostics must never raise while describing an error
            return ""

    def _call(self, name: str, *args: Any) -> None:
        self.on_call(name)
        try:
            self._check(name, int(self._fn(name)(*args)))
        finally:
            self.on_call(None)

    def _uint(self, name: str, *leading: Any) -> int:
        value = ctypes.c_uint()
        self._call(name, self._handle, *leading, ctypes.byref(value))
        return int(value.value)

    def _ulonglong(self, name: str) -> int:
        value = ctypes.c_ulonglong()
        self._call(name, self._handle, ctypes.byref(value))
        return int(value.value)

    # -- lifecycle -----------------------------------------------------------------------------------------------

    def open(self) -> None:
        self._lib = (
            ctypes.WinDLL(self._path) if hasattr(ctypes, "WinDLL") else ctypes.CDLL(self._path)
        )
        self._call("nvmlInit_v2")
        try:
            count = ctypes.c_uint()
            self._call("nvmlDeviceGetCount_v2", ctypes.byref(count))
            if self._index >= count.value:
                raise NvmlError(
                    "nvmlDeviceGetCount_v2",
                    NVML_ERROR_GPU_IS_LOST,
                    f"index {self._index} of {count.value}",
                )
            self._call("nvmlDeviceGetHandleByIndex_v2", self._index, ctypes.byref(self._handle))
        except NvmlError:
            self.close()  # leave NVML shut down so the recorder can retry from a clean state
            raise

    def close(self) -> None:
        if self._lib is not None:
            try:
                self._fn("nvmlShutdown")()
            except Exception:  # noqa: BLE001 - shutting down a lost device may fail; nothing to recover
                pass

    def describe(self) -> dict[str, Any]:
        info: dict[str, Any] = {"nvml_library": self._path, "index": self._index}
        buffer = ctypes.create_string_buffer(96)
        try:
            self._call("nvmlSystemGetDriverVersion", buffer, 96)
            info["driver_version"] = buffer.value.decode("ascii", "replace")
        except NvmlError as exc:
            info["driver_version_error"] = str(exc)
        name = ctypes.create_string_buffer(96)
        try:
            self._call("nvmlDeviceGetName", self._handle, name, 96)
            info["name"] = name.value.decode("ascii", "replace")
        except NvmlError as exc:
            info["name_error"] = str(exc)
        pci = _PciInfo()
        try:
            self._call("nvmlDeviceGetPciInfo_v3", self._handle, ctypes.byref(pci))
            info["pci_bus_id"] = pci.busId.decode("ascii", "replace")
            info["pci_device_id"] = f"{pci.pciDeviceId:#010x}"
            info["pci_subsystem_id"] = f"{pci.pciSubSystemId:#010x}"
        except NvmlError as exc:
            info["pci_error"] = str(exc)
        for key, call in (("pcie_gen_max", "nvmlDeviceGetGpuMaxPcieLinkGeneration"),):
            try:
                info[key] = self._uint(call)
            except NvmlError as exc:
                info[key + "_error"] = str(exc)
        return info

    # -- metrics -------------------------------------------------------------------------------------------------

    def _utilization(self) -> _Utilization:
        value = _Utilization()
        self._call("nvmlDeviceGetUtilizationRates", self._handle, ctypes.byref(value))
        return value

    def _memory(self) -> _Memory:
        value = _Memory()
        self._call("nvmlDeviceGetMemoryInfo", self._handle, ctypes.byref(value))
        return value

    def _throttle(self) -> str:
        for name in (
            "nvmlDeviceGetCurrentClocksEventReasons",
            "nvmlDeviceGetCurrentClocksThrottleReasons",
        ):
            if hasattr(self._lib, name):
                return f"{self._ulonglong(name):#06x}"
        raise NvmlError(
            "throttle_reasons", NVML_ERROR_NOT_SUPPORTED, "no throttle-reason entry point"
        )

    def metrics(self) -> dict[str, Callable[[], float | int | str]]:
        def clock(kind: int) -> Callable[[], int]:
            return lambda: self._uint("nvmlDeviceGetClockInfo", kind)

        return {
            "util_gpu_pct": lambda: int(self._utilization().gpu),
            "util_mem_pct": lambda: int(self._utilization().memory),
            "mem_used_mb": lambda: int(self._memory().used // (1024 * 1024)),
            "power_w": lambda: round(self._uint("nvmlDeviceGetPowerUsage") / 1000.0, 2),
            "power_limit_w": lambda: round(
                self._uint("nvmlDeviceGetEnforcedPowerLimit") / 1000.0, 1
            ),
            "temp_c": lambda: self._uint("nvmlDeviceGetTemperature", _NVML_TEMPERATURE_GPU),
            "fan_pct": lambda: self._uint("nvmlDeviceGetFanSpeed"),
            "clock_gr_mhz": clock(_NVML_CLOCK_GRAPHICS),
            "clock_sm_mhz": clock(_NVML_CLOCK_SM),
            "clock_mem_mhz": clock(_NVML_CLOCK_MEM),
            "clock_video_mhz": clock(_NVML_CLOCK_VIDEO),
            "pstate": lambda: self._uint_pstate(),
            "throttle": self._throttle,
            "pcie_gen": lambda: self._uint("nvmlDeviceGetCurrPcieLinkGeneration"),
            "pcie_width": lambda: self._uint("nvmlDeviceGetCurrPcieLinkWidth"),
            "pcie_replay": lambda: self._uint("nvmlDeviceGetPcieReplayCounter"),
            "energy_mj": lambda: self._ulonglong("nvmlDeviceGetTotalEnergyConsumption"),
        }

    def _uint_pstate(self) -> int:
        value = ctypes.c_int()
        self._call("nvmlDeviceGetPerformanceState", self._handle, ctypes.byref(value))
        return int(value.value)

    def pcie_throughput(self) -> dict[str, int]:
        return {
            "pcie_tx_kbps": self._uint("nvmlDeviceGetPcieThroughput", _NVML_PCIE_UTIL_TX_BYTES),
            "pcie_rx_kbps": self._uint("nvmlDeviceGetPcieThroughput", _NVML_PCIE_UTIL_RX_BYTES),
        }


# --------------------------------------------------------------------------------------------------------------------
# Host state (commit charge matters: system commit near its limit was seen in earlier losses)
# --------------------------------------------------------------------------------------------------------------------


class _PerformanceInformation(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("CommitTotal", ctypes.c_size_t),
        ("CommitLimit", ctypes.c_size_t),
        ("CommitPeak", ctypes.c_size_t),
        ("PhysicalTotal", ctypes.c_size_t),
        ("PhysicalAvailable", ctypes.c_size_t),
        ("SystemCache", ctypes.c_size_t),
        ("KernelTotal", ctypes.c_size_t),
        ("KernelPaged", ctypes.c_size_t),
        ("KernelNonpaged", ctypes.c_size_t),
        ("PageSize", ctypes.c_size_t),
        ("HandleCount", ctypes.c_ulong),
        ("ProcessCount", ctypes.c_ulong),
        ("ThreadCount", ctypes.c_ulong),
    ]


def read_host_state() -> dict[str, Any]:
    """Commit and physical memory in MB; ``{}`` off Windows or if the call fails (never raises)."""

    if not hasattr(ctypes, "windll"):
        return {}
    try:
        info = _PerformanceInformation()
        info.cb = ctypes.sizeof(info)
        if not ctypes.windll.psapi.GetPerformanceInfo(ctypes.byref(info), info.cb):
            return {}
        mb = info.PageSize / (1024 * 1024)
        return {
            "commit_used_mb": round(info.CommitTotal * mb),
            "commit_limit_mb": round(info.CommitLimit * mb),
            "phys_avail_mb": round(info.PhysicalAvailable * mb),
            "kernel_nonpaged_mb": round(info.KernelNonpaged * mb),
            "processes": int(info.ProcessCount),
            "threads": int(info.ThreadCount),
        }
    except Exception:  # noqa: BLE001 - a host probe must never take the recorder down
        return {}


# --------------------------------------------------------------------------------------------------------------------
# Recorder
# --------------------------------------------------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class _RotatingJsonl:
    """Append-only JSONL that flushes every record, fsyncs on an interval and prunes old files."""

    def __init__(
        self,
        directory: Path,
        stem: str,
        *,
        max_bytes: int,
        keep: int,
        fsync_interval_s: float,
        clock: Callable[[], float],
        fsync: Callable[[int], None] = os.fsync,
    ) -> None:
        self._dir = directory
        self._stem = stem
        self._max_bytes = max_bytes
        self._keep = max(1, keep)
        self._fsync_interval = fsync_interval_s
        self._clock = clock
        self._fsync = fsync
        self._lock = threading.Lock()
        self._file: IO[str] | None = None
        self._size = 0
        self._part = 0
        self._last_sync = 0.0
        self.header: dict[str, Any] | None = None

    def _open_next(self) -> None:
        if self._file is not None:
            self._file.close()
        self._part += 1
        path = self._dir / f"{self._stem}_{self._part:03d}.jsonl"
        self._file = path.open("a", encoding="utf-8", newline="\n")
        self._size = 0
        self._prune()
        if self.header is not None and self._part > 1:
            self._write_locked(dict(self.header, continued=True, part=self._part))

    def _prune(self) -> None:
        files = sorted(self._dir.glob(f"{self._stem}_*.jsonl"))
        for old in files[: max(0, len(files) - self._keep)]:
            try:
                old.unlink()
            except OSError:
                pass

    def _write_locked(self, record: Mapping[str, Any]) -> None:
        if self._file is None:
            self._open_next()
        assert self._file is not None
        line = json.dumps(record, separators=(",", ":"), default=str) + "\n"
        self._file.write(line)
        self._file.flush()
        self._size += len(line)
        now = self._clock()
        if now - self._last_sync >= self._fsync_interval:
            self._fsync(self._file.fileno())
            self._last_sync = now
        if self._size >= self._max_bytes:
            self._open_next()

    def write(self, record: Mapping[str, Any], *, sync: bool = False) -> None:
        with self._lock:
            self._write_locked(record)
            if sync and self._file is not None:
                self._fsync(self._file.fileno())
                self._last_sync = self._clock()

    def close(self) -> None:
        with self._lock:
            if self._file is not None:
                self._fsync(self._file.fileno())
                self._file.close()
                self._file = None


class Recorder:
    """Samples a provider, writes JSONL, and turns a loss into an incident file."""

    def __init__(
        self,
        provider: Provider,
        *,
        out_dir: Path,
        interval_ms: float = DEFAULT_INTERVAL_MS,
        pcie_throughput_hz: float = 2.0,
        max_file_mb: float = DEFAULT_MAX_FILE_MB,
        keep_files: int = DEFAULT_KEEP_FILES,
        host_reader: HostReader = read_host_state,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        fsync: Callable[[int], None] = os.fsync,
        stamp: str | None = None,
        blocked_after_ms: float = BLOCKED_AFTER_MS,
    ) -> None:
        self._provider = provider
        self._out_dir = out_dir
        self._interval_s = max(MIN_INTERVAL_MS, float(interval_ms)) / 1000.0
        self._tp_every = (
            max(1, round(1.0 / (self._interval_s * pcie_throughput_hz)))
            if pcie_throughput_hz > 0
            else 0
        )
        self._host_reader = host_reader
        self._clock = clock
        self._sleep = sleep
        self._blocked_after_s = blocked_after_ms / 1000.0
        self._stamp = stamp or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        self._seq = 0
        self._recent: deque[dict[str, Any]] = deque()
        self._lost = False
        self._opened = False
        self._open_error: NvmlError | None = None
        self._metrics: dict[str, Callable[[], float | int | str]] = {}
        self._incidents = 0
        self._inflight: tuple[str, float] | None = None
        self._stop = threading.Event()
        self._watchdog: threading.Thread | None = None
        self._last_block_event = 0.0
        out_dir.mkdir(parents=True, exist_ok=True)
        self._log = _RotatingJsonl(
            out_dir,
            f"gpu_hang_recorder_{self._stamp}_{os.getpid()}",
            max_bytes=int(max_file_mb * 1024 * 1024),
            keep=keep_files,
            fsync_interval_s=FSYNC_INTERVAL_S,
            clock=clock,
            fsync=fsync,
        )
        on_call = getattr(provider, "on_call", None)
        if on_call is not None:
            provider.on_call = self._note_call  # type: ignore[attr-defined]

    # -- in-flight call tracking (read by the watchdog) --------------------------------------------------------------

    def _note_call(self, name: str | None) -> None:
        self._inflight = None if name is None else (name, self._clock())

    def _watchdog_loop(self) -> None:
        while not self._stop.wait(0.1):
            inflight = self._inflight
            if inflight is None:
                continue
            name, started = inflight
            now = self._clock()
            blocked_s = now - started
            if (
                blocked_s >= self._blocked_after_s
                and now - self._last_block_event >= BLOCKED_REPEAT_S
            ):
                self._last_block_event = now
                self._log.write(
                    {
                        "event": "nvml_call_blocked",
                        "t_utc": _utc_now(),
                        "call": name,
                        "blocked_ms": round(blocked_s * 1000),
                        "last_seq": self._seq,
                        "host": self._host_reader(),
                    },
                    sync=True,
                )

    # -- sampling -----------------------------------------------------------------------------------------------------

    def start(self) -> None:
        self._log.header = {
            "event": "header",
            "schema": SCHEMA,
            "tool_version": TOOL_VERSION,
            "t_utc": _utc_now(),
            "pid": os.getpid(),
            "argv": sys.argv,
            "interval_ms": self._interval_s * 1000.0,
            "platform": platform.platform(),
            "python": sys.version.split()[0],
        }
        description = self._try_open()
        self._log.write({**self._log.header, "device": description}, sync=True)
        self._watchdog = threading.Thread(
            target=self._watchdog_loop, name="gpu-hang-watchdog", daemon=True
        )
        self._watchdog.start()

    def _try_open(self) -> dict[str, Any]:
        """Open NVML and read the device description; an NVML failure leaves the recorder probing for the device."""

        try:
            self._provider.open()
            description = self._provider.describe()
        except NvmlError as exc:
            self._opened = False
            self._open_error = exc
            self._lost = True
            return {"open_error": str(exc), "open_error_code": exc.code}
        self._metrics = self._provider.metrics()
        self._opened = True
        self._open_error = None
        return description

    def _unopened_record(self) -> dict[str, Any]:
        self._seq += 1
        error = self._open_error
        return {
            "t_utc": _utc_now(),
            "seq": self._seq,
            "read_ms": 0.0,
            "status": "lost",
            "lost_code": error.code if error else NVML_ERROR_GPU_IS_LOST,
            "errors": {"open": error.code if error else NVML_ERROR_GPU_IS_LOST},
        }

    def sample_once(self) -> dict[str, Any]:
        """Read every metric once. A per-metric failure is recorded; a device-level failure marks the sample lost."""

        self._seq += 1
        started = self._clock()
        values: dict[str, Any] = {}
        errors: dict[str, int] = {}
        lost_code: int | None = None
        for key, read in self._metrics.items():
            try:
                values[key] = read()
            except NvmlError as exc:
                errors[key] = exc.code
                if exc.code in LOST_CODES:
                    lost_code = exc.code
        if self._tp_every and self._seq % self._tp_every == 0:
            try:
                values.update(self._provider.pcie_throughput())
            except NvmlError as exc:
                errors["pcie_throughput"] = exc.code
        read_ms = round((self._clock() - started) * 1000.0, 2)
        if lost_code is None and all(key in errors for key in CORE_METRICS):
            lost_code = next(iter(errors.values()))
        record: dict[str, Any] = {
            "t_utc": _utc_now(),
            "seq": self._seq,
            "read_ms": read_ms,
            "status": "lost" if lost_code is not None else ("partial" if errors else "ok"),
            **values,
        }
        if errors:
            record["errors"] = errors
        if lost_code is not None:
            record["lost_code"] = lost_code
        host = self._host_reader()
        if host:
            record["host"] = host
        return record

    def _remember(self, record: dict[str, Any]) -> None:
        self._recent.append(record)
        horizon = max(10, int(INCIDENT_WINDOW_S / self._interval_s))
        while len(self._recent) > horizon:
            self._recent.popleft()

    def _write_incident(self, trigger: dict[str, Any]) -> Path:
        self._incidents += 1
        path = self._out_dir / f"incident_{self._stamp}_{self._incidents:02d}.json"
        payload = {
            "schema": SCHEMA,
            "t_utc": trigger.get("t_utc"),
            "trigger": trigger,
            "window_seconds": INCIDENT_WINDOW_S,
            "samples": list(self._recent),
            "host": self._host_reader(),
        }
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, default=str)
            handle.flush()
            os.fsync(handle.fileno())
        return path

    def step(self) -> float:
        """One loop iteration; returns the seconds to wait before the next one."""

        if not self._opened:
            description = self._try_open()
            if self._opened:
                self._lost = False
                self._log.write(
                    {
                        "event": "gpu_back",
                        "t_utc": _utc_now(),
                        "seq": self._seq,
                        "device": description,
                    },
                    sync=True,
                )
            else:
                self._log.write(self._unopened_record())
                return LOST_POLL_INTERVAL_S
        record = self.sample_once()
        self._log.write(record)
        if record["read_ms"] >= SLOW_READ_MS and record["status"] != "lost":
            self._log.write(
                {
                    "event": "slow_read",
                    "t_utc": record["t_utc"],
                    "seq": record["seq"],
                    "read_ms": record["read_ms"],
                }
            )
        if record["status"] == "lost":
            if not self._lost:
                self._lost = True
                incident = self._write_incident(record)
                self._log.write(
                    {
                        "event": "gpu_lost",
                        "t_utc": record["t_utc"],
                        "seq": record["seq"],
                        "incident_file": incident.name,
                        "lost_code": record.get("lost_code"),
                    },
                    sync=True,
                )
            return LOST_POLL_INTERVAL_S
        self._remember(record)
        if self._lost:
            self._lost = False
            self._log.write(
                {"event": "gpu_back", "t_utc": record["t_utc"], "seq": record["seq"]}, sync=True
            )
        return self._interval_s

    def run(self, *, duration_s: float | None = None) -> None:
        self.start()
        deadline = None if duration_s is None else self._clock() + duration_s
        try:
            next_at = self._clock()
            while not self._stop.is_set():
                if deadline is not None and self._clock() >= deadline:
                    break
                wait = self.step()
                next_at += wait
                delay = next_at - self._clock()
                if delay > 0:
                    self._sleep(delay)
                else:
                    next_at = self._clock()  # fell behind (a slow read); do not burst to catch up
        finally:
            self.close()

    def request_stop(self) -> None:
        self._stop.set()

    def close(self) -> None:
        self._stop.set()
        if self._watchdog is not None:
            self._watchdog.join(timeout=1.0)
        self._log.write({"event": "stopped", "t_utc": _utc_now(), "seq": self._seq}, sync=True)
        self._log.close()
        try:
            self._provider.close()
        except Exception:  # noqa: BLE001 - closing a lost device must not raise out of a diagnostic
            pass


# --------------------------------------------------------------------------------------------------------------------
# Single-instance lock and CLI
# --------------------------------------------------------------------------------------------------------------------


class InstanceLock:
    """An OS file lock held for the life of the process; released automatically if the process dies."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._handle: IO[bytes] | None = None

    def acquire(self) -> bool:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle = self._path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None


def probe(provider: Provider) -> int:
    """Open, read every field once, print the result, and return 0 only if the device answered fully."""

    try:
        provider.open()
    except NvmlError as exc:
        print(json.dumps({"open_error": str(exc), "code": exc.code}))
        return 2
    try:
        report: dict[str, Any] = {"device": provider.describe(), "metrics": {}, "errors": {}}
        for key, read in provider.metrics().items():
            try:
                report["metrics"][key] = read()
            except NvmlError as exc:
                report["errors"][key] = str(exc)
        try:
            report["metrics"].update(provider.pcie_throughput())
        except NvmlError as exc:
            report["errors"]["pcie_throughput"] = str(exc)
        report["host"] = read_host_state()
        print(json.dumps(report, indent=2, default=str))
        return 0 if not report["errors"] else 1
    finally:
        provider.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--interval-ms",
        type=float,
        default=DEFAULT_INTERVAL_MS,
        help=f"sample period, minimum {MIN_INTERVAL_MS}",
    )
    parser.add_argument("--index", type=int, default=0, help="NVML device index")
    parser.add_argument(
        "--pcie-throughput-hz",
        type=float,
        default=2.0,
        help="0 disables; each read blocks about 20 ms",
    )
    parser.add_argument(
        "--duration-s",
        type=float,
        default=None,
        help="stop after this many seconds (default: until Ctrl+C)",
    )
    parser.add_argument("--max-file-mb", type=float, default=DEFAULT_MAX_FILE_MB)
    parser.add_argument("--keep-files", type=int, default=DEFAULT_KEEP_FILES)
    parser.add_argument("--nvml-path", default=None)
    parser.add_argument(
        "--probe", action="store_true", help="read every field once, print it, exit 0/1/2"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    provider = NvmlProvider(index=args.index, library_path=args.nvml_path)
    if args.probe:
        return probe(provider)
    out_dir = Path(args.out_dir)
    lock = InstanceLock(out_dir / ".recorder.lock")
    if not lock.acquire():
        print(
            "another gpu_hang_recorder is already running against this output directory",
            file=sys.stderr,
        )
        return 3
    recorder = Recorder(
        provider,
        out_dir=out_dir,
        interval_ms=args.interval_ms,
        pcie_throughput_hz=args.pcie_throughput_hz,
        max_file_mb=args.max_file_mb,
        keep_files=args.keep_files,
    )
    print(
        f"recording to {out_dir} every {max(MIN_INTERVAL_MS, args.interval_ms):.0f} ms; Ctrl+C to stop",
        file=sys.stderr,
    )
    try:
        recorder.run(duration_s=args.duration_s)
    except KeyboardInterrupt:
        pass
    finally:
        lock.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
