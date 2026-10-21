"""Locate the external ``rife-ncnn-vulkan`` runtime and choose its model and factor (PR-VID-SMOOTH-302).

Backend-neutral: native SVD frames and finished Comfy clips interpolate through the same executable, the same
model choice and the same factor rule. Nothing here starts a process; it only inspects the filesystem.

The executable's *default* model is an old one (rife-v2.3) that rejects a custom frame target, so StableNew
always names a modern ``rife-v4.x`` model folder next to the executable when one is there, and records the
choice in the run's command.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

RIFE_EXECUTABLE_NAMES = ("rife-ncnn-vulkan.exe", "rife-ncnn-vulkan")
SUPPORTED_RIFE_MULTIPLIERS = frozenset((2, 4))
# A source at or above this rate is smoothed x2; a slower one x4, so the export lands at 24 fps or more.
RIFE_X2_MIN_SOURCE_FPS = 14
# A usable ncnn model folder holds both of these.
_MODEL_FILES = ("flownet.param", "flownet.bin")
_MODEL_NAME = re.compile(r"^rife-v(?P<version>\d+(?:\.\d+)*)(?P<variant>.*)$", re.IGNORECASE)


def default_rife_tools_dir(repo_root: Path | None = None) -> Path:
    """The folder an operator drops a RIFE release into (``tools/rife`` under the repository)."""

    root = repo_root if repo_root is not None else Path(__file__).resolve().parents[2]
    return root / "tools" / "rife"


def _executable_in(folder: Path) -> Path | None:
    for name in RIFE_EXECUTABLE_NAMES:
        candidate = folder / name
        if candidate.is_file():
            return candidate
    return None


def find_rife_executable(
    explicit: str | os.PathLike[str] | None = None, *, repo_root: Path | None = None
) -> Path | None:
    """Resolve the executable: explicit path, ``STABLENEW_RIFE_EXE``, ``PATH``, then the tools folder.

    The tools folder is searched one level down too, because a downloaded release unpacks into a versioned
    ``rife-ncnn-vulkan-<date>-<os>`` directory.
    """

    if explicit:
        path = Path(explicit)
        if path.exists():
            return path
    env_candidate = os.getenv("STABLENEW_RIFE_EXE")
    if env_candidate and Path(env_candidate).exists():
        return Path(env_candidate)
    which_path = shutil.which("rife-ncnn-vulkan")
    if which_path:
        return Path(which_path)
    tools = default_rife_tools_dir(repo_root)
    if not tools.is_dir():
        return None
    direct = _executable_in(tools)
    if direct is not None:
        return direct
    try:
        children = sorted(child for child in tools.iterdir() if child.is_dir())
    except OSError:
        return None
    for child in children:
        nested = _executable_in(child)
        if nested is not None:
            return nested
    return None


def _model_rank(name: str) -> tuple[tuple[int, ...], int, str] | None:
    match = _MODEL_NAME.match(name)
    if match is None:
        return None
    version = tuple(int(part) for part in match.group("version").split("."))
    # The plain model beats its ``-lite`` / ``-ensemble`` variants of the same version.
    plain = 1 if not match.group("variant") else 0
    return version, plain, name


def find_rife_model_dir(
    executable: Path, explicit: str | os.PathLike[str] | None = None
) -> Path | None:
    """The model folder to pass as ``-m``: the configured one, else the newest ``rife-v4.x`` beside the exe.

    Only ``rife-v4`` and later qualify: they are the models that accept a custom frame count. ``None`` means
    the executable's own default model would run.
    """

    if explicit:
        configured = Path(explicit)
        if not configured.is_absolute():
            beside = executable.parent / configured
            configured = beside if beside.exists() else configured
        return configured.resolve() if configured.exists() else configured
    try:
        children = [child for child in executable.parent.iterdir() if child.is_dir()]
    except OSError:
        return None
    ranked: list[tuple[tuple[tuple[int, ...], int, str], Path]] = []
    for child in children:
        rank = _model_rank(child.name)
        if rank is None or rank[0][0] < 4:
            continue
        if not all((child / filename).is_file() for filename in _MODEL_FILES):
            continue
        ranked.append((rank, child))
    if not ranked:
        return None
    return max(ranked, key=lambda item: item[0])[1].resolve()


def default_rife_multiplier(source_fps: int | float) -> int:
    """x2 for a source of 14 fps or more, x4 below, so the smoothed clip plays at 24 fps or more."""

    return 2 if float(source_fps) >= RIFE_X2_MIN_SOURCE_FPS else 4


def get_rife_multiplier_validation_error(multiplier: int) -> str | None:
    """The bounded admission error for an unsupported factor."""

    if multiplier not in SUPPORTED_RIFE_MULTIPLIERS:
        return (
            f"RIFE interpolation multiplier {multiplier} is unsupported. "
            "StableNew supports only 2x or 4x duration-preserving interpolation."
        )
    return None


__all__ = [
    "RIFE_EXECUTABLE_NAMES",
    "RIFE_X2_MIN_SOURCE_FPS",
    "SUPPORTED_RIFE_MULTIPLIERS",
    "default_rife_multiplier",
    "default_rife_tools_dir",
    "find_rife_executable",
    "find_rife_model_dir",
    "get_rife_multiplier_validation_error",
]
