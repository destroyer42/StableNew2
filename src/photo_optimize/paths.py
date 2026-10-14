"""Windows extended paths for managed photo files with long provenance names."""
from __future__ import annotations

import errno
import os
import sys
from pathlib import Path


def io_path(path: Path | str, *, force: bool = False) -> Path:
    candidate = Path(path)
    if os.name != "nt":
        return candidate
    raw = str(candidate.absolute())
    if raw.startswith("\\\\?\\") or (not force and len(raw) < 240):
        return candidate
    if raw.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + raw[2:])
    return Path("\\\\?\\" + raw)


def canonical_path(path: Path | str) -> Path:
    raw = str(Path(path).absolute())
    if raw.startswith("\\\\?\\UNC\\"):
        return Path("\\\\" + raw[8:])
    if raw.startswith("\\\\?\\"):
        return Path(raw[4:])
    return Path(raw)


def rename_without_replace(source: Path, destination: Path) -> None:
    """Atomic publication that cannot replace even an empty competing directory."""
    if os.name == "nt":
        io_path(source, force=True).rename(io_path(destination, force=True))
        return
    # POSIX rename can replace an empty directory. Keep Windows' no-replace guarantee on Linux CI too.
    if sys.platform == "linux":
        import ctypes

        library = ctypes.CDLL(None, use_errno=True)
        rename = getattr(library, "renameat2", None)
        if rename is not None:
            rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
            rename.restype = ctypes.c_int
            if rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1) == 0:
                return
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code), str(destination))
    raise OSError(errno.ENOTSUP, "Safe no-replace directory publication is unavailable", str(destination))
