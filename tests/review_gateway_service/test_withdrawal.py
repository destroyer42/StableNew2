"""PHONE-FAST: the one-time withdrawal of already-published frames on the gateway is not a decision."""

from __future__ import annotations

import pytest

from .test_actions import prepare


@pytest.fixture
def world(rig):
    rig.frame = rig.publish("frame")
    rig.other = rig.publish("other")
    rig.device = rig.pair(scopes=("review", "queue"))
    return rig


def listed(rig) -> set[str]:
    runs = rig.phone.get("/api/runs").json()["runs"]
    return {
        item["library_id"]
        for run in runs
        for item in rig.phone.get(f"/api/runs/{run['run_id']}").json()["items"]
    }


def withdraw(rig, *items):
    response = rig.sync.post(
        "/sync/v1/withdrawals",
        json={
            "schema_version": "stablenew.review-gateway-sync.v1",
            "type": "item_withdrawal",
            "library_ids": [item["library_id"] for item in items],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_health_offers_withdrawal(world) -> None:
    assert "item_withdraw" in world.sync.get("/sync/v1/health").json()["features"]


def test_a_withdrawn_item_leaves_the_inbox_without_a_decision(world) -> None:
    assert withdraw(world, world.frame) == {"withdrawn": 1}
    assert listed(world) == {world.other["library_id"]}
    assert world.outbox()["records"] == []
    assert withdraw(world, world.frame) == {"withdrawn": 0}


def test_a_withdrawn_item_cannot_come_back(world) -> None:
    withdraw(world, world.frame)
    manifest, _blobs = world.manifest("frame")
    assert world.sync.post("/sync/v1/items", json=manifest).json()["status"] == "purged"
    assert world.frame["library_id"] not in listed(world)


def test_a_decided_or_requested_item_is_left_alone(world) -> None:
    world.decide(world.frame, "keep")
    prepare(world, world.other)
    assert withdraw(world, world.frame, world.other) == {"withdrawn": 0}
    assert listed(world) == {world.frame["library_id"], world.other["library_id"]}


def test_an_unknown_field_is_refused(world) -> None:
    response = world.sync.post("/sync/v1/withdrawals", json={"library_ids": ["lib-00000001"]})
    assert response.status_code == 422
