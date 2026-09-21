"""Scan-index dispositions: incremental for classified artifacts, never for waiting ones."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.learning.discovered_review_store import DiscoveredReviewStore
from src.learning.discovered_scan_service import apply_scan
from src.learning.output_scanner import OutputScanner
from tools.operator_journey.fixtures import MODEL, NEGATIVE, PROMPT, write_png

RUN = "Pipeline/20260101_000000_run"


def _artifact(output: Path, cfg: int, *, learning_context: dict | None = None) -> tuple[Path, Path]:
    image = output / RUN / f"txt2img_cfg{cfg}.png"
    manifest = output / RUN / "manifests" / f"txt2img_cfg{cfg}.json"
    write_png(image, (cfg * 20, 60, 90))
    manifest.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "stage": "txt2img",
        "final_prompt": PROMPT,
        "final_negative_prompt": NEGATIVE,
        "model": MODEL,
        "sampler_name": "Euler a",
        "scheduler": "normal",
        "steps": 20,
        "cfg_scale": float(cfg),
        "seed": 1,
        "width": 64,
        "height": 64,
    }
    if learning_context:
        data["learning_context"] = learning_context
    manifest.write_text(json.dumps(data), encoding="utf-8")
    return image, manifest


def _scan(store: DiscoveredReviewStore, output: Path):
    scanner = OutputScanner(output, scan_index=store.load_scan_index())
    records = scanner.scan_incremental()
    outcome = apply_scan(
        scanner,
        store,
        records,
        is_controlled=lambda r: bool(
            (r.extra_fields.get("learning_context") or {}).get("experiment_id")
        ),
    )
    return records, outcome


@pytest.fixture
def world(tmp_path: Path):
    return tmp_path / "output", DiscoveredReviewStore(tmp_path / "learning")


def test_new_group_completes_the_index_and_unchanged_rescan_reads_nothing(world) -> None:
    output, store = world
    for cfg in (5, 7, 9):
        _artifact(output, cfg)
    records, outcome = _scan(store, output)
    assert (len(records), outcome.new_group_count) == (3, 1)
    (handle,) = store.list_handles()
    index = store.load_scan_index()
    assert len(index) == 3
    assert all(e.eligible and e.group_id == handle.group_id and e.scan_key for e in index.values())
    assert {e.scan_key for e in index.values()} == {r.scan_key for r in records}

    records, outcome = _scan(store, output)
    assert records == [] and outcome.new_group_count == 0 and len(store.list_handles()) == 1


def test_reviewed_groups_are_untouched_by_ordinary_rescans(world) -> None:
    output, store = world
    for cfg in (5, 7, 9):
        _artifact(output, cfg)
    _scan(store, output)
    (handle,) = store.list_handles()
    group = store.load_group(handle.group_id)
    first = group.items[0]
    store.save_item_rating(handle.group_id, first.item_id, 4)
    store.ignore_group(handle.group_id)
    _scan(store, output)
    after = store.load_group(handle.group_id)
    assert after.status == "ignored" and [i.item_id for i in after.items] == [
        i.item_id for i in group.items
    ]
    assert next(i for i in after.items if i.item_id == first.item_id).rating == 4
    assert len(store.list_handles()) == 1


def test_waiting_artifacts_are_not_indexed_so_a_later_sibling_completes_the_group(world) -> None:
    output, store = world
    _artifact(output, 5)
    _artifact(output, 7)
    records, outcome = _scan(store, output)
    assert len(records) == 2 and outcome.new_group_count == 0
    assert store.load_scan_index() == {}  # still reconsiderable
    _artifact(output, 9)
    records, outcome = _scan(store, output)
    assert len(records) == 3 and outcome.new_group_count == 1
    assert len(store.load_scan_index()) == 3


def test_changed_manifest_is_reconsidered_and_its_key_is_not_advanced(world) -> None:
    output, store = world
    manifests = [_artifact(output, cfg)[1] for cfg in (5, 7, 9)]
    _scan(store, output)
    old_key = store.load_scan_index()[str(manifests[0].parent.parent / "txt2img_cfg5.png")].scan_key
    data = json.loads(manifests[0].read_text(encoding="utf-8"))
    data["steps"] = 30
    manifests[0].write_text(json.dumps(data), encoding="utf-8")
    records, _ = _scan(store, output)
    assert [Path(r.artifact_path).name for r in records] == ["txt2img_cfg5.png"]
    entry = store.load_scan_index()[records[0].artifact_path]
    assert entry.scan_key == old_key and entry.scan_key != records[0].scan_key
    records_again, _ = _scan(store, output)
    assert len(records_again) == 1  # still unreconciled, not hidden


def test_invalid_manifest_is_a_definitive_ineligible_disposition(world) -> None:
    output, store = world
    image, manifest = _artifact(output, 5)
    manifest.write_text("{}", encoding="utf-8")  # parses but yields no record
    records, _ = _scan(store, output)
    assert records == []
    (entry,) = store.load_scan_index().values()
    assert entry.eligible is False and entry.group_id == ""
    scanner = OutputScanner(output, scan_index=store.load_scan_index())
    assert scanner.scan_incremental() == []


def test_controlled_artifacts_are_indexed_ineligible_until_their_manifest_changes(world) -> None:
    output, store = world
    _artifact(output, 5, learning_context={"experiment_id": "exp-1"})
    records, outcome = _scan(store, output)
    assert len(records) == 1 and outcome.record_count == 0 and store.list_handles() == []
    (entry,) = store.load_scan_index().values()
    assert entry.eligible is False and entry.group_id == ""
    assert _scan(store, output)[0] == []
    _artifact(output, 5, learning_context={"experiment_id": "exp-1", "note": "edited"})
    assert len(_scan(store, output)[0]) == 1


def test_existing_group_without_index_is_never_backfilled(world) -> None:
    output, store = world
    for cfg in (5, 7, 9):
        _artifact(output, cfg)
    _scan(store, output)
    (handle,) = store.list_handles()
    group = store.load_group(handle.group_id)
    store.save_item_rating(handle.group_id, group.items[0].item_id, 4)
    store.close_group(handle.group_id)
    before = store.load_group(handle.group_id)
    store.save_scan_index({})  # historical / lost index
    for _ in range(2):
        records, outcome = _scan(store, output)
        assert len(records) == 3 and outcome.new_group_count == 0  # reconsidered every scan
        assert store.load_scan_index() == {}
    after = store.load_group(handle.group_id)
    assert (after.status, [(i.item_id, i.rating) for i in after.items]) == (
        before.status,
        [(i.item_id, i.rating) for i in before.items],
    )
    assert len(store.list_handles()) == 1


@pytest.mark.parametrize("field", ["vae", "clip_skip"])
def test_manifest_changed_in_a_non_persisted_field_is_never_hidden(world, field: str) -> None:
    """Items do not store VAE/clip skip, so equality with an old group is unprovable."""

    output, store = world
    manifests = [_artifact(output, cfg)[1] for cfg in (5, 7, 9)]
    _scan(store, output)
    (handle,) = store.list_handles()
    group_before = store.load_group(handle.group_id)
    store.save_scan_index({})
    data = json.loads(manifests[1].read_text(encoding="utf-8"))
    data[field] = "changed-vae" if field == "vae" else 1
    manifests[1].write_text(json.dumps(data), encoding="utf-8")
    for _ in range(2):
        records, _ = _scan(store, output)
        assert "txt2img_cfg7.png" in {Path(r.artifact_path).name for r in records}
        assert store.load_scan_index() == {}  # the new key was never persisted
    assert [i.item_id for i in store.load_group(handle.group_id).items] == [
        i.item_id for i in group_before.items
    ]


def test_rebuild_reconstructs_the_index_without_touching_files(world) -> None:
    output, store = world
    artifacts = [_artifact(output, cfg) for cfg in (5, 7, 9)]
    _scan(store, output)
    store.reset_filesystem_scan_state()
    assert store.load_scan_index() == {} and store.list_handles() == []
    _, outcome = _scan(store, output)
    assert outcome.new_group_count == 1 and len(store.load_scan_index()) == 3
    assert all(i.exists() and m.exists() for i, m in artifacts)


def test_clean_missing_references_removes_the_stale_index_entry(world) -> None:
    output, store = world
    artifacts = [_artifact(output, cfg) for cfg in (5, 7, 9)]
    _scan(store, output)
    artifacts[2][0].unlink()
    store.prune_missing_scanner_items()
    index = store.load_scan_index()
    assert len(index) == 2 and str(artifacts[2][0]) not in index
    assert artifacts[2][1].exists()
