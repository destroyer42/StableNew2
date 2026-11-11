"""UI state persistence for StableNew v2.6.

Provides save/restore functionality for window geometry, tab selection,
and other UI state that should survive app restarts.

PR-PERSIST-001: Complete UI state persistence
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from threading import RLock
from typing import Any

from src.state.workspace_paths import workspace_paths
from src.utils.atomic_io import atomic_write_text

logger = logging.getLogger(__name__)

UI_STATE_PATH = workspace_paths.ui_state()
SCHEMA_VERSION = "2.6"
DEFAULT_CONTENT_VISIBILITY_STATE = {"mode": "nsfw"}


class UIStateStore:
    """Manages persistence of UI state across sessions."""

    def __init__(self, path: Path | str | None = None) -> None:
        self._lock = RLock()
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
            with self._lock:
                self._read_state()  # Refuse to replace unreadable or unsupported state.
                payload = {**state, "schema_version": SCHEMA_VERSION}
                atomic_write_text(self._path, json.dumps(payload, indent=2))
            logger.debug(f"Saved UI state to {self._path}")
            return True
        except Exception as e:
            logger.warning(f"Failed to save UI state: {e}")
            return False

    def update_state(self, changes: dict[str, Any]) -> bool:
        """Merge the supplied keys into the latest state and publish atomically."""
        with self._lock:
            try:
                state = self.load_state(strict=True) or {}
            except (OSError, ValueError):
                return False
            return self.save_state({**state, **changes})

    def _read_state(self) -> dict[str, Any] | None:
        try:
            state = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        if not isinstance(state, dict) or state.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("UI state must be a JSON object with a supported schema version")
        return state

    def load_state(self, *, strict: bool = False) -> dict[str, Any] | None:
        """Load saved state, optionally surfacing read errors to a draft editor."""
        try:
            state = self._read_state()
        except (OSError, ValueError) as exc:
            logger.warning("Failed to load UI state from %s: %s", self._path, exc)
            if strict:
                raise
            return None
        if state is not None:
            content_visibility = state.get("content_visibility")
            if not isinstance(content_visibility, dict) or content_visibility.get("mode") not in {
                "sfw",
                "nsfw",
            }:
                state["content_visibility"] = dict(DEFAULT_CONTENT_VISIBILITY_STATE)
        return state

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
