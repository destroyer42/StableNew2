"""Queue persistence store for V2 queue system.

Provides load/save functionality for queue state that survives app restarts.
Uses JSON format with a versioned schema based on QueueJobV2 snapshots.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default location for queue state file
DEFAULT_QUEUE_STATE_PATH = Path("state") / "queue_state_v2.json"

# Schema version for forward compatibility
SCHEMA_VERSION = 1


@dataclass
class QueueSnapshotV1:
    """Serializable queue state snapshot.
    
    Attributes:
        jobs: List of job snapshot dicts from QueueJobV2.to_dict()
        auto_run_enabled: Whether auto-run is enabled
        paused: Whether queue is paused
        schema_version: Version for forward compatibility
    """
    jobs: list[dict[str, Any]] = field(default_factory=list)
    auto_run_enabled: bool = False
    paused: bool = False
    schema_version: int = SCHEMA_VERSION


def get_queue_state_path(base_dir: Path | str | None = None) -> Path:
    """Get the path for the queue state file.
    
    Args:
        base_dir: Optional base directory. If None, uses current working directory.
        
    Returns:
        Path to the queue state JSON file.
    """
    if base_dir:
        return Path(base_dir) / "queue_state_v2.json"
    return DEFAULT_QUEUE_STATE_PATH


def load_queue_snapshot(path: Path | str | None = None) -> QueueSnapshotV1 | None:
    """Load queue state from disk.
    
    Args:
        path: Optional path to the queue state file. Uses default if not provided.
        
    Returns:
        QueueSnapshotV1 if loaded successfully, None if file missing or invalid.
    """
    state_path = Path(path) if path else get_queue_state_path()
    
    if not state_path.exists():
        logger.debug(f"Queue state file not found: {state_path}")
        return None
    
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # Validate schema version
        schema_version = data.get("schema_version", 1)
        if schema_version > SCHEMA_VERSION:
            logger.warning(f"Queue state has newer schema version {schema_version}, attempting to load anyway")
        
        snapshot = QueueSnapshotV1(
            jobs=data.get("jobs", []),
            auto_run_enabled=bool(data.get("auto_run_enabled", False)),
            paused=bool(data.get("paused", False)),
            schema_version=schema_version,
        )
        
        logger.info(f"Loaded queue state: {len(snapshot.jobs)} jobs, auto_run={snapshot.auto_run_enabled}, paused={snapshot.paused}")
        return snapshot
        
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse queue state file: {e}")
        return None
    except Exception as e:
        logger.warning(f"Failed to load queue state: {e}")
        return None


def save_queue_snapshot(snapshot: QueueSnapshotV1, path: Path | str | None = None) -> bool:
    """Save queue state to disk.
    
    Args:
        snapshot: The queue snapshot to save.
        path: Optional path to the queue state file. Uses default if not provided.
        
    Returns:
        True if saved successfully, False on error.
    """
    state_path = Path(path) if path else get_queue_state_path()
    
    try:
        # Ensure directory exists
        state_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Convert to dict for JSON serialization
        data = asdict(snapshot)
        
        # Write atomically by writing to temp file then renaming
        temp_path = state_path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        
        temp_path.replace(state_path)
        
        logger.debug(f"Saved queue state: {len(snapshot.jobs)} jobs")
        return True
        
    except Exception as e:
        logger.error(f"Failed to save queue state: {e}")
        return False


def delete_queue_snapshot(path: Path | str | None = None) -> bool:
    """Delete the queue state file.
    
    Args:
        path: Optional path to the queue state file. Uses default if not provided.
        
    Returns:
        True if deleted or didn't exist, False on error.
    """
    state_path = Path(path) if path else get_queue_state_path()
    
    try:
        if state_path.exists():
            state_path.unlink()
            logger.info(f"Deleted queue state file: {state_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to delete queue state: {e}")
        return False


__all__ = [
    "QueueSnapshotV1",
    "load_queue_snapshot",
    "save_queue_snapshot",
    "delete_queue_snapshot",
    "get_queue_state_path",
]
