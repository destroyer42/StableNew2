"""Conservative host-memory readiness for the FLUX.2 Klein profile (PR-IMG-116).

PR-IMG-115 proved the GPU fit but severe host-memory pressure on the only qualified machine: the
Forge process tree's private memory peaked near 26 GiB and available RAM fell to ~0 during the lazy
model load. So a Klein dispatch is gated on the *total* physical RAM of the qualified machine class
(a hard failure below 32e9 bytes). Currently available RAM is recorded as evidence only: no floor and no
numeric warning exist because IMG-115 captured no trustworthy pre-dispatch baseline to derive one from.

This is a read-only probe. It does not schedule, lease, free or kill anything, and it is not a
generic resource manager (PR-IMG-130 / scheduler work is out of scope).
"""

from __future__ import annotations

import ctypes
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from src.image_backends.forge_klein_profile import KleinProfile, KleinProfileError

logger = logging.getLogger(__name__)

_GB = 1e9


@dataclass(frozen=True, slots=True)
class HostMemorySnapshot:
    total_bytes: int
    available_bytes: int
    #: Windows commit headroom (commit limit - commit total); ``None`` where unsupported.
    commit_headroom_bytes: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_physical_gb": round(self.total_bytes / _GB, 2),
            "available_physical_gb": round(self.available_bytes / _GB, 2),
            "commit_headroom_gb": (
                None
                if self.commit_headroom_bytes is None
                else round(self.commit_headroom_bytes / _GB, 2)
            ),
        }


@dataclass(frozen=True, slots=True)
class KleinReadiness:
    snapshot: HostMemorySnapshot

    def as_dict(self) -> dict[str, Any]:
        return {**self.snapshot.as_dict(), "available_ram_policy": "observational only; no floor"}


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


def _commit_headroom_bytes() -> int | None:
    if sys.platform != "win32":
        return None
    try:
        info = _PerformanceInformation()
        info.cb = ctypes.sizeof(info)
        if not ctypes.windll.psapi.GetPerformanceInfo(ctypes.byref(info), info.cb):  # type: ignore[attr-defined,unused-ignore]
            return None
        return int(max(0, info.CommitLimit - info.CommitTotal) * info.PageSize)
    except Exception:
        logger.debug("Commit headroom is unavailable", exc_info=True)
        return None


def read_host_memory() -> HostMemorySnapshot:
    import psutil

    memory = psutil.virtual_memory()
    return HostMemorySnapshot(
        total_bytes=int(memory.total),
        available_bytes=int(memory.available),
        commit_headroom_bytes=_commit_headroom_bytes(),
    )


def check_klein_host_memory(
    profile: KleinProfile,
    *,
    probe: Callable[[], HostMemorySnapshot] = read_host_memory,
) -> KleinReadiness:
    """Raise ``KleinProfileError`` below the 32-GB-class total RAM; otherwise return the readings (evidence)."""

    snapshot = probe()
    if snapshot.total_bytes < profile.min_total_ram_bytes:
        raise KleinProfileError(
            f"{profile.display_name} requires a 32-GB-class host (at least "
            f"{profile.min_total_ram_bytes / _GB:.0f} GB of physical RAM); this host reports "
            f"{snapshot.total_bytes / _GB:.1f} GB. Host memory readings: {snapshot.as_dict()}"
        )
    return KleinReadiness(snapshot=snapshot)


__all__ = [
    "HostMemorySnapshot",
    "KleinReadiness",
    "check_klein_host_memory",
    "read_host_memory",
]
