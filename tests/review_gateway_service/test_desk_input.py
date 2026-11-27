"""PHONE-FAST (k): a desk reprocess result is shown beside its input without being regrouped."""

from __future__ import annotations

import pytest

RUN = "20261125_101500_pack"
LATER = "20261127_090000_reprocess"


@pytest.fixture
def world(rig):
    rig.original = rig.publish("original", source="pipeline")
    rig.result = rig.publish("result", run_id=LATER, source="reprocess", made_from=rig.original)
    rig.pair()
    return rig


def result_of(rig, run_id: str = LATER) -> dict:
    items = rig.phone.get(f"/api/runs/{run_id}").json()["items"]
    return next(i for i in items if i["library_id"] == rig.result["library_id"])


def test_the_result_stays_in_its_folder_and_is_compared(world) -> None:
    shown = result_of(world)
    assert shown["compare"]["library_id"] == world.original["library_id"]
    assert shown["compare"]["desk"] is True and shown["original_missing"] is False
    sections = world.phone.get("/api/sections").json()["sections"]
    assert {entry["id"]: entry["total"] for entry in sections} == {"pipeline": 1, "reprocess": 1}


def test_an_input_named_by_other_bytes_is_found_by_its_library_id(rig) -> None:
    original = rig.publish("original")
    named = {"library_id": original["library_id"], "sha256": "ab" * 32}
    rig.result = rig.publish("result", run_id=LATER, made_from=named)
    rig.pair()
    assert result_of(rig)["compare"]["sha256"] == original["sha256"]


def test_an_input_the_gateway_does_not_hold_says_so_until_it_arrives(rig) -> None:
    manifest, _blobs = rig.manifest("original")
    rig.result = rig.publish("result", run_id=LATER, made_from=manifest["item"])
    rig.pair()
    assert result_of(rig)["compare"] is None and result_of(rig)["original_missing"] is True
    rig.publish("original")
    assert result_of(rig)["compare"] and result_of(rig)["original_missing"] is False


def test_an_input_the_pc_could_not_find_says_so(rig) -> None:
    manifest, blobs = rig.manifest("result", run_id=LATER)
    manifest["input_missing"] = True
    for digest in rig.sync.post("/sync/v1/items", json=manifest).json()["missing"]:
        rig.sync.put(f"/sync/v1/media/{digest}", content=blobs[digest])
    rig.result = manifest["item"]
    rig.pair()
    assert result_of(rig)["original_missing"] is True


def test_a_deleted_original_is_not_offered(world) -> None:
    world.decide(world.original, "delete")
    assert result_of(world)["compare"] is None and result_of(world)["original_missing"] is True


def test_retention_keeps_an_original_until_its_result_is_judged(world) -> None:
    world.gateway.store.undecided_days = 30
    world.clock.advance(days=31)
    # both are stale and undecided; the original waits for the result, which goes first
    assert world.gateway.retention()["items_purged"] == 1
    assert world.gateway.retention()["items_purged"] == 1


def test_health_offers_the_feature(rig) -> None:
    assert "item_input" in rig.sync.get("/sync/v1/health").json()["features"]
