"""Move files to the Windows Recycle Bin, and say beforehand when it cannot take them (KEEP-SPACE).

Nothing here deletes a file. Windows deletes permanently what a Recycle Bin cannot hold (an item larger than its size
limit, and the oldest items once it is full), so a caller moves only what fits in the free room of the drive's bin, and
anything that cannot be established is a refusal. The move is also made with ``FOF_WANTNUKEWARNING``: if Windows would
destroy a file after all, it asks first instead of doing it quietly.

The Shell API reports what a bin holds (``SHQueryRecycleBinW``) but has no call for its size limit; the limit is read
where Explorer's Recycle Bin Properties keeps it, per volume, in the user's registry.
"""

from __future__ import annotations

import ctypes
import os
from collections.abc import Sequence
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Protocol

MAX_SHELL_PATH: Final = 259  # SHFileOperationW takes no longer path
BATCH_FILES: Final = 200

FO_DELETE: Final = 0x0003
FOF_SILENT: Final = 0x0004
FOF_NOCONFIRMATION: Final = 0x0010
FOF_ALLOWUNDO: Final = 0x0040
FOF_NOERRORUI: Final = 0x0400
FOF_NO_CONNECTED_ELEMENTS: Final = 0x2000
FOF_WANTNUKEWARNING: Final = 0x4000
RECYCLE_FLAGS: Final = (
    FOF_ALLOWUNDO
    | FOF_WANTNUKEWARNING
    | FOF_NOCONFIRMATION
    | FOF_NOERRORUI
    | FOF_SILENT
    | FOF_NO_CONNECTED_ELEMENTS
)
_DRIVE_FIXED: Final = 3
_MEBIBYTE: Final = 1024 * 1024
_EXPLORER: Final = r"Software\Microsoft\Windows\CurrentVersion\Explorer\BitBucket\Volume"
_POLICIES: Final = r"Software\Microsoft\Windows\CurrentVersion\Policies\Explorer"


class RecycleBinRefused(RuntimeError):
    """The Recycle Bin cannot take the files, or whether it can is unknown. The message is for the operator."""


@dataclass(frozen=True)
class BinRoom:
    volume: str
    limit_bytes: int
    used_bytes: int

    @property
    def free_bytes(self) -> int:
        return max(0, self.limit_bytes - self.used_bytes)

    def describe(self) -> str:
        return (
            f"The Recycle Bin of {self.volume} has {self.free_bytes / 1e9:.1f} GB free of its "
            f"{self.limit_bytes / 1e9:.1f} GB limit."
        )


class Shell(Protocol):
    """The Windows calls this module needs; tests replace them."""

    def volume_root(self, folder: str) -> str: ...

    def is_fixed_drive(self, volume: str) -> bool: ...

    def used_bytes(self, volume: str) -> int: ...

    def limit(self, volume: str) -> tuple[int | None, bool]:
        """The bin's limit in MB (``None`` when not recorded) and whether Windows skips the bin there."""
        ...

    def move_to_bin(self, paths: Sequence[str]) -> bool:
        """Whether the shell reports the whole move done."""
        ...


class _SHQUERYRBINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("i64Size", ctypes.c_longlong),
        ("i64NumItems", ctypes.c_longlong),
    ]


class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", ctypes.c_void_p),  # a list of paths, each NUL-ended, closed by one more NUL
        ("pTo", ctypes.c_void_p),
        ("fFlags", wintypes.WORD),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


def _library(name: str) -> Any:
    loader: Any = getattr(ctypes, "WinDLL", None)  # Windows only
    if loader is None:
        raise RecycleBinRefused("The Recycle Bin is available on Windows only.")
    return loader(name, use_last_error=True)


class WindowsShell:
    def volume_root(self, folder: str) -> str:
        buffer = ctypes.create_unicode_buffer(1024)
        if not _library("kernel32").GetVolumePathNameW(folder, buffer, len(buffer)):
            raise RecycleBinRefused(f"The drive of {folder} cannot be identified.")
        return buffer.value

    def is_fixed_drive(self, volume: str) -> bool:
        return bool(_library("kernel32").GetDriveTypeW(volume) == _DRIVE_FIXED)

    def used_bytes(self, volume: str) -> int:
        info = _SHQUERYRBINFO()
        info.cbSize = ctypes.sizeof(info)
        if _library("shell32").SHQueryRecycleBinW(volume, ctypes.byref(info)) != 0:
            raise RecycleBinRefused(
                f"Windows cannot report what the Recycle Bin of {volume} holds."
            )
        return int(info.i64Size)

    def limit(self, volume: str) -> tuple[int | None, bool]:
        import winreg

        reg: Any = winreg  # typed for Windows only

        def value(hive: Any, key: str, name: str) -> int | None:
            try:
                with reg.OpenKey(hive, key) as handle:
                    return int(reg.QueryValueEx(handle, name)[0])
            except (OSError, ValueError):
                return None

        buffer = ctypes.create_unicode_buffer(64)
        if not _library("kernel32").GetVolumeNameForVolumeMountPointW(volume, buffer, len(buffer)):
            return None, False
        guid = buffer.value[buffer.value.find("{") : buffer.value.find("}") + 1]
        key = rf"{_EXPLORER}\{guid}"
        disabled = bool(value(reg.HKEY_CURRENT_USER, key, "NukeOnDelete")) or any(
            value(hive, _POLICIES, "NoRecycleFiles")
            for hive in (reg.HKEY_CURRENT_USER, reg.HKEY_LOCAL_MACHINE)
        )
        return value(reg.HKEY_CURRENT_USER, key, "MaxCapacity"), disabled

    def move_to_bin(self, paths: Sequence[str]) -> bool:
        shell32 = _library("shell32")
        ole32 = _library("ole32")
        names = ctypes.create_unicode_buffer("\0".join(paths) + "\0")
        operation = _SHFILEOPSTRUCTW()
        operation.wFunc = FO_DELETE
        operation.pFrom = ctypes.cast(names, ctypes.c_void_p)
        operation.fFlags = RECYCLE_FLAGS
        initialised = ole32.CoInitializeEx(None, 0x2 | 0x4) in (0, 1)  # apartment threaded
        try:
            code = shell32.SHFileOperationW(ctypes.byref(operation))
        finally:
            if initialised:
                ole32.CoUninitialize()
        return code == 0 and not operation.fAnyOperationsAborted


class RecycleBin:
    def __init__(self, shell: Shell | None = None) -> None:
        self._shell: Shell = shell or WindowsShell()

    def volume_of(self, folder: str | Path) -> str:
        return self._shell.volume_root(os.path.realpath(folder))

    def room(self, volume: str) -> BinRoom:
        """How much the bin of ``volume`` can still take without Windows deleting anything."""

        if not self._shell.is_fixed_drive(volume):
            raise RecycleBinRefused(
                f"{volume} is not a local fixed drive, so files removed there may not reach a Recycle Bin."
            )
        limit_mb, disabled = self._shell.limit(volume)
        if disabled:
            raise RecycleBinRefused(
                f"The Recycle Bin is turned off for {volume}: Windows would delete the files permanently."
            )
        if limit_mb is None:
            raise RecycleBinRefused(
                f"The size limit of the Recycle Bin of {volume} is not recorded. Open Recycle Bin Properties, "
                "select that drive and choose OK."
            )
        return BinRoom(volume, limit_mb * _MEBIBYTE, self._shell.used_bytes(volume))

    def move(self, paths: Sequence[Path]) -> None:
        """Move ``paths`` in batches; stops at the first batch that does not wholly leave its place."""

        names = [os.path.abspath(path) for path in paths]
        if any(len(name) > MAX_SHELL_PATH for name in names):
            raise RecycleBinRefused("A file path is too long for the Recycle Bin.")
        for start in range(0, len(names), BATCH_FILES):
            batch = names[start : start + BATCH_FILES]
            done = self._shell.move_to_bin(batch)
            if not done or any(os.path.lexists(name) for name in batch):
                raise RecycleBinRefused("Windows did not move every file to the Recycle Bin.")


__all__ = [
    "BATCH_FILES",
    "MAX_SHELL_PATH",
    "RECYCLE_FLAGS",
    "BinRoom",
    "RecycleBin",
    "RecycleBinRefused",
    "Shell",
    "WindowsShell",
]
