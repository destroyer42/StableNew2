from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import logging
import os
import time
from typing import Any

from src.utils.process_observation import (
    OwnedTreeEvidence,
    ProcessLifecycleEvent,
    ProcessTreeSample,
)

if os.name != "nt":
    raise RuntimeError("Windows job objects are only available on Windows platforms.")

logger = logging.getLogger(__name__)

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
PROCESS_ALL_ACCESS = 0x1F0FFF
PROCESS_SUSPEND_RESUME = 0x0800
JOB_OBJECT_BASIC_AND_IO_ACCOUNTING_INFORMATION = 8
JOB_OBJECT_ASSOCIATE_COMPLETION_PORT_INFORMATION = 7
# Completion-port messages the job object posts (winnt.h JOB_OBJECT_MSG_*); the PID rides in lpOverlapped.
_MSG_ACTIVE_PROCESS_ZERO = 4
_MSG_NEW_PROCESS = 6
_MSG_EXIT_PROCESS = 7
_MSG_ABNORMAL_EXIT_PROCESS = 8
_TEARDOWN_WAIT_SECONDS = 5.0
# A console host outlives its program by a moment; give natural exits this long before terminating what remains.
_NATURAL_EXIT_GRACE_SECONDS = 0.3
_MAX_LIFECYCLE_EVENTS = 4096


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class JOBOBJECT_ASSOCIATE_COMPLETION_PORT(ctypes.Structure):
    _fields_ = [("CompletionKey", ctypes.c_void_p), ("CompletionPort", wintypes.HANDLE)]


class JOBOBJECT_BASIC_ACCOUNTING_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_int64),
        ("TotalKernelTime", ctypes.c_int64),
        ("ThisPeriodTotalUserTime", ctypes.c_int64),
        ("ThisPeriodTotalKernelTime", ctypes.c_int64),
        ("TotalPageFaultCount", wintypes.DWORD),
        ("TotalProcesses", wintypes.DWORD),
        ("ActiveProcesses", wintypes.DWORD),
        ("TotalTerminatedProcesses", wintypes.DWORD),
    ]


class JOBOBJECT_BASIC_AND_IO_ACCOUNTING_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicInfo", JOBOBJECT_BASIC_ACCOUNTING_INFORMATION),
        ("IoInfo", IO_COUNTERS),
    ]


kernel32.CreateJobObjectW.restype = wintypes.HANDLE
kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.TerminateJobObject.restype = wintypes.BOOL
kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
kernel32.CloseHandle.restype = wintypes.BOOL
ntdll = ctypes.WinDLL("ntdll")  # type: ignore[attr-defined]  # Windows-only module
ntdll.NtResumeProcess.restype = ctypes.c_long
ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.SetInformationJobObject.restype = wintypes.BOOL
kernel32.SetInformationJobObject.argtypes = [
    wintypes.HANDLE,
    wintypes.INT,
    wintypes.LPVOID,
    wintypes.DWORD,
]

kernel32.QueryInformationJobObject.argtypes = [
    wintypes.HANDLE,
    wintypes.INT,
    wintypes.LPVOID,
    wintypes.DWORD,
    wintypes.LPVOID,
]
kernel32.QueryInformationJobObject.restype = wintypes.BOOL
kernel32.CreateIoCompletionPort.argtypes = [
    wintypes.HANDLE,
    wintypes.HANDLE,
    ctypes.c_size_t,
    wintypes.DWORD,
]
kernel32.CreateIoCompletionPort.restype = wintypes.HANDLE
kernel32.GetQueuedCompletionStatus.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(ctypes.c_size_t),
    ctypes.POINTER(ctypes.c_void_p),
    wintypes.DWORD,
]
kernel32.GetQueuedCompletionStatus.restype = wintypes.BOOL
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
kernel32.IsProcessInJob.restype = wintypes.BOOL
kernel32.GetPriorityClass.argtypes = [wintypes.HANDLE]
kernel32.GetPriorityClass.restype = wintypes.DWORD
kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)]
kernel32.GetProcessTimes.restype = wintypes.BOOL
get_process_memory_info = kernel32.K32GetProcessMemoryInfo


class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
        (name, ctypes.c_size_t)
        for name in (
            "PeakWorkingSetSize",
            "WorkingSetSize",
            "QuotaPeakPagedPoolUsage",
            "QuotaPagedPoolUsage",
            "QuotaPeakNonPagedPoolUsage",
            "QuotaNonPagedPoolUsage",
            "PagefileUsage",
            "PeakPagefileUsage",
            "PrivateUsage",
        )
    ]


get_process_memory_info.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(PROCESS_MEMORY_COUNTERS_EX),
    wintypes.DWORD,
]
get_process_memory_info.restype = wintypes.BOOL


def _member_sample(job_handle: Any, pid: int) -> tuple[int, int, float, int]:
    # No mutation, even for a recycled PID: prove membership on the retained handle,
    # then read that same kernel object. Never reopen by PID between check and use.
    handle = kernel32.OpenProcess(0x0400 | 0x0010, False, pid)
    if not handle:
        raise OSError("owned member inaccessible")
    try:
        member = wintypes.BOOL()
        if (
            not kernel32.IsProcessInJob(handle, job_handle, ctypes.byref(member))
            or not member.value
        ):
            raise OSError("process is not in the owned job")
        info = PROCESS_MEMORY_COUNTERS_EX()
        info.cb = ctypes.sizeof(info)
        times = [wintypes.FILETIME() for _ in range(4)]
        priority = kernel32.GetPriorityClass(handle)
        if not priority or not get_process_memory_info(handle, ctypes.byref(info), info.cb):
            raise OSError("owned member telemetry unavailable")
        if not kernel32.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
            raise OSError("owned member CPU telemetry unavailable")
        cpu = sum((t.dwHighDateTime << 32) | t.dwLowDateTime for t in times[2:]) / 10_000_000
        return int(info.PrivateUsage), int(info.WorkingSetSize), cpu, int(priority)
    finally:
        kernel32.CloseHandle(handle)


def _member_image(job_handle: Any, pid: int) -> str | None:
    """The executable of ``pid``, only if the handle just opened is a member of this job (PID reuse reads nothing)."""

    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        member = wintypes.BOOL()
        if (
            not kernel32.IsProcessInJob(handle, job_handle, ctypes.byref(member))
            or not member.value
        ):
            return None
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return None
        return buffer.value or None
    finally:
        kernel32.CloseHandle(handle)


def resume_suspended_process(pid: int) -> bool:
    """Resume a process that was created with ``CREATE_SUSPENDED`` and has not run yet.

    Resumes through ``NtResumeProcess`` (the call ``psutil.Process.resume`` makes), which decrements the suspend count
    of the process's threads; for a fresh ``CREATE_SUSPENDED`` process that is its one initial thread.  ``True`` only if
    Windows accepted the request; the caller must not assume the child runs otherwise."""

    handle = kernel32.OpenProcess(PROCESS_SUSPEND_RESUME, False, pid)
    if not handle:
        logger.warning("Could not open pid %s to resume it", pid)
        return False
    try:
        status = ntdll.NtResumeProcess(handle)
    finally:
        kernel32.CloseHandle(handle)
    if status < 0:  # NTSTATUS: negative is failure, 0 and positive statuses are success
        logger.warning("NtResumeProcess failed for pid %s: status %#x", pid, status & 0xFFFFFFFF)
        return False
    return True


class WindowsJobObject:
    """One anonymous Windows job object owned by exactly one container.

    ``name`` is only a diagnostic label. The job object itself is never named: a named job object is a
    session-wide kernel object, so a second container (another StableNew process, a test, a tool) that used
    the same name would silently open the *same* job and ``kill_all`` would terminate the first owner's
    processes. An anonymous job can only be reached through the handle this instance holds.
    """

    def __init__(
        self, name: str, memory_limit_mb: float | None = None, record_lifecycle: bool = False
    ) -> None:
        self._name = name
        self._memory_limit_mb = memory_limit_mb
        self._port: Any = None
        self._events: list[ProcessLifecycleEvent] = []
        self._event_problems: list[str] = []
        self._killed = False
        self._handle = kernel32.CreateJobObjectW(None, None)
        if not self._handle:
            error = ctypes.get_last_error()
            raise OSError(f"CreateJobObjectW failed: {error}")
        self._apply_limits()
        if record_lifecycle:
            self._associate_completion_port()

    def _apply_limits(self) -> None:
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if self._memory_limit_mb:
            info.BasicLimitInformation.LimitFlags |= JOB_OBJECT_LIMIT_JOB_MEMORY
            info.JobMemoryLimit = int(self._memory_limit_mb * 1024 * 1024)
        if self._set_limits(info):
            return
        if self._memory_limit_mb:
            # The memory cap is optional; kill-on-close is what makes the job a safety net.
            logger.warning("Job memory limit was refused; retrying with kill-on-close only")
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            info.JobMemoryLimit = 0
            if self._set_limits(info):
                self._memory_limit_mb = None
                return
        self.close()
        raise OSError(f"SetInformationJobObject(kill-on-close) failed: {ctypes.get_last_error()}")

    def _associate_completion_port(self) -> None:
        """Have the kernel post every process creation and exit in this job to a private port.

        Associated before any process is assigned, so no member can start unrecorded. The runner drains the port
        (``poll_lifecycle``); there is no background thread."""

        port = kernel32.CreateIoCompletionPort(wintypes.HANDLE(-1), None, 0, 1)
        if not port:
            error = getattr(ctypes, "get_last_error", lambda: 0)()
            self.close()
            raise OSError(f"CreateIoCompletionPort failed: {error}")
        self._port = port
        association = JOBOBJECT_ASSOCIATE_COMPLETION_PORT()
        association.CompletionKey = 1
        association.CompletionPort = port
        if not kernel32.SetInformationJobObject(
            self._handle,
            JOB_OBJECT_ASSOCIATE_COMPLETION_PORT_INFORMATION,
            ctypes.byref(association),
            ctypes.sizeof(association),
        ):
            error = getattr(ctypes, "get_last_error", lambda: 0)()
            self.close()
            raise OSError(f"associating the job completion port failed: {error}")

    def poll_lifecycle(self) -> None:
        """Drain every notification the kernel has queued for this job (non-blocking)."""

        if self._port is None:
            return
        while True:
            message = wintypes.DWORD()
            key = ctypes.c_size_t()
            overlapped = ctypes.c_void_p()
            ok = kernel32.GetQueuedCompletionStatus(
                self._port,
                ctypes.byref(message),
                ctypes.byref(key),
                ctypes.byref(overlapped),
                0,
            )
            if not ok:
                if overlapped.value is not None:
                    self._event_problems.append("completion_port_failed_packet")
                break  # timeout (queue empty) or a port failure; a failure shows as incomplete counts
            code = int(message.value)
            kind = {
                _MSG_NEW_PROCESS: "new",
                _MSG_EXIT_PROCESS: "exit",
                _MSG_ABNORMAL_EXIT_PROCESS: "abnormal_exit",
                _MSG_ACTIVE_PROCESS_ZERO: "active_zero",
            }.get(code, f"message_{code}")
            has_pid = code in (_MSG_NEW_PROCESS, _MSG_EXIT_PROCESS, _MSG_ABNORMAL_EXIT_PROCESS)
            pid = int(overlapped.value) if has_pid and overlapped.value else None
            if len(self._events) >= _MAX_LIFECYCLE_EVENTS:
                if "lifecycle_event_cap" not in self._event_problems:
                    self._event_problems.append("lifecycle_event_cap")
                continue
            image = _member_image(self._handle, pid) if kind == "new" and pid else None
            self._events.append(ProcessLifecycleEvent(kind, pid, time.perf_counter_ns(), image))

    def lifecycle_events(self) -> tuple[ProcessLifecycleEvent, ...]:
        if self._port is None:
            raise OSError("owned lifecycle recording was not enabled")
        self.poll_lifecycle()
        return tuple(self._events)

    def _accounting(self) -> tuple[int, int, int, int, int, int]:
        info = JOBOBJECT_BASIC_AND_IO_ACCOUNTING_INFORMATION()
        if not self._handle or not kernel32.QueryInformationJobObject(
            self._handle,
            JOB_OBJECT_BASIC_AND_IO_ACCOUNTING_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
            None,
        ):
            raise OSError("owned job accounting unavailable")
        return (
            int(info.BasicInfo.TotalProcesses),
            int(info.BasicInfo.ActiveProcesses),
            int(info.BasicInfo.TotalTerminatedProcesses),
            int(info.IoInfo.ReadTransferCount),
            int(info.IoInfo.WriteTransferCount),
            int(info.IoInfo.OtherTransferCount),
        )

    def verify_teardown(
        self, root_pid: int, wait_seconds: float = _TEARDOWN_WAIT_SECONDS
    ) -> OwnedTreeEvidence:
        """Close out the owned tree: terminate any member still alive, then prove from the job itself that none remains.

        The record is ``complete`` only when the creation and exit notifications received equal the job's own process
        total and its active count is zero. Any inconsistency leaves ``complete`` false with the reason."""

        if self._port is None:
            raise OSError("owned lifecycle recording was not enabled")
        self.poll_lifecycle()
        total, survivors, _, _, _, _ = self._accounting()
        if survivors and not self._killed:
            grace = time.monotonic() + _NATURAL_EXIT_GRACE_SECONDS
            while survivors and time.monotonic() < grace:
                time.sleep(0.01)
                self.poll_lifecycle()
                total, survivors, _, _, _, _ = self._accounting()
        if survivors:
            self.kill_all()
        deadline = time.monotonic() + max(0.0, wait_seconds)
        while True:
            self.poll_lifecycle()
            total, active, _, read_b, write_b, other_b = self._accounting()
            exits = sum(1 for e in self._events if e.kind in ("exit", "abnormal_exit"))
            if (active == 0 and (exits >= total or self._killed)) or time.monotonic() >= deadline:
                break
            time.sleep(0.01)
        problems = list(self._event_problems)
        events = tuple(self._events)
        created = sum(1 for e in events if e.kind == "new")
        exited = sum(1 for e in events if e.kind in ("exit", "abnormal_exit"))
        if active:
            problems.append("members_still_active_after_kill")
        if created != total:
            problems.append("creation_notifications_do_not_match_job_total")
        # TerminateJobObject posts no exit notification for the members it kills, so after a runner kill a creation
        # without an exit is a terminated member. Without a kill, every member must have reported its own exit.
        exited_pids = {e.pid for e in events if e.kind in ("exit", "abnormal_exit")}
        unreported = [e.pid for e in events if e.kind == "new" and e.pid not in exited_pids]
        if unreported and not self._killed:
            problems.append("exit_notifications_do_not_match_job_total")
        if self._killed:
            now = time.perf_counter_ns()
            events = events + tuple(
                ProcessLifecycleEvent("terminated", pid, now) for pid in unreported
            )
        if exited > total:
            problems.append("more_exits_than_job_total")
        if not any(e.kind == "new" and e.pid == root_pid for e in events):
            problems.append("root_creation_not_recorded")
        return OwnedTreeEvidence(
            root_pid=root_pid,
            events=events,
            total_processes=total,
            survivors_at_end=survivors,
            runner_terminated_survivors=self._killed,
            active_after_teardown=active,
            io_read_bytes=read_b,
            io_write_bytes=write_b,
            io_other_bytes=other_b,
            complete=not problems,
            problems=tuple(problems),
        )

    def _set_limits(self, info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION) -> bool:
        return bool(
            kernel32.SetInformationJobObject(
                self._handle,
                JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(info),
                ctypes.sizeof(info),
            )
        )

    def assign(self, pid: int) -> bool:
        """Assign ``pid`` to this job; ``True`` only if Windows accepted it."""
        proc_handle = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
        if not proc_handle:
            logger.debug("OpenProcess failed for pid %s: %s", pid, ctypes.get_last_error())
            return False
        try:
            if not kernel32.AssignProcessToJobObject(self._handle, proc_handle):
                logger.debug(
                    "AssignProcessToJobObject failed for pid %s: %s", pid, ctypes.get_last_error()
                )
                return False
            return True
        finally:
            kernel32.CloseHandle(proc_handle)

    def kill_all(self) -> None:
        if not self._handle:
            return
        self._killed = True
        kernel32.TerminateJobObject(self._handle, 1)

    def observe_tree(self, root_pid: int) -> ProcessTreeSample:
        if not self._handle:
            raise OSError("owned job is closed")
        # Job membership includes workers even after their launcher exits. Retry a
        # growing list, but never accept a truncated list as complete telemetry.
        for capacity in (64, 256, 1024, 4096):

            class PidList(ctypes.Structure):
                _fields_ = [
                    ("assigned", wintypes.DWORD),
                    ("count", wintypes.DWORD),
                    ("pids", ctypes.c_size_t * capacity),
                ]

            members = PidList()
            ok = kernel32.QueryInformationJobObject(
                self._handle, 3, ctypes.byref(members), ctypes.sizeof(members), None
            )
            if ok and members.count <= capacity and members.assigned == members.count:
                break
        else:
            raise OSError("owned job membership unavailable or oversized")
        if not members.count:
            raise OSError("owned child exited before observation")
        rows = [_member_sample(self._handle, int(pid)) for pid in members.pids[: members.count]]
        return ProcessTreeSample(
            root_pid,
            len(rows),
            sum(r[0] for r in rows),
            sum(r[1] for r in rows),
            sum(r[2] for r in rows),
            all(r[3] == 0x4000 for r in rows),
            rows[0][3],
        )

    def close(self) -> None:
        if self._handle:
            kernel32.CloseHandle(self._handle)
            self._handle = None
        if self._port:
            kernel32.CloseHandle(self._port)
            self._port = None

    def enforced_memory_limit_bytes(self) -> int | None:
        """The committed-memory limit the OS holds for this job right now, read back from the job object.

        ``None`` when the job is closed, the query fails, or no job-wide memory limit is set. This is the OS's answer, not
        the value this instance asked for."""

        if not self._handle:
            return None
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        if not kernel32.QueryInformationJobObject(
            self._handle,
            JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
            None,
        ):
            return None
        if not info.BasicLimitInformation.LimitFlags & JOB_OBJECT_LIMIT_JOB_MEMORY:
            return None
        return int(info.JobMemoryLimit) or None

    def inspect(self) -> dict[str, Any]:
        return {
            "name": self._name,
            "memory_limit_mb": self._memory_limit_mb,
            "handle_open": bool(self._handle),
        }
