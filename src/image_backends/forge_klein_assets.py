"""Local, cryptographic identity of the Klein files the serving Forge will actually load (PR-IMG-116 review repair).

Forge API names (``/sd-models``, ``/sd-modules``, the ``/options`` read-back) say which *names* are selected, never which
*bytes* are behind them, and an external Forge can expose the expected names over different bytes. Qualified Klein v1
therefore requires the StableNew-owned managed Forge: before a dispatch the data directory is taken from the *actual
launch-session command* of the process the existing ``WebUIProcessManager`` owns and that serves the client's endpoint, and
the exact size and SHA-256 of the three files are verified there against the immutable profile. Any link that cannot be
positively established fails closed (no adoption, restart or modification of an external Forge). This restriction is for
the qualified Klein profile only; ordinary Forge support is untouched.

A verified file is remembered keyed by its stat identity (path, size, mtime, ctime, inode, device): the first use is
hashed, any observed change forces a rehash, so ~12.45 GB is not re-read on every job.
"""

from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path
from typing import Any

from src.image_backends.forge_klein_profile import KleinAsset, KleinProfile, KleinProfileError

_DATA_DIR_FLAG = "--data-dir"
_VERIFIED: dict[tuple[Any, ...], str] = {}
_LOCK = threading.Lock()


def clear_verified_cache() -> None:
    with _LOCK:
        _VERIFIED.clear()


def data_dir_from_launch_command(command: list[str]) -> Path | None:
    """The managed runtime's ``--data-dir`` from its launch command (``--data-dir X`` or ``--data-dir=X``)."""

    for index, token in enumerate(command):
        if token == _DATA_DIR_FLAG and index + 1 < len(command):
            return Path(command[index + 1])
        if token.startswith(_DATA_DIR_FLAG + "="):
            return Path(token.split("=", 1)[1])
    return None


_MANAGED_ONLY = (
    "Qualified Klein v1 requires the StableNew-owned managed Forge: StableNew must bind the asset provenance "
    "to the files loaded by the serving runtime. Start Forge through StableNew's managed runtime profile "
    "(external Forge remains supported for other models); an external Forge is never adopted, restarted or modified."
)


def _active_manager() -> Any:
    """The current ``WebUIProcessManager`` (the existing lifecycle authority), or ``None``."""

    from src.api.webui_process_manager import get_global_webui_process_manager

    return get_global_webui_process_manager()


def _normalized_endpoint(url: str) -> tuple[str, str, int | None]:
    from urllib.parse import urlparse

    parsed = urlparse(str(url or "").strip().rstrip("/"))
    host = (parsed.hostname or "").lower()
    return parsed.scheme.lower(), "127.0.0.1" if host == "localhost" else host, parsed.port


def resolve_owned_forge_data_dir(endpoint: str) -> Path:
    """The data directory of the Forge process StableNew itself launched and that serves ``endpoint``.

    Established only through the existing ``WebUIProcessManager`` authority: a current manager with identity
    ``forge_webui`` that currently owns its live launch-session process, whose endpoint is the client's endpoint,
    and whose *actual launch-session command* (not a configured profile, port or filename) names ``--data-dir``.
    Anything else fails closed. Endpoint health, PID existence, port occupancy or a Forge API identity are never
    taken as ownership.
    """

    manager = _active_manager()
    if manager is None:
        raise KleinProfileError("No StableNew WebUI process manager is active. " + _MANAGED_ONLY)
    if getattr(manager, "runtime_identity", "") != "forge_webui":
        raise KleinProfileError(
            f"The active runtime manager is '{getattr(manager, 'runtime_identity', '')}', not forge_webui. " + _MANAGED_ONLY
        )
    if not getattr(manager, "owns_process", False):
        raise KleinProfileError("StableNew does not own the Forge process serving this endpoint. " + _MANAGED_ONLY)
    if not endpoint or _normalized_endpoint(manager.endpoint) != _normalized_endpoint(endpoint):
        raise KleinProfileError(
            f"The managed Forge serves '{getattr(manager, 'endpoint', '')}', not the client endpoint '{endpoint}'. " + _MANAGED_ONLY
        )
    command = manager.launch_session_command
    data_dir = data_dir_from_launch_command(list(command)) if command else None
    if data_dir is None:
        raise KleinProfileError(
            f"The owned Forge launch session declares no {_DATA_DIR_FLAG}, so its model files cannot be located. " + _MANAGED_ONLY
        )
    return data_dir


def _stat_key(path: Path, size: int, stat: os.stat_result) -> tuple[Any, ...]:
    return (str(path), size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino, stat.st_dev)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _verify_one(data_dir: Path, asset: KleinAsset) -> dict[str, Any]:
    path = data_dir / "models" / asset.models_subdir / asset.filename
    if not path.is_file():
        raise KleinProfileError(
            f"The {asset.role} {asset.filename} is not installed in the managed Forge model tree "
            "(install it with scripts/install_forge_klein_assets.ps1)."
        )
    stat = path.stat()
    if stat.st_size != asset.size:
        raise KleinProfileError(f"The installed {asset.filename} has {stat.st_size} bytes, expected {asset.size}.")
    key = _stat_key(path, asset.size, stat)
    with _LOCK:
        cached = _VERIFIED.get(key)
    if cached == asset.sha256:
        return {"name": asset.filename, "size": asset.size, "sha256": cached, "verified": "sha256", "cache": "hit"}
    actual = _sha256(path)
    if actual != asset.sha256:
        raise KleinProfileError(
            f"The installed {asset.filename} has SHA-256 {actual}, expected {asset.sha256}; "
            "refusing to run Klein on files that are not the qualified assets."
        )
    with _LOCK:
        _VERIFIED[key] = actual
    return {"name": asset.filename, "size": asset.size, "sha256": actual, "verified": "sha256", "cache": "miss"}


def verify_klein_assets(
    profile: KleinProfile, *, endpoint: str = "", data_dir: Path | None = None
) -> dict[str, Any]:
    """Exact size + SHA-256 of transformer, text encoder and VAE as installed in the OWNED serving Forge's data dir.

    ``endpoint`` is the endpoint the client dispatches to; ``data_dir`` is a test seam that bypasses the manager.
    """

    root = Path(data_dir) if data_dir is not None else resolve_owned_forge_data_dir(endpoint)
    return {asset.role: _verify_one(root, asset) for asset in profile.assets}


__all__ = [
    "clear_verified_cache",
    "data_dir_from_launch_command",
    "resolve_owned_forge_data_dir",
    "verify_klein_assets",
]
