from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Optional


class FileAccessLogger:
    """
    Lightweight logger for recording unique file paths touched at runtime.

    This is used in the V2.5 clean-house effort to see which files are
    actually used when running the StableNew GUI and pipelines.
    """

    def __init__(self, log_path: Path) -> None:
        self._log_path = log_path
        self._seen: set[str] = set()
        self._lock = threading.Lock()
        self._is_writing = False  # NEW: track when writing own log file

        # Ensure parent directory exists
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def log_path(self) -> Path:
        """Return the path of the log file."""
        return self._log_path

    def record(self, path: Path, reason: str, stack: Optional[str] = None) -> None:
        """
        Record a single file access.

        - path: filesystem path that was accessed
        - reason: "open", "path_open", "import", etc.
        - stack: optional stack snippet for debugging
        """
        try:
            norm = str(path.resolve())
        except Exception:
            norm = str(path)

        with self._lock:
            if norm in self._seen:
                return
            self._seen.add(norm)

            entry = {
                "path": norm,
                "reason": reason,
                "stack": stack,
            }

            # Avoid recursive logging when we write *our own* log file
            if self._is_writing:
                return

            self._is_writing = True
            try:
                with self._log_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(entry) + "\n")
            finally:
                self._is_writing = False
