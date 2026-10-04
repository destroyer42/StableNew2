"""Local, cryptographic identity of the Klein files Forge will actually load (PR-IMG-116 review repair).

Forge API names (``/sd-models``, ``/sd-modules``, the ``/options`` read-back) say which *names* are selected, never which
*bytes* are behind them. Before a qualified Klein dispatch the three files are therefore located through the existing
managed-Forge runtime authority (the ``forge_runtime_profile_path`` setting -> the launch profile's ``--data-dir``; no second
path authority, nothing machine-local persisted in an NJR) and their exact size and SHA-256 are verified against the
immutable profile. If StableNew cannot establish that identity, Klein fails closed.

A verified file is remembered keyed by its stat identity (path, size, mtime, ctime, inode, device): the first use is
hashed, any observed change forces a rehash, so ~12.45 GB is not re-read on every job.
"""

from __future__ import annotations

import hashlib
import os
import threading
from collections.abc import Callable
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


def resolve_forge_data_dir() -> Path:
    """The configured managed Forge's data directory, via the existing runtime-profile authority or an error."""

    try:
        from src.api.webui_process_manager import load_managed_forge_runtime_profile
        from src.utils.config import ConfigManager

        profile_path = str(ConfigManager().load_settings().get("forge_runtime_profile_path") or "").strip()
        if not profile_path:
            raise KleinProfileError(
                "No managed Forge runtime profile is configured (setting 'forge_runtime_profile_path'), so the "
                "identity of the Klein model files cannot be established; Klein will not run on an unverifiable runtime."
            )
        data_dir = data_dir_from_launch_command(list(load_managed_forge_runtime_profile(profile_path)["command"]))
    except KleinProfileError:
        raise
    except Exception as exc:
        raise KleinProfileError(
            f"The managed Forge runtime profile could not be read ({type(exc).__name__}: {exc}); the identity of "
            "the Klein model files cannot be established."
        ) from exc
    if data_dir is None:
        raise KleinProfileError(
            f"The managed Forge launch command declares no {_DATA_DIR_FLAG}; the Klein model files cannot be located."
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
    profile: KleinProfile, *, data_dir: Path | None = None, resolver: Callable[[], Path] | None = None
) -> dict[str, Any]:
    """Exact size + SHA-256 of transformer, text encoder and VAE as installed, or ``KleinProfileError``."""

    root = Path(data_dir) if data_dir is not None else (resolver or resolve_forge_data_dir)()
    return {asset.role: _verify_one(root, asset) for asset in profile.assets}


__all__ = [
    "clear_verified_cache",
    "data_dir_from_launch_command",
    "resolve_forge_data_dir",
    "verify_klein_assets",
]
