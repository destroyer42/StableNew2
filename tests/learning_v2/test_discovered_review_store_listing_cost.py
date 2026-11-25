"""PR-GUI-STALL-ATTRIBUTION: listing discovered-review groups must stay cheap on the Tk thread.

A captured 10 s UI stall had the Tk thread inside ``DiscoveredReviewStore.list_handles`` resolving (``realpath``,
which opens each file on Windows) every stored artifact path of every group, on every call, and the scan service asked
for the whole list only to learn the existing group ids. These tests pin the cost properties, not the timings: how many
filesystem resolutions a listing makes, and how often each ``items.json`` is parsed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.learning.discovered_review_models import DiscoveredReviewExperiment, DiscoveredReviewItem
from src.learning.discovered_review_store import DiscoveredReviewStore


def _group(
    root: Path, group_id: str, *, files: int, missing: int = 0
) -> DiscoveredReviewExperiment:
    items = []
    for index in range(files + missing):
        path = root / f"{group_id}-{index}.png"
        if index < files:
            path.write_bytes(b"png")
        items.append(
            DiscoveredReviewItem(
                item_id=f"{group_id}-{index}",
                artifact_path=str(path),
                stage="txt2img",
                model="m",
                sampler="Euler",
                steps=20,
                cfg_scale=7.0,
                positive_prompt="p",
            )
        )
    return DiscoveredReviewExperiment(
        group_id=group_id,
        display_name=group_id,
        stage="txt2img",
        prompt_hash=group_id,
        items=items,
        varying_fields=["cfg_scale"],
    )


@pytest.fixture
def store(tmp_path: Path) -> DiscoveredReviewStore:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    built = DiscoveredReviewStore(tmp_path / "learning")
    built.save_group(_group(artifacts, "g1", files=3, missing=1))
    built.save_group(_group(artifacts, "g2", files=2))
    return built


def test_available_items_are_confirmed_without_resolving_their_paths(
    store: DiscoveredReviewStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    resolved: list[str] = []
    real = os.path.realpath

    def counting_realpath(path, *args, **kwargs):
        resolved.append(str(path))
        return real(path, *args, **kwargs)

    monkeypatch.setattr(os.path, "realpath", counting_realpath)

    handles = {h.group_id: h for h in store.list_handles()}

    artifact_resolutions = [p for p in resolved if p.endswith(".png") and "artifacts" in p]
    # Only the one missing item may take the (slow) repair path; the five present files are one stat each.
    assert len(artifact_resolutions) <= 1
    assert (
        handles["g1"].item_count,
        handles["g1"].available_item_count,
        handles["g1"].missing_item_count,
    ) == (4, 3, 1)
    assert (
        handles["g2"].item_count,
        handles["g2"].available_item_count,
        handles["g2"].missing_item_count,
    ) == (2, 2, 0)


def test_each_items_file_is_parsed_once_per_listing(
    store: DiscoveredReviewStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    reads: list[str] = []
    real_read = DiscoveredReviewStore._read_json

    def counting_read(path: Path):
        reads.append(Path(path).name)
        return real_read(path)

    monkeypatch.setattr(DiscoveredReviewStore, "_read_json", staticmethod(counting_read))

    store.list_handles()

    assert reads.count("items.json") == 2  # one per group, not three
    assert reads.count("meta.json") == 2


def test_group_ids_are_listed_without_reading_items_or_paths(
    store: DiscoveredReviewStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*_a, **_k):
        raise AssertionError("listing group ids must not touch item files")

    monkeypatch.setattr(os.path, "realpath", forbidden)
    real_read = DiscoveredReviewStore._read_json

    def only_meta(path: Path):
        assert Path(path).name == "meta.json", f"unexpected read of {path}"
        return real_read(path)

    monkeypatch.setattr(DiscoveredReviewStore, "_read_json", staticmethod(only_meta))

    assert store.list_group_ids() == {"g1", "g2"}


def test_group_ids_use_the_recorded_id_not_just_the_folder_name(tmp_path: Path) -> None:
    built = DiscoveredReviewStore(tmp_path / "learning")
    built.save_group(_group(tmp_path, "g1", files=1))
    group_dir = built._groups_root / "g1"  # noqa: SLF001
    meta = json.loads((group_dir / "meta.json").read_text(encoding="utf-8"))
    meta["group_id"] = "renamed-id"
    (group_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

    assert built.list_group_ids() == {"renamed-id"}
    assert [h.group_id for h in built.list_handles()] == ["renamed-id"]


def test_the_scan_service_asks_only_for_group_ids(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from src.learning.discovered_scan_service import apply_scan

    built = DiscoveredReviewStore(tmp_path / "learning")
    built.save_group(_group(tmp_path, "g1", files=1))

    def forbidden(*_a, **_k):
        raise AssertionError("apply_scan must not build full handles just to learn existing ids")

    monkeypatch.setattr(DiscoveredReviewStore, "list_handles", forbidden)

    class _Scanner:
        scan_index: dict = {}

    outcome = apply_scan(_Scanner(), built, [], is_controlled=lambda _record: False)  # type: ignore[arg-type]

    assert outcome.new_group_count == 0


def test_group_ids_agree_with_handles_for_unreadable_and_missing_meta(tmp_path: Path) -> None:
    built = DiscoveredReviewStore(tmp_path / "learning")
    built.save_group(_group(tmp_path, "good", files=1))
    built.save_group(_group(tmp_path, "corrupt-meta", files=1))
    built.save_group(_group(tmp_path, "no-meta", files=1))
    (built._groups_root / "corrupt-meta" / "meta.json").write_text("{not json", encoding="utf-8")  # noqa: SLF001
    (built._groups_root / "no-meta" / "meta.json").unlink()  # noqa: SLF001

    assert built.list_group_ids() == {h.group_id for h in built.list_handles()}
    assert built.list_group_ids() == {"good", "corrupt-meta"}
