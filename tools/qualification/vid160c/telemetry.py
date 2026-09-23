"""Commit-aware resource telemetry and the revised PR-VID-160C adjudication stop rule.

Extends -- without modifying -- ``tools.qualification.vid160b.telemetry``'s GPU/RAM/swap sampling
(the sampler that produced the original PR-VID-160B and first-160C evidence, left completely
unchanged and preserved as-is) with Windows-native system commit-charge and owned-process memory
telemetry (``tools.qualification.vid160c.win_memory``), because ``psutil``-reported "available
physical RAM" is reclaimable-cache-aware and is not the same signal as actual Windows
virtual-memory (commit) exhaustion.

Frozen revised stop rule (documented before the adjudication run, not tuned afterward):

1. system commit >= ``COMMIT_PERCENT_ABORT`` of commit limit for ``CONSECUTIVE_SAMPLES``
   consecutive samples; OR
2. system commit headroom < ``COMMIT_HEADROOM_ABORT_GB`` for ``CONSECUTIVE_SAMPLES`` consecutive
   samples; OR
3. available physical RAM < ``EMERGENCY_RAM_GB`` for ``CONSECUTIVE_SAMPLES`` consecutive samples
   (an emergency responsiveness floor, independent of commit); OR
4. CUDA OOM / Comfy allocation failure -- surfaced separately by the Comfy HTTP client; OR
5. GPU-lost / black-screen / max-fan -- surfaced separately by the GPU sampler's own failure to
   reach ``nvidia-smi``.

Available physical RAM below ``WARN_RAM_GB`` (the *original* PR-VID-160B/first-160C threshold) is
recorded as a warning marker only in this module and no longer aborts the run by itself.
"""

from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from tools.qualification.vid160c.win_memory import (
    ProcessMemory,
    read_process_memory,
    read_system_commit,
)

WARN_RAM_GB = 1.0  # the original PR-VID-160B/first-160C threshold -- now a warning, not an abort
EMERGENCY_RAM_GB = 0.25
COMMIT_PERCENT_ABORT = 97.0
COMMIT_HEADROOM_ABORT_GB = 1.0
CONSECUTIVE_SAMPLES = 2

GPU_QUERY = "memory.used,temperature.gpu,power.draw,utilization.gpu"
TELEMETRY_HEADER = (
    "elapsed_s,vram_mib,temp_c,power_w,util_pct,"
    "ram_available_gb,swap_used_gb,swap_percent,"
    "commit_total_gb,commit_limit_gb,commit_headroom_gb,commit_percent,"
    "comfy_working_set_gb,comfy_private_usage_gb,warn_ram_low"
)


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


def _fmt(value: float | None) -> str:
    return "" if value is None else f"{value:.3f}"


@dataclass
class CommitAwarePeaks:
    samples: int = 0
    vram_baseline_mib: int = 0
    vram_peak_mib: int = 0
    ram_available_min_gb: float = 0.0
    swap_used_max_gb: float = 0.0
    swap_percent_max: float = 0.0
    temp_peak_c: int = 0
    power_peak_w: float = 0.0
    commit_limit_gb: float = 0.0
    commit_total_peak_gb: float = 0.0
    commit_percent_peak: float = 0.0
    commit_headroom_min_gb: float = 0.0
    comfy_working_set_peak_gb: float = 0.0
    comfy_private_usage_peak_gb: float = 0.0
    ram_low_consecutive: int = 0
    ram_emergency_consecutive: int = 0
    commit_percent_consecutive: int = 0
    commit_headroom_consecutive: int = 0
    warn_ram_low_seen: bool = False
    stop_reason: str = ""

    def as_dict(self) -> dict[str, float | int | str | bool]:
        return {
            "samples": self.samples,
            "vram_baseline_mib": self.vram_baseline_mib,
            "vram_peak_mib": self.vram_peak_mib,
            "ram_available_min_gb": self.ram_available_min_gb,
            "swap_used_max_gb": self.swap_used_max_gb,
            "swap_percent_max": self.swap_percent_max,
            "temp_peak_c": self.temp_peak_c,
            "power_peak_w": self.power_peak_w,
            "commit_limit_gb": round(self.commit_limit_gb, 2),
            "commit_total_peak_gb": round(self.commit_total_peak_gb, 2),
            "commit_percent_peak": round(self.commit_percent_peak, 2),
            "commit_headroom_min_gb": round(self.commit_headroom_min_gb, 2),
            "comfy_working_set_peak_gb": round(self.comfy_working_set_peak_gb, 2),
            "comfy_private_usage_peak_gb": round(self.comfy_private_usage_peak_gb, 2),
            "warn_ram_low_seen": self.warn_ram_low_seen,
            "stop_reason": self.stop_reason,
        }


class CommitAwareResourceSampler:
    """Background sampler implementing the revised commit-aware PR-VID-160C stop rule. Reuses the
    same ``abort_reason()`` contract ``tools.qualification.vid110.comfy_client.ComfyClient.wait``
    already expects, so it plugs in exactly like ``tools.qualification.vid160b.telemetry
    .ProbeResourceSampler`` did for the first run."""

    def __init__(
        self, *, comfy_pid: int | None, interval: float = 0.5, log_path: Path | None = None
    ) -> None:
        self.interval = interval
        self._comfy_pid = comfy_pid
        self._log_path = log_path
        self._log = None
        self._t0 = time.monotonic()
        self.peaks = CommitAwarePeaks()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def _sample(self) -> None:
        import psutil

        try:
            vram, temp, power, util = _gpu_sample()
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            return
        vmem = psutil.virtual_memory()
        smem = psutil.swap_memory()
        available_gb = vmem.available / 1e9
        swap_used_gb = smem.used / 1e9
        swap_percent = float(smem.percent)

        try:
            commit = read_system_commit()
        except OSError:
            commit = None

        proc_mem: ProcessMemory | None = None
        if self._comfy_pid is not None:
            proc_mem = read_process_memory(self._comfy_pid)

        commit_percent = 0.0
        commit_headroom: float | None = None
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

            if available_gb < WARN_RAM_GB:
                peaks.ram_low_consecutive += 1
                if peaks.ram_low_consecutive >= CONSECUTIVE_SAMPLES:
                    peaks.warn_ram_low_seen = True
            else:
                peaks.ram_low_consecutive = 0

            if available_gb < EMERGENCY_RAM_GB:
                peaks.ram_emergency_consecutive += 1
            else:
                peaks.ram_emergency_consecutive = 0

            if commit is not None:
                peaks.commit_limit_gb = commit.commit_limit_gb
                peaks.commit_total_peak_gb = max(peaks.commit_total_peak_gb, commit.commit_total_gb)
                commit_percent = commit.commit_percent
                peaks.commit_percent_peak = max(peaks.commit_percent_peak, commit_percent)
                commit_headroom = commit.commit_headroom_gb
                if (
                    peaks.commit_headroom_min_gb == 0.0
                    or commit_headroom < peaks.commit_headroom_min_gb
                ):
                    peaks.commit_headroom_min_gb = round(commit_headroom, 2)

                if commit_percent >= COMMIT_PERCENT_ABORT:
                    peaks.commit_percent_consecutive += 1
                else:
                    peaks.commit_percent_consecutive = 0
                if commit_headroom < COMMIT_HEADROOM_ABORT_GB:
                    peaks.commit_headroom_consecutive += 1
                else:
                    peaks.commit_headroom_consecutive = 0

            if proc_mem is not None:
                peaks.comfy_working_set_peak_gb = max(
                    peaks.comfy_working_set_peak_gb, proc_mem.working_set_gb
                )
                peaks.comfy_private_usage_peak_gb = max(
                    peaks.comfy_private_usage_peak_gb, proc_mem.private_usage_gb
                )

            if not peaks.stop_reason:
                if peaks.commit_percent_consecutive >= CONSECUTIVE_SAMPLES:
                    peaks.stop_reason = (
                        f"system commit {commit_percent:.1f}% >= {COMMIT_PERCENT_ABORT}% of "
                        f"commit limit for {peaks.commit_percent_consecutive} consecutive samples"
                    )
                elif peaks.commit_headroom_consecutive >= CONSECUTIVE_SAMPLES:
                    peaks.stop_reason = (
                        f"system commit headroom < {COMMIT_HEADROOM_ABORT_GB} GB for "
                        f"{peaks.commit_headroom_consecutive} consecutive samples "
                        f"(last={commit_headroom:.2f} GB)"
                    )
                elif peaks.ram_emergency_consecutive >= CONSECUTIVE_SAMPLES:
                    peaks.stop_reason = (
                        f"available RAM < {EMERGENCY_RAM_GB} GB (emergency floor) for "
                        f"{peaks.ram_emergency_consecutive} consecutive samples "
                        f"(last={available_gb:.2f} GB)"
                    )
        if self._log is not None:
            self._log.write(
                f"{time.monotonic() - self._t0:.1f},{vram},{temp},{power},{util},"
                f"{available_gb:.2f},{swap_used_gb:.2f},{swap_percent:.1f},"
                f"{_fmt(commit.commit_total_gb if commit else None)},"
                f"{_fmt(commit.commit_limit_gb if commit else None)},"
                f"{_fmt(commit_headroom)},"
                f"{_fmt(commit_percent if commit else None)},"
                f"{_fmt(proc_mem.working_set_gb if proc_mem else None)},"
                f"{_fmt(proc_mem.private_usage_gb if proc_mem else None)},"
                f"{int(available_gb < WARN_RAM_GB)}\n"
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

    def __enter__(self) -> CommitAwareResourceSampler:
        try:
            self.peaks.vram_baseline_mib = _vram_used_mib()
        except (OSError, subprocess.SubprocessError, ValueError):
            self.peaks.vram_baseline_mib = 0
        self.peaks.vram_peak_mib = self.peaks.vram_baseline_mib
        try:
            self.peaks.commit_limit_gb = read_system_commit().commit_limit_gb
        except OSError:
            pass
        if self._log_path is not None:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log = self._log_path.open("w", encoding="utf-8")
            self._log.write(TELEMETRY_HEADER + "\n")
        self._t0 = time.monotonic()
        self._thread = threading.Thread(
            target=self._run, name="vid160c-commit-sampler", daemon=True
        )
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._sample()
