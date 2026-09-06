"""Tests for the ``WorkspacePaths`` contract.

All tests are fully isolated: they use pytest's ``tmp_path`` fixture to avoid
touching the real data/ tree and do not perform any network I/O.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.state.workspace_paths import WorkspacePaths, workspace_paths


# ---------------------------------------------------------------------------
# Default instance smoke tests
# ---------------------------------------------------------------------------


class TestDefaultInstance:
    """The module-level ``workspace_paths`` singleton uses the repo root."""

    def test_is_workspace_paths_instance(self):
        assert isinstance(workspace_paths, WorkspacePaths)

    def test_root_is_absolute(self):
        assert workspace_paths.root.is_absolute()

    def test_root_contains_src(self):
        src = workspace_paths.root / "src"
        assert src.exists(), f"Expected src/ under root, got root={workspace_paths.root}"


# ---------------------------------------------------------------------------
# Path structure tests (using tmp_path for isolation)
# ---------------------------------------------------------------------------


class TestPathStructure:
    """All path getters return a Path underneath the configured root."""

    @pytest.fixture
    def wp(self, tmp_path: Path) -> WorkspacePaths:
        return WorkspacePaths(root=tmp_path)

    def test_learning_records_under_root(self, wp, tmp_path):
        p = wp.learning_records(create_parent=False)
        assert str(p).startswith(str(tmp_path))

    def test_learning_records_correct_name(self, wp):
        p = wp.learning_records(create_parent=False)
        assert p.name == "learning_records.jsonl"

    def test_learning_records_correct_parent(self, wp, tmp_path):
        p = wp.learning_records(create_parent=False)
        assert p.parent == tmp_path / "data" / "learning"

    def test_learning_experiments_root_correct_path(self, wp, tmp_path):
        p = wp.learning_experiments_root(create=False)
        assert p == (tmp_path / "data" / "learning" / "experiments").resolve()

    def test_learning_discovered_root_correct_path(self, wp, tmp_path):
        p = wp.learning_discovered_root(create=False)
        assert p == (tmp_path / "data" / "learning").resolve()

    def test_photo_optimize_root_correct_path(self, wp, tmp_path):
        p = wp.photo_optimize_root(create=False)
        assert p == (tmp_path / "data" / "photo_optimize").resolve()

    def test_state_dir_correct_path(self, wp, tmp_path):
        p = wp.state_dir(create=False)
        assert p == (tmp_path / "state").resolve()

    def test_state_file_helpers_resolve_under_state_dir(self, wp, tmp_path):
        expected = (tmp_path / "state").resolve()
        assert wp.queue_state().parent == expected
        assert wp.ui_state().parent == expected
        assert wp.sidebar_state().parent == expected
        assert wp.preview_panel_state().parent == expected
        assert wp.custom_pack_lists().parent == expected
        assert wp.last_run_v2().parent == expected
        assert wp.last_run_v2_5().parent == expected

    def test_state_file_helpers_use_canonical_filenames(self, wp):
        assert wp.queue_state().name == "queue_state_v2.json"
        assert wp.ui_state().name == "ui_state.json"
        assert wp.sidebar_state().name == "sidebar_state.json"
        assert wp.preview_panel_state().name == "preview_panel_state.json"
        assert wp.custom_pack_lists().name == "custom_pack_lists.json"
        assert wp.last_run_v2().name == "last_run_v2.json"
        assert wp.last_run_v2_5().name == "last_run_v2_5.json"


# ---------------------------------------------------------------------------
# Directory-creation side-effect tests
# ---------------------------------------------------------------------------


class TestDirectoryCreation:
    """create=True (default) causes the directories to be created."""

    @pytest.fixture
    def wp(self, tmp_path: Path) -> WorkspacePaths:
        return WorkspacePaths(root=tmp_path)

    def test_learning_records_creates_parent(self, wp):
        p = wp.learning_records(create_parent=True)
        assert p.parent.exists()

    def test_learning_experiments_root_creates_dir(self, wp):
        p = wp.learning_experiments_root(create=True)
        assert p.exists()

    def test_learning_discovered_root_creates_dir(self, wp):
        p = wp.learning_discovered_root(create=True)
        assert p.exists()

    def test_photo_optimize_root_creates_dir(self, wp):
        p = wp.photo_optimize_root(create=True)
        assert p.exists()

    def test_state_dir_creates_dir(self, wp):
        p = wp.state_dir(create=True)
        assert p.exists()

    def test_no_create_does_not_create_dir(self, wp, tmp_path):
        p = wp.learning_experiments_root(create=False)
        # The dir should NOT be present (tmp_path starts empty).
        assert not p.exists()

    def test_file_path_helpers_do_not_create_state_dir(self, tmp_path):
        root = tmp_path / "missing-workspace"
        wp = WorkspacePaths(root=root)

        paths = [
            wp.queue_state(),
            wp.ui_state(),
            wp.sidebar_state(),
            wp.preview_panel_state(),
            wp.custom_pack_lists(),
            wp.last_run_v2(),
            wp.last_run_v2_5(),
        ]

        assert all(path.parent == root.resolve() / "state" for path in paths)
        assert not root.exists()


# ---------------------------------------------------------------------------
# Custom root isolation tests
# ---------------------------------------------------------------------------


class TestCustomRoot:
    """Passing a custom root redirects all path helpers to that root."""

    def test_custom_str_root(self, tmp_path):
        wp = WorkspacePaths(root=str(tmp_path))
        assert wp.root == tmp_path.resolve()

    def test_all_paths_under_custom_root(self, tmp_path):
        wp = WorkspacePaths(root=tmp_path)
        paths = [
            wp.learning_records(create_parent=False),
            wp.learning_experiments_root(create=False),
            wp.learning_discovered_root(create=False),
            wp.photo_optimize_root(create=False),
            wp.state_dir(create=False),
        ]
        for p in paths:
            assert str(p).startswith(str(tmp_path.resolve())), (
                f"Path {p} is not under tmp_path {tmp_path.resolve()}"
            )

    def test_different_roots_give_different_paths(self, tmp_path):
        wp1 = WorkspacePaths(root=tmp_path / "a")
        wp2 = WorkspacePaths(root=tmp_path / "b")
        assert wp1.learning_records(create_parent=False) != wp2.learning_records(
            create_parent=False
        )


# ---------------------------------------------------------------------------
# Consistency with learning_paths constants
# ---------------------------------------------------------------------------


class TestLearningPathsConsistency:
    """The constants in learning_paths.py now delegate to workspace_paths."""

    def test_learning_paths_constants_are_absolute(self):
        from src.learning.learning_paths import (
            CANONICAL_LEARNING_RECORDS_PATH,
            CANONICAL_LEARNING_EXPERIMENTS_ROOT,
            CANONICAL_DISCOVERED_EXPERIMENTS_ROOT,
        )
        assert CANONICAL_LEARNING_RECORDS_PATH.is_absolute()
        assert CANONICAL_LEARNING_EXPERIMENTS_ROOT.is_absolute()
        assert CANONICAL_DISCOVERED_EXPERIMENTS_ROOT.is_absolute()

    def test_learning_paths_match_workspace_paths(self):
        from src.learning.learning_paths import (
            CANONICAL_LEARNING_RECORDS_PATH,
            CANONICAL_LEARNING_EXPERIMENTS_ROOT,
            CANONICAL_DISCOVERED_EXPERIMENTS_ROOT,
        )
        assert CANONICAL_LEARNING_RECORDS_PATH == workspace_paths.learning_records(
            create_parent=False
        )
        assert CANONICAL_LEARNING_EXPERIMENTS_ROOT == workspace_paths.learning_experiments_root(
            create=False
        )
        assert CANONICAL_DISCOVERED_EXPERIMENTS_ROOT == workspace_paths.learning_discovered_root(
            create=False
        )
