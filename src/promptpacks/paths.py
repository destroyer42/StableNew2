"""Resolve the per-user directory that owns native PromptPack documents."""

from __future__ import annotations

import os
import platform
from collections.abc import Mapping
from pathlib import Path


def resolve_prompt_pack_dir(
    packs_dir: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    system_name: str | None = None,
    home_dir: str | Path | None = None,
) -> Path:
    """Return the canonical PromptPack directory without creating it.

    Explicit dependency injection wins, followed by the environment override.
    The remaining locations follow the platform's normal per-user data
    convention and deliberately never consult a repository-relative ``packs``
    directory.
    """

    if packs_dir is not None:
        return Path(packs_dir)

    environment = os.environ if environ is None else environ
    configured_dir = environment.get("STABLENEW_PROMPTPACK_DIR")
    if configured_dir:
        return Path(configured_dir)

    resolved_system = system_name or platform.system()
    if resolved_system == "Windows":
        local_app_data = environment.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "StableNew" / "PromptPacks"
        # LOCALAPPDATA is present on supported Windows installations. Keep a
        # deterministic user-scoped fallback for constrained test/process hosts.
        home = Path(home_dir) if home_dir is not None else Path.home()
        return home / "AppData" / "Local" / "StableNew" / "PromptPacks"

    data_home = environment.get("XDG_DATA_HOME")
    if data_home:
        return Path(data_home) / "StableNew" / "PromptPacks"
    home = Path(home_dir) if home_dir is not None else Path.home()
    return home / ".local" / "share" / "StableNew" / "PromptPacks"


__all__ = ["resolve_prompt_pack_dir"]
