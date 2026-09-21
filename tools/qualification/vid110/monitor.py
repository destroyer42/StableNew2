"""Peak VRAM / system-RAM sampling while a qualification run executes."""

from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

LOW_RAM_GB = 0.25  # Windows transiently dips this low while mmap-loading big weights
GPU_QUERY = (
    "memory.used,temperature.gpu,power.draw,clocks.gr,clocks.mem,utilization.gpu,"
    "clocks_event_reasons.active"
)
TELEMETRY_HEADER = "elapsed_s,vram_mib,temp_c,power_w,gpu_mhz,mem_mhz,util_pct,throttle_hex,ram_gb"


@dataclass
class ResourcePeaks:
    samples: int = 0
    vram_baseline_mib: int = 0
    vram_peak_mib: int = 0
    ram_available_min_gb: float = 0.0
    last_ram_gb: float = 0.0
    temp_peak_c: int = 0
    power_peak_w: float = 0.0
    gpu_mhz_min_busy: int = 0  # lowest graphics clock while the GPU was >50% utilised
    throttle_reasons_seen: int = 0  # OR of every nvidia-smi clocks_event_reasons bitmask
    low_ram_samples: int = 0  # consecutive samples under the sampler's low-RAM mark
    vram_series: list[int] = field(default_factory=list)

    @property
    def vram_delta_peak_mib(self) -> int:
        """Peak whole-GPU use above the pre-run baseline (other apps stay in the baseline)."""

        return max(0, self.vram_peak_mib - self.vram_baseline_mib)

    def as_dict(self) -> dict[str, float | int]:
        return {
            "samples": self.samples,
            "vram_baseline_mib": self.vram_baseline_mib,
            "vram_peak_mib": self.vram_peak_mib,
            "vram_delta_peak_mib": self.vram_delta_peak_mib,
            "ram_available_min_gb": self.ram_available_min_gb,
            "temp_peak_c": self.temp_peak_c,
            "power_peak_w": self.power_peak_w,
            "gpu_mhz_min_busy": self.gpu_mhz_min_busy,
            "throttle_reasons_seen": hex(self.throttle_reasons_seen),
        }


@dataclass(frozen=True)
class GpuSample:
    vram_mib: int
    temp_c: int
    power_w: float
    gpu_mhz: int
    mem_mhz: int
    util_pct: int
    throttle: int


def parse_gpu_line(line: str) -> GpuSample:
    """Parse one ``nvidia-smi --query-gpu=GPU_QUERY --format=csv,noheader,nounits`` row."""

    fields = [part.strip() for part in line.split(",")]
    vram, temp, power, gpu_mhz, mem_mhz, util, throttle = fields[:7]
    return GpuSample(
        vram_mib=int(vram),
        temp_c=int(temp),
        power_w=float(power),
        gpu_mhz=int(gpu_mhz),
        mem_mhz=int(mem_mhz),
        util_pct=int(util),
        throttle=int(throttle, 16),
    )


def _gpu_sample() -> GpuSample:
    out = subprocess.check_output(
        ["nvidia-smi", f"--query-gpu={GPU_QUERY}", "--format=csv,noheader,nounits"],
        text=True,
        timeout=10,
    )
    return parse_gpu_line(out.strip().splitlines()[0])


def _vram_used_mib() -> int:
    return _gpu_sample().vram_mib


class ResourceSampler:
    """Background sampler (owned thread, always joined) of GPU and RAM headroom."""

    def __init__(self, interval: float = 0.5, *, log_path: Path | None = None) -> None:
        self.interval = interval
        self._log_path = log_path
        self._log = None
        self._t0 = time.monotonic()
        self.peaks = ResourcePeaks()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _sample(self) -> None:
        import psutil

        try:
            gpu = _gpu_sample()
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            return
        used = gpu.vram_mib
        peaks = self.peaks
        peaks.samples += 1
        peaks.vram_peak_mib = max(peaks.vram_peak_mib, used)
        peaks.vram_series.append(used)
        peaks.temp_peak_c = max(peaks.temp_peak_c, gpu.temp_c)
        peaks.power_peak_w = max(peaks.power_peak_w, gpu.power_w)
        peaks.throttle_reasons_seen |= gpu.throttle
        if gpu.util_pct > 50 and (
            peaks.gpu_mhz_min_busy == 0 or gpu.gpu_mhz < peaks.gpu_mhz_min_busy
        ):
            peaks.gpu_mhz_min_busy = gpu.gpu_mhz
        available = psutil.virtual_memory().available / 1e9
        peaks.last_ram_gb = round(available, 2)
        peaks.low_ram_samples = peaks.low_ram_samples + 1 if available < LOW_RAM_GB else 0
        if peaks.ram_available_min_gb == 0.0 or available < peaks.ram_available_min_gb:
            peaks.ram_available_min_gb = round(available, 2)
        if self._log is not None:  # flushed per row so a hard crash still leaves the trail
            self._log.write(
                f"{time.monotonic() - self._t0:.1f},{used},{gpu.temp_c},{gpu.power_w},"
                f"{gpu.gpu_mhz},{gpu.mem_mhz},{gpu.util_pct},{gpu.throttle:#x},{available:.2f}\n"
            )
            self._log.flush()

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            self._sample()
        if self._log is not None:
            self._log.close()
            self._log = None

    def __enter__(self) -> ResourceSampler:
        try:
            self.peaks.vram_baseline_mib = _vram_used_mib()
        except (OSError, subprocess.SubprocessError, ValueError):
            self.peaks.vram_baseline_mib = 0
        self.peaks.vram_peak_mib = self.peaks.vram_baseline_mib
        if self._log_path is not None:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log = self._log_path.open("w", encoding="utf-8")
            self._log.write(TELEMETRY_HEADER + "\n")
        self._t0 = time.monotonic()
        self._thread = threading.Thread(target=self._run, name="vid110-sampler", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._sample()
