"""PR-GUI-UX-580: planning and applying the operator-confirmed import of existing images into the managed workspace."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from src.photo_optimize.managed_import import (
    EXISTING,
    IMPORT_COPY,
    NEW,
    OPEN_EXISTING,
    REFUSED,
    apply_managed_import,
    plan_managed_import,
)
from src.photo_optimize.store import PhotoOptimizeStore


def _image(path: Path, color=(10, 20, 30), size=(48, 32)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return path


@pytest.fixture
def store(tmp_path):
    return PhotoOptimizeStore(tmp_path / "managed")


def _asset_ids(store) -> list[str]:
    return sorted(asset.asset_id for asset in store.list_assets(include_archived=True))


def test_planning_is_read_only(store, tmp_path):
    first = _image(tmp_path / "in" / "a.png", (1, 2, 3))
    plan = plan_managed_import(store, [first])
    assert [row.status for row in plan.rows] == [NEW]
    assert _asset_ids(store) == []  # nothing was copied or created
    assert not (tmp_path / "managed").exists() or not list(
        (tmp_path / "managed").rglob("sidecar*.json")
    )


def test_identity_is_the_exact_bytes_not_the_filename(store, tmp_path):
    original = _image(tmp_path / "in" / "same_name.png", (9, 9, 9))
    imported = store.import_photo(original)
    twin = _image(tmp_path / "other" / "different_name.png", (9, 9, 9))  # identical bytes
    namesake = _image(tmp_path / "third" / "same_name.png", (200, 0, 0))  # same name, other bytes
    plan = plan_managed_import(store, [twin, namesake])
    assert plan.rows[0].status == EXISTING and plan.rows[0].existing_asset_ids == (
        imported.asset_id,
    )
    assert plan.rows[1].status == NEW


def test_missing_unsupported_unreadable_and_in_selection_duplicates_are_refused_with_a_reason(
    store, tmp_path
):
    good = _image(tmp_path / "in" / "good.png", (5, 5, 5))
    dup = tmp_path / "in" / "copy.png"
    dup.write_bytes(good.read_bytes())
    broken = tmp_path / "in" / "broken.png"
    broken.write_bytes(b"not an image")
    text = tmp_path / "in" / "notes.txt"
    text.write_text("hello")
    plan = plan_managed_import(store, [good, dup, broken, tmp_path / "in" / "gone.png", text])
    statuses = [row.status for row in plan.rows]
    assert statuses == [NEW, REFUSED, REFUSED, REFUSED, REFUSED]
    assert "earlier in this selection" in plan.rows[1].reason
    assert "missing" in plan.rows[3].reason.lower()
    assert "Unsupported" in plan.rows[4].reason
    described = plan.describe()
    assert "good.png" in described and "REFUSED" in described


def test_confirmed_apply_copies_new_images_and_reports_per_file_outcomes(store, tmp_path):
    new = _image(tmp_path / "in" / "new.png", (11, 22, 33))
    gone = tmp_path / "in" / "gone.png"
    plan = plan_managed_import(store, [new, gone])
    result = apply_managed_import(store, plan, baseline_defaults=None)
    assert len(result.imported) == 1 and result.imported[0][0] == str(new)
    assert [path for path, _reason in result.failed] == [str(gone)]
    assert new.exists()  # the original is never moved or deleted
    assert _asset_ids(store) == [result.imported[0][1]]


def test_duplicates_open_the_existing_asset_or_import_a_separate_copy_as_the_operator_chose(
    store, tmp_path
):
    source = _image(tmp_path / "in" / "dup.png", (70, 80, 90))
    existing = store.import_photo(source)
    plan = plan_managed_import(store, [source])
    opened = apply_managed_import(store, plan, baseline_defaults=None, duplicates=OPEN_EXISTING)
    assert opened.opened_existing == [(str(source), existing.asset_id)] and not opened.imported
    assert len(_asset_ids(store)) == 1
    copied = apply_managed_import(store, plan, baseline_defaults=None, duplicates=IMPORT_COPY)
    assert len(copied.imported) == 1 and copied.imported[0][1] != existing.asset_id
    assert len(_asset_ids(store)) == 2


def test_a_source_that_changed_after_the_operator_reviewed_it_is_skipped_not_guessed(
    store, tmp_path
):
    source = _image(tmp_path / "in" / "moving.png", (1, 1, 1))
    plan = plan_managed_import(store, [source])
    _image(source, (250, 250, 250))  # replaced between planning and confirmation
    result = apply_managed_import(store, plan, baseline_defaults=None)
    assert not result.imported and "changed since you reviewed it" in result.failed[0][1]
    assert _asset_ids(store) == []


def test_the_managed_asset_carries_no_lineage_from_where_it_came_from(store, tmp_path):
    source = _image(tmp_path / "in" / "from_history.png", (3, 6, 9))
    plan = plan_managed_import(store, [source])
    result = apply_managed_import(
        store, plan, baseline_defaults={"prompt": "operator default", "source": "manual"}
    )
    asset_id = result.imported[0][1]
    payload = json.loads(store.sidecar_path(asset_id).read_text(encoding="utf-8"))
    flat = json.dumps(payload).lower()
    for forbidden in (
        "history_iterate",
        "source_job_id",
        "parent_job",
        "parent_artifact",
        "source_artifact_id",
    ):
        assert forbidden not in flat
    assert payload["baseline"]["prompt"] == "operator default"
