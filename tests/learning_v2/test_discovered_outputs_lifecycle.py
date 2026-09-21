"""Discovered Outputs scanner/store lifecycle over the journey's synthetic fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.learning.discovered_grouping import GroupingEngine
from src.learning.discovered_review_store import DiscoveredReviewStore
from src.learning.output_scanner import OutputScanner
from tools.operator_journey.fixtures import CFG_VALUES, write_discovered_fixture


def _scan_into(store: DiscoveredReviewStore, output_root: Path) -> list[str]:
    """What trigger_background_scan does, minus the thread: scan, group, persist."""

    scanner = OutputScanner(output_root, scan_index=store.load_scan_index())
    records = scanner.scan_incremental()
    store.save_scan_index(scanner.scan_index)
    existing = {h.group_id for h in store.list_handles()}
    candidates = GroupingEngine().build_candidates(records, existing_group_ids=existing)
    for candidate in candidates:
        store.save_group(candidate)
    return [c.group_id for c in candidates]


@pytest.fixture
def world(tmp_path: Path):
    output = tmp_path / "output"
    fixture = write_discovered_fixture(output)
    store = DiscoveredReviewStore(tmp_path / "learning")
    return output, fixture, store


def test_fixture_forms_exactly_one_cfg_group(world) -> None:
    output, fixture, store = world
    created = _scan_into(store, output)
    assert len(created) == 1
    handle = store.list_handles()[0]
    assert tuple(handle.varying_fields) == ("cfg_scale",)
    assert (handle.item_count, handle.available_item_count, handle.missing_item_count) == (3, 3, 0)
    group = store.load_group(handle.group_id)
    assert sorted(i.cfg_scale for i in group.items) == sorted(CFG_VALUES)
    assert all(Path(i.artifact_path).is_file() for i in group.items)
    assert group.origin == "filesystem_scan"


def test_done_survives_reload_and_restore_is_distinct_from_dismiss(world) -> None:
    output, _, store = world
    (group_id,) = _scan_into(store, output)
    assert store.close_group(group_id)
    assert DiscoveredReviewStore(store.root).list_handles()[0].status == "closed"
    assert store.reopen_group(group_id)
    assert store.list_handles()[0].status == "waiting_review"
    assert store.ignore_group(group_id)
    assert DiscoveredReviewStore(store.root).list_handles()[0].status == "ignored"


def test_dismiss_suppresses_duplicate_groups_on_ordinary_rescan(world) -> None:
    output, _, store = world
    (group_id,) = _scan_into(store, output)
    store.ignore_group(group_id)
    assert _scan_into(store, output) == []
    assert [(h.group_id, h.status) for h in store.list_handles()] == [(group_id, "ignored")]


def test_missing_artifact_changes_available_and_missing_counts(world) -> None:
    output, fixture, store = world
    _scan_into(store, output)
    fixture[2].image.unlink()
    handle = store.list_handles()[0]
    assert (handle.item_count, handle.available_item_count, handle.missing_item_count) == (3, 2, 1)


def test_zero_available_group_is_not_active_work(world) -> None:
    output, fixture, store = world
    _scan_into(store, output)
    for artifact in fixture:
        artifact.image.unlink()
    handle = store.list_handles()[0]
    assert handle.available_item_count == 0 and handle.missing_item_count == 3
    assert store.preview_missing_cleanup()["zero_available_groups"] == 1


def test_clean_missing_references_never_deletes_physical_artifacts(world) -> None:
    output, fixture, store = world
    _scan_into(store, output)
    fixture[2].image.unlink()
    counts = store.prune_missing_scanner_items()
    assert counts["missing_items"] == 1 and counts["groups_removed"] == 0
    handle = store.list_handles()[0]
    assert (handle.item_count, handle.available_item_count, handle.missing_item_count) == (2, 2, 0)
    assert all(a.manifest.exists() for a in fixture)
    assert all(a.image.exists() for a in fixture[:2])


def test_rebuild_resets_scanner_state_without_deleting_files(world) -> None:
    output, fixture, store = world
    (group_id,) = _scan_into(store, output)
    counts = store.reset_filesystem_scan_state()
    assert counts["groups_removed"] == 1 and store.list_handles() == []
    assert all(a.image.exists() and a.manifest.exists() for a in fixture)
    (rebuilt,) = _scan_into(store, output)
    assert rebuilt == group_id and len(store.list_handles()) == 1  # deterministic id, no duplicate


def test_rebuild_preserves_dismissed_groups_and_never_duplicates_them(world) -> None:
    output, _, store = world
    (group_id,) = _scan_into(store, output)
    store.ignore_group(group_id)
    assert store.reset_filesystem_scan_state()["groups_removed"] == 0
    assert _scan_into(store, output) == []
    assert [(h.group_id, h.status) for h in store.list_handles()] == [(group_id, "ignored")]
