from __future__ import annotations

from pathlib import Path

from src.video.continuity_models import ContinuityPack
from src.video.continuity_store import ContinuityStore


def _make_pack(pack_id: str, display_name: str) -> ContinuityPack:
    return ContinuityPack(
        pack_id=pack_id,
        display_name=display_name,
        created_at="2026-03-19T00:00:00+00:00",
        updated_at="2026-03-19T01:00:00+00:00",
        tags=[display_name.lower()],
    )


def test_save_and_load_pack_round_trip(tmp_path: Path) -> None:
    store = ContinuityStore(tmp_path)
    pack = _make_pack("cont-001", "Hero Pack")

    path = store.save_pack(pack)
    loaded = store.load_pack("cont-001")

    assert path.exists()
    assert loaded is not None
    assert loaded.to_dict() == pack.to_dict()


def test_list_pack_summaries_sorted_by_display_name(tmp_path: Path) -> None:
    store = ContinuityStore(tmp_path)
    store.save_pack(_make_pack("cont-z", "Zulu Pack"))
    store.save_pack(_make_pack("cont-a", "Alpha Pack"))

    summaries = store.list_pack_summaries()

    assert [summary.pack_id for summary in summaries] == ["cont-a", "cont-z"]


def test_get_link_returns_pack_summary(tmp_path: Path) -> None:
    store = ContinuityStore(tmp_path)
    store.save_pack(_make_pack("cont-001", "Hero Pack"))

    link = store.get_link("cont-001")

    assert link is not None
    assert link.pack_id == "cont-001"
    assert link.pack_summary is not None
    assert link.pack_summary.display_name == "Hero Pack"


def test_load_missing_pack_returns_none(tmp_path: Path) -> None:
    store = ContinuityStore(tmp_path)

    assert store.load_pack("missing-pack") is None