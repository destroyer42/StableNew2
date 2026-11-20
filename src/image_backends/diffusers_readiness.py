"""Offline readiness and resource floors for the Diffusers Ideogram 4 backend (PR-IMG-120).

Everything here is read-only and cheap: package presence is checked by import spec and distribution metadata (nothing
is imported), the pinned weight snapshot by file existence in the local Hugging Face cache (nothing is hashed or
downloaded), free VRAM by one bounded ``nvidia-smi`` query (the application process never initializes CUDA) and host
RAM by ``psutil``. The GUI uses ``check_installation`` to decide whether to offer the model; the backend re-checks it and
the floors immediately before every launch.
"""

from __future__ import annotations

import importlib.util
import os
from collections.abc import Callable
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

from src.image_backends.diffusers_ideogram4_profile import IDEOGRAM4_PROFILE_V1, Ideogram4Profile

#: The Diffusers release that introduced ``Ideogram4Pipeline`` and that PR-IMG-110R qualified.
MIN_DIFFUSERS_VERSION = (0, 40, 0)
#: The bitsandbytes version PR-IMG-110R qualified; the optional extra pins exactly this one.
QUALIFIED_BITSANDBYTES_VERSION = "0.50.2"
NVIDIA_SMI_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class InstallationStatus:
    ready: bool
    reasons: tuple[str, ...]
    snapshot_dir: Path | None

    @property
    def summary(self) -> str:
        return "ready" if self.ready else "; ".join(self.reasons)


@dataclass(frozen=True, slots=True)
class GpuMemory:
    free_mib: int
    used_mib: int
    total_mib: int


def hf_hub_cache_dir(environ: dict[str, str] | None = None) -> Path:
    """The local Hugging Face hub cache, resolved the way ``huggingface_hub`` resolves it (no import)."""

    env = os.environ if environ is None else environ
    if env.get("HF_HUB_CACHE"):
        return Path(env["HF_HUB_CACHE"]).expanduser()
    if env.get("HF_HOME"):
        return Path(env["HF_HOME"]).expanduser() / "hub"
    if env.get("XDG_CACHE_HOME"):
        return Path(env["XDG_CACHE_HOME"]).expanduser() / "huggingface" / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def snapshot_dir(
    profile: Ideogram4Profile = IDEOGRAM4_PROFILE_V1, cache_dir: Path | None = None
) -> Path:
    repo_folder = "models--" + profile.repo_id.replace("/", "--")
    return (cache_dir or hf_hub_cache_dir()) / repo_folder / "snapshots" / profile.revision


def _version_tuple(text: str) -> tuple[int, ...]:
    parts: list[int] = []
    for piece in text.split("+", 1)[0].split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def _distribution_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def check_installation(
    profile: Ideogram4Profile = IDEOGRAM4_PROFILE_V1,
    *,
    cache_dir: Path | None = None,
    find_spec: Callable[[str], object | None] = importlib.util.find_spec,
    version_of: Callable[[str], str | None] = _distribution_version,
) -> InstallationStatus:
    """Whether the runtime packages and the complete pinned snapshot are present (no import, hash or network)."""

    reasons: list[str] = []
    for package in profile.runtime_packages:
        if find_spec(package) is None:
            hint = (
                " (install the optional Ideogram extra: requirements-ideogram.txt)"
                if package == "bitsandbytes"
                else ""
            )
            reasons.append(f"Python package '{package}' is not installed{hint}")
    diffusers_version = version_of("diffusers")
    if diffusers_version is not None and _version_tuple(diffusers_version) < MIN_DIFFUSERS_VERSION:
        reasons.append(
            f"diffusers {diffusers_version} predates Ideogram4Pipeline (needs 0.40.0 or later)"
        )
    directory = snapshot_dir(profile, cache_dir)
    if not directory.is_dir():
        reasons.append(
            f"the pinned weights {profile.repo_id}@{profile.revision[:8]} are not in the local Hugging Face cache"
        )
        return InstallationStatus(False, tuple(reasons), None)
    missing = []
    for component in profile.components:
        path = (
            directory / component.subfolder / component.filename
            if component.subfolder
            else directory / component.filename
        )
        try:
            if not path.is_file() or path.stat().st_size <= 0:
                missing.append(f"{component.subfolder}/{component.filename}".lstrip("/"))
        except OSError:
            missing.append(f"{component.subfolder}/{component.filename}".lstrip("/"))
    if missing:
        reasons.append("the pinned snapshot is incomplete: missing " + ", ".join(missing))
    return InstallationStatus(not reasons, tuple(reasons), directory)


def parse_nvidia_smi_memory(text: str) -> GpuMemory:
    """Parse ``memory.free,memory.used,memory.total`` (MiB, csv, no header/units); the first GPU line wins."""

    for line in text.splitlines():
        fields = [field.strip() for field in line.split(",")]
        if len(fields) >= 3 and all(field.isdigit() for field in fields[:3]):
            return GpuMemory(int(fields[0]), int(fields[1]), int(fields[2]))
    raise ValueError("nvidia-smi reported no GPU memory line")


def query_gpu_memory() -> GpuMemory:
    """One bounded, contained ``nvidia-smi`` query; raises ``RuntimeError`` when it cannot be read."""

    from src.utils.managed_process import run_bounded

    outcome = run_bounded(
        [
            "nvidia-smi",
            "--query-gpu=memory.free,memory.used,memory.total",
            "--format=csv,noheader,nounits",
        ],
        timeout_seconds=NVIDIA_SMI_TIMEOUT_SECONDS,
        max_stdout_bytes=16 * 1024,
    )
    if outcome.launch_error or outcome.timed_out or outcome.returncode != 0:
        detail = outcome.launch_error or (
            "timed out" if outcome.timed_out else f"exit code {outcome.returncode}"
        )
        raise RuntimeError(f"nvidia-smi could not report GPU memory ({detail})")
    return parse_nvidia_smi_memory(outcome.stdout.decode("utf-8", errors="replace"))


def available_host_ram_bytes() -> int:
    import psutil

    return int(psutil.virtual_memory().available)


__all__ = [
    "GpuMemory",
    "InstallationStatus",
    "MIN_DIFFUSERS_VERSION",
    "QUALIFIED_BITSANDBYTES_VERSION",
    "available_host_ram_bytes",
    "check_installation",
    "hf_hub_cache_dir",
    "parse_nvidia_smi_memory",
    "query_gpu_memory",
    "snapshot_dir",
]
