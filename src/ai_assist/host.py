"""Read-only host seams: memory and generation activity. Injected into the service so tests never touch the machine.

Memory is reported in GiB (1024**3 bytes) throughout this package. The repository also contains decimal-GB readings
(``forge_klein_readiness``); an AI gate must never mix the two, so the unit is part of every field name here.
"""

from __future__ import annotations

import ctypes
import logging
import math
import sys
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_GIB = 1024**3


@dataclass(frozen=True, slots=True)
class HostMemory:
    available_gib: float
    commit_headroom_gib: float


@dataclass(frozen=True, slots=True)
class GenerationActivity:
    """What generation is doing right now, as reported by an injected read-only provider."""

    running_jobs: int = 0
    gpu_quarantined: bool = False


MemoryProbe = Callable[[], HostMemory | None]
GenerationActivityProvider = Callable[[], GenerationActivity]


def checked_activity(value: object) -> GenerationActivity | None:
    """``value`` if it is a well-formed activity reading, else ``None`` (which every caller treats as a conflict)."""

    if (
        isinstance(value, GenerationActivity)
        and type(value.running_jobs) is int
        and value.running_jobs >= 0
        and type(value.gpu_quarantined) is bool
    ):
        return value
    return None


def checked_memory(value: object) -> HostMemory | None:
    """``value`` if it is a well-formed, finite, non-negative reading, else ``None`` (treated as a failed reading).

    A NaN would compare false against every threshold and read as "plenty", so it must never get past this point.
    """

    if isinstance(value, HostMemory) and all(
        isinstance(number, (int, float))
        and not isinstance(number, bool)
        and math.isfinite(number)
        and number >= 0
        for number in (value.available_gib, value.commit_headroom_gib)
    ):
        return value
    return None


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


def read_host_memory() -> HostMemory | None:
    """System available physical RAM and commit headroom in GiB, or ``None`` when either cannot be read.

    ``None`` is a failed reading, never "plenty": the caller must refuse. Commit headroom exists only on Windows, which is
    the supported platform for this feature.
    """

    if sys.platform != "win32":
        return None
    try:
        info = _PerformanceInformation()
        info.cb = ctypes.sizeof(info)
        if not ctypes.windll.psapi.GetPerformanceInfo(ctypes.byref(info), info.cb):  # type: ignore[attr-defined,unused-ignore]
            return None
        page = int(info.PageSize)
        return HostMemory(
            available_gib=int(info.PhysicalAvailable) * page / _GIB,
            commit_headroom_gib=max(0, int(info.CommitLimit) - int(info.CommitTotal)) * page / _GIB,
        )
    except Exception:  # noqa: BLE001 - any failure to read is "unknown", which the caller treats as a refusal
        logger.debug("Host memory is unreadable", exc_info=True)
        return None


__all__ = [
    "GenerationActivity",
    "GenerationActivityProvider",
    "HostMemory",
    "MemoryProbe",
    "checked_activity",
    "checked_memory",
    "read_host_memory",
]
