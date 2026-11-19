from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from threading import Event

import pytest
from PIL import Image

from src.app import site_output_library
from src.app.site_output_catalog import SiteOutputCatalog
from src.app.site_phone_connector import (
    PhoneConnectorError,
    PhoneHttp,
    SitePhoneConnector,
    _desktop_call,
)
from src.app.site_phone_credentials import PhoneFolder, PhoneGrant, PhoneGrantStore
from src.app.site_rating_sync import root_identity
from src.gui.site_phone_dialog import DEFAULT_NATIVE_REVIEW, pairing_permissions
from src.learning.learning_record import SITE_REVIEW_RECEIPT, LearningRecordWriter
from src.review.review_evidence import (
    build_review_rating_record,
    lookup_disposition,
    lookup_rating,
    save_disposition,
)

_GRANT = "1" * 32
_SESSION = "2" * 32
_CALL = "3" * 32
_CHALLENGE = "4" * 32
_SITE = "fixture-only-site-secret"
_HOST = "5" * 64


def _grant(root: Path) -> PhoneGrant:
    return PhoneGrant(_GRANT, "Fixture phone", _SITE, _HOST, PhoneFolder.approve(root), True)


@pytest.mark.skipif(os.name != "nt", reason="Windows current-user DPAPI")
def test_protected_store_round_trips_synthetic_credentials(tmp_path):
    store = PhoneGrantStore(tmp_path / "fixture.dpapi")
    grant = _grant(tmp_path)
    store.save(grant)
    protected = store.path.read_bytes()
    assert _SITE.encode() not in protected
    assert _HOST.encode() not in protected
    assert store.load() == grant
    store.clear()
    assert store.load() is None


def test_protected_legacy_grant_does_not_gain_native_review(tmp_path, monkeypatch):
    monkeypatch.setattr("src.app.site_phone_credentials._dpapi", lambda data, **_options: data)
    store = PhoneGrantStore(tmp_path / "phone.dpapi")
    record = asdict(_grant(tmp_path))
    del record["native_review"]
    del record["queue_submit"]
    store.path.write_text(json.dumps(record))
    grant = store.load()
    assert grant is not None and grant.rating and not grant.native_review and not grant.queue_submit
    store.path.write_text(json.dumps({**record, "native_review": 1}))
    with pytest.raises(ValueError, match="Invalid phone pairing"):
        store.load()
    store.path.write_text(json.dumps({**record, "queue_submit": 1}))
    with pytest.raises(ValueError, match="Invalid phone pairing"):
        store.load()


def test_phone_queue_permission_is_explicit_and_independent(tmp_path):
    assert "Phone queue submission permission off" in pairing_permissions(True, True)
    assert "Preview and submit saved PromptPacks" in pairing_permissions(False, False, True)
    store = _MemoryStore()
    http = _FakePhone(rating=False)
    connector = SitePhoneConnector(store, http)
    connector.start()
    try:
        enrollment = connector.inspect(_SITE, _CHALLENGE).result(timeout=3)
        connector.enroll(enrollment, tmp_path, False, queue_submit=True).result(timeout=3)
        assert http.delivered.wait(4)
        assert store.grant.queue_submit is True
        assert store.grant.native_review is False
        assert http.enrollment["queue_submit"] is True
        assert "native_review" not in http.enrollment
    finally:
        connector.close()


@pytest.mark.parametrize("native_review", [DEFAULT_NATIVE_REVIEW, False])
def test_windows_enrollment_keeps_native_review_independent(tmp_path, native_review):
    assert DEFAULT_NATIVE_REVIEW is True
    summary = pairing_permissions(False, native_review)
    assert "gallery and video ratings" not in summary
    if native_review:
        assert "Write native Review evidence with ratings, Retain, and Mark for rework" in summary
    else:
        assert "Native Review evidence permission off" in summary
    store = _MemoryStore()
    http = _FakePhone(rating=False)
    connector = SitePhoneConnector(store, http, review_records=tmp_path / "learning.jsonl")
    connector.start()
    try:
        enrollment = connector.inspect(_SITE, _CHALLENGE).result(timeout=3)
        connector.enroll(enrollment, tmp_path, False, native_review=native_review).result(timeout=3)
        assert http.delivered.wait(4)
        assert store.grant.native_review is native_review
        assert http.enrollment.get("native_review", False) is native_review
        assert http.result["native_review"] is native_review
    finally:
        connector.close()


class _MemoryStore(PhoneGrantStore):
    def __init__(self, grant=None):
        self.grant = grant
        self.revoked = Event()

    def load(self):
        return self.grant

    def save(self, grant):
        self.grant = grant
        if grant.revoked:
            self.revoked.set()

    def clear(self):
        self.grant = None


class _FakePhone(PhoneHttp):
    def __init__(self, *, offline=False, rating=True):
        self.actions = []
        self.delivered = Event()
        self.polled = Event()
        self.offline = offline
        self.instance = ""
        self.result = None
        self.rating = rating
        self.enrollment = {}

    def request(self, action, site_secret, credential, **kwargs):
        assert site_secret == _SITE
        self.actions.append(action)
        if action == "inspect":
            assert credential == _CHALLENGE
            return {"id": _GRANT, "name": "Fixture phone"}
        if action == "enroll":
            assert credential == _CHALLENGE
            self.enrollment = kwargs["body"]
            assert self.enrollment["rating"] is self.rating
            return {"id": _GRANT}
        if action == "poll":
            self.instance = kwargs["instance"]
            self.polled.set()
            call = None
            if kwargs["body"]["claim"] and self.actions.count("poll") == 1:
                call = {
                    "id": _CALL,
                    "ttl": 75000,
                    "method": "GET",
                    "path": "/v1/output/status",
                    "body": None,
                }
            return {"session": _SESSION, "ttl": 30000, "call": call}
        if action == f"fulfill/{_CALL}":
            assert kwargs["session"] == _SESSION
            self.result = json.loads(kwargs["body"].data)
            self.delivered.set()
        if action == "revoke" and self.offline:
            raise PhoneConnectorError("fixture offline")
        return {}


def test_enroll_resume_same_grant_and_graceful_close(tmp_path):
    store = _MemoryStore()
    http = _FakePhone()
    connector = SitePhoneConnector(store, http)
    connector.start()
    try:
        enrollment = connector.inspect(_SITE, _CHALLENGE).result(timeout=3)
        connector.enroll(enrollment, tmp_path, True).result(timeout=3)
        assert http.delivered.wait(4)
        assert http.result["library"] is True
        assert store.grant.id == _GRANT
        assert store.grant.pending == ""
    finally:
        connector.close()
    assert http.actions[-1] == "close"
    resumed_http = _FakePhone()
    resumed = SitePhoneConnector(store, resumed_http)
    resumed.start()
    try:
        assert resumed_http.polled.wait(3)
        assert resumed_http.instance != http.instance
        assert "enroll" not in resumed_http.actions
    finally:
        resumed.close()


def test_offline_revoke_persists_before_another_process_can_poll(tmp_path):
    store = _MemoryStore(_grant(tmp_path))
    http = _FakePhone(offline=True)
    connector = SitePhoneConnector(store, http)
    connector.start()
    try:
        assert http.polled.wait(3)
        connector.revoke()
        assert store.revoked.wait(3)
    finally:
        connector.close()
    assert store.grant.revoked is True
    retry = _FakePhone()
    resumed = SitePhoneConnector(store, retry)
    resumed.start()
    try:
        deadline = time.monotonic() + 3
        while store.grant is not None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert store.grant is None
        assert retry.actions == ["revoke"]
    finally:
        resumed.close()


def _first_image(catalog):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        page = catalog.library.search(
            {
                "field": "all",
                "kind": "image",
                "query": "",
                "offset": 0,
                "revision": "",
                "refresh": False,
            }
        )
        if page["items"]:
            return catalog.library.inspect(page["items"][0]["id"])
        time.sleep(0.01)
    pytest.fail("The fixture image was not indexed")


def _native_request(catalog, action, **body):
    reply = _desktop_call(
        catalog,
        "POST",
        "/v1/output/library",
        {"scope": catalog.scope, "action": action, **body},
        False,
    )
    return reply.status, json.loads(reply.data)


@pytest.fixture
def native_review(tmp_path):
    root = tmp_path / "output"
    root.mkdir()
    image = root / "fixture.png"
    Image.new("RGB", (16, 16), "blue").save(image)
    records = tmp_path / "learning.jsonl"
    catalog = SiteOutputCatalog(root, review_records=records)
    proof = _first_image(catalog)
    status, snapshot = _native_request(
        catalog, "native_review", id=proof["item"]["id"], digest=proof["digest"]
    )
    assert status == 200
    edit = {
        "root": root_identity(root),
        "target": proof["rating_target"],
        "digest": proof["digest"],
        "section": "rating",
        "revision": snapshot["rating"]["revision"],
        "base": {"score": None},
        "changes": {"score": 3},
        "operation": "a" * 32,
        "actor_time": "2026-11-18T20:25:00.123Z",
    }
    yield catalog, image, records, proof, edit, snapshot
    catalog.revoke()


def test_native_rating_merges_fields_and_deduplicates_after_rebind_and_undo(
    native_review, monkeypatch
):
    catalog, image, records, _proof, edit, _snapshot = native_review
    writer = LearningRecordWriter(records)
    save = writer.append_record_atomic
    original_bytes = image.read_bytes()

    def lose_response(self, record, *, before_replace):
        save(record, before_replace=before_replace)
        raise OSError("Fixture interrupted after commit")

    with monkeypatch.context() as patch:
        patch.setattr(LearningRecordWriter, "append_record_atomic", lose_response)
        assert _native_request(catalog, "native_review_sync", **edit) == (
            409,
            {"error": "rating_retry"},
        )
    on_disk = records.read_bytes()
    assert on_disk.count(b"\n") == 1
    assert edit["actor_time"].encode() in on_disk
    catalog.revoke()
    new = SiteOutputCatalog(image.parent, review_records=records)
    _first_image(new)
    assert _native_request(new, "native_review_sync", **edit)[1]["saved"]
    assert records.read_bytes() == on_disk
    native = build_review_rating_record(
        {
            "image_path": str(image),
            "rating": 5,
            "source_job_id": "fixture-job",
            "subscores": {"anatomy": 5, "composition": 4, "prompt_adherence": 5},
        },
        artifact_sha256=edit["digest"],
    )
    assert writer.append_record(native)
    notes = {
        **edit,
        "base": {"notes": ""},
        "changes": {"notes": "After a PC edit"},
        "operation": "b" * 32,
    }
    assert _native_request(new, "native_review_sync", **notes)[1]["saved"]
    rated = lookup_rating(records, image, edit["digest"]).row
    assert rated["metadata"]["user_rating_raw"] == 5
    assert rated["metadata"]["user_notes"] == "After a PC edit"
    assert rated["metadata"]["source_job_id"] == "fixture-job"
    assert rated["metadata"]["subscores"]["composition"] == 4
    conflict = {**edit, "operation": "c" * 32}
    assert _native_request(new, "native_review_sync", **conflict)[1]["conflict"] == {"score": 5}
    assert writer.remove_latest_review_feedback(run_id=rated["run_id"], image_path=str(image))
    after_undo = records.read_bytes()
    assert _native_request(new, "native_review_sync", **notes)[1]["saved"]
    assert records.read_bytes() == after_undo
    assert lookup_rating(records, image, edit["digest"]).row["run_id"] == native.run_id
    assert image.read_bytes() == original_bytes
    new.revoke()


def test_native_decisions_are_explicit_scoped_and_leave_assets_in_place(native_review):
    catalog, image, records, proof, edit, snapshot = native_review
    ordinary = SiteOutputCatalog(image.parent)
    ordinary_proof = _first_image(ordinary)
    hold = {
        **edit,
        "section": "decision",
        "revision": snapshot["decision"]["revision"],
        "base": {"decision": ""},
        "changes": {"decision": "retain"},
    }
    assert (
        _native_request(
            ordinary, "native_review", id=ordinary_proof["item"]["id"], digest=proof["digest"]
        )[0]
        == 403
    )
    assert _native_request(ordinary, "native_review_sync", **hold)[0] == 403
    assert not records.exists()
    assert _native_request(catalog, "native_review_sync", **hold)[1]["saved"]
    change = {**hold, "operation": "d" * 32, "changes": {"decision": "rework"}}
    assert _native_request(catalog, "native_review_sync", **change)[1]["conflict"] == {
        "decision": "retain"
    }
    assert _native_request(
        catalog, "native_review_sync", **{**change, "base": {"decision": "retain"}}
    )[1]["saved"]
    assert lookup_disposition(records, image, proof["digest"]).disposition == "rework"
    rows = [json.loads(line)["metadata"] for line in records.read_text().splitlines()]
    assert rows[0]["user_rating"] == 4.0
    assert "user_rating" not in rows[1]
    assert rows[1][SITE_REVIEW_RECEIPT]["actor_time"] == edit["actor_time"]
    bad_decision = {**change, "changes": {"decision": "discard"}}
    assert _native_request(catalog, "native_review_sync", **bad_decision) == (
        409,
        {"error": "invalid_rating"},
    )
    assert list(image.parent.iterdir()) == [image]
    save_disposition(
        LearningRecordWriter(records),
        image_path=image,
        disposition="discard",
        artifact_sha256=proof["digest"],
    )
    assert _native_request(catalog, "native_review_sync", **{**hold, "operation": "e" * 32}) == (
        409,
        {"error": "review_archive_required"},
    )
    ordinary.revoke()


@pytest.mark.parametrize("interruption", ["revoked", "changed"])
def test_native_review_rechecks_permission_and_media_before_commit(
    native_review, monkeypatch, interruption
):
    catalog, image, records, _proof, edit, _snapshot = native_review
    save = LearningRecordWriter.append_record_atomic

    def interrupt(self, record, *, before_replace):
        if interruption == "revoked":
            catalog.revoke()
        else:
            Image.new("RGB", (12, 12), "red").save(image)
        save(self, record, before_replace=before_replace)

    monkeypatch.setattr(LearningRecordWriter, "append_record_atomic", interrupt)
    unexpected = "output_folder_not_shared" if interruption == "revoked" else "media_changed"
    assert _native_request(catalog, "native_review_sync", **edit) == (409, {"error": unexpected})
    assert not records.exists()


def test_phone_allowlist_and_competing_rating_writes_use_native_records(tmp_path, monkeypatch):
    Image.new("RGB", (8, 8), "blue").save(tmp_path / "fixture.png")
    browser = SiteOutputCatalog(tmp_path)
    phone = SiteOutputCatalog(tmp_path)
    native_image, phone_image = _first_image(browser), _first_image(phone)
    body = {
        "scope": phone.scope,
        "action": "rate",
        "id": phone_image["item"]["id"],
        "digest": phone_image["digest"],
        "revision": 0,
        "operation": "a" * 32,
        "score": 3,
        "notes": "Fixture phone rating",
    }
    route = "/v1/output/library"
    assert _desktop_call(phone, "POST", route, body, False).status == 403
    assert _desktop_call(phone, "POST", route, {**body, "action": "save_album"}, True).status == 403
    assert _desktop_call(phone, "POST", "/v1/submit", {}, True).status == 403
    assert _desktop_call(phone, "GET", "/v1/preview", None, True).status != 200

    native_body = {
        **body,
        "scope": browser.scope,
        "id": native_image["item"]["id"],
        "operation": "b" * 32,
        "score": 4,
    }
    writing, release = Event(), Event()
    original = site_output_library.atomic_write_bytes

    def wait_before_publish(path, data):
        writing.set()
        assert release.wait(3)
        return original(path, data)

    monkeypatch.setattr(site_output_library, "atomic_write_bytes", wait_before_publish)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(_desktop_call, phone, "POST", route, body, True)
            try:
                assert writing.wait(3)
                second = pool.submit(_desktop_call, browser, "POST", route, native_body, True)
                assert not second.done()
            finally:
                release.set()
            assert first.result(timeout=3).status == 200
            assert second.result(timeout=3).status == 409
        rated = browser.library.inspect(native_body["id"])["rating"]
        assert rated["score"] == 3
        assert rated["revision"] == 1
    finally:
        browser.revoke()
        phone.revoke()


def test_folder_replacement_refuses_old_grant(tmp_path):
    output = tmp_path / "fixture-output"
    output.mkdir()
    folder = PhoneFolder.approve(output)
    output.rename(tmp_path / "old-output")
    output.mkdir()
    assert not folder.matches()
