"""Where the offline AI runtime, weights and records live. Pure: nothing is created or read here."""

from __future__ import annotations

import os
import platform
from collections.abc import Mapping
from pathlib import Path

ACTIVE_POINTER_NAME = "active.json"
ATTESTATION_NAME = "egress_attestation.json"
EVENTS_NAME = "events.jsonl"


def resolve_ai_root(
    root: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    system_name: str | None = None,
    home_dir: str | Path | None = None,
) -> Path:
    """The per-user directory for runtimes, models and records, without creating it.

    An explicit argument wins, then ``STABLENEW_AI_DIR``, then the platform's per-user data convention. A repository-relative
    directory is never consulted: weights and binaries are operator-imported user data, not repository content.
    """

    if root is not None:
        return Path(root)
    environment = os.environ if environ is None else environ
    configured = environment.get("STABLENEW_AI_DIR")
    if configured:
        return Path(configured)
    home = Path(home_dir) if home_dir is not None else Path.home()
    if (system_name or platform.system()) == "Windows":
        local_app_data = environment.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else home / "AppData" / "Local"
        return base / "StableNew" / "ManagedAi"
    data_home = environment.get("XDG_DATA_HOME")
    base = Path(data_home) if data_home else home / ".local" / "share"
    return base / "StableNew" / "ManagedAi"


def runtime_dir(root: Path, build_id: str) -> Path:
    return root / "runtimes" / build_id


def model_dir(root: Path, sha256: str) -> Path:
    return root / "models" / sha256


def active_pointer_path(root: Path) -> Path:
    return root / ACTIVE_POINTER_NAME


def attestation_path(root: Path) -> Path:
    return root / ATTESTATION_NAME


def events_path(root: Path) -> Path:
    return root / EVENTS_NAME


def work_dir(root: Path, request_id: str) -> Path:
    return root / "work" / request_id


__all__ = [
    "ACTIVE_POINTER_NAME",
    "ATTESTATION_NAME",
    "EVENTS_NAME",
    "active_pointer_path",
    "attestation_path",
    "events_path",
    "model_dir",
    "resolve_ai_root",
    "runtime_dir",
    "work_dir",
]
