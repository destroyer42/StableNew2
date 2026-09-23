"""Windows-native commit-charge telemetry via ``ctypes`` (no new dependency).

``psutil.virtual_memory().available`` (the signal PR-VID-160B's original safety guard used)
describes immediately available/reclaimable *physical* RAM. Windows treats standby file-cache
pages as "available" even though they can be discarded instantly, so a low reading there does not
by itself prove the system is out of allocatable memory. The more meaningful Windows exhaustion
signal is *system commit* -- committed virtual memory (RAM + pagefile) versus the current commit
limit -- which this module reads directly via ``GetPerformanceInfo`` (psapi.dll) and
``GlobalMemoryStatusEx`` (kernel32.dll), and per-process committed memory via
``GetProcessMemoryInfo``. No administrator privileges are required for a same-user process.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

_GB = 1024**3

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_PROCESS_VM_READ = 0x0010


class _PERFORMANCE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
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
        ("HandleCount", wintypes.DWORD),
        ("ProcessCount", wintypes.DWORD),
        ("ThreadCount", wintypes.DWORD),
    ]


class _PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


class _PROCESS_MEMORY_COUNTERS_EX2(ctypes.Structure):
    _fields_ = _PROCESS_MEMORY_COUNTERS_EX._fields_ + [
        ("PrivateWorkingSetSize", ctypes.c_size_t),
        ("SharedCommitUsage", ctypes.c_uint64),
    ]


@dataclass(frozen=True)
class SystemCommit:
    commit_total_gb: float
    commit_limit_gb: float
    commit_peak_gb: float
    commit_headroom_gb: float
    commit_percent: float
    physical_total_gb: float
    physical_available_gb: float


@dataclass(frozen=True)
class ProcessMemory:
    working_set_gb: float
    peak_working_set_gb: float
    private_usage_gb: float
    pagefile_usage_gb: float
    peak_pagefile_usage_gb: float
    private_working_set_gb: float | None  # EX2 only; None on EX fallback
    shared_commit_gb: float | None  # EX2 only; None on EX fallback


def read_system_commit() -> SystemCommit:
    """Raises ``OSError`` if ``GetPerformanceInfo`` fails (e.g. non-Windows)."""

    info = _PERFORMANCE_INFORMATION()
    info.cb = ctypes.sizeof(info)
    ok = ctypes.windll.psapi.GetPerformanceInfo(ctypes.byref(info), info.cb)  # type: ignore[attr-defined]
    if not ok:
        raise OSError("GetPerformanceInfo failed")
    page = info.PageSize or 4096
    commit_total = info.CommitTotal * page
    commit_limit = info.CommitLimit * page
    commit_peak = info.CommitPeak * page
    physical_total = info.PhysicalTotal * page
    physical_available = info.PhysicalAvailable * page
    headroom = commit_limit - commit_total
    percent = (commit_total / commit_limit * 100.0) if commit_limit else 0.0
    return SystemCommit(
        commit_total_gb=commit_total / _GB,
        commit_limit_gb=commit_limit / _GB,
        commit_peak_gb=commit_peak / _GB,
        commit_headroom_gb=headroom / _GB,
        commit_percent=percent,
        physical_total_gb=physical_total / _GB,
        physical_available_gb=physical_available / _GB,
    )


def read_process_memory(pid: int) -> ProcessMemory | None:
    """Best-effort ``PROCESS_MEMORY_COUNTERS_EX2``, cleanly falling back to ``EX`` when the OS/
    Python combination does not populate the EX2 extension fields. Returns ``None`` if the process
    cannot be opened (e.g. it has already exited) rather than raising."""

    handle = ctypes.windll.kernel32.OpenProcess(  # type: ignore[attr-defined]
        _PROCESS_QUERY_LIMITED_INFORMATION | _PROCESS_VM_READ, False, pid
    )
    if not handle:
        return None
    try:
        ex2 = _PROCESS_MEMORY_COUNTERS_EX2()
        ex2.cb = ctypes.sizeof(ex2)
        if ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(ex2), ex2.cb):  # type: ignore[attr-defined]
            return ProcessMemory(
                working_set_gb=ex2.WorkingSetSize / _GB,
                peak_working_set_gb=ex2.PeakWorkingSetSize / _GB,
                private_usage_gb=ex2.PrivateUsage / _GB,
                pagefile_usage_gb=ex2.PagefileUsage / _GB,
                peak_pagefile_usage_gb=ex2.PeakPagefileUsage / _GB,
                private_working_set_gb=ex2.PrivateWorkingSetSize / _GB,
                shared_commit_gb=ex2.SharedCommitUsage / _GB,
            )
        ex = _PROCESS_MEMORY_COUNTERS_EX()
        ex.cb = ctypes.sizeof(ex)
        if ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(ex), ex.cb):  # type: ignore[attr-defined]
            return ProcessMemory(
                working_set_gb=ex.WorkingSetSize / _GB,
                peak_working_set_gb=ex.PeakWorkingSetSize / _GB,
                private_usage_gb=ex.PrivateUsage / _GB,
                pagefile_usage_gb=ex.PagefileUsage / _GB,
                peak_pagefile_usage_gb=ex.PeakPagefileUsage / _GB,
                private_working_set_gb=None,
                shared_commit_gb=None,
            )
        return None
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]
