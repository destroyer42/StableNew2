"""Prompt pack discovery and descriptors for Architecture_v2."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.pipeline.run_config import PromptSource, RunConfig

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
    descriptors: list[PromptPackInfo] = []
    for pack_path in pack_paths:
        descriptors.append(
            PromptPackInfo(
                name=pack_path.stem,
                path=pack_path,
                preset_name="",
            )
        )
    return descriptors


def build_run_config_from_prompt_pack(
    pack_id: str,
    pack_data: Mapping[str, Any],
    selected_keys: list[str],
    *,
    base_config: RunConfig | None = None,
) -> RunConfig:
    """Build a RunConfig from a prompt pack selection.

    Args:
        pack_id: Identifier of the prompt pack.
        pack_data: The full pack data dict (must contain "prompts" key).
        selected_keys: Which prompt keys were selected from the pack.
        base_config: Optional base config to copy from.

    Returns:
        A RunConfig with prompt_source=PACK and populated pack fields.
    """
    cfg = RunConfig(
        prompt_source=base_config.prompt_source if base_config else PromptSource.MANUAL,
        prompt_pack_id=base_config.prompt_pack_id if base_config else None,
        prompt_keys=list(base_config.prompt_keys) if base_config else [],
        prompt_payload=dict(base_config.prompt_payload) if base_config else {},
        run_mode=base_config.run_mode if base_config else "direct",
        source=base_config.source if base_config else "gui",
    )

    cfg.prompt_source = PromptSource.PACK
    cfg.prompt_pack_id = pack_id
    cfg.prompt_keys = list(selected_keys)

    # Minimal prompt payload for history/learning
    prompts_data = pack_data.get("prompts", {})
    prompts = {k: prompts_data.get(k) for k in selected_keys if k in prompts_data}
    cfg.prompt_payload = {"pack_id": pack_id, "prompts": prompts}

    return cfg


def build_run_config_for_manual_prompt(
    prompt: str,
    negative_prompt: str = "",
    *,
    base_config: RunConfig | None = None,
) -> RunConfig:
    """Build a RunConfig for a manually entered prompt.

    Args:
        prompt: The user-entered prompt text.
        negative_prompt: The user-entered negative prompt text.
        base_config: Optional base config to copy from.

    Returns:
        A RunConfig with prompt_source=MANUAL and populated prompt payload.
    """
    cfg = RunConfig(
        prompt_source=base_config.prompt_source if base_config else PromptSource.MANUAL,
        prompt_pack_id=base_config.prompt_pack_id if base_config else None,
        prompt_keys=list(base_config.prompt_keys) if base_config else [],
        prompt_payload=dict(base_config.prompt_payload) if base_config else {},
        run_mode=base_config.run_mode if base_config else "direct",
        source=base_config.source if base_config else "gui",
    )

    cfg.prompt_source = PromptSource.MANUAL
    cfg.prompt_pack_id = None
    cfg.prompt_keys = []
    cfg.prompt_payload = {
        "prompt": prompt,
        "negative_prompt": negative_prompt,
    }

    return cfg


__all__ = [
    "PromptPackInfo",
    "discover_packs",
    "build_run_config_from_prompt_pack",
    "build_run_config_for_manual_prompt",
]
