"""Gateway settings, the sync secret file, and the listener rules (RG-100 D9, S2)."""

from __future__ import annotations

import hashlib
import ipaddress
import os
import secrets
import ssl
import stat
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

from .contract import SCHEMA_FILE_NAME

_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
# Tailscale's address ranges: the sync API must never be reachable from the tailnet.
_TAILNET = (
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("fd7a:115c:a1e0::/48"),
)
_MINIMUM_SECRET = 32
_PATH_SETTINGS = (
    "data_dir",
    "media_dir",
    "secret_file",
    "schema_file",
    "sync_tls_cert",
    "sync_tls_key",
)


class ConfigError(Exception):
    """A setting the gateway refuses to start with."""


def default_schema_file() -> Path:
    """The installed copy next to the package, else the repository's ``docs/schemas`` authority."""

    installed = _PACKAGE_ROOT / "schema" / SCHEMA_FILE_NAME
    if installed.is_file():
        return installed
    return _PACKAGE_ROOT.parents[1] / "docs" / "schemas" / SCHEMA_FILE_NAME


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    media_dir: Path
    secret_file: Path
    schema_file: Path
    sync_host: str
    sync_port: int = 9443
    phone_host: str = "127.0.0.1"
    phone_port: int = 8443
    sync_tls_cert: Path | None = None
    sync_tls_key: Path | None = None

    def check_listeners(self) -> None:
        """The phone app is loopback only (published by ``tailscale serve``); sync is one LAN address."""

        phone = _address("phone_host", self.phone_host)
        if not phone.is_loopback:
            raise ConfigError("phone_host must be a loopback address; tailscale serve publishes it")
        sync = _address("sync_host", self.sync_host)
        if sync.is_unspecified:
            raise ConfigError("sync_host must be the LAN address, not every interface")
        if any(sync in network for network in _TAILNET):
            raise ConfigError("sync_host is a tailnet address; the sync API is LAN only")
        if self.phone_port == self.sync_port:
            raise ConfigError("phone_port and sync_port must differ")
        if (self.sync_tls_cert is None) != (self.sync_tls_key is None):
            raise ConfigError("sync_tls_cert and sync_tls_key go together")
        if self.sync_tls_cert is None and not sync.is_loopback:
            raise ConfigError("sync_tls_cert and sync_tls_key are required on a LAN sync_host")


def _address(name: str, value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        raise ConfigError(f"{name} must be an IP address, got {value!r}") from None


def load_settings(path: Path) -> Settings:
    try:
        raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise ConfigError(f"cannot read {path}: {error}") from error
    known = {field.name for field in fields(Settings)}
    if unknown := sorted(set(raw) - known):
        raise ConfigError(f"unknown setting(s) in {path}: {', '.join(unknown)}")
    raw.setdefault("schema_file", str(default_schema_file()))
    for name in _PATH_SETTINGS:
        if name in raw:
            raw[name] = Path(raw[name])
    try:
        return Settings(**raw)
    except TypeError as error:
        raise ConfigError(f"missing setting in {path}: {error}") from error


def certificate_fingerprint(path: Path | None) -> str:
    """SHA-256 over the certificate's DER bytes: what the desktop pins before it sends the secret."""

    if path is None:
        raise ConfigError("no sync_tls_cert is configured")
    try:
        der = ssl.PEM_cert_to_DER_cert(path.read_text(encoding="ascii").strip())
    except (OSError, ValueError) as error:
        raise ConfigError(f"cannot read the certificate {path}: {error}") from error
    return hashlib.sha256(der).hexdigest()


def create_secret(path: Path) -> bool:
    """Write a new sync secret with mode 0600 unless one exists. Returns whether it was created."""

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(handle, "w", encoding="ascii") as stream:
        stream.write(secrets.token_urlsafe(32) + "\n")
    return True


def read_secret(path: Path) -> bytes:
    try:
        mode = path.stat().st_mode
        value = path.read_bytes().strip()
    except OSError as error:
        raise ConfigError(f"cannot read the sync secret {path}: {error.strerror}") from error
    # Windows has no group/other permission bits; the deployment target is Linux.
    if os.name == "posix" and stat.S_IMODE(mode) & 0o077:
        raise ConfigError(f"{path} must be readable only by its owner (chmod 600)")
    if len(value) < _MINIMUM_SECRET:
        raise ConfigError(f"{path} is shorter than {_MINIMUM_SECRET} characters")
    return value
