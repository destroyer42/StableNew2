"""PHONE-FAST (e) and (f): one review stream, the PC's status for every phone, and bounded retention of the cache."""

from __future__ import annotations

import pytest
from review_gateway.config import ConfigError, load_settings

from .test_actions import prepare

RUN = "20261125_101500_pack"
OTHER = "20261126_090000_second run"


@pytest.fixture
def world(rig):
    rig.first = rig.publish("first")
    rig.clock.advance(minutes=1)
    rig.second = rig.publish("second")
    rig.clock.advance(minutes=1)
    rig.later = rig.publish("later", run_id=OTHER)
    rig.device = rig.pair(scopes=("review", "queue"))
    return rig


def ids(rig, run_id) -> list[str]:
    return [item["library_id"] for item in rig.phone.get(f"/api/runs/{run_id}").json()["items"]]


def names(*items) -> list[str]:
    return [item["library_id"] for item in items]


def test_the_stream_holds_what_is_left_to_review_across_runs(world) -> None:
    assert ids(world, "all") == names(world.later, world.first, world.second)
    world.decide(world.first, "keep")
    assert ids(world, "all") == names(world.later, world.second)


def test_every_review_phone_sees_the_queue(world) -> None:
    assert world.phone.get("/api/status").json()["pc"] is None
    status = {
        "schema_version": "stablenew.review-gateway-sync.v1",
        "type": "pc_status",
        "published_at": world.clock.stamp(),
        "checkout": {},
        "queue": {"state": "running", "queued": 4},
        "remote_update_enabled": False,
        "update": {"state": "idle"},
    }
    assert world.sync.put("/sync/v1/pc-status", json=status).status_code == 200
    shown = world.phone.get("/api/status").json()
    assert (shown["pc"]["state"], shown["pc"]["queued"]) == ("running", 4)
    assert set(shown["pc"]) == {"state", "queued", "received_at"}
    assert shown["cache"]["bytes"] > 0 and not shown["cache"]["over"]


def test_a_cache_over_its_warning_level_says_so_and_keeps_working(world) -> None:
    world.gateway.store.cache_warn_bytes = 1
    assert world.phone.get("/api/status").json()["cache"]["over"] is True
    assert world.publish("more")


def test_an_unpaired_phone_sees_no_status(rig) -> None:
    assert rig.phone.get("/api/status").status_code == 401


def test_undecided_items_leave_after_thirty_days(world) -> None:
    world.decide(world.second, "keep")
    world.clock.advance(days=29)
    assert world.gateway.retention()["items_purged"] == 0
    world.clock.advance(days=2)
    assert world.gateway.retention()["items_purged"] == 2
    assert ids(world, RUN) == names(world.second)


def test_a_waiting_request_keeps_its_item(world) -> None:
    prepare(world, world.first)
    world.clock.advance(days=40)
    world.gateway.retention()
    assert ids(world, RUN) == names(world.first)


def test_purging_undecided_items_can_be_switched_off(world) -> None:
    world.gateway.store.undecided_days = 0
    world.clock.advance(days=400)
    assert world.gateway.retention()["items_purged"] == 0


@pytest.mark.parametrize("line", ["undecided_days = -1", 'cache_warn_gib = "20"'])
def test_a_bad_housekeeping_setting_is_refused(tmp_path, line) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        f'data_dir = "d"\nmedia_dir = "m"\nsecret_file = "s"\nsync_host = "127.0.0.1"\n{line}\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_settings(config)
