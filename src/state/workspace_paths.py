"""workspace_paths — runtime workspace root provider for StableNew.

Central registry for all runtime data paths used across subsystems.  Using
``WorkspacePaths`` instead of hard-coded ``Path("data/...")`` literals allows:

1. Tests to redirect all I/O to a ``tmp_path`` by passing a custom root.
2. Future multi-workspace support without scattered literal changes.
3. A single place to audit what runtime directories the application writes to.

Usage::

    from src.state.workspace_paths import workspace_paths

    records = workspace_paths.learning_records()    # data/learning/learning_records.jsonl
    root    = workspace_paths.learning_experiments_root()   # data/learning/experiments/
    opt     = workspace_paths.photo_optimize_root()  # data/photo_optimize/

To override in tests::

    from src.state.workspace_paths import WorkspacePaths
    custom = WorkspacePaths(root=tmp_path)
    records = custom.learning_records()
"""

from __future__ import annotations

from pathlib import Path


class WorkspacePaths:
    """Provides resolved runtime paths anchored to a configurable root.

    The default root is the repository root (inferred at import time as the
    parent-parent of this file's directory, i.e. ``src/state/../../``).

    All path accessors return absolute Path objects.  Side-effect methods
    (``create_parent``, ``create``) are opt-in and default to True for
    backward-compatibility with the old ``learning_paths.py`` constants.
    """

    def __init__(self, root: Path | str | None = None) -> None:
        if root is None:
            # Default: two levels up from src/state/ = project root.
            root = Path(__file__).parent.parent.parent
        self._root = Path(root).resolve()

    @property
    def root(self) -> Path:
        return self._root

    # ------------------------------------------------------------------
    # Learning subsystem paths
    # ------------------------------------------------------------------

    def learning_records(self, *, create_parent: bool = True) -> Path:
        """Absolute path to the canonical learning records JSONL file."""
        path = self._root / "data" / "learning" / "learning_records.jsonl"
        if create_parent:
            path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def learning_experiments_root(self, *, create: bool = True) -> Path:
        """Absolute path to the learning experiments workspace directory."""
        path = self._root / "data" / "learning" / "experiments"
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def learning_discovered_root(self, *, create: bool = True) -> Path:
        """Absolute path to the discovered-review store root (data/learning/)."""
        path = self._root / "data" / "learning"
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    # ------------------------------------------------------------------
    # Photo-optimize subsystem paths
    # ------------------------------------------------------------------

    def photo_optimize_root(self, *, create: bool = True) -> Path:
        """Absolute path to the photo-optimize assets directory."""
        path = self._root / "data" / "photo_optimize"
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    # ------------------------------------------------------------------
    # State / persistence paths
    # ------------------------------------------------------------------

    def state_dir(self, *, create: bool = True) -> Path:
        """Absolute path to the runtime state directory (queue state, etc.)."""
        path = self._root / "state"
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def queue_state(self) -> Path:
        """Absolute path to the canonical queue runtime state file."""
        return self.state_dir() / "queue_state_v2.json"

    def ui_state(self) -> Path:
        """Absolute path to the canonical UI runtime state file."""
        return self.state_dir() / "ui_state.json"

    def sidebar_state(self) -> Path:
        """Absolute path to the sidebar runtime state file."""
        return self.state_dir() / "sidebar_state.json"

    def preview_panel_state(self) -> Path:
        """Absolute path to the preview-panel runtime state file."""
        return self.state_dir() / "preview_panel_state.json"

    def custom_pack_lists(self) -> Path:
        """Absolute path to the saved custom prompt-pack list file."""
        return self.state_dir() / "custom_pack_lists.json"

    def last_run_v2(self) -> Path:
        """Absolute path to the canonical last-run payload."""
        return self.state_dir() / "last_run_v2.json"

    def last_run_v2_5(self) -> Path:
        """Absolute path to the legacy v2.5 last-run payload."""
        return self.state_dir() / "last_run_v2_5.json"


# Module-level default instance (equivalent to the old module-level constants).
# All subsystem code should import and use this object.
workspace_paths: WorkspacePaths = WorkspacePaths()
