"""
Utility functions for loading prompt pack metadata from JSON files.

Provides helpers to load matrix configurations and other metadata
from .json pack files alongside .txt pack files.
"""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def load_pack_metadata(pack_path: Path | str) -> dict[str, Any]:
    """
    Load metadata from a prompt pack JSON file.
    
    Looks for a .json file with the same base name as the pack.
    Returns empty dict if JSON doesn't exist or can't be loaded.
    
    Args:
        pack_path: Path to .txt pack file (or base path without extension)
        
    Returns:
        Dictionary containing pack metadata including matrix config
    """
    pack_path = Path(pack_path)
    
    # Try exact path if it's already .json
    if pack_path.suffix == ".json":
        json_path = pack_path
    else:
        # Otherwise, replace extension with .json
        json_path = pack_path.with_suffix(".json")
    
    if not json_path.exists():
        logger.debug(f"No JSON metadata found for pack: {pack_path.name}")
        return {}
    
    try:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
        logger.debug(f"Loaded metadata from {json_path.name}")
        return data
    except Exception as e:
        logger.warning(f"Failed to load pack metadata from {json_path}: {e}")
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
