"""Filesystem operations for a revocable, approved Site output root."""

from __future__ import annotations

import hashlib
import os
import stat
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".m4v": "video/mp4",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
}


class SiteOutputError(ValueError):
    """A path-free refusal suitable for display in the Site."""


def is_link(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def inside(root: Path, path: Path) -> Path:
    """Reject traversal and every link/junction below a pinned canonical root."""
    if not path.is_relative_to(root):
        raise SiteOutputError("outside_output_folder")
    cursor = root
    if is_link(cursor.lstat()):
        raise SiteOutputError("outside_output_folder")
    for part in path.relative_to(root).parts:
        if part == ".." or ":" in part:
            raise SiteOutputError("outside_output_folder")
        cursor /= part
        if is_link(cursor.lstat()):
            raise SiteOutputError("outside_output_folder")
    if path.resolve(strict=True) != path:
        raise SiteOutputError("outside_output_folder")
    return path


def _windows_final_path(stream: BinaryIO) -> Path:
    if sys.platform != "win32":
        raise OSError("Windows handle required")
    import ctypes
    import msvcrt
    from ctypes import wintypes

    get_final = ctypes.WinDLL("kernel32", use_last_error=True).GetFinalPathNameByHandleW
    get_final.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    get_final.restype = wintypes.DWORD
    buffer = ctypes.create_unicode_buffer(32768)
    size = get_final(msvcrt.get_osfhandle(stream.fileno()), buffer, len(buffer), 0)
    if not 0 < size < len(buffer):
        raise OSError("Cannot verify open media path")
    final = buffer.value
    if final.startswith("\\\\?\\UNC\\"):
        final = "\\\\" + final[8:]
    elif final.startswith("\\\\?\\"):
        final = final[4:]
    return Path(final)


@contextmanager
def open_scoped(root: Path, path: Path) -> Iterator[BinaryIO]:
    """Verify the opened file before reading it, including a Windows rename race."""
    path = inside(root, path)
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(opened.st_mode)
            or (os.name == "nt" and _windows_final_path(stream) != path)
            or not os.path.samestat(opened, inside(root, path).stat())
        ):
            raise SiteOutputError("media_changed")
        yield stream


def checked_digest(stream: BinaryIO, *, size_limit: int) -> str:
    digest = hashlib.sha256()
    size = 0
    while chunk := stream.read(1024 * 1024):
        size += len(chunk)
        if size > size_limit:
            raise SiteOutputError("media_too_large")
        digest.update(chunk)
    return digest.hexdigest()
