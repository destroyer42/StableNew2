"""Centralized paths for mutable StableNew workspace data.

Production code uses :data:`workspace_paths`. Tests and tools can construct a
``WorkspacePaths`` instance with a temporary root, keeping repository data
untouched. Merely importing this module or asking for a file path performs no
filesystem writes.
"""

from __future__ import annotations

from pathlib import Path


class WorkspacePaths:
    """Provide absolute runtime paths anchored to a configurable root."""

    def __init__(self, root: Path | str | None = None) -> None:
        if root is None:
            root = Path(__file__).parent.parent.parent
        self._root = Path(root).resolve()

    @property
    def root(self) -> Path:
        return self._root

    def learning_records(self, *, create_parent: bool = True) -> Path:
        """Return the canonical learning-records JSONL path."""
        path = self._root / "data" / "learning" / "learning_records.jsonl"
        if create_parent:
            path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def learning_experiments_root(self, *, create: bool = True) -> Path:
        """Return the learning experiments directory."""
        path = self._root / "data" / "learning" / "experiments"
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def learning_discovered_root(self, *, create: bool = True) -> Path:
        """Return the discovered-review store root."""
        path = self._root / "data" / "learning"
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def photo_optimize_root(self, *, create: bool = True) -> Path:
        """Return the photo-optimization workspace root."""
        path = self._root / "data" / "photo_optimize"
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def state_dir(self, *, create: bool = True) -> Path:
        """Return the mutable runtime-state directory."""
        path = self._root / "state"
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def queue_state(self) -> Path:
        """Return the legacy queue JSON path for offline migration only."""
        return self.state_dir(create=False) / "queue_state_v2.json"

    def job_repository(self) -> Path:
        """Return the authoritative SQLite job repository path."""
        return self.state_dir(create=False) / "jobs.sqlite3"

    def ui_state(self) -> Path:
        """Return the UI-state path without creating its parent."""
        return self.state_dir(create=False) / "ui_state.json"

    def sidebar_state(self) -> Path:
        """Return the sidebar-state path without creating its parent."""
        return self.state_dir(create=False) / "sidebar_state.json"

    def preview_panel_state(self) -> Path:
        """Return the preview-panel-state path without creating its parent."""
        return self.state_dir(create=False) / "preview_panel_state.json"

    def custom_pack_lists(self) -> Path:
        """Return the custom PromptPack-list path without creating its parent."""
        return self.state_dir(create=False) / "custom_pack_lists.json"

    def last_run_v2(self) -> Path:
        """Return the v2 last-run path without creating its parent."""
        return self.state_dir(create=False) / "last_run_v2.json"

    def last_run_v2_5(self) -> Path:
        """Return the legacy v2.5 last-run path without creating its parent."""
        return self.state_dir(create=False) / "last_run_v2_5.json"


workspace_paths: WorkspacePaths = WorkspacePaths()
