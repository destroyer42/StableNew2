"""NAME-INFO on the gateway: "More info" is stored with the item and returned for it and for each compare side."""

from __future__ import annotations

from pathlib import Path

INFO = {
    "stage_path": "txt2img → ADetailer",
    "model": "photoMomentum",
    "model_name": "photoMomentumSDXLNSFW_v20",
    "pack": "000-Style",
    "prompt_number": 1,
    "variant": 2,
    "made_at": "2026-11-27T16:48:00Z",
    "seed": "123456789012345678",
    "batch": "night batch",
}
RUN = "20261125_101500_pack"
STATIC = Path(__file__).resolve().parents[2] / "services/review_gateway/review_gateway/static"


def send(rig, name, *, info=None, parent=None) -> dict:
    manifest, blobs = rig.manifest(name, run_id=RUN)
    if info is not None:
        manifest["info"] = info
    if parent is not None:
        manifest["parent"] = parent
    response = rig.sync.post("/sync/v1/items", json=manifest)
    assert response.status_code == 200, response.text
    for digest in response.json()["missing"]:
        assert rig.sync.put(f"/sync/v1/media/{digest}", content=blobs[digest]).is_success
    return manifest["item"]


def listed(rig) -> dict[str, dict]:
    items = rig.phone.get(f"/api/runs/{RUN}").json()["items"]
    return {item["library_id"]: item for item in items}


def test_health_offers_the_info_field(rig) -> None:
    assert "item_info" in rig.sync.get("/sync/v1/health").json()["features"]


def test_info_is_returned_with_the_item_and_an_item_without_it_says_none(rig) -> None:
    rig.pair()
    described = send(rig, "described", info=INFO)
    old = send(rig, "old")

    items = listed(rig)

    assert items[described["library_id"]]["info"] == INFO
    assert items[old["library_id"]]["info"] is None
    assert items[old["library_id"]]["display"]["model"] == "juggernaut"


def test_publishing_again_without_info_keeps_it(rig) -> None:
    rig.pair()
    item = send(rig, "described", info=INFO)
    send(rig, "described")
    assert listed(rig)[item["library_id"]]["info"] == INFO


def test_each_side_of_a_compare_carries_its_own_info(rig) -> None:
    rig.pair()
    original = send(rig, "original", info={**INFO, "stage_path": "txt2img"})
    result = send(rig, "result", info=INFO, parent=original)

    side = listed(rig)[result["library_id"]]["compare"]

    assert side["info"]["stage_path"] == "txt2img"
    assert side["display"]["model"] == "juggernaut"
    assert side["created_at"]


def test_info_with_an_unknown_field_is_refused(rig) -> None:
    manifest, _blobs = rig.manifest("bad")
    manifest["info"] = {**INFO, "path": "somewhere"}
    assert rig.sync.post("/sync/v1/items", json=manifest).status_code == 422


def test_the_page_has_more_info_on_both_views(rig) -> None:
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    assert script.count("· More info`") == 2
    assert "infoPanel(item, original)" in script
    assert rig.phone.get("/static/moreinfo.js").status_code == 200
