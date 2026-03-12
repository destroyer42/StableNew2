"""Canonical paths for learning data artifacts.

All path constants are now derived from ``WorkspacePaths``, which resolves
paths relative to the repository root.  Call sites that already used the
``get_*`` helpers are unaffected.  Legacy callers that import the ``Path``
constants directly will receive absolute paths (same semantics as before, but
now rooted at the true project root rather than the process cwd).
"""

from __future__ import annotations

from pathlib import Path

from src.state.workspace_paths import workspace_paths as _wp

# Public constants — absolute paths derived from WorkspacePaths.
CANONICAL_LEARNING_RECORDS_PATH: Path = _wp.learning_records(create_parent=False)
CANONICAL_LEARNING_EXPERIMENTS_ROOT: Path = _wp.learning_experiments_root(create=False)
CANONICAL_DISCOVERED_EXPERIMENTS_ROOT: Path = _wp.learning_discovered_root(create=False)


def get_learning_records_path(*, create_parent: bool = True) -> Path:
    """Return canonical learning records path."""
    return _wp.learning_records(create_parent=create_parent)


def get_learning_experiments_root(*, create: bool = True) -> Path:
    """Return canonical learning experiments workspace root."""
    return _wp.learning_experiments_root(create=create)


def get_discovered_experiments_root(*, create: bool = True) -> Path:
    """Return canonical root for the DiscoveredReviewStore."""
    return _wp.learning_discovered_root(create=create)
