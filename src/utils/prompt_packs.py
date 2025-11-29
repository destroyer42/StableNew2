"""Prompt pack discovery and descriptors for Architecture_v2."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

from .file_io import get_prompt_packs


@dataclass(frozen=True)
class PromptPackInfo:
    """Simple descriptor for a prompt pack file."""

    name: str
    path: Path
    preset_name: str = ""


def _ensure_path(value: Path | str | None) -> Path:
    if value is None:
        return Path("packs")
    return Path(value)


def discover_packs(packs_dir: Path | str | None = None) -> list[PromptPackInfo]:
    """
    Discover prompt packs from the given directory.

    Returns:
        List of PromptPackInfo entries sorted by file name.
    """
    directory = _ensure_path(packs_dir)
    pack_paths = get_prompt_packs(directory)
    descriptors: List[PromptPackInfo] = []
    for pack_path in pack_paths:
        descriptors.append(
            PromptPackInfo(
                name=pack_path.stem,
                path=pack_path,
                preset_name="",
            )
        )
    return descriptors


__all__ = ["PromptPackInfo", "discover_packs"]
