"""Resource telemetry and the frozen safety-stop rule for the PR-VID-160B probe.

Extends the PR-VID-110/150 GPU-sampler concept (``tools/qualification/vid110/monitor.py``) with
closer host-memory observation, since host RAM is this probe's principal identified risk
(PR-VID-160A Gate D). Samples roughly every 0.5s and flushes each row immediately so a hard
failure still leaves a telemetry trail.

Frozen stop rule (documented before the physical run, not tuned afterward):

- available physical RAM < ``LOW_RAM_GB`` for ``LOW_RAM_CONSECUTIVE`` consecutive samples; OR
- swap/pagefile usage >= ``HIGH_SWAP_PERCENT`` while available RAM is also below ``LOW_RAM_GB``
  (rapidly growing pagefile *together with* near-exhausted physical RAM, not swap activity alone).

CUDA OOM / Comfy allocation failure and GPU-lost are surfaced separately by the Comfy HTTP client
and the GPU sampler's own failure to reach ``nvidia-smi``; this module's ``abort_reason`` covers
only the host-memory gate.
"""

from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

LOW_RAM_GB = 1.0
LOW_RAM_CONSECUTIVE = 2
HIGH_SWAP_PERCENT = 90.0

GPU_QUERY = "memory.used,temperature.gpu,power.draw,utilization.gpu"
TELEMETRY_HEADER = (
    "elapsed_s,vram_mib,temp_c,power_w,util_pct,ram_available_gb,swap_used_gb,swap_percent"
)


@dataclass
class ProbePeaks:
    samples: int = 0
    vram_baseline_mib: int = 0
    vram_peak_mib: int = 0
    ram_available_min_gb: float = 0.0
    swap_used_max_gb: float = 0.0
    swap_percent_max: float = 0.0
    temp_peak_c: int = 0
    power_peak_w: float = 0.0
    low_ram_consecutive: int = 0
    stop_reason: str = ""

    def as_dict(self) -> dict[str, float | int | str]:
        return {
            "samples": self.samples,
            "vram_baseline_mib": self.vram_baseline_mib,
            "vram_peak_mib": self.vram_peak_mib,
            "ram_available_min_gb": self.ram_available_min_gb,
            "swap_used_max_gb": self.swap_used_max_gb,
            "swap_percent_max": self.swap_percent_max,
            "temp_peak_c": self.temp_peak_c,
            "power_peak_w": self.power_peak_w,
            "stop_reason": self.stop_reason,
        }


def _gpu_sample() -> tuple[int, int, float, int]:
    out = subprocess.check_output(
        ["nvidia-smi", f"--query-gpu={GPU_QUERY}", "--format=csv,noheader,nounits"],
        text=True,
        timeout=10,
    )
    vram, temp, power, util = (part.strip() for part in out.strip().splitlines()[0].split(","))
    return int(vram), int(temp), float(power), int(util)


def _vram_used_mib() -> int:
    return _gpu_sample()[0]


class ProbeResourceSampler:
    """Background sampler with a frozen host-RAM/swap safety-stop rule.

    Pass ``abort_reason`` to ``tools.qualification.vid110.comfy_client.ComfyClient.wait`` to make
    the client interrupt its own prompt and raise ``ComfyRunError`` the moment the rule trips.
    """

    def __init__(self, interval: float = 0.5, *, log_path: Path | None = None) -> None:
        self.interval = interval
        self._log_path = log_path
        self._log = None
        self._t0 = time.monotonic()
        self.peaks = ProbePeaks()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def _sample(self) -> None:
        import psutil

        try:
            vram, temp, power, _util = _gpu_sample()
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            return
        vmem = psutil.virtual_memory()
        smem = psutil.swap_memory()
        available_gb = vmem.available / 1e9
        swap_used_gb = smem.used / 1e9
        swap_percent = float(smem.percent)

        with self._lock:
            peaks = self.peaks
            peaks.samples += 1
            peaks.vram_peak_mib = max(peaks.vram_peak_mib, vram)
            peaks.temp_peak_c = max(peaks.temp_peak_c, temp)
            peaks.power_peak_w = max(peaks.power_peak_w, power)
            peaks.swap_used_max_gb = max(peaks.swap_used_max_gb, round(swap_used_gb, 2))
            peaks.swap_percent_max = max(peaks.swap_percent_max, swap_percent)
            if peaks.ram_available_min_gb == 0.0 or available_gb < peaks.ram_available_min_gb:
                peaks.ram_available_min_gb = round(available_gb, 2)
            if available_gb < LOW_RAM_GB:
                peaks.low_ram_consecutive += 1
            else:
                peaks.low_ram_consecutive = 0
            if peaks.low_ram_consecutive >= LOW_RAM_CONSECUTIVE and not peaks.stop_reason:
                peaks.stop_reason = (
                    f"available RAM < {LOW_RAM_GB} GB for {peaks.low_ram_consecutive} "
                    f"consecutive samples (last={available_gb:.2f} GB)"
                )
            elif (
                swap_percent >= HIGH_SWAP_PERCENT
                and available_gb < LOW_RAM_GB
                and not peaks.stop_reason
            ):
                peaks.stop_reason = (
                    f"swap {swap_percent:.0f}% (>= {HIGH_SWAP_PERCENT}%) while available RAM "
                    f"{available_gb:.2f} GB (< {LOW_RAM_GB} GB)"
                )
        if self._log is not None:
            self._log.write(
                f"{time.monotonic() - self._t0:.1f},{vram},{temp},{power},{_util},"
                f"{available_gb:.2f},{swap_used_gb:.2f},{swap_percent:.1f}\n"
            )
            self._log.flush()

    def abort_reason(self) -> str:
        with self._lock:
            return self.peaks.stop_reason

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            self._sample()
        if self._log is not None:
            self._log.close()
            self._log = None

    def __enter__(self) -> ProbeResourceSampler:
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
        self._thread = threading.Thread(target=self._run, name="vid160b-sampler", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._sample()
