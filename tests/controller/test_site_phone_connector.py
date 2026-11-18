from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
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
    def __init__(self, *, offline=False):
        self.actions = []
        self.delivered = Event()
        self.polled = Event()
        self.offline = offline
        self.instance = ""
        self.result = None

    def request(self, action, site_secret, credential, **kwargs):
        assert site_secret == _SITE
        self.actions.append(action)
        if action == "inspect":
            assert credential == _CHALLENGE
            return {"id": _GRANT, "name": "Fixture phone"}
        if action == "enroll":
            assert credential == _CHALLENGE
            assert kwargs["body"]["rating"] is True
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
