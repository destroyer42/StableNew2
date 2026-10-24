"""
Utilities for reading metadata from native JSON PromptPacks.
"""

import logging
import os
import re
from pathlib import Path
from typing import Any

from src.promptpacks.storage import load_prompt_pack_document

logger = logging.getLogger(__name__)

_SLOT_NAME_NORMALIZER = re.compile(r"[^a-z0-9]+")


def load_pack_metadata(pack_path: Path | str) -> dict[str, Any]:
    """
    Load metadata from an exact native PromptPack JSON path.

    Args:
        pack_path: Path to the native .json PromptPack

    Returns:
        Dictionary containing pack metadata including matrix config
    """
    pack_path = Path(pack_path)

    if pack_path.suffix.lower() != ".json" or not pack_path.exists():
        logger.debug(f"No JSON metadata found for pack: {pack_path.name}")
        return {}
    try:
        data = load_prompt_pack_document(pack_path)
        logger.debug(f"Loaded metadata from {pack_path.name}")
        return data
    except Exception as e:
        logger.warning(f"Failed to load pack metadata from {pack_path}: {e}")
        return {}


def get_matrix_slots_dict(metadata: dict[str, Any]) -> dict[str, list[str]]:
    """
    Extract matrix slots from pack metadata in format suitable for PromptRandomizer.

    Args:
        metadata: Pack metadata dictionary (from load_pack_metadata)

    Returns:
        Dictionary mapping slot names to value lists
        Example: {"job": ["wizard", "knight"], "environment": ["forest", "castle"]}
    """
    # Matrix config is in pack_data section of the JSON
    pack_data = metadata.get("pack_data", {})
    matrix_config = pack_data.get("matrix", {})
    if not matrix_config.get("enabled"):
        return {}

    slots = matrix_config.get("slots", [])
    slot_dict = {}

    for slot in slots:
        name = slot.get("name")
        values = slot.get("values", [])
        if name and values:
            slot_dict[name] = values

    logger.debug(f"Extracted {len(slot_dict)} matrix slots from metadata")
    return slot_dict


def get_matrix_config_summary(metadata: dict[str, Any]) -> dict[str, Any]:
    """
    Get matrix configuration summary for logging/debugging.

    Args:
        metadata: Pack metadata dictionary

    Returns:
        Dictionary with matrix config summary
    """
    # Matrix config is in pack_data section of the JSON
    pack_data = metadata.get("pack_data", {})
    matrix_config = pack_data.get("matrix", {})

    return {
        "enabled": matrix_config.get("enabled", False),
        "mode": matrix_config.get("mode", "fanout"),
        "limit": matrix_config.get("limit", 8),
        "slot_count": len(matrix_config.get("slots", [])),
        "slot_names": [s.get("name") for s in matrix_config.get("slots", []) if s.get("name")],
    }


def pack_json_path(pack_id: str | Path, packs_dir: str | Path) -> Path:
    """The native JSON file a pack id names. No existence check.

    An absolute id names its own file (``.json`` is forced); any other id is a stem inside ``packs_dir``. This is the
    one resolution rule: the PromptPack compiler uses it to find a pack, and Preview invalidation uses it to decide
    whether a saved file is the pack the job draft compiles.
    """
    candidate = Path(str(pack_id))
    if candidate.is_absolute():
        return candidate if candidate.suffix.lower() == ".json" else candidate.with_suffix(".json")
    return Path(packs_dir) / f"{candidate.stem}.json"


def same_pack_file(left: str | Path, right: str | Path) -> bool:
    """True when both paths are the same file (same inode when both exist, else the same normalized path)."""
    first, second = Path(left), Path(right)
    try:
        if first.exists() and second.exists():
            return os.path.samefile(first, second)
    except OSError:
        pass
    return os.path.normcase(os.path.abspath(first)) == os.path.normcase(os.path.abspath(second))


def normalize_matrix_slot_name(name: str | None) -> str:
    """Normalize slot names so legacy token spellings still resolve.

    Examples:
    - hair-color -> haircolor
    - hair_color -> haircolor
    - Hair Color -> haircolor
    """
    text = str(name or "").strip().lower()
    if not text:
        return ""
    return _SLOT_NAME_NORMALIZER.sub("", text)


def resolve_matrix_slot_value(
    token_name: str,
    slots: dict[str, str] | None,
) -> str | None:
    """Resolve a matrix token name against exact and normalized aliases."""
    if not slots:
        return None
    if token_name in slots:
        return slots[token_name]

    normalized_token = normalize_matrix_slot_name(token_name)
    if not normalized_token:
        return None

    for slot_name, slot_value in slots.items():
        if normalize_matrix_slot_name(slot_name) == normalized_token:
            return slot_value
    return None
