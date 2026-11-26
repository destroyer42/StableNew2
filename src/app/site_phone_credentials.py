"""Windows-local persistence for a single Operator Site phone grant."""

from __future__ import annotations

import ctypes
import json
import os
import re
import stat
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from src.utils.atomic_io import atomic_write_bytes

IDENTIFIER = re.compile(r"[a-f0-9]{32}")
HOST_SECRET = re.compile(r"[a-f0-9]{64}")
SITE_SECRET = re.compile(r"[!-~]{1,4096}")


@dataclass(frozen=True)
class PhoneFolder:
    path: str
    device: int
    inode: int

    @classmethod
    def approve(cls, path: Path) -> PhoneFolder:
        resolved = path.resolve(strict=True)
        info = resolved.stat()
        if not stat.S_ISDIR(info.st_mode) or not info.st_ino:
            raise ValueError("Output folder identity is unavailable")
        return cls(str(resolved), info.st_dev, info.st_ino)

    def matches(self) -> bool:
        try:
            return self == self.approve(Path(self.path))
        except (OSError, ValueError):
            return False


@dataclass(frozen=True, repr=False)
class PhoneGrant:
    id: str
    name: str
    site_secret: str
    host_secret: str
    folder: PhoneFolder
    rating: bool
    pending: str = ""
    revoked: bool = False
    native_review: bool = False
    queue_submit: bool = False


class _Blob(ctypes.Structure):
    _fields_ = [("size", ctypes.c_uint32), ("data", ctypes.c_void_p)]


def _dpapi(data: bytes, *, decrypt: bool) -> bytes:
    if sys.platform != "win32":
        raise OSError("Phone pairing requires Windows data protection")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    operation = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    operation.argtypes = [
        ctypes.POINTER(_Blob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(_Blob),
    ]
    operation.restype = ctypes.c_int
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    buffer = ctypes.create_string_buffer(data)
    source = _Blob(len(data), ctypes.addressof(buffer))
    result = _Blob()
    # CRYPTPROTECT_UI_FORBIDDEN. Omitting LOCAL_MACHINE binds protection to the current user.
    if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise OSError("Windows could not access the phone pairing credentials")
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel32.LocalFree(result.data)


def protect_for_current_user(data: bytes) -> bytes:
    """Encrypt for the current Windows user (DPAPI); shared with the review gateway settings (RG-120)."""
    return _dpapi(data, decrypt=False)


def unprotect_for_current_user(data: bytes) -> bytes:
    return _dpapi(data, decrypt=True)


class PhoneGrantStore:
    def __init__(self, path: Path | None = None) -> None:
        self._configured_path = path

    @property
    def path(self) -> Path:
        if self._configured_path is not None:
            return self._configured_path
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        if not local.is_absolute():
            raise OSError("Windows local application data is unavailable")
        return local / "StableNew" / "operator-phone.dpapi"

    def load(self) -> PhoneGrant | None:
        try:
            with self.path.open("rb") as source:
                encrypted = source.read(65537)
        except FileNotFoundError:
            return None
        if len(encrypted) > 65536:
            raise ValueError("Invalid phone pairing record")
        try:
            value = json.loads(_dpapi(encrypted, decrypt=True))
            value["folder"] = PhoneFolder(**value["folder"])
            grant = PhoneGrant(**value)
            valid = (
                IDENTIFIER.fullmatch(grant.id)
                and isinstance(grant.name, str)
                and SITE_SECRET.fullmatch(grant.site_secret)
                and HOST_SECRET.fullmatch(grant.host_secret)
                and (grant.pending == "" or IDENTIFIER.fullmatch(grant.pending))
                and type(grant.rating) is bool
                and type(grant.native_review) is bool
                and type(grant.queue_submit) is bool
                and type(grant.revoked) is bool
                and Path(grant.folder.path).is_absolute()
                and type(grant.folder.device) is int
                and type(grant.folder.inode) is int
                and grant.folder.inode > 0
            )
        except (TypeError, KeyError, ValueError) as error:
            raise ValueError("Invalid phone pairing record") from error
        if not valid:
            raise ValueError("Invalid phone pairing record")
        return grant

    def save(self, grant: PhoneGrant) -> None:
        payload = json.dumps(asdict(grant), ensure_ascii=True).encode("utf-8")
        atomic_write_bytes(self.path, _dpapi(payload, decrypt=False))

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)
