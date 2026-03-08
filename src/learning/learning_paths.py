"""Canonical paths for learning data artifacts."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


CANONICAL_LEARNING_RECORDS_PATH = Path("data/learning/learning_records.jsonl")
LEGACY_LEARNING_RECORDS_PATHS: tuple[Path, ...] = (
    Path("data/learning_records.jsonl"),
    Path("output/learning/learning_records.jsonl"),
)


def get_learning_records_path(*, create_parent: bool = True) -> Path:
    """Return canonical learning records path."""
    path = CANONICAL_LEARNING_RECORDS_PATH
    if create_parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


def iter_learning_records_candidates() -> Iterable[Path]:
    """Yield canonical then legacy locations for read compatibility."""
    yield CANONICAL_LEARNING_RECORDS_PATH
    for path in LEGACY_LEARNING_RECORDS_PATHS:
        yield path


def pick_existing_learning_records_path() -> Path:
    """Return first existing records path, falling back to canonical."""
    for path in iter_learning_records_candidates():
        if path.exists():
            return path
    return CANONICAL_LEARNING_RECORDS_PATH
