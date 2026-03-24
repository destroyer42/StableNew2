from __future__ import annotations

from src.learning import learning_paths
from src.state.workspace_paths import workspace_paths


def test_learning_records_path_is_canonical_only() -> None:
    path = learning_paths.get_learning_records_path(create_parent=False)
    assert path == workspace_paths.learning_records(create_parent=False)
    assert path.is_absolute()
    assert path.as_posix().endswith("/data/learning/learning_records.jsonl")


def test_learning_paths_has_no_legacy_fallback_exports() -> None:
    assert not hasattr(learning_paths, "LEGACY_LEARNING_RECORDS_PATHS")
    assert not hasattr(learning_paths, "iter_learning_records_candidates")
    assert not hasattr(learning_paths, "pick_existing_learning_records_path")

