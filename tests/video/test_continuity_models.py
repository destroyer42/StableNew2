from __future__ import annotations

from src.video.continuity_models import (
    ContinuityAnchorReference,
    ContinuityAnchorSet,
    ContinuityCharacterReference,
    ContinuityPack,
    ContinuityPackLink,
    ContinuitySceneReference,
    ContinuityWardrobeReference,
    normalize_continuity_link,
)


def _make_pack(pack_id: str = "cont-001", display_name: str = "Hero Pack") -> ContinuityPack:
    return ContinuityPack(
        pack_id=pack_id,
        display_name=display_name,
        created_at="2026-03-19T00:00:00+00:00",
        updated_at="2026-03-19T01:00:00+00:00",
        anchors=[
            ContinuityAnchorReference(
                anchor_id="anchor-001",
                image_path="C:/anchors/hero.png",
                label="Hero Anchor",
                tags=["hero"],
            )
        ],
        anchor_sets=[
            ContinuityAnchorSet(
                anchor_set_id="set-001",
                display_name="Hero Base",
                anchor_ids=["anchor-001"],
            )
        ],
        characters=[
            ContinuityCharacterReference(
                character_id="char-001",
                display_name="Hero",
                anchor_set_id="set-001",
            )
        ],
        wardrobes=[
            ContinuityWardrobeReference(
                wardrobe_id="wardrobe-001",
                display_name="Field Jacket",
                character_id="char-001",
                anchor_set_id="set-001",
            )
        ],
        scenes=[
            ContinuitySceneReference(
                scene_id="scene-001",
                display_name="Rooftop",
                anchor_set_id="set-001",
            )
        ],
        tags=["video", "hero"],
        metadata={"project": "video"},
    )


def test_continuity_pack_round_trip() -> None:
    pack = _make_pack()

    restored = ContinuityPack.from_dict(pack.to_dict())

    assert restored.pack_id == "cont-001"
    assert restored.anchor_sets[0].anchor_ids == ["anchor-001"]
    assert restored.characters[0].anchor_set_id == "set-001"
    assert restored.wardrobes[0].character_id == "char-001"
    assert restored.scenes[0].display_name == "Rooftop"


def test_continuity_pack_summary_counts() -> None:
    summary = _make_pack().summary()

    assert summary.pack_id == "cont-001"
    assert summary.character_count == 1
    assert summary.wardrobe_count == 1
    assert summary.scene_count == 1
    assert summary.anchor_set_count == 1
    assert summary.anchor_count == 1


def test_continuity_pack_link_round_trip() -> None:
    link = _make_pack().link()

    restored = ContinuityPackLink.from_dict(link.to_dict())

    assert restored is not None
    assert restored.pack_id == "cont-001"
    assert restored.pack_summary is not None
    assert restored.pack_summary.display_name == "Hero Pack"


def test_normalize_continuity_link_accepts_string() -> None:
    link = normalize_continuity_link("cont-001")

    assert link == {"pack_id": "cont-001"}


def test_normalize_continuity_link_accepts_pack() -> None:
    link = normalize_continuity_link(_make_pack())

    assert link is not None
    assert link["pack_id"] == "cont-001"
    assert link["pack_summary"]["character_count"] == 1