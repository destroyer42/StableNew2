"""Canonical paths for learning data artifacts."""

from __future__ import annotations

from pathlib import Path


CANONICAL_LEARNING_RECORDS_PATH = Path("data/learning/learning_records.jsonl")


def get_learning_records_path(*, create_parent: bool = True) -> Path:
    """Return canonical learning records path."""
    path = CANONICAL_LEARNING_RECORDS_PATH
    if create_parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path
