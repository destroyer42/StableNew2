"""PR-AI-QUAL-114 privilege-boundary probes: is this process, or an owned child, running with an elevated token?

The qualification harness, the runtime import and every downloaded binary run under a standard-user token. The only
rights the harness needs beyond that are the OS's own delegated right to control event traces (membership of the
``Performance Log Users`` group, granted once by an administrator); nothing here starts, needs or talks to a privileged
process. These probes are read-only: they open a process token with ``TOKEN_QUERY`` and read ``TokenElevation``.

``None`` always means "could not be determined" and is never read as "not elevated".
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

TOKEN_QUERY = 0x0008
TOKEN_ELEVATION = 20  # TOKEN_INFORMATION_CLASS.TokenElevation
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
#: ``BUILTIN\Performance Log Users``: the group the OS delegates trace control to without administrator rights.
PERFORMANCE_LOG_USERS_SID = "S-1-5-32-559"


def _token_elevated(process_handle: int) -> bool | None:
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(
        wintypes.HANDLE(process_handle), TOKEN_QUERY, ctypes.byref(token)
    ):
        return None
    try:
        elevated = wintypes.DWORD(0)
        returned = wintypes.DWORD(0)
        ok = advapi32.GetTokenInformation(
            token,
            TOKEN_ELEVATION,
            ctypes.byref(elevated),
            ctypes.sizeof(elevated),
            ctypes.byref(returned),
        )
        return bool(elevated.value) if ok and returned.value == ctypes.sizeof(elevated) else None
    finally:
        kernel32.CloseHandle(token)


def current_process_elevated() -> bool | None:
    """Whether this process runs with an elevated (full administrator) token. ``None`` off Windows or if unreadable."""

    if os.name != "nt":
        return None
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        return _token_elevated(kernel32.GetCurrentProcess())
    except Exception:  # noqa: BLE001 - unreadable is "unknown", which every caller treats as a refusal
        return None


def process_token_elevated(pid: int) -> bool | None:
    """Whether the live process ``pid`` has an elevated token (read-only, ``PROCESS_QUERY_LIMITED_INFORMATION``).

    Callers pass the pid of a child the bounded runner owns and that is still running; the answer is only meaningful
    then. ``None`` when the process cannot be opened or its token cannot be read."""

    if os.name != "nt":
        return None
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return None
        try:
            return _token_elevated(handle)
        finally:
            kernel32.CloseHandle(handle)
    except Exception:  # noqa: BLE001
        return None


def in_performance_log_users() -> bool:
    """Whether this process's token carries the (enabled) ``Performance Log Users`` group, the OS's delegated right to
    create and control event-trace sessions without administrator rights."""

    if os.name != "nt":
        return False
    try:
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        sid = ctypes.c_void_p()
        advapi32.ConvertStringSidToSidW.argtypes = [
            wintypes.LPCWSTR,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        advapi32.CheckTokenMembership.argtypes = [
            wintypes.HANDLE,
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.BOOL),
        ]
        if not advapi32.ConvertStringSidToSidW(PERFORMANCE_LOG_USERS_SID, ctypes.byref(sid)):
            return False
        try:
            member = wintypes.BOOL(0)
            ok = advapi32.CheckTokenMembership(None, sid, ctypes.byref(member))
            return bool(ok and member.value)
        finally:
            kernel32.LocalFree.argtypes = [ctypes.c_void_p]
            kernel32.LocalFree(sid)
    except Exception:  # noqa: BLE001
        return False


__all__ = [
    "PERFORMANCE_LOG_USERS_SID",
    "current_process_elevated",
    "in_performance_log_users",
    "process_token_elevated",
]
