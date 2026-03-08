"""UI state persistence for StableNew v2.6.

Provides save/restore functionality for window geometry, tab selection,
and other UI state that should survive app restarts.

PR-PERSIST-001: Complete UI state persistence
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

UI_STATE_PATH = Path("state") / "ui_state.json"
SCHEMA_VERSION = "2.6"


class UIStateStore:
    """Manages persistence of UI state across sessions."""

    def __init__(self, path: Path | str | None = None) -> None:
        self._path = Path(path) if path else UI_STATE_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def save_state(self, state: dict[str, Any]) -> bool:
        """Save UI state to disk.
        
        Args:
            state: Dictionary containing UI state. Expected structure:
                {
                    "window": {
                        "geometry": "1200x800+100+50",
                        "state": "normal"  # or "zoomed"
                    },
                    "tabs": {
                        "selected_index": 0
                    },
                    "schema_version": "2.6"
                }
        
        Returns:
            True if save succeeded, False otherwise
        """
        try:
            # Ensure schema version is set
            state["schema_version"] = SCHEMA_VERSION
            
            self._path.write_text(json.dumps(state, indent=2))
            logger.debug(f"Saved UI state to {self._path}")
            return True
        except Exception as e:
            logger.warning(f"Failed to save UI state: {e}")
            return False

    def load_state(self) -> dict[str, Any] | None:
        """Load UI state from disk.
        
        Returns:
            Dictionary containing UI state, or None if file doesn't exist
            or schema version is unsupported
        """
        if not self._path.exists():
            logger.debug(f"No UI state file found at {self._path}")
            return None
        
        try:
            state = json.loads(self._path.read_text())
            
            # Validate schema version
            if state.get("schema_version") != SCHEMA_VERSION:
                logger.warning(
                    f"Unsupported UI state schema: {state.get('schema_version')}, expected {SCHEMA_VERSION}"
                )
                return None
            
            logger.debug(f"Loaded UI state from {self._path}")
            return state
        except Exception as e:
            logger.warning(f"Failed to load UI state: {e}")
            return None

    def clear_state(self) -> bool:
        """Delete the saved UI state file.
        
        Returns:
            True if deletion succeeded or file didn't exist, False on error
        """
        try:
            if self._path.exists():
                self._path.unlink()
                logger.info(f"Cleared UI state from {self._path}")
            return True
        except Exception as e:
            logger.warning(f"Failed to clear UI state: {e}")
            return False


# Global instance for convenience
_global_store: UIStateStore | None = None


def get_ui_state_store() -> UIStateStore:
    """Get the global UI state store instance."""
    global _global_store
    if _global_store is None:
        _global_store = UIStateStore()
    return _global_store


__all__ = ["UIStateStore", "get_ui_state_store", "UI_STATE_PATH"]
