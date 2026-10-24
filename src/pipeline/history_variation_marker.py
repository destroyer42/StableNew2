"""The persisted marker of an edited history variation (PR-HISTORY-610A); dependency-free so projections can read it.

An edited variation is a ``history_replay`` NJR whose ``SourceDescriptor.metadata`` carries this block. An unchanged
Replay never does, so a consumer can tell the two apart without a new ``SourceKind`` or schema.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

VARIATION_KEY = "history_variation"
VARIATION_SCHEMA = "stablenew.history-variation.v1"


def is_history_variation(source_metadata: Mapping[str, Any] | None) -> bool:
    """Whether a ``SourceDescriptor.metadata`` block marks an edited variation (not an unchanged Replay)."""

    block = (source_metadata or {}).get(VARIATION_KEY)
    return isinstance(block, Mapping) and block.get("schema") == VARIATION_SCHEMA


__all__ = ["VARIATION_KEY", "VARIATION_SCHEMA", "is_history_variation"]
