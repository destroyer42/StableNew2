"""PHONE-FAST (d) on the gateway: "sent for rework" counts as reviewed, and a result is offered beside its original."""

from __future__ import annotations

import pytest

from .test_actions import confirm, prepare

RUN = "20261125_101500_pack"
RESULTS = "20261125_120000_Reprocess"


@pytest.fixture
def world(rig):
    rig.original = rig.publish("original")
    rig.device = rig.pair(scopes=("review", "queue"))
    return rig


def items(rig, run_id=RUN) -> dict[str, dict]:
    listed = rig.phone.get(f"/api/runs/{run_id}").json()["items"]
    return {item["library_id"]: item for item in listed}


def state(rig, item=None, run_id=RUN) -> str:
    return items(rig, run_id)[(item or rig.original)["library_id"]]["state"]


def queue(rig, action="fix_face") -> str:
    words = {"text": "smiling"} if action == "prompt_tweak" else {}
    prepared = prepare(rig, rig.original, action, **words).json()["record_id"]
    return confirm(rig, rig.original, prepared, action).json()["record_id"]


def result_of(rig, parent, name="result") -> dict:
    manifest, blobs = rig.manifest(name, run_id=RESULTS)
    manifest["parent"] = parent
    response = rig.sync.post("/sync/v1/items", json=manifest)
    assert response.status_code == 200, response.text
    for digest in response.json()["missing"]:
        assert rig.sync.put(f"/sync/v1/media/{digest}", content=blobs[digest]).is_success
    return manifest["item"]


def test_health_offers_the_parent_field(world) -> None:
    assert "item_parent" in world.sync.get("/sync/v1/health").json()["features"]


def test_a_prepare_alone_does_not_mark_the_item(world) -> None:
    prepare(world, world.original)
    assert state(world) == "undecided"


@pytest.mark.parametrize(
    "action", ["fix_face", "fix_hands", "fix_both", "another_model", "aspect_ratio"]
)
def test_a_queued_rework_counts_as_reviewed(world, action) -> None:
    queue(world, action)
    assert state(world) == "rework"
    [run] = world.phone.get("/api/runs").json()["runs"]
    assert (run["undecided"], run["rework"]) == (0, 1)


@pytest.mark.parametrize("action", ["more_like_this", "prompt_tweak", "make_video"])
def test_a_variation_does_not_mark_the_item(world, action) -> None:
    queue(world, action)
    assert state(world) == "undecided"


def test_a_refused_rework_returns_the_item(world) -> None:
    record = queue(world)
    world.outbox()
    world.acknowledge(record, "refused", reason_code="admission_refused")
    assert state(world) == "undecided"


def test_an_applied_rework_stays_marked_until_it_is_decided(world) -> None:
    record = queue(world)
    world.outbox()
    world.acknowledge(record, "applied", receipt={"job_ids": ["job-1"]})
    assert state(world) == "rework"
    world.decide(world.original, "keep")
    assert state(world) == "pending"


def test_a_result_is_offered_beside_its_original(world) -> None:
    queue(world)
    result = result_of(world, world.original)
    shown = items(world, RESULTS)[result["library_id"]]
    assert shown["state"] == "undecided"
    assert shown["compare"]["library_id"] == world.original["library_id"]
    assert shown["compare"]["sha256"] == world.original["sha256"]
    assert "preview" in shown["compare"]["variants"]
    assert shown["compare"]["state"] == "rework"


def test_a_republish_without_the_parent_keeps_the_lineage(world) -> None:
    result = result_of(world, world.original)
    manifest, _blobs = world.manifest("result", run_id=RESULTS)
    assert world.sync.post("/sync/v1/items", json=manifest).is_success
    assert items(world, RESULTS)[result["library_id"]]["compare"] is not None


def test_a_deleted_or_unknown_original_leaves_an_ordinary_item(world) -> None:
    orphan = result_of(world, {"library_id": "lib-nowhere_", "sha256": "ab" * 32}, "orphan")
    assert items(world, RESULTS)[orphan["library_id"]]["compare"] is None
    result = result_of(world, world.original)
    world.decide(world.original, "delete")
    assert items(world, RESULTS)[result["library_id"]]["compare"] is None


def test_an_ordinary_item_has_no_compare(world) -> None:
    assert items(world)[world.original["library_id"]]["compare"] is None


def test_an_older_database_gains_the_parent_columns(world, tmp_path) -> None:
    store = world.gateway.store
    with store.write() as db:
        db.execute("ALTER TABLE item DROP COLUMN parent_library_id")
        db.execute("ALTER TABLE item DROP COLUMN parent_sha256")
    type(store)(store.database, store.media, store.contract, store.clock)
    assert state(world) == "undecided"
