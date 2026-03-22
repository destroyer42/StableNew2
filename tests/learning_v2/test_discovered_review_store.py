# Tests: Learning subsystem
# PR: PR-GUI-LEARN-039 — Discovered-review models and store

"""Tests for DiscoveredReviewStore, DiscoveredReviewExperiment, and related models."""

from __future__ import annotations

import pytest

from src.curation.models import SelectionEvent
from src.learning.discovered_review_models import (
    RATING_MAX,
    RATING_MIN,
    RATING_UNRATED,
    STATUS_CLOSED,
    STATUS_IGNORED,
    STATUS_IN_REVIEW,
    STATUS_WAITING_REVIEW,
    DiscoveredReviewExperiment,
    DiscoveredReviewHandle,
    DiscoveredReviewItem,
    OutputScanIndexEntry,
)
from src.learning.discovered_review_store import DiscoveredReviewStore


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_item(item_id: str = "item-1", stage: str = "txt2img") -> DiscoveredReviewItem:
    return DiscoveredReviewItem(
        item_id=item_id,
        artifact_path=f"output/run1/{item_id}.png",
        stage=stage,
        model="sd_xl_base_1.0",
        sampler="Euler",
        steps=20,
        cfg_scale=7.0,
        positive_prompt="a fantasy knight",
    )


def _make_experiment(
    group_id: str = "group-001",
    item_count: int = 3,
) -> DiscoveredReviewExperiment:
    items = [_make_item(f"item-{i+1}") for i in range(item_count)]
    return DiscoveredReviewExperiment(
        group_id=group_id,
        display_name="test group",
        stage="txt2img",
        prompt_hash="abc123",
        items=items,
        varying_fields=["cfg_scale"],
    )


@pytest.fixture
def store(tmp_path):
    return DiscoveredReviewStore(tmp_path)


# ---------------------------------------------------------------------------
# Model round-trip
# ---------------------------------------------------------------------------


def test_item_round_trip():
    item = _make_item()
    item.rating = 4
    item.rating_notes = "good"
    restored = DiscoveredReviewItem.from_dict(item.to_dict())
    assert restored.item_id == item.item_id
    assert restored.rating == 4
    assert restored.rating_notes == "good"
    assert restored.stage == item.stage


def test_experiment_round_trip():
    exp = _make_experiment()
    meta = exp.to_meta_dict()
    items = exp.to_items_list()
    restored = DiscoveredReviewExperiment.from_meta_and_items(meta, items)
    assert restored.group_id == exp.group_id
    assert restored.display_name == exp.display_name
    assert len(restored.items) == len(exp.items)
    assert restored.varying_fields == exp.varying_fields


def test_handle_round_trip():
    handle = DiscoveredReviewHandle(
        group_id="g1",
        display_name="test",
        stage="txt2img",
        status=STATUS_WAITING_REVIEW,
        item_count=5,
        varying_fields=("cfg_scale", "steps"),
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-02T00:00:00Z",
    )
    restored = DiscoveredReviewHandle.from_dict(handle.to_dict())
    assert restored.group_id == handle.group_id
    assert restored.varying_fields == handle.varying_fields
    assert restored.item_count == 5


def test_scan_index_entry_round_trip():
    entry = OutputScanIndexEntry(
        artifact_path="output/run1/img.png",
        scan_key="sha256abc",
        scanned_at="2026-01-01T00:00:00Z",
        group_id="group-001",
        eligible=True,
    )
    restored = OutputScanIndexEntry.from_dict(entry.to_dict())
    assert restored.artifact_path == entry.artifact_path
    assert restored.scan_key == entry.scan_key
    assert restored.eligible is True


# ---------------------------------------------------------------------------
# Status lifecycle
# ---------------------------------------------------------------------------


def test_status_lifecycle_valid_transitions():
    exp = _make_experiment()
    assert exp.status == STATUS_WAITING_REVIEW
    exp.transition_status(STATUS_IN_REVIEW)
    assert exp.status == STATUS_IN_REVIEW
    exp.transition_status(STATUS_CLOSED)
    assert exp.status == STATUS_CLOSED
    exp.transition_status(STATUS_WAITING_REVIEW)
    assert exp.status == STATUS_WAITING_REVIEW


def test_status_lifecycle_invalid_raises():
    exp = _make_experiment()
    with pytest.raises(ValueError):
        exp.transition_status("bogus_status")


def test_is_fully_rated_false_initially():
    exp = _make_experiment()
    assert not exp.is_fully_rated()


def test_is_fully_rated_true_when_all_rated():
    exp = _make_experiment()
    for item in exp.items:
        item.rating = 3
    assert exp.is_fully_rated()


def test_is_fully_rated_false_partial():
    exp = _make_experiment()
    exp.items[0].rating = 4
    # others still 0
    assert not exp.is_fully_rated()


# ---------------------------------------------------------------------------
# Store: create and load
# ---------------------------------------------------------------------------


def test_store_save_and_load_round_trip(store):
    exp = _make_experiment("g-rt-001")
    store.save_group(exp)
    loaded = store.load_group("g-rt-001")
    assert loaded is not None
    assert loaded.group_id == "g-rt-001"
    assert len(loaded.items) == 3
    assert loaded.schema_version == "1.0"


def test_store_load_missing_returns_none(store):
    assert store.load_group("does-not-exist") is None


def test_store_saves_updated_at_on_save(store):
    exp = _make_experiment("g-ts-001")
    old_ts = exp.updated_at
    store.save_group(exp)
    loaded = store.load_group("g-ts-001")
    assert loaded is not None
    assert loaded.updated_at >= old_ts


# ---------------------------------------------------------------------------
# Store: listing and handles
# ---------------------------------------------------------------------------


def test_store_list_handles_empty(store):
    assert store.list_handles() == []


def test_store_list_handles_returns_all(store):
    store.save_group(_make_experiment("g-list-001"))
    store.save_group(_make_experiment("g-list-002"))
    handles = store.list_handles()
    ids = {h.group_id for h in handles}
    assert "g-list-001" in ids
    assert "g-list-002" in ids


def test_store_list_handles_status_filter(store):
    store.save_group(_make_experiment("g-open"))
    closed_exp = _make_experiment("g-closed")
    closed_exp.status = STATUS_CLOSED
    store.save_group(closed_exp)

    waiting = store.list_handles(status=STATUS_WAITING_REVIEW)
    assert all(h.status == STATUS_WAITING_REVIEW for h in waiting)
    closed = store.list_handles(status=STATUS_CLOSED)
    assert all(h.status == STATUS_CLOSED for h in closed)


def test_store_list_handles_by_statuses(store):
    store.save_group(_make_experiment("g-w"))
    exp_c = _make_experiment("g-c")
    exp_c.status = STATUS_CLOSED
    store.save_group(exp_c)
    results = store.list_handles_by_status([STATUS_WAITING_REVIEW, STATUS_CLOSED])
    assert len(results) == 2


# ---------------------------------------------------------------------------
# Store: status transitions
# ---------------------------------------------------------------------------


def test_store_close_group(store):
    store.save_group(_make_experiment("g-close"))
    assert store.close_group("g-close")
    loaded = store.load_group("g-close")
    assert loaded.status == STATUS_CLOSED


def test_store_ignore_group(store):
    store.save_group(_make_experiment("g-ignore"))
    assert store.ignore_group("g-ignore")
    loaded = store.load_group("g-ignore")
    assert loaded.status == STATUS_IGNORED


def test_store_reopen_group(store):
    exp = _make_experiment("g-reopen")
    exp.status = STATUS_CLOSED
    store.save_group(exp)
    assert store.reopen_group("g-reopen")
    loaded = store.load_group("g-reopen")
    assert loaded.status == STATUS_WAITING_REVIEW


def test_store_begin_review(store):
    store.save_group(_make_experiment("g-review"))
    assert store.begin_review("g-review")
    loaded = store.load_group("g-review")
    assert loaded.status == STATUS_IN_REVIEW


def test_store_transition_missing_group_returns_false(store):
    assert not store.transition_status("ghost", STATUS_CLOSED)


# ---------------------------------------------------------------------------
# Store: per-item rating
# ---------------------------------------------------------------------------


def test_store_save_item_rating(store):
    exp = _make_experiment("g-rate")
    store.save_group(exp)
    ok = store.save_item_rating("g-rate", "item-2", rating=5, notes="excellent")
    assert ok
    loaded = store.load_group("g-rate")
    target = next(i for i in loaded.items if i.item_id == "item-2")
    assert target.rating == 5
    assert target.rating_notes == "excellent"
    assert target.rated_at != ""


def test_store_save_item_rating_missing_group(store):
    assert not store.save_item_rating("ghost", "item-1", rating=3)


def test_store_rating_persists_across_reload(store):
    exp = _make_experiment("g-persist")
    store.save_group(exp)
    store.save_item_rating("g-persist", "item-1", rating=4)
    loaded = store.load_group("g-persist")
    item = next(i for i in loaded.items if i.item_id == "item-1")
    assert item.rating == 4


def test_store_append_and_load_selection_events(store):
    exp = _make_experiment("g-curation")
    store.save_group(exp)
    event = SelectionEvent(
        event_id="sel-1",
        workflow_id="curation:g-curation",
        candidate_id="item-1",
        stage="scout",
        decision="advanced_to_refine",
        timestamp="2026-03-21T23:00:00Z",
        reason_tags=["good_composition"],
        notes="worth a refine pass",
    )
    assert store.append_selection_event("g-curation", event) is True
    loaded = store.load_selection_events("g-curation")
    assert len(loaded) == 1
    assert loaded[0].candidate_id == "item-1"
    assert loaded[0].decision == "advanced_to_refine"


def test_store_append_selection_event_missing_group_returns_false(store):
    event = SelectionEvent(
        event_id="sel-missing",
        workflow_id="curation:ghost",
        candidate_id="item-1",
        stage="scout",
        decision="not_advanced",
        timestamp="2026-03-21T23:05:00Z",
    )
    assert store.append_selection_event("ghost", event) is False


# ---------------------------------------------------------------------------
# Store: scan index
# ---------------------------------------------------------------------------


def test_store_scan_index_empty_initially(store):
    assert store.load_scan_index() == {}


def test_store_save_and_load_scan_index(store):
    entries = [
        OutputScanIndexEntry(
            artifact_path="output/r1/img.png",
            scan_key="sha1",
            scanned_at="2026-01-01T00:00:00Z",
            group_id="g1",
            eligible=True,
        )
    ]
    store.update_scan_index_entries(entries)
    index = store.load_scan_index()
    assert "output/r1/img.png" in index
    assert index["output/r1/img.png"].eligible is True


def test_store_scan_index_incremental_update(store):
    e1 = OutputScanIndexEntry("a.png", "k1", "2026-01-01T00:00:00Z", eligible=False)
    store.update_scan_index_entries([e1])
    e2 = OutputScanIndexEntry("b.png", "k2", "2026-01-02T00:00:00Z", eligible=True)
    store.update_scan_index_entries([e2])
    index = store.load_scan_index()
    assert "a.png" in index
    assert "b.png" in index


def test_store_is_artifact_in_index(store):
    store.update_scan_index_entries(
        [OutputScanIndexEntry("img.png", "k", "2026-01-01T00:00:00Z")]
    )
    assert store.is_artifact_in_index("img.png")
    assert not store.is_artifact_in_index("missing.png")


def test_store_scan_index_update_overwrites_entry(store):
    e1 = OutputScanIndexEntry("img.png", "k1", "2026-01-01T00:00:00Z", eligible=False)
    store.update_scan_index_entries([e1])
    e2 = OutputScanIndexEntry("img.png", "k1-updated", "2026-01-02T00:00:00Z", eligible=True)
    store.update_scan_index_entries([e2])
    index = store.load_scan_index()
    assert index["img.png"].scan_key == "k1-updated"
    assert index["img.png"].eligible is True


# ---------------------------------------------------------------------------
# Store: delete group
# ---------------------------------------------------------------------------


def test_store_delete_group(store):
    store.save_group(_make_experiment("g-del"))
    assert store.delete_group("g-del")
    assert store.load_group("g-del") is None


def test_store_delete_missing_group_returns_false(store):
    assert not store.delete_group("ghost")


# ---------------------------------------------------------------------------
# Deterministic ordering
# ---------------------------------------------------------------------------


def test_store_list_handles_order_is_deterministic(store):
    for i in range(5):
        store.save_group(_make_experiment(f"z-group-{i:03d}"))
    handles1 = store.list_handles()
    handles2 = store.list_handles()
    assert [h.group_id for h in handles1] == [h.group_id for h in handles2]
