"""RG-170: the PC takes an already published eval clip out of the Review inbox. No decision is made for the owner."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Event

import pytest
from jsonschema import Draft202012Validator
from review_gateway.contract import Contract

from src.app.review_gateway_client import GatewayClient
from src.app.review_gateway_store import SyncLedger
from src.app.review_gateway_withdraw import INTERVAL_SECONDS, EvalWithdrawal
from tests.app.test_review_gateway_ratings import AppTransport
from tests.review_gateway_service.conftest import SCHEMA_PATH, SCHEMA_VERSION, SECRET, Rig

NOW = "2026-11-27T12:00:00Z"


def payload(item: dict) -> dict:
    return {"schema_version": SCHEMA_VERSION, "type": "item_withdrawal", "item": item}


def withdraw(rig: Rig, item: dict) -> str:
    response = rig.sync.post("/sync/v1/item-withdrawals", json=payload(item))
    assert response.status_code == 200, response.text
    return response.json()["status"]


def inbox(rig: Rig) -> int:
    return sum(run["total"] for run in rig.phone.get("/api/runs").json()["runs"])


def test_the_withdrawal_payload_is_part_of_the_contract() -> None:
    sample = payload({"library_id": "lib-00000001", "sha256": "a" * 64})
    Contract(SCHEMA_PATH).validate("item_withdrawal", sample)
    Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))).validate(sample)


def test_an_undecided_item_leaves_the_inbox_without_any_decision(rig: Rig) -> None:
    item = rig.publish("one", kind="video")
    other = rig.publish("two")
    rig.pair()

    assert withdraw(rig, item) == "withdrawn"
    assert withdraw(rig, item) == "withdrawn"

    assert inbox(rig) == 1
    assert rig.outbox()["records"] == []
    assert rig.gateway.store.status()["pending_records"] == 0
    url = f"/media/{item['library_id']}/{item['sha256']}/thumb"
    assert rig.phone.get(url).status_code == 404
    manifest, _blobs = rig.manifest("one", kind="video")
    assert rig.sync.post("/sync/v1/items", json=manifest).json()["status"] == "purged"
    assert other["library_id"] != item["library_id"]


def test_an_item_the_gateway_does_not_hold_is_reported(rig: Rig) -> None:
    assert withdraw(rig, {"library_id": "lib-00000009", "sha256": "b" * 64}) == "unknown"


def test_an_item_still_owed_to_the_pc_or_to_immich_is_left_alone(rig: Rig) -> None:
    item = rig.publish("one")
    rig.pair()
    record_id = rig.decide(item, "keep").json()["record_id"]

    assert withdraw(rig, item) == "kept"  # the PC has not answered the Keep

    rig.acknowledge(record_id)
    assert withdraw(rig, item) == "kept"  # Immich does not have it yet
    assert inbox(rig) == 1

    rig.confirm_uploads()
    assert withdraw(rig, item) == "withdrawn"


# --- the PC's side --------------------------------------------------------------------------------------------------


@pytest.fixture
def pc(rig: Rig, tmp_path: Path):
    root = tmp_path / "output"
    run = root / "Reprocess" / "run"
    (run / "manifests").mkdir(parents=True)
    (run / "manifests" / "eval.json").write_text(
        json.dumps({"video_path": "eval.mp4", "artifact": {"job_id": "job-eval"}}), encoding="utf-8"
    )
    (root / "video_eval" / "demo").mkdir(parents=True)
    (root / "video_eval" / "demo" / "run.json").write_text(
        json.dumps({"jobs": [{"job_id": "job-eval"}]}), encoding="utf-8"
    )
    ledger = SyncLedger(tmp_path / "state" / "ledger.sqlite3")
    items = {}
    for name, relative in (("one", "Reprocess/run/eval.mp4"), ("two", "Reprocess/run/keeper.mp4")):
        items[name] = rig.publish(name, kind="video")
        ledger.mark_published(
            items[name]["library_id"],
            "v1",
            relative,
            items[name]["sha256"],
            "video",
            "published",
            NOW,
        )
    transport = AppTransport(rig)
    client = GatewayClient(transport, SECRET)
    client.health()
    return root, ledger, items, client, transport


def test_the_pc_withdraws_only_eval_clips_once(rig: Rig, pc) -> None:
    root, ledger, items, client, transport = pc
    rig.pair()
    time = [0.0]
    withdrawal = EvalWithdrawal(ledger, monotonic=lambda: time[0])

    withdrawal.step(client, root, Event())

    assert inbox(rig) == 1
    assert ledger.published(items["one"]["library_id"])["state"] == "withdrawn"
    assert ledger.published(items["two"]["library_id"])["state"] == "published"
    transport.calls.clear()
    time[0] += INTERVAL_SECONDS
    withdrawal.step(client, root, Event())
    assert transport.calls == []


def test_a_gateway_without_withdrawal_is_sent_nothing(pc) -> None:
    root, ledger, _items, client, transport = pc
    client.features = frozenset()
    transport.calls.clear()

    EvalWithdrawal(ledger).step(client, root, Event())

    assert transport.calls == []
