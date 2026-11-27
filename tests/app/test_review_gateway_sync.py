"""RG-120: the PC sync worker against a fake gateway (hermetic: temp roots, no network, no display)."""

from __future__ import annotations

import ast
import hashlib
import json
import logging
import socket
import sys
import time
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest
from PIL import Image

from src.app import review_gateway_publish
from src.app.review_gateway_apply import RecordApplier
from src.app.review_gateway_client import (
    GatewayClient,
    GatewayPinMismatch,
    GatewayUnauthorized,
    PinnedHttpsTransport,
    check_pin,
)
from src.app.review_gateway_protocol import ACTIONS, PAIRING_ALPHABET
from src.app.review_gateway_publish import GatewayPublisher, run_id_for
from src.app.review_gateway_store import GatewaySettings, GatewaySettingsStore, SyncLedger
from src.app.review_gateway_sync import BUSY_PUBLISH_SECONDS, ReviewGatewaySync
from src.app.runtime_stack import build_review_gateway_sync
from src.app.site_output_library import LibraryItem, OutputLibrary
from src.review.archive import archive_root, restore_file
from src.review.review_evidence import (
    REVIEW_FAVORITE,
    REVIEW_GATEWAY_RECEIPT,
    REVIEW_TAGS,
    EvidenceIndex,
    disposition_favorite,
)
from tests.helpers.review_gateway_fakes import SECRET, FakeGateway

FINGERPRINT = "ab" * 32
RUN = "20261125_213000_portraits"
SRC = Path(__file__).resolve().parents[2] / "src"


def _codec_store(path: Path) -> GatewaySettingsStore:
    def xor(data: bytes) -> bytes:
        return bytes(byte ^ 0x5A for byte in data)

    return GatewaySettingsStore(path, protect=xor, unprotect=xor)


class Env:
    def __init__(self, tmp_path: Path, *, busy=lambda: False, monotonic=time.monotonic) -> None:
        self.root = (tmp_path / "output").resolve()
        run = self.root / RUN
        run.mkdir(parents=True)
        self.large = run / "large.png"
        self.small = run / "small.png"
        Image.new("RGB", (1600, 1200), "#335577").save(self.large)
        Image.new("RGB", (64, 48), "#775533").save(self.small)
        self.records = tmp_path / "learning" / "learning_records.jsonl"
        self.ledger_path = tmp_path / "state" / "ledger.sqlite3"
        self.ledger = SyncLedger(self.ledger_path)
        self.gateway = FakeGateway()
        self.library = OutputLibrary(self.root, "review-gateway", lambda: None)
        self.publisher = GatewayPublisher(self.library, self.ledger, transcode=None)
        self.applier = RecordApplier(self.ledger, self.root, self.records, active_inputs=set)
        self.sync = ReviewGatewaySync(
            settings_store=_codec_store(tmp_path / "state" / "settings.bin"),
            ledger=self.ledger,
            publisher_factory=lambda: self.publisher,
            applier=self.applier,
            busy=busy,
            transport_factory=lambda _settings: self.gateway,
            monotonic=monotonic,
        )
        self.sync.configure("192.168.1.50", FINGERPRINT, SECRET)

    def publish_all(self, count: int = 2) -> None:
        deadline = time.monotonic() + 30
        while len(self.gateway.manifests) < count:
            assert time.monotonic() < deadline, "items were not published"
            self.sync.run_cycle()
            time.sleep(0.02)

    def item(self, path: Path) -> tuple[str, str]:
        rel = path.relative_to(self.root).as_posix()
        for library_id, manifest in self.gateway.manifests.items():
            row = self.ledger.published(library_id)
            if row is not None and row["rel_path"] == rel:
                return library_id, manifest["item"]["sha256"]
        raise AssertionError("not published")

    def pair(self) -> str:
        code = self.sync.create_pairing("Pixel")
        assert self.sync.status().pairing_code == code  # shown at once, before the worker runs
        assert len(code) == 9 and set(code.replace("-", "")) <= set(PAIRING_ALPHABET)
        self.sync.run_cycle()
        device = self.gateway.enroll(self.gateway.offers[-1])
        self.sync.run_cycle()  # the PC binds the device from the next outbox page
        assert self.ledger.device(device) is not None
        return device

    def ack(self, record) -> dict:
        found = [a for a in self.gateway.acks if a["record_id"] == record["record_id"]]
        assert found, "record was not acknowledged"
        return found[-1]

    def disposition(self, path: Path, digest: str):
        return EvidenceIndex.read(self.records).disposition_evidence(path, digest).row

    def close(self) -> None:
        self.library.close()
        self.ledger.close()


@pytest.fixture
def env(tmp_path):
    environment = Env(tmp_path)
    yield environment
    environment.close()


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# -- publish --------------------------------------------------------------------------------------------------------


def test_publish_sends_manifests_and_media_without_any_path(env, tmp_path):
    env.publish_all()
    large_id, large_sha = env.item(env.large)
    small_id, small_sha = env.item(env.small)
    assert large_sha == _digest(env.large) and small_sha == _digest(env.small)
    large = env.gateway.manifests[large_id]
    assert set(large["media"]) == {"thumb_320", "preview_1080", "original"}
    assert large["media"]["preview_1080"]["width"] == 1080
    assert set(env.gateway.manifests[small_id]["media"]) == {"thumb_320", "original"}
    assert env.gateway.media[large_sha] == env.large.read_bytes()
    assert large["run_id"] == RUN and large["kind"] == "image"
    text = json.dumps(env.gateway.manifests)
    for forbidden in (str(tmp_path), "large.png", "small.png", "\\\\", "output/"):
        assert forbidden not in text


BATCH = {
    "batch_id": "5b0c4f8e-2a1d-4e3b-9c7a-1f2e3d4c5b6a",
    "name": "2026-11-26 portraits x 2 models",
    "cell": {"pack": "portraits", "model": "juggernautXL.safetensors"},
}


@pytest.mark.parametrize(
    "features, expected", [(None, None), (["item_batch"], BATCH), (["other"], None)]
)
def test_a_batch_is_published_only_to_a_gateway_that_groups_by_it(tmp_path, features, expected):
    """An older gateway's schema refuses a manifest with ``batch``, so it is sent only when health lists the feature."""

    environment = Env(tmp_path)
    try:
        environment.gateway.features = features
        environment.publisher = GatewayPublisher(
            environment.library,
            environment.ledger,
            transcode=None,
            batch_of=lambda path: BATCH if path.name == "large.png" else None,
        )
        environment.publish_all()
        large_id, _sha = environment.item(environment.large)
        small_id, _sha = environment.item(environment.small)
        assert environment.gateway.manifests[large_id].get("batch") == expected
        assert "batch" not in environment.gateway.manifests[small_id]
    finally:
        environment.close()


def test_an_unreadable_batch_never_holds_an_item_back(env):
    def broken(_path):
        raise RuntimeError("the job database is locked")

    env.gateway.features = ["item_batch"]
    env.publisher = GatewayPublisher(env.library, env.ledger, transcode=None, batch_of=broken)
    env.publish_all()
    assert all("batch" not in manifest for manifest in env.gateway.manifests.values())


def _snapshot(batch):
    return {"normalized_job": {"job_id": "job-1", "provenance": {"metadata": {"batch": batch}}}}


def test_the_batch_of_an_image_is_read_from_the_job_that_wrote_it(tmp_path):
    from src.app.review_gateway_publish import job_batch_reader
    from src.controller.app_controller_services.pack_model_batch_service import batch_identity

    n5 = {
        "schema": "stablenew.batch.v1",
        "batch_id": BATCH["batch_id"],
        "name": BATCH["name"],
        "cell": {
            "pack_id": "portraits",
            "pack_name": "portraits",
            "model": "C:\\Forge\\models\\juggernautXL.safetensors",
            "model_key": "juggernautxl",
        },
        "cells": 2,
        "jobs": 8,
    }
    entries = {
        "job-1": SimpleNamespace(snapshot=_snapshot(n5)),
        # A Video Workflow batch has the same key but no name: grouped by run folder.
        "job-2": SimpleNamespace(
            snapshot=_snapshot({"schema": "stablenew.batch.v1", "batch_id": "b", "source_index": 0})
        ),
    }
    repository = SimpleNamespace(get_job=entries.get)
    job_ids = {"a.png": "job-1", "b.png": "job-2", "c.png": "job-3", "d.png": ""}
    read = job_batch_reader(repository, batch_identity, job_id_of=lambda path: job_ids[path.name])

    assert read(tmp_path / "a.png") == {
        "batch_id": BATCH["batch_id"],
        "name": BATCH["name"],
        "cell": {"pack": "portraits", "model": "C:\\Forge\\models\\juggernautXL.safetensors"},
    }
    for name in ("b.png", "c.png", "d.png"):
        assert read(tmp_path / name) is None
    assert (
        read(tmp_path / "clip.mp4") is None
    )  # N5 batches are images; a clip's job is not looked up

    def locked(_job_id):
        raise OSError("database is locked")

    unreadable = job_batch_reader(
        SimpleNamespace(get_job=locked), batch_identity, job_id_of=lambda _p: "job-1"
    )
    assert unreadable(tmp_path / "a.png") is None


def test_publish_is_idempotent_and_resumes_after_restart(env, tmp_path):
    env.publish_all()
    uploads = list(env.gateway.uploads)
    env.sync.run_cycle()
    assert env.gateway.uploads == uploads  # nothing is sent twice

    # Restart: a fresh ledger handle on the same file publishes nothing new.
    env.ledger.close()
    restarted = SyncLedger(env.ledger_path)
    publisher = GatewayPublisher(env.library, restarted, transcode=None)
    client = GatewayClient(env.gateway, SECRET)
    assert publisher.publish(client, limit=8, cancel=Event()).published == 0

    # Interrupted before the ledger write: the manifest is re-sent, the bodies are not.
    large_id, _sha = env.item(env.large)
    with restarted._transaction() as db:
        db.execute("DELETE FROM published WHERE library_id = ?", (large_id,))
    env.gateway.manifests.pop(large_id)
    assert publisher.publish(client, limit=8, cancel=Event()).published == 1
    assert env.gateway.uploads == uploads and large_id in env.gateway.manifests
    restarted.close()
    env.ledger = SyncLedger(env.ledger_path)


def test_publish_defers_an_item_whose_manifest_the_gateway_refuses(env):
    env.publish_all()
    library_id, _sha = env.item(env.small)
    with env.ledger._transaction() as db:
        db.execute("DELETE FROM published WHERE library_id = ?", (library_id,))
    env.gateway.manifests.pop(library_id)
    env.gateway.media.clear()  # the gateway lost its cache: bodies are uploaded again
    result = env.publisher.publish(GatewayClient(env.gateway, SECRET), limit=8, cancel=Event())
    assert result.published == 1 and library_id in env.gateway.manifests


def test_busy_generation_throttles_publishing(tmp_path):
    clock = [1000.0]
    environment = Env(tmp_path, busy=lambda: True, monotonic=lambda: clock[0])
    try:
        deadline = time.monotonic() + 30
        while not environment.gateway.manifests:
            assert time.monotonic() < deadline
            clock[0] += BUSY_PUBLISH_SECONDS
            environment.sync.run_cycle()
            time.sleep(0.02)
        assert len(environment.gateway.manifests) == 1
        environment.sync.run_cycle()  # same instant: no second item while a job runs
        assert len(environment.gateway.manifests) == 1
        clock[0] += BUSY_PUBLISH_SECONDS
        environment.sync.run_cycle()
        assert len(environment.gateway.manifests) == 2
    finally:
        environment.close()


def test_mobile_video_is_transcoded_only_when_needed(env, monkeypatch):
    clip = env.root / RUN / "clip.mp4"
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"x" * 4096)
    stat = clip.stat()
    item = LibraryItem(
        path=f"{RUN}/clip.mp4",
        mime="video/mp4",
        version=(stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns),
    )

    def transcode(source, target: Path, cancelled) -> bool:
        assert source.read(12) == clip.read_bytes()[:12] and not cancelled()
        target.write_bytes(b"mobile-mp4")
        return True

    publisher = GatewayPublisher(env.library, env.ledger, transcode=transcode)
    with publisher._extra_bodies(item, clip, Event(), lambda: True) as extra:
        assert extra == {}  # a small MP4 plays from its original
    monkeypatch.setattr(review_gateway_publish, "MOBILE_DIRECT_LIMIT", 0)
    with publisher._extra_bodies(item, clip, Event(), lambda: False) as extra:
        assert extra == {}  # never transcode while a job runs
    with publisher._extra_bodies(item, clip, Event(), lambda: True) as extra:
        variant = extra["mobile_video"].variant
        assert variant.sha256 == hashlib.sha256(b"mobile-mp4").hexdigest()
        assert variant.content_type == "video/mp4"


def _clip(env, name: str, **fields) -> LibraryItem:
    clip = env.root / RUN / name
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42" + name.encode() * 512)
    stat = clip.stat()
    return LibraryItem(
        path=f"{RUN}/{name}",
        mime="video/mp4",
        version=(stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns),
        **fields,
    )


def _publish_only(env, items: list[LibraryItem], monkeypatch, *, hold: bool = False):
    from src.app.site_library_reconcile import key_for
    from src.app.site_output_library import Preview

    monkeypatch.setattr(
        env.publisher, "candidates", lambda _limit: [(key_for(item.path), item) for item in items]
    )
    monkeypatch.setattr(
        env.library, "grid_preview", lambda *_a, **_k: Preview("image/jpeg", b"\xff\xd8thumb")
    )
    return env.publisher.publish(
        GatewayClient(env.gateway, SECRET), limit=8, cancel=Event(), hold_unlabelled_video=hold
    )


def test_a_retained_rife_source_clip_is_never_published(env, monkeypatch):
    """Owner bug 2026-11-26: with RIFE on, the un-smoothed clip reached phone review and Immich."""

    smoothed = _clip(env, "clip_smooth.mp4", provenance="embedded", role="primary")
    source = _clip(env, "clip.mp4", provenance="embedded", role="retained_source")
    legacy = _clip(env, "older.mp4", provenance="embedded")  # written before roles existed

    result = _publish_only(env, [smoothed, source, legacy], monkeypatch)

    published = {env.ledger.published(key)["rel_path"] for key in env.gateway.manifests}
    assert published == {smoothed.path, legacy.path}
    assert result.published == 2 and result.skipped == 1
    from src.app.site_library_reconcile import key_for

    assert env.ledger.published(key_for(source.path))["state"] == "retained"


def test_a_video_without_stablenew_metadata_waits_while_a_job_runs(env, monkeypatch):
    """The un-smoothed clip lands before RIFE finishes and its role is written; it must not slip out meanwhile."""

    unlabelled = _clip(
        env, "clip.mp4"
    )  # provenance "unknown": its job has not written metadata yet
    result = _publish_only(env, [unlabelled], monkeypatch, hold=True)
    assert result.pending == 1 and not env.gateway.manifests

    result = _publish_only(env, [unlabelled], monkeypatch, hold=False)
    assert result.published == 1  # idle: an unlabelled clip (not from a job) is published as before


def test_library_reads_the_output_role_from_embedded_metadata():
    basic = LibraryItem(path=f"{RUN}/clip.mp4", mime="video/mp4", version=(1, 2, 3, 4, 5))
    assert OutputLibrary._describe(basic, {"output_role": "retained_source"}, "embedded").role == (
        "retained_source"
    )
    assert OutputLibrary._describe(basic, {"output_role": "primary"}, "embedded").role == "primary"
    assert OutputLibrary._describe(basic, {"output_role": "bogus"}, "embedded").role is None
    assert OutputLibrary._describe(basic, {"prompt": "x"}, "embedded").role is None
    # Rows indexed before the field existed still load.
    row = {"body": json.dumps({k: v for k, v in basic.__dict__.items() if k != "role"})}
    assert LibraryItem.from_row(row).role is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("https://gw.tail1234.ts.net:9443", ("gw.tail1234.ts.net", 9443)),
        ("https://192.168.1.23:9443/", ("192.168.1.23", 9443)),
        ("HTTPS://gateway.lan", ("gateway.lan", 9443)),
        ("https://[fd7a:115c::1]:9443", ("fd7a:115c::1", 9443)),
        ("192.168.1.23:9443", ("192.168.1.23", 9443)),
    ],
)
def test_gateway_address_accepts_the_installer_sync_url(text, expected):
    from src.app.review_gateway_store import parse_address

    assert parse_address(text) == expected


@pytest.mark.parametrize(
    "text",
    ["http://gateway.lan:9443", "https://gateway.lan:9443/sync", "https://", "https://u@h:9443"],
)
def test_gateway_address_still_refuses_other_urls(text):
    from src.app.review_gateway_store import parse_address

    with pytest.raises(ValueError):
        parse_address(text)


def test_run_id_falls_back_to_a_dated_group():
    from datetime import UTC, datetime

    moment = datetime(2026, 11, 25, 22, 0, tzinfo=UTC)
    assert run_id_for(f"{RUN}/x.png", moment) == RUN
    assert run_id_for("txt2img/x.png", moment) == "20261125_000000_txt2img"
    assert run_id_for("x.png", moment) == "20261125_000000_output"


# -- decisions ------------------------------------------------------------------------------------------------------


def test_keep_and_favorite_write_retain_evidence(env):
    env.publish_all()
    device = env.pair()
    library_id, sha = env.item(env.large)
    record = env.gateway.decide(library_id, sha, "keep", favorite=True, tags=["needs_fix", "hands"])
    plain_id, plain_sha = env.item(env.small)
    plain = env.gateway.decide(plain_id, plain_sha, "keep", device_id=device)
    env.sync.run_cycle()
    ack = env.ack(record)
    assert ack["outcome"] == "applied" and ack["receipt"]["review_evidence_id"]
    row = env.disposition(env.large, sha)
    assert row["metadata"]["review_disposition"] == "retain"
    assert row["metadata"][REVIEW_FAVORITE] is True and disposition_favorite(row)
    assert row["metadata"][REVIEW_TAGS] == ["needs_fix", "hands"]
    assert row["metadata"][REVIEW_GATEWAY_RECEIPT]["record_id"] == record["record_id"]
    assert env.ack(plain)["outcome"] == "applied"
    plain_row = env.disposition(env.small, plain_sha)
    assert REVIEW_FAVORITE not in plain_row["metadata"] and not disposition_favorite(plain_row)
    assert env.large.exists() and env.gateway.outbox == []


def test_delete_moves_into_the_archive_and_desktop_restore_brings_it_back(env):
    env.publish_all()
    env.pair()
    library_id, sha = env.item(env.large)
    record = env.gateway.decide(library_id, sha, "delete", tags=["hands"])
    env.sync.run_cycle()
    ack = env.ack(record)
    assert ack["outcome"] == "applied" and ack["receipt"]["archived"] is True
    archived = archive_root(env.root) / RUN / "large.png"
    assert not env.large.exists() and _digest(archived) == sha
    assert env.disposition(env.large, sha)["metadata"]["review_disposition"] == "discard"
    outcome = restore_file(env.large, output_root=env.root, digest=sha)
    assert outcome.moved and _digest(env.large) == sha and not archived.exists()


def test_keep_after_a_phone_delete_restores_the_file(env):
    env.publish_all()
    env.pair()
    library_id, sha = env.item(env.small)
    env.gateway.decide(library_id, sha, "delete")
    env.sync.run_cycle()
    assert not env.small.exists()
    undo = env.gateway.decide(library_id, sha, "keep")
    env.sync.run_cycle()
    assert env.ack(undo)["outcome"] == "applied"
    assert _digest(env.small) == sha
    assert env.disposition(env.small, sha)["metadata"]["review_disposition"] == "retain"


def test_retried_and_duplicate_records_are_answered_without_reapplying(env):
    env.publish_all()
    env.pair()
    library_id, sha = env.item(env.small)
    first = env.gateway.decide(library_id, sha, "keep", key="same-key-0000000001")
    env.sync.run_cycle()
    env.gateway.outbox.append(first)  # the gateway lost the acknowledgement and re-sends
    twin = env.gateway.decide(library_id, sha, "keep", key="same-key-0000000001")
    env.sync.run_cycle()
    acks = [a for a in env.gateway.acks if a["record_id"] == first["record_id"]]
    assert [a["outcome"] for a in acks] == ["applied", "applied"]
    assert env.ack(twin)["outcome"] == "duplicate"
    rows = [
        json.loads(line)
        for line in env.records.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) == 1


def _refusal(env, record) -> str:
    ack = env.ack(record)
    assert ack["outcome"] == "refused"
    return ack["reason_code"]


def test_forged_and_unauthorized_records_are_refused(env):
    env.publish_all()
    device = env.pair()
    library_id, sha = env.item(env.large)
    other_id, other_sha = env.item(env.small)
    gateway = env.gateway
    cases = {
        "unknown_item": gateway.decide("c" * 32, sha, "keep"),
        "digest_mismatch": gateway.decide(library_id, other_sha, "keep"),
        "favorite_with_delete": gateway.decide(library_id, sha, "delete", favorite=True),
        "revoked_device": gateway.decide(library_id, sha, "keep", device_id="never-enrolled-1"),
    }
    path_field = gateway.decide(library_id, sha, "delete")
    path_field["path"] = str(env.large)
    target_path = gateway.decide(library_id, sha, "delete")
    target_path["target"]["path"] = "../../Windows/System32"
    unknown_kind = gateway.decide(library_id, sha, "keep")
    unknown_kind["kind"] = "shell"
    needs_fix_delete = gateway.decide(library_id, sha, "delete", tags=["needs_fix"])
    nameless = {"kind": "decision", "target": {"library_id": library_id, "sha256": sha}}
    gateway.outbox.append(nameless)
    actions = []
    for action in sorted(ACTIONS):
        record = gateway.decide(library_id, sha, "keep")
        record.pop("decision")
        record.update(
            kind="action_request", action_request={"action": action, "params": _prepare(action)}
        )
        actions.append(record)
    env.sync.run_cycle()

    for reason, record in cases.items():
        assert _refusal(env, record) == reason
    for record in (path_field, target_path, unknown_kind, needs_fix_delete):
        assert _refusal(env, record) == "invalid_record"
    assert all(_refusal(env, record) == "not_granted" for record in actions)
    assert nameless in gateway.outbox  # nothing to acknowledge it by; it is never applied
    assert env.large.exists() and env.small.exists()
    assert not env.records.exists()  # no evidence written for any refusal
    assert env.sync.status().refused == len(cases) + 4 + len(actions)

    # Bytes changed after publishing: the record names the old digest.
    env.small.write_bytes(env.large.read_bytes())
    changed = gateway.decide(other_id, other_sha, "delete", device_id=device)
    env.sync.run_cycle()
    assert _refusal(env, changed) == "digest_mismatch"  # pull runs before the next publish
    assert env.small.exists()


def test_revoked_or_unscoped_devices_are_refused(env):
    env.publish_all()
    device = env.pair()
    library_id, sha = env.item(env.small)
    assert env.sync.revoke(device)
    record = env.gateway.decide(library_id, sha, "delete", device_id=device)
    env.sync.run_cycle()
    assert _refusal(env, record) == "revoked_device"
    assert env.gateway.revocations[-1]["device_id"] == device
    assert env.small.exists()

    # A device enrolled from an offer that grants only "queue" cannot review.
    env.ledger.add_offer(
        "11111111-2222-4333-8444-555555555555", ("queue",), "", "2026-11-25T22:00:00.000Z", "{}"
    )
    env.ledger.mark_offer_sent("11111111-2222-4333-8444-555555555555")
    env.gateway.enrolled = [
        {
            "device_id": "queue-only-device",
            "offer_id": "11111111-2222-4333-8444-555555555555",
            "enrolled_at": "2026-11-25T21:30:00Z",
        },
        # An enrollment for an offer this PC never issued is not trusted.
        {
            "device_id": "stranger-device",
            "offer_id": "99999999-2222-4333-8444-555555555555",
            "enrolled_at": "2026-11-25T21:30:00Z",
        },
    ]
    unscoped = env.gateway.decide(library_id, sha, "keep", device_id="queue-only-device")
    stranger = env.gateway.decide(library_id, sha, "keep", device_id="stranger-device")
    env.sync.run_cycle()
    assert _refusal(env, unscoped) == "not_granted"
    assert _refusal(env, stranger) == "revoked_device"
    # A second device cannot claim an offer already bound (single use).
    assert not env.ledger.bind_device(
        "late-device-1", env.gateway.offers[0]["offer_id"], "", "2026-11-25T21:30:00Z"
    )


def test_a_device_the_gateway_no_longer_lists_is_refused(env):
    env.publish_all()
    device = env.pair()
    library_id, sha = env.item(env.small)
    env.gateway.enrolled = []  # revoked on the gateway itself (S11)
    record = env.gateway.decide(library_id, sha, "delete", device_id=device)
    env.sync.run_cycle()
    assert _refusal(env, record) == "revoked_device"
    assert env.ledger.device(device).revoked and env.small.exists()
    assert env.gateway.revocations == []  # nothing to send back: the gateway revoked it


def test_a_refused_or_expired_pairing_offer_is_dead(env):
    env.gateway.refuse_offers = True
    code = env.sync.create_pairing()
    env.sync.run_cycle()
    assert env.ledger.unsent_offers() == [] and env.sync.status().pairing_code == ""
    offer_id = env.ledger._read("SELECT offer_id FROM offers")[0]["offer_id"]
    assert not env.ledger.bind_device("late-device-1", offer_id, "", "2026-11-25T21:30:00Z")
    assert code  # shown once, never usable

    # An offer that expired while the gateway was unreachable is never sent.
    env.gateway.refuse_offers = False
    env.ledger.add_offer(
        "22222222-2222-4333-8444-555555555555", ("review",), "", "2020-01-01T00:00:00.000Z", "{}"
    )
    env.sync.run_cycle()
    assert env.gateway.offers == [] and env.ledger.unsent_offers() == []


def test_acknowledgements_owed_from_an_earlier_cycle_are_settled(env):
    env.ledger.record_outcome(
        "33333333-2222-4333-8444-555555555555", None, "refused", "invalid_record", {}, "t"
    )
    env.sync.run_cycle()  # the gateway answers 404 (withdrawn record): settled, not retried forever
    assert env.ledger.unsent_acknowledgements() == []
    assert env.sync.status().state == "idle"


def test_health_preflight_runs_before_any_upload(env):
    env.gateway.secret = "rotated-secret-" + "z" * 30
    env.sync.run_cycle()
    assert env.gateway.calls == [("GET", "/sync/v1/health")]
    assert env.sync.status().state == "refused_secret"


def test_immich_receipts_are_stored_for_published_items_only(env):
    env.publish_all()
    library_id, sha = env.item(env.small)
    base = {
        "schema_version": "stablenew.review-gateway-sync.v1",
        "type": "immich_receipt",
        "status": "uploaded",
        "at": "2026-11-25T21:40:00Z",
    }
    env.gateway.immich_page = {
        "schema_version": "stablenew.review-gateway-sync.v1",
        "type": "immich_receipt_page",
        "receipts": [
            {
                **base,
                "record_id": "11111111-0000-4000-8000-000000000001",
                "item": {"library_id": library_id, "sha256": sha},
                "immich_asset_id": "asset-1",
                "favorite": True,
            },
            {
                **base,
                "record_id": "11111111-0000-4000-8000-000000000002",
                "item": {"library_id": "d" * 32, "sha256": sha},
            },
            {**base, "record_id": "bad"},
        ],
        "next_cursor": None,
    }
    env.sync.run_cycle()
    stored = env.ledger.immich_receipt("11111111-0000-4000-8000-000000000001")
    assert stored is not None and stored["asset_id"] == "asset-1" and stored["favorite"] == 1
    assert env.ledger.immich_receipt("11111111-0000-4000-8000-000000000002") is None


def test_immich_receipt_pages_are_followed_and_the_cursor_is_kept(env):
    env.publish_all()
    library_id, sha = env.item(env.small)

    def page(number, next_cursor):
        receipts = [
            {
                "schema_version": "stablenew.review-gateway-sync.v1",
                "type": "immich_receipt",
                "record_id": f"11111111-0000-4000-8000-00000000000{number}",
                "item": {"library_id": library_id, "sha256": sha},
                "status": "uploaded",
                "at": "2026-11-25T21:40:00Z",
            }
        ]
        return {
            "schema_version": "stablenew.review-gateway-sync.v1",
            "type": "immich_receipt_page",
            "receipts": receipts if number else [],
            "next_cursor": next_cursor,
        }

    env.gateway.immich_pages = {
        "": page(1, "epoch:1"),
        "epoch:1": page(2, "epoch:2"),
        "epoch:2": page(0, None),
    }

    def asked():
        return [path for _method, path in env.gateway.calls if "immich-receipts" in path]

    env.gateway.calls.clear()
    env.sync.run_cycle()

    assert len(asked()) == 3 and asked()[-1].endswith("?cursor=epoch%3A2")
    for number in (1, 2):
        assert env.ledger.immich_receipt(f"11111111-0000-4000-8000-00000000000{number}")
    env.gateway.calls.clear()
    env.sync.run_cycle()  # only what is new since last time
    assert asked() == ["/sync/v1/immich-receipts?cursor=epoch%3A2"]


def test_status_reports_gateway_refusals_without_secrets(env, caplog):
    env.gateway.secret = "other-secret-" + "x" * 30
    env.sync.run_cycle()
    status = env.sync.status()
    assert status.state == "refused_secret" and "secret" in status.message
    assert SECRET not in caplog.text and SECRET not in repr(env.sync._settings)


def test_sync_logs_carry_no_prompt_or_secret(tmp_path, caplog):
    """N11 / RG-100 E1: a full publish, pair and decide cycle logs neither the prompt nor the sync secret."""

    from PIL.PngImagePlugin import PngInfo

    prompt = "zebra-quokka-marker in a moonlit field"
    caplog.set_level(logging.DEBUG)
    environment = Env(tmp_path)
    try:
        info = PngInfo()
        info.add_text(
            "parameters", f"{prompt}\nNegative prompt: blurry-walrus-marker\nSteps: 20, Seed: 7"
        )
        Image.new("RGB", (64, 48), "#557733").save(environment.small, pnginfo=info)
        environment.publish_all()
        environment.pair()
        library_id, sha = environment.item(environment.small)
        environment.gateway.decide(library_id, sha, "keep", favorite=True, tags=["hands"])
        environment.gateway.secret = "other-secret-" + "x" * 30  # a refused cycle logs too
        environment.sync.run_cycle()
        environment.gateway.secret = SECRET
        environment.sync.run_cycle()
    finally:
        environment.close()

    assert "zebra-quokka-marker" in json.dumps(
        environment.gateway.manifests
    )  # the prompt did flow to the phone
    for forbidden in ("zebra-quokka-marker", "blurry-walrus-marker", SECRET):
        assert forbidden not in caplog.text


# -- boundaries -----------------------------------------------------------------------------------------------------


def test_no_inbound_socket_is_opened(env, monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("the PC must not listen (RG-100 invariant 1)")

    monkeypatch.setattr(socket.socket, "bind", refuse)
    monkeypatch.setattr(socket.socket, "listen", refuse)
    monkeypatch.setattr(socket, "create_server", refuse)
    env.publish_all()
    env.pair()
    library_id, sha = env.item(env.small)
    env.gateway.decide(library_id, sha, "delete")
    env.sync.run_cycle()
    for module in SRC.glob("app/review_gateway_*.py"):
        text = module.read_text(encoding="utf-8")
        for forbidden in (".bind(", ".listen(", "create_server", "socketserver", "http.server"):
            assert forbidden not in text, (module.name, forbidden)


def _prepare(action: str) -> dict:
    """A well-formed prepare for ``action`` (a prompt tweak carries its words, RG-140 slice 2)."""

    return {"step": "prepare", **({"text": "smiling"} if action == "prompt_tweak" else {})}


def _gateway_modules():
    return [*SRC.glob("app/review_gateway_*.py"), SRC / "gui" / "review_gateway_dialog.py"]


def test_no_phone_record_can_reach_the_runner(tmp_path):
    """RG-100 invariant 6: the sync modules have no submission path of their own; phone actions (RG-140) reach the queue only through the injected admission (tests/app/test_review_gateway_actions.py)."""

    for module in _gateway_modules():
        tree = ast.parse(module.read_text(encoding="utf-8"))
        imported = {
            node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        } | {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        for name in imported:
            assert not name.startswith(("src.queue", "src.controller")), (module.name, name)
            assert name not in ("src.pipeline.pipeline_runner", "src.app.site_phone_admission")
        identifiers = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
            node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
        }
        for forbidden in ("submit_njrs", "run_njr", "PipelineRunner", "JobService", "job_queue"):
            assert forbidden not in identifiers, (module.name, forbidden)

    root = (tmp_path / "output").resolve()
    (root / RUN).mkdir(parents=True)
    image = root / RUN / "a.png"
    Image.new("RGB", (32, 32), "#123456").save(image)
    calls: list[str] = []

    def forbidden(name):
        def call(*_args, **_kwargs):
            calls.append(name)
            raise AssertionError(name)

        return call

    runner = SimpleNamespace(current_job_id=None, run_njr=forbidden("run_njr"))
    queue = SimpleNamespace(list_active_jobs_ordered=lambda: [], submit=forbidden("queue.submit"))
    app = SimpleNamespace(
        _config_manager=SimpleNamespace(get_setting=lambda key, default=None: str(root)),
        job_service=SimpleNamespace(
            runner=runner,
            job_queue=queue,
            submit_njrs=forbidden("submit_njrs"),
            submit_job_with_run_mode=forbidden("submit_job_with_run_mode"),
        ),
    )
    gateway = FakeGateway()
    sync = build_review_gateway_sync(
        app,
        state_dir=tmp_path / "state",
        records_path=tmp_path / "learning.jsonl",
        settings_store=_codec_store(tmp_path / "state" / "settings.bin"),
        transport_factory=lambda _settings: gateway,
    )
    try:
        sync.configure("gateway.lan", FINGERPRINT, SECRET)
        deadline = time.monotonic() + 30
        while not gateway.manifests:
            assert time.monotonic() < deadline
            sync.run_cycle()
            time.sleep(0.02)
        sync.create_pairing()
        sync.run_cycle()
        device = gateway.enroll(gateway.offers[-1])
        library_id, manifest = next(iter(gateway.manifests.items()))
        sha = manifest["item"]["sha256"]
        records = []
        for action in sorted(ACTIONS):
            record = gateway.decide(library_id, sha, "keep", device_id=device)
            record.pop("decision")
            record.update(
                kind="action_request",
                action_request={"action": action, "params": _prepare(action)},
            )
            records.append(record)
        sync.run_cycle()
        acks = {a["record_id"]: a for a in gateway.acks}
        assert all(acks[r["record_id"]]["reason_code"] == "not_granted" for r in records)
        assert calls == []
    finally:
        sync.stop(timeout=0)


def test_worker_thread_is_registered_and_stops(env):
    from src.utils.thread_registry import get_thread_registry

    env.sync.start()
    try:
        names = [tracked.name for tracked in get_thread_registry().get_active_threads()]
        assert "Review gateway sync" in names
        deadline = time.monotonic() + 30
        while len(env.gateway.manifests) < 2:
            assert time.monotonic() < deadline
            env.sync.sync_now()
            time.sleep(0.05)
    finally:
        env.sync.stop(timeout=5)
    assert env.sync.status().state == "stopped" and env.sync.stopping


def test_an_unexpected_failure_does_not_stop_the_worker(env, monkeypatch, caplog):
    calls = []

    def explode():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("C:/secret/path/in/message")
        return 0.01

    monkeypatch.setattr(env.sync, "run_cycle", explode)
    env.sync.start()
    try:
        deadline = time.monotonic() + 10
        while len(calls) < 2:
            assert time.monotonic() < deadline
            env.sync.sync_now()
            time.sleep(0.02)
    finally:
        env.sync.stop(timeout=5)
    assert "RuntimeError" in caplog.text and "secret/path" not in caplog.text


def test_ffmpeg_input_uses_the_restricted_demuxer_options(monkeypatch, tmp_path):
    from src.app import site_library_video
    from src.utils import managed_process

    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr("src.pipeline.video.resolve_ffmpeg_executable", lambda: Path("ffmpeg"))
    monkeypatch.setattr(managed_process, "run_bounded", fake_run)
    with (tmp_path / "clip.mp4").open("wb+") as stream:
        assert not review_gateway_publish.ffmpeg_mobile_transcode(
            stream, tmp_path / "out.mp4", lambda: False
        )
    command = captured["command"]
    options = list(site_library_video.INPUT_OPTIONS)
    assert command[1 : 1 + len(options)] == options
    assert command[command.index("-protocol_whitelist") + 1] == "fd"
    assert command.index("-format_whitelist") < command.index("-i")


# -- credentials and transport --------------------------------------------------------------------------------------


def test_settings_are_validated_and_stored_protected(tmp_path):
    store = _codec_store(tmp_path / "settings.bin")
    settings = GatewaySettings.build("Gateway.LAN:9443", "AB:" * 31 + "AB", SECRET)
    assert settings.fingerprint == "ab" * 32 and settings.host == "gateway.lan"
    store.save(settings)
    assert SECRET.encode() not in (tmp_path / "settings.bin").read_bytes()
    assert store.load() == settings and SECRET not in repr(settings)
    for address in ("http://gateway", "gateway/sync", "user@gateway", "gateway:99999", ""):
        with pytest.raises(ValueError):
            GatewaySettings.build(address, FINGERPRINT, SECRET)
    with pytest.raises(ValueError):
        GatewaySettings.build("gateway", "abc", SECRET)
    with pytest.raises(ValueError):
        GatewaySettings.build("gateway", FINGERPRINT, "short")
    assert GatewaySettings.build("[fd7a::1]:9443", FINGERPRINT, SECRET).address == "[fd7a::1]:9443"


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")
def test_settings_round_trip_through_windows_dpapi(tmp_path):
    store = GatewaySettingsStore(tmp_path / "settings.dpapi")
    settings = GatewaySettings.build("192.168.1.50", FINGERPRINT, SECRET)
    store.save(settings)
    assert SECRET.encode() not in (tmp_path / "settings.dpapi").read_bytes()
    assert store.load() == settings


def test_pin_mismatch_refuses_before_any_request(monkeypatch):
    sent = []

    class FakeSSLSocket:
        def getpeercert(self, binary_form=False):
            return b"another certificate"

        def settimeout(self, _value):
            pass

    import ssl

    monkeypatch.setattr(ssl, "SSLSocket", FakeSSLSocket)

    class FakeConnection:
        def __init__(self, *args, **kwargs):
            self.sock = None

        def connect(self):
            self.sock = FakeSSLSocket()

        def request(self, *args, **kwargs):
            sent.append(kwargs.get("headers"))

        def close(self):
            pass

    import http.client

    monkeypatch.setattr(http.client, "HTTPSConnection", FakeConnection)
    transport = PinnedHttpsTransport(GatewaySettings.build("192.168.1.50", FINGERPRINT, SECRET))
    with pytest.raises(GatewayPinMismatch):
        GatewayClient(transport, SECRET).outbox(None)
    assert sent == []  # the secret never left the PC
    der = b"pinned certificate"
    check_pin(der, hashlib.sha256(der).hexdigest())
    with pytest.raises(GatewayPinMismatch):
        check_pin(None, FINGERPRINT)


def test_a_refused_secret_is_reported(env):
    client = GatewayClient(env.gateway, "wrong-secret-" + "y" * 30)
    with pytest.raises(GatewayUnauthorized):
        client.outbox(None)
