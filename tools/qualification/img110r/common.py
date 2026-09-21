"""Shared, torch-free pieces of the IMG-110R qualification: levels, presets, records, telemetry.

The run scripts import this module inside the disposable environments (standard library
plus ``psutil`` only).  Failure classification and the verdict rules live here and in
``verdict.py`` so they can be unit-tested without a GPU.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

OFFICIAL_REPO = "ideogram-ai/ideogram-4-nf4"
OFFICIAL_REVISION = "f664347839e0a87bc495f5c9483cc0014b8e344e"
DIFFUSERS_REPO = "ideogram-ai/ideogram-4-nf4-diffusers"
DIFFUSERS_REVISION = "1874bc70267ba2c823a7239e1d70dd308c8d64dc"
SEED = 0

# name -> (num_steps, guidance in the OFFICIAL loop-index order, mu, std).  Index 0 of the
# guidance tuple is the LAST sampling step; Diffusers wants first-step-first (reversed).
PRESETS: dict[str, tuple[int, tuple[float, ...], float, float]] = {
    "V4_QUALITY_48": (48, (3.0,) * 3 + (7.0,) * 45, 0.0, 1.5),
    "V4_DEFAULT_20": (20, (3.0,) * 2 + (7.0,) * 18, 0.0, 1.75),
    "V4_TURBO_12": (12, (3.0,) * 1 + (7.0,) * 11, 0.5, 1.75),
}


@dataclass(frozen=True)
class Level:
    number: int
    width: int
    height: int
    preset: str

    @property
    def pixels(self) -> int:
        return self.width * self.height


LEVELS: dict[int, Level] = {
    1: Level(1, 512, 512, "V4_TURBO_12"),
    2: Level(2, 768, 1024, "V4_TURBO_12"),
    3: Level(3, 1024, 1024, "V4_DEFAULT_20"),
    4: Level(4, 1024, 1024, "V4_QUALITY_48"),
}


def diffusers_guidance(preset: str) -> list[float]:
    """The preset's per-step guidance in Diffusers' first-step-first order."""

    return list(reversed(PRESETS[preset][1]))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def mib(value: float) -> float:
    return round(value / (1024 * 1024), 2)


# --------------------------------------------------------------------------- telemetry

GPU_QUERY = (
    "memory.used,memory.total,temperature.gpu,power.draw,clocks.gr,utilization.gpu,"
    "clocks_event_reasons.active"
)
TELEMETRY_HEADER = (
    "elapsed_s,vram_used_mib,temp_c,power_w,gpu_mhz,util_pct,throttle_hex,"
    "torch_alloc_mib,torch_reserved_mib,proc_private_mib,ram_available_gb,stage"
)


@dataclass(frozen=True)
class GpuSample:
    vram_used_mib: int
    vram_total_mib: int
    temp_c: int
    power_w: float
    gpu_mhz: int
    util_pct: int
    throttle: int


def parse_gpu_line(line: str) -> GpuSample:
    fields = [part.strip() for part in line.split(",")]
    used, total, temp, power, clock, util, throttle = fields[:7]
    return GpuSample(
        int(used), int(total), int(temp), float(power), int(clock), int(util), int(throttle, 16)
    )


def query_gpu() -> GpuSample:
    out = subprocess.check_output(
        ["nvidia-smi", f"--query-gpu={GPU_QUERY}", "--format=csv,noheader,nounits"],
        text=True,
        timeout=10,
    )
    return parse_gpu_line(out.strip().splitlines()[0])


@dataclass
class Peaks:
    samples: int = 0
    vram_used_mib: int = 0
    torch_allocated_mib: float = 0.0
    torch_reserved_mib: float = 0.0
    proc_private_mib: float = 0.0
    ram_available_min_gb: float = 0.0
    temp_c: int = 0
    power_w: float = 0.0
    util_pct: int = 0
    throttle_seen: int = 0
    gpu_mhz_min_busy: int = 0

    def as_dict(self) -> dict[str, Any]:
        record = asdict(self)
        record["throttle_seen"] = hex(self.throttle_seen)
        return record


class Telemetry:
    """Background sampler: driver VRAM, Torch allocator, process/system RAM, GPU health.

    ``torch_stats`` is an optional callable returning ``(allocated_mib, reserved_mib)``.
    Every row is flushed so a hard reset still leaves a trail on disk.
    """

    def __init__(self, log_path: Path, torch_stats: Any = None, interval: float = 0.5) -> None:
        self.log_path = log_path
        self.torch_stats = torch_stats
        self.interval = interval
        self.peaks = Peaks()
        self.stage = "init"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._log: Any = None
        self._t0 = time.monotonic()

    def _sample(self) -> None:
        import psutil

        try:
            gpu = query_gpu()
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            return
        allocated = reserved = 0.0
        if self.torch_stats is not None:
            try:
                allocated, reserved = self.torch_stats()
            except Exception:  # noqa: BLE001 - a poisoned CUDA context must not kill the sampler
                allocated = reserved = -1.0
        process = psutil.Process()
        private = mib(getattr(process.memory_info(), "private", process.memory_info().rss))
        available = psutil.virtual_memory().available / 1e9
        peaks = self.peaks
        peaks.samples += 1
        peaks.vram_used_mib = max(peaks.vram_used_mib, gpu.vram_used_mib)
        peaks.torch_allocated_mib = max(peaks.torch_allocated_mib, allocated)
        peaks.torch_reserved_mib = max(peaks.torch_reserved_mib, reserved)
        peaks.proc_private_mib = max(peaks.proc_private_mib, private)
        peaks.temp_c = max(peaks.temp_c, gpu.temp_c)
        peaks.power_w = max(peaks.power_w, gpu.power_w)
        peaks.util_pct = max(peaks.util_pct, gpu.util_pct)
        peaks.throttle_seen |= gpu.throttle
        if gpu.util_pct > 50 and (
            peaks.gpu_mhz_min_busy == 0 or gpu.gpu_mhz < peaks.gpu_mhz_min_busy
        ):
            peaks.gpu_mhz_min_busy = gpu.gpu_mhz
        if peaks.ram_available_min_gb == 0.0 or available < peaks.ram_available_min_gb:
            peaks.ram_available_min_gb = round(available, 2)
        if self._log is not None:
            self._log.write(
                f"{time.monotonic() - self._t0:.1f},{gpu.vram_used_mib},{gpu.temp_c},{gpu.power_w},"
                f"{gpu.gpu_mhz},{gpu.util_pct},{gpu.throttle:#x},{allocated:.0f},{reserved:.0f},"
                f"{private:.0f},{available:.2f},{self.stage}\n"
            )
            self._log.flush()

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            self._sample()

    def __enter__(self) -> Telemetry:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log = self.log_path.open("w", encoding="utf-8")
        self._log.write(TELEMETRY_HEADER + "\n")
        self._t0 = time.monotonic()
        self._thread = threading.Thread(target=self._run, name="img110r-telemetry", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._sample()
        if self._log is not None:
            self._log.close()
            self._log = None


# ----------------------------------------------------------------------------- records


@dataclass
class RunRecord:
    run_id: str
    runtime: str  # official-as-shipped | official-staged | diffusers-* ...
    family: str  # official | diffusers
    level: int
    width: int
    height: int
    preset: str
    steps: int
    seed: int = SEED
    vram_cap_mib: int | None = None
    prompt_sha256: str = ""
    model: dict[str, str] = field(default_factory=dict)
    packages: dict[str, str] = field(default_factory=dict)
    gpu_baseline: dict[str, Any] = field(default_factory=dict)
    timing: dict[str, Any] = field(default_factory=dict)
    peaks: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)
    success: bool = False
    stage: str = "created"
    exception_type: str = ""
    exception: str = ""
    failing_operation: str = ""
    context_poisoned: bool = False
    timed_out: bool = False
    fault_events: list[dict[str, Any]] = field(default_factory=list)
    classification: str = ""
    notes: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def read(cls, path: Path) -> RunRecord:
        return cls(**json.loads(path.read_text(encoding="utf-8")))


# Message fragments that mean the CUDA context can no longer be trusted (never retried).
_POISON = (
    "illegal memory access",
    "unspecified launch failure",
    "device-side assert",
    "cuda error",
    "cublas_status",
    "cudnn_status",
    "gpu is lost",
    "misaligned address",
)
_ACQUISITION = (
    "filenotfounderror",
    "entrynotfound",
    "gatedrepo",
    "repositorynotfound",
    "missing keys",
    "unexpected keys",
    "size mismatch",
    "no such file",
    "401",
    "403",
    "404",
)


def is_context_poisoning(exception_type: str, message: str) -> bool:
    text = f"{exception_type} {message}".lower()
    if "out of memory" in text and "cuda error" not in text:
        return False
    return any(marker in text for marker in _POISON)


def classify_failure(record: RunRecord) -> str:
    """Map one run to a root-cause class (the brief's a-f) or ``success``.

    Classes: success, acquisition_schema, harness, runtime_api_offload,
    dtype_kernel_driver, resource_exhaustion, performance_only, no_progress_timeout,
    machine_fault, unclassified.
    """

    if record.success:
        return "success"
    text = f"{record.exception_type} {record.exception}".lower()
    reached_denoising = record.stage in {"denoising", "decoding", "complete_failed_after_step"}
    if "out of memory" in text or "outofmemoryerror" in text:
        return "resource_exhaustion"
    if record.timed_out:
        return "performance_only" if reached_denoising else "no_progress_timeout"
    if record.context_poisoned or is_context_poisoning(record.exception_type, record.exception):
        return "dtype_kernel_driver"
    if any(marker in text for marker in _ACQUISITION):
        return "acquisition_schema"
    if "offload" in text or "hook" in text or "meta tensor" in text or "device_map" in text:
        return "runtime_api_offload"
    if "typeerror" in text or "unexpected keyword" in text or "attributeerror" in text:
        return "harness"
    if record.stage in {"created", "started"} and not record.exception_type:
        return "machine_fault"  # process vanished with no exception: crash/reset
    return "unclassified"
