"""PHONE-FAST (g): review sections with a count of what is left and of what is new to this phone."""

from __future__ import annotations

import pytest

from .conftest import SCHEMA_VERSION

RUN = "20261125_101500_pack"
LEARNING = "20261126_090000_learning"


@pytest.fixture
def world(rig):
    rig.pipeline = rig.publish("pipeline", source="pipeline")
    rig.learning = rig.publish("learning", run_id=LEARNING, source="learning")
    rig.old = rig.publish("old", run_id="20261120_000000_older")
    rig.pair()
    return rig


def sections(rig, **seen) -> dict[str, dict]:
    response = rig.phone.get("/api/sections", params=seen)
    assert response.status_code == 200, response.text
    return {entry["id"]: entry for entry in response.json()["sections"]}


def label(rig, *pairs):
    items = [{"library_id": item["library_id"], "source": source} for item, source in pairs]
    body = {"schema_version": SCHEMA_VERSION, "type": "item_sources", "items": items}
    return rig.sync.post("/sync/v1/item-sources", json=body)


def test_each_source_counts_what_is_left_and_an_item_without_one_is_other(world):
    listed = sections(world)
    assert list(listed) == ["pipeline", "learning", "other"]
    assert listed["learning"] == {"id": "learning", "total": 1, "unreviewed": 1, "new": 1}
    world.decide(world.learning, "keep")
    assert sections(world)["learning"] == {"id": "learning", "total": 1, "unreviewed": 0, "new": 0}


def test_new_counts_what_arrived_since_the_phone_looked(world):
    seen = world.phone.get("/api/status").json()["now"]
    assert sections(world, pipeline=seen)["pipeline"]["new"] == 0
    world.clock.advance(minutes=1)
    world.publish("later", source="pipeline")
    listed = sections(world, pipeline=seen)
    assert (listed["pipeline"]["new"], listed["pipeline"]["unreviewed"]) == (1, 2)


def test_a_section_lists_only_its_own_runs_and_stream(world):
    runs = world.phone.get("/api/runs", params={"source": "learning"}).json()["runs"]
    assert [run["run_id"] for run in runs] == [LEARNING]
    stream = world.phone.get("/api/runs/all:learning").json()["items"]
    assert [item["library_id"] for item in stream] == [world.learning["library_id"]]
    assert len(world.phone.get("/api/runs/all").json()["items"]) == 3
    assert world.phone.get("/api/runs", params={"source": "x"}).status_code == 422


def test_the_pc_names_the_sections_of_earlier_items_and_does_not_rename_them(world):
    assert label(world, (world.old, "video")).json() == {"labelled": 1}
    assert sections(world)["video"]["total"] == 1
    assert label(world, (world.pipeline, "testing")).json() == {"labelled": 0}


def test_a_rework_result_joins_its_originals_section(world):
    manifest, blobs = world.manifest("result", source="reprocess")
    manifest["parent"] = world.learning
    for digest in world.sync.post("/sync/v1/items", json=manifest).json()["missing"]:
        world.sync.put(f"/sync/v1/media/{digest}", content=blobs[digest])
    assert world.sync.post("/sync/v1/items", json=manifest).json()["status"] == "ready"
    assert sections(world)["learning"]["total"] == 2
    assert "reprocess" not in sections(world)


def test_a_bad_section_is_refused_and_an_unpaired_phone_sees_none(rig):
    manifest, _blobs = rig.manifest("bad", source="eval")
    assert rig.sync.post("/sync/v1/items", json=manifest).status_code == 422
    assert rig.phone.get("/api/sections").status_code == 401


def test_health_offers_the_feature(rig):
    assert "item_source" in rig.sync.get("/sync/v1/health").json()["features"]
