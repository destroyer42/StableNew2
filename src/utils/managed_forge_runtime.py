"""The single StableNew-owned authority for the managed Forge Neo launch profile (PR-IMG-FORGE-RUNTIME-100 / -120).

``config/managed_forge_runtime.json`` owns the installation identity and the launch policy. This module turns that
contract into the launch profile ``WebUIProcessManager`` runs, and it is consumed by BOTH:

* ``tools/runtime/verify_managed_forge.py`` (the read-only drift check, ``--print-profile``), and
* ``src.api.webui_process_manager.build_default_webui_process_config`` (the default Forge production path),

so the command-building rules exist exactly once. Nothing here starts a process, writes, downloads, installs or
touches the network, and nothing is evaluated at import time. It is standard-library only on purpose: the verifier
runs under the managed runtime's own Python 3.13 interpreter, which does not carry the application dependencies.

Installing the managed runtime stays an explicit operator action (``scripts/bootstrap_managed_forge_windows.ps1``).
When it is absent or incomplete, :func:`resolve_default_launch_profile` raises :class:`ManagedForgeUnavailable` with
setup guidance; there is never an automatic install and never a fall-through to A1111.
"""

from __future__ import annotations

import functools
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "config" / "managed_forge_runtime.json"
RUNBOOK = "docs/runbooks/managed_forge_runtime.md"

_SETUP_GUIDANCE = (
    "Managed Forge is StableNew's default still-image runtime, but it is not installed automatically. Build it once "
    f"with scripts/bootstrap_managed_forge_windows.ps1 (see {RUNBOOK}), or select the A1111 rollback explicitly by "
    "setting webui_runtime_identity to a1111_webui. StableNew does not install Forge and does not fall back to A1111."
)


class ManagedForgeUnavailable(RuntimeError):
    """The default managed Forge runtime cannot be configured; the message says what to do."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Managed Forge is not ready: {reason}. {_SETUP_GUIDANCE}")


def load_manifest(path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("manifest must be a JSON object")
    return data


@functools.lru_cache(maxsize=1)
def accepted_detector_names() -> tuple[str, ...]:
    """The ADetailer detectors the managed runtime guarantees (the manifest's two YOLO files; never MediaPipe)."""

    return tuple(load_manifest()["detectors"]["files"])


# --- install identity -------------------------------------------------------------------------------------------


def default_install_root(manifest: dict[str, Any]) -> Path:
    """The manifest's default install root with ``%LOCALAPPDATA%`` expanded (Windows runtime)."""

    template = str(manifest["install"]["default_root"])
    expanded = os.path.expandvars(template)
    if "%" in expanded or "$" in expanded:
        raise ManagedForgeUnavailable(
            f"the default install root {template!r} cannot be resolved on this machine (managed Forge is a Windows runtime)"
        )
    return Path(expanded)


def managed_install_dir(manifest: dict[str, Any], install_root: Path | str | None = None) -> Path:
    """``<root>/neo-<revision8>``: the one install directory the contract's revision names."""

    root = Path(install_root) if install_root else default_install_root(manifest)
    return root / f"neo-{str(manifest['upstream']['revision'])[:8]}"


def default_port(manifest: dict[str, Any]) -> int:
    return int(manifest["launch_policy"]["default_port"])


def endpoint_for_port(port: int) -> str:
    return f"http://127.0.0.1:{int(port)}"


def default_endpoint(manifest: dict[str, Any] | None = None) -> str:
    """The accepted managed Forge endpoint (loopback, the manifest's default port: 7871)."""

    return endpoint_for_port(default_port(manifest or load_manifest()))


def port_from_endpoint(url: str) -> int:
    """The port of an explicit managed-Forge endpoint; managed Forge is loopback only."""

    parsed = urlparse(str(url or "").strip())
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.port is None:
        raise ManagedForgeUnavailable(
            f"webui_base_url {url!r} must be an explicit loopback http://127.0.0.1:<port> endpoint for the managed Forge runtime"
        )
    return int(parsed.port)


# --- launch profile (built, never executed) -------------------------------------------------------------------


def build_launch_profile(manifest: dict[str, Any], *, install_dir: Path, model_home: Path, port: int) -> dict[str, Any]:
    """The WebUIProcessManager launch profile: command, working directory and environment, loopback only."""

    policy = manifest["launch_policy"]
    venv = install_dir / "venv"
    runtime = manifest["runtime_dirs"]
    command = [
        str(venv / "Scripts" / "python.exe"),
        policy["launch_script"],
        "--uv",
        "--api",
        "--port",
        str(port),
        policy["data_dir_flag"],
        str(install_dir / manifest["runtime_dirs"]["data"]),
        policy["model_reference_flag"],
        str(model_home),
        "--ad-no-huggingface",
        "--skip-install",
    ]
    env = dict(policy["env"])
    env.update(
        {
            "HF_HUB_CACHE": str(install_dir / runtime["huggingface_cache"]),
            "MPLCONFIGDIR": str(install_dir / runtime["matplotlib"]),
            "YOLO_CONFIG_DIR": str(install_dir / runtime["yolo_config"]),
            "UV_CACHE_DIR": str(install_dir / runtime["uv_cache"]),
            "UV_PYTHON": str(venv / "Scripts" / "python.exe"),
            "VIRTUAL_ENV": str(venv),
            "PATH": str(venv / "Scripts") + os.pathsep + os.environ.get("PATH", ""),
        }
    )
    return {
        "runtime_identity": manifest["runtime_identity"],
        "command": command,
        "working_dir": str(install_dir / "source"),
        "env_overrides": env,
        "endpoint": endpoint_for_port(port),
        "startup_timeout_seconds": 180,
    }


def check_launch_command(command: list[str], manifest: dict[str, Any]) -> list[str]:
    """A launch command keeps the qualified semantics: required flags present, loopback, nothing tuned."""

    policy = manifest["launch_policy"]
    flags = {part for part in command if part.startswith("--")}
    problems = [f"launch command lacks required flag {flag}" for flag in policy["required_flags"] if flag not in flags]
    if policy["model_reference_flag"] not in flags:
        problems.append(f"launch command lacks {policy['model_reference_flag']} (the accepted model reference)")
    problems += [
        f"launch command carries tuning/exposure flag {flag}"
        for flag in sorted(flags)
        if any(fragment in flag.lower() for fragment in policy["forbidden_flag_fragments"])
    ]
    return problems


# --- default production resolution -----------------------------------------------------------------------------


def _read_marker(install_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    marker_path = install_dir / str(manifest["install"]["marker"])
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raise ManagedForgeUnavailable(f"no managed Forge install was found at {install_dir}") from None
    except (OSError, ValueError) as exc:
        raise ManagedForgeUnavailable(f"the ownership marker {marker_path} is unreadable ({exc})") from None
    if not isinstance(marker, dict):
        raise ManagedForgeUnavailable(f"the ownership marker {marker_path} is not a JSON object")
    return marker


def resolve_default_launch_profile(
    *,
    model_home: Path | str | None,
    base_url: str | None = None,
    manifest: dict[str, Any] | None = None,
    install_root: Path | str | None = None,
) -> dict[str, Any]:
    """The launch profile of the canonical managed Forge install, or :class:`ManagedForgeUnavailable`.

    Cheap structural readiness only (no hashing, no ``pip``, no process): the install the manifest's revision names
    exists, carries the bootstrap's ``verified`` ownership marker for exactly that revision, and has its interpreter,
    source and data directories; the referenced A1111 model home exists; and the built command keeps the qualified
    flags. Full drift detection stays the verifier's job (``scripts/bootstrap_managed_forge_windows.ps1 -CheckOnly``).

    ``base_url`` is an explicit endpoint choice (loopback port); ``None`` selects the manifest's default port.
    """

    contract = manifest if manifest is not None else load_manifest()
    install_dir = managed_install_dir(contract, install_root)
    marker = _read_marker(install_dir, contract)
    revision = str(contract["upstream"]["revision"])
    if marker.get("revision") != revision:
        raise ManagedForgeUnavailable(
            f"the install at {install_dir} is revision {marker.get('revision')!r}, not the pinned {revision}"
        )
    if marker.get("status") != "verified":
        raise ManagedForgeUnavailable(
            f"the install at {install_dir} is marked {marker.get('status')!r}, not 'verified' (an interrupted build?)"
        )
    expected = {
        "interpreter": install_dir / "venv" / "Scripts" / "python.exe",
        "Forge launch script": install_dir / "source" / str(contract["launch_policy"]["launch_script"]),
        "data directory": install_dir / str(contract["runtime_dirs"]["data"]),
    }
    for label, path in expected.items():
        if not path.exists():
            raise ManagedForgeUnavailable(f"the {label} is missing: {path}")
    home_text = str(model_home or "").strip()
    if not home_text:
        raise ManagedForgeUnavailable(
            "no model reference home is configured (set webui_workdir to your existing A1111 folder; Forge references its models)"
        )
    home = Path(home_text)
    if not (home / "models").is_dir():
        raise ManagedForgeUnavailable(f"the model reference home {home} has no 'models' folder")
    port = port_from_endpoint(base_url) if base_url else default_port(contract)
    profile = build_launch_profile(contract, install_dir=install_dir, model_home=home, port=port)
    problems = check_launch_command(profile["command"], contract)
    if problems:
        raise ManagedForgeUnavailable("the launch command breaks the qualified contract: " + "; ".join(problems))
    return profile


__all__ = [
    "DEFAULT_MANIFEST",
    "accepted_detector_names",
    "ManagedForgeUnavailable",
    "build_launch_profile",
    "check_launch_command",
    "default_endpoint",
    "default_install_root",
    "default_port",
    "endpoint_for_port",
    "load_manifest",
    "managed_install_dir",
    "port_from_endpoint",
    "resolve_default_launch_profile",
]
