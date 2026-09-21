"""Peak VRAM / system-RAM sampling while a qualification run executes."""

from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass, field

LOW_RAM_GB = 0.25  # Windows transiently dips this low while mmap-loading big weights


@dataclass
class ResourcePeaks:
    samples: int = 0
    vram_baseline_mib: int = 0
    vram_peak_mib: int = 0
    ram_available_min_gb: float = 0.0
    last_ram_gb: float = 0.0
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
        }


def _vram_used_mib() -> int:
    out = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        text=True,
        timeout=10,
    )
    return int(out.strip().splitlines()[0])


class ResourceSampler:
    """Background sampler (owned thread, always joined) of GPU and RAM headroom."""

    def __init__(self, interval: float = 0.5) -> None:
        self.interval = interval
        self.peaks = ResourcePeaks()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _sample(self) -> None:
        import psutil

        try:
            used = _vram_used_mib()
        except (OSError, subprocess.SubprocessError, ValueError):
            return
        peaks = self.peaks
        peaks.samples += 1
        peaks.vram_peak_mib = max(peaks.vram_peak_mib, used)
        peaks.vram_series.append(used)
        available = psutil.virtual_memory().available / 1e9
        peaks.last_ram_gb = round(available, 2)
        peaks.low_ram_samples = peaks.low_ram_samples + 1 if available < LOW_RAM_GB else 0
        if peaks.ram_available_min_gb == 0.0 or available < peaks.ram_available_min_gb:
            peaks.ram_available_min_gb = round(available, 2)

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            self._sample()

    def __enter__(self) -> ResourceSampler:
        try:
            self.peaks.vram_baseline_mib = _vram_used_mib()
        except (OSError, subprocess.SubprocessError, ValueError):
            self.peaks.vram_baseline_mib = 0
        self.peaks.vram_peak_mib = self.peaks.vram_baseline_mib
        self._thread = threading.Thread(target=self._run, name="vid110-sampler", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._sample()
