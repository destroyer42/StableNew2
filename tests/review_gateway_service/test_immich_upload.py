"""RG-130: keepers go to Immich once, from a durable queue, and the PC gets a receipt (D3, S5).

The gateway talks real HTTP to ``FakeImmich`` on loopback; the clock is faked, so backoff and the settle delay
are advanced rather than slept through.
"""

from __future__ import annotations

import logging
import os
import threading

import pytest
from review_gateway.__main__ import main

from src.app.review_gateway_protocol import parse_immich_receipt
from tests.review_gateway_service.conftest import SCHEMA_PATH, SECRET, Rig
from tests.review_gateway_service.fake_immich import API_KEY, FakeImmich
from tests.review_gateway_service.test_config_cli_server import config_file

RUN = "20261125_101500_pack"
SETTLE = 61


class Immich:
    """A rig wired to a fake Immich, with the steps these tests repeat."""

    def __init__(self, tmp_path, clock) -> None:
        self.fake = FakeImmich()
        self.key_file = tmp_path / "immich_api_key"
        self.write_key(API_KEY)
        self.rig = Rig(tmp_path, clock, immich_url=self.fake.url, immich_key_file=self.key_file)
        self.clock = clock
        self.rig.pair()
        self.uploader = self.rig.gateway.uploader()

    def close(self) -> None:
        self.rig.close()
        self.fake.close()

    def write_key(self, value: str) -> None:
        self.key_file.write_text(value + "\n" if value else "", encoding="utf-8")
        self.key_file.chmod(0o600)

    def keep(self, name: str = "one", *, favorite: bool = False, **options) -> tuple[dict, str]:
        item = self.rig.publish(name, **options)
        return item, self.decide(item, favorite=favorite)

    def decide(self, item: dict, verdict: str = "keep", *, favorite: bool = False) -> str:
        response = self.rig.decide(item, verdict, favorite=favorite)
        assert response.status_code == 200, response.text
        return response.json()["record_id"]

    def settle(self, seconds: float = SETTLE) -> list[str]:
        """Let the delay pass, then run the uploader until it has nothing more to do right now."""

        self.clock.advance(seconds=seconds)
        outcomes = []
        for _ in range(20):
            outcomes.append(self.uploader.run_once())
            if outcomes[-1] != "done":
                break
        return outcomes

    def page(self, cursor: str | None = None) -> dict:
        query = f"?cursor={cursor}" if cursor else ""
        response = self.rig.sync.get(f"/sync/v1/immich-receipts{query}")
        assert response.status_code == 200, response.text
        return response.json()

    def receipts(self) -> dict[str, dict]:
        found = {}
        for receipt in self.page()["receipts"]:
            self.rig.gateway.contract.validate("immich_receipt", receipt)
            parse_immich_receipt(receipt)  # the PC's strict parser takes it as it is
            found[receipt["record_id"]] = receipt
        return found

    def only_asset(self) -> tuple[str, dict]:
        assert len(self.fake.assets) == 1, self.fake.assets
        return next(iter(self.fake.assets.items()))


@pytest.fixture
def immich(tmp_path, clock):
    instance = Immich(tmp_path, clock)
    yield instance
    instance.close()


def test_a_descriptive_file_name_is_the_name_in_immich(immich) -> None:
    """NAME-INFO: the PC's descriptive name when the item has one; the run and digest otherwise."""

    name = "20261127-1648_txt2img_photoMomentum_000-Style_p01v02_8f87e4a2.png"
    manifest, blobs = immich.rig.manifest("named")
    manifest["info"] = {"file_name": name}
    response = immich.rig.sync.post("/sync/v1/items", json=manifest)
    assert response.status_code == 200, response.text
    for digest in response.json()["missing"]:
        assert immich.rig.sync.put(f"/sync/v1/media/{digest}", content=blobs[digest]).is_success
    immich.decide(manifest["item"])

    immich.settle()

    assert [sent["assetData.filename"] for sent in immich.fake.uploads] == [name]


def original(name: str = "one") -> bytes:
    return f"original-{name}".encode() * 4


# --- upload, album, favorite ----------------------------------------------------------------------------------------


def test_a_keep_is_uploaded_into_the_run_album_while_the_pc_has_not_answered(immich) -> None:
    item, record_id = immich.keep()

    assert immich.settle(seconds=0) == ["idle"]  # a quick change of mind is still possible
    assert immich.fake.requests == []
    assert immich.settle() == ["done", "idle"]

    asset_id, asset = immich.only_asset()
    assert asset["data"] == original() and asset["favorite"] is False
    [album] = immich.fake.albums.values()
    assert album == {"name": RUN, "assets": [asset_id]}
    sent = immich.fake.uploads[0]
    assert sent["assetData.type"] == "image/png"
    assert sent["assetData.filename"] == f"{RUN}_{item['sha256'][:8]}.png"
    assert sent["fileCreatedAt"].startswith("2026-11-25T12:00:00")
    assert len(sent["x-immich-checksum"]) == 40
    assert "deviceId" not in sent  # removed in Immich v3
    receipt = immich.receipts()[record_id]
    assert receipt == {
        "schema_version": "stablenew.review-gateway-sync.v1",
        "type": "immich_receipt",
        "record_id": record_id,
        "item": item,
        "status": "uploaded",
        "immich_asset_id": asset_id,
        "album": RUN,
        "favorite": False,
        "at": receipt["at"],
    }
    assert immich.rig.outbox()["records"][0]["record_id"] == record_id  # still the PC's to answer


def test_a_clip_is_uploaded_as_its_original_not_the_phone_rendition(immich) -> None:
    immich.keep("clip", kind="video")

    immich.settle()

    assert immich.only_asset()[1]["data"] == original("clip")
    assert immich.fake.uploads[0]["assetData.filename"].endswith(".mp4")


def test_immich_v2_is_sent_the_device_fields_it_requires(immich) -> None:
    immich.fake.major = 2
    immich.keep()

    assert immich.settle() == ["done", "idle"]

    sent = immich.fake.uploads[0]
    assert sent["deviceId"] == "stablenew-review-gateway" and sent["deviceAssetId"]


def test_an_immich_too_old_to_scope_keys_this_way_is_not_uploaded_to(immich) -> None:
    immich.fake.major = 1
    _item, record_id = immich.keep()

    assert immich.settle() == ["unavailable"]

    assert immich.fake.assets == {}
    assert immich.receipts()[record_id]["error_code"] == "immich_unsupported_version"


def test_favorite_sets_the_immich_favorite_flag(immich) -> None:
    _item, record_id = immich.keep(favorite=True)

    immich.settle()

    assert immich.only_asset()[1]["favorite"] is True
    assert immich.receipts()[record_id]["favorite"] is True


def test_one_album_per_run(immich) -> None:
    immich.keep("one")
    immich.keep("two")
    immich.keep("three", run_id="20261126_080000_other")

    assert immich.settle().count("done") == 3

    albums = {album["name"]: len(album["assets"]) for album in immich.fake.albums.values()}
    assert albums == {RUN: 2, "20261126_080000_other": 1}
    assert immich.fake.calls("POST", "/api/albums") == 2


def test_an_album_that_already_exists_is_used(immich) -> None:
    album_id = immich.fake.add_album(RUN)
    immich.fake.add_album("Holiday")
    immich.keep()

    immich.settle()

    assert immich.fake.calls("POST", "/api/albums") == 0
    assert len(immich.fake.albums[album_id]["assets"]) == 1


def test_an_album_deleted_in_immich_is_made_again(immich) -> None:
    immich.keep("one")
    immich.settle()
    immich.fake.albums.clear()
    _item, record_id = immich.keep("two")

    assert immich.settle() == ["done", "idle"]

    [album] = immich.fake.albums.values()
    assert album["name"] == RUN and len(album["assets"]) == 1
    assert immich.receipts()[record_id]["status"] == "uploaded"


# --- never a second asset -------------------------------------------------------------------------------------------


def test_media_immich_already_has_is_not_sent_again(immich) -> None:
    asset_id = immich.fake.add_asset(original())
    _item, record_id = immich.keep(favorite=True)

    immich.settle()

    assert immich.fake.calls("POST", "/api/assets") == 0
    assert immich.only_asset() == (asset_id, immich.fake.assets[asset_id])
    assert immich.fake.assets[asset_id]["favorite"] is True
    receipt = immich.receipts()[record_id]
    assert receipt["status"] == "duplicate" and receipt["immich_asset_id"] == asset_id


def test_a_retry_after_a_half_finished_upload_creates_no_second_asset(immich) -> None:
    immich.fake.fail[("PUT", "/api/albums/")] = 502
    _item, record_id = immich.keep()

    assert immich.settle() == ["failed"]
    assert len(immich.fake.assets) == 1 and immich.receipts() == {}
    immich.fake.fail.clear()
    assert immich.settle(seconds=31) == ["done", "idle"]

    asset_id, _asset = immich.only_asset()
    assert immich.fake.calls("POST", "/api/assets") == 1
    assert immich.receipts()[record_id]["status"] == "uploaded"
    assert immich.receipts()[record_id]["immich_asset_id"] == asset_id


def test_deciding_again_reuses_the_asset_and_answers_the_new_record(immich) -> None:
    item, first = immich.keep()
    immich.settle()
    immich.rig.outbox()  # the PC has seen the first record, so the second is a new one

    second = immich.decide(item, favorite=True)
    immich.settle()

    assert immich.only_asset()[1]["favorite"] is True
    assert immich.fake.calls("POST", "/api/assets") == 1
    receipts = immich.receipts()
    assert receipts[first]["status"] == "uploaded"
    assert receipts[second]["status"] == "duplicate" and receipts[second]["favorite"] is True


def test_republishing_after_an_upload_creates_nothing(immich) -> None:
    immich.keep()
    immich.settle()
    before = len(immich.fake.requests)

    immich.rig.publish()

    assert immich.settle() == ["idle"]
    assert len(immich.fake.requests) == before


def test_taking_back_a_favorite_clears_only_the_flag_the_gateway_set(immich) -> None:
    item, _record = immich.keep(favorite=True)
    immich.settle()
    immich.rig.outbox()
    immich.decide(item)
    immich.settle()
    assert immich.only_asset()[1]["favorite"] is False

    mine = immich.fake.add_asset(original("two"), favorite=True)  # the owner's own favorite
    immich.keep("two")
    immich.settle()
    assert immich.fake.assets[mine]["favorite"] is True


# --- changes of mind and refusals -----------------------------------------------------------------------------------


def test_delete_before_the_upload_cancels_it(immich) -> None:
    item, _record = immich.keep()
    immich.decide(item, "delete")

    assert immich.settle() == ["idle"]
    assert immich.fake.requests == [] and immich.receipts() == {}


def test_delete_after_the_upload_leaves_immich_alone(immich) -> None:
    item, _record = immich.keep()
    immich.settle()
    immich.rig.outbox()
    before = len(immich.fake.requests)

    immich.decide(item, "delete")

    assert immich.settle() == ["idle"]
    assert len(immich.fake.requests) == before and len(immich.fake.assets) == 1


def test_a_keep_the_pc_refuses_before_the_upload_is_not_uploaded(immich) -> None:
    _item, record_id = immich.keep()
    immich.rig.outbox()
    immich.rig.acknowledge(record_id, "refused", reason_code="digest_mismatch")

    assert immich.settle() == ["idle"]
    assert immich.fake.requests == []


def test_a_refused_delete_leaves_the_earlier_keep_owed(immich) -> None:
    item, keep = immich.keep()
    immich.rig.outbox()
    immich.rig.acknowledge(keep, "applied")
    delete = immich.decide(item, "delete")
    immich.rig.outbox()
    immich.rig.acknowledge(delete, "refused", reason_code="archive_failed")

    assert immich.settle() == ["done", "idle"]
    assert immich.receipts()[keep]["status"] == "uploaded"


def test_a_revoked_phones_unanswered_keep_waits_for_the_pc(immich) -> None:
    _item, record_id = immich.keep()
    [device] = immich.rig.gateway.store.devices()
    immich.rig.gateway.store.revoke_device(device["device_id"])

    assert immich.settle() == ["idle"]
    immich.rig.outbox()
    immich.rig.acknowledge(record_id, "applied")  # the PC decided it was a real decision
    assert immich.settle() == ["done", "idle"]


# --- outages and failures -------------------------------------------------------------------------------------------


def test_an_outage_neither_loses_nor_duplicates_the_upload_and_review_continues(immich) -> None:
    immich.fake.down = True
    _item, first = immich.keep("one")

    for wait in (SETTLE, 900, 900):
        assert immich.settle(seconds=wait) == ["unavailable"]
    _other, second = immich.keep("two")  # review is not blocked
    assert immich.receipts() == {}

    restarted = immich.rig.gateway.__class__(immich.rig.settings, clock=immich.clock)
    immich.uploader = restarted.uploader()  # the queue is on disk
    immich.fake.down = False
    assert immich.settle().count("done") == 2

    assert len(immich.fake.assets) == 2
    assert {immich.receipts()[key]["status"] for key in (first, second)} == {"uploaded"}


def test_a_server_error_is_retried_with_backoff_and_reported_after_five_tries(immich) -> None:
    immich.fake.fail[("POST", "/api/assets")] = 500
    _item, record_id = immich.keep()

    assert immich.settle() == ["failed"]
    assert immich.settle(seconds=29) == ["idle"]  # not due yet
    for wait in (2, 61, 121):
        assert immich.settle(seconds=wait) == ["failed"]
        assert immich.receipts() == {}
    assert immich.settle(seconds=241) == ["failed"]
    receipt = immich.receipts()[record_id]
    assert receipt["status"] == "failed" and receipt["error_code"] == "immich_server_error"
    cursor = immich.page()["next_cursor"]

    assert immich.settle(seconds=900) == ["failed"]
    assert immich.page(cursor)["receipts"] == []  # the same failure is not reported twice
    immich.fake.fail.clear()
    assert immich.settle(seconds=900) == ["done", "idle"]

    [updated] = immich.page(cursor)["receipts"]  # success replaces the failure and is seen again
    assert updated["record_id"] == record_id and updated["status"] == "uploaded"
    assert len(immich.receipts()) == 1


def test_a_refusal_by_immich_is_reported_at_once_and_does_not_block_other_items(immich) -> None:
    immich.fake.fail[("POST", "/api/assets")] = 400
    _item, record_id = immich.keep("one")

    assert immich.settle() == ["failed"]
    receipt = immich.receipts()[record_id]
    assert receipt["status"] == "failed" and receipt["error_code"] == "immich_rejected_400"
    assert "immich_asset_id" not in receipt

    immich.fake.fail.clear()
    immich.keep("two")
    assert immich.settle() == ["done", "done", "idle"]  # the refused one is due again too


@pytest.mark.parametrize(
    ("setup", "error_code"),
    [("wrong_key", "immich_unauthorized"), ("missing_permission", "immich_forbidden")],
)
def test_a_key_immich_will_not_take_is_reported_and_uploads_resume_once_fixed(
    immich, setup, error_code
) -> None:
    if setup == "wrong_key":
        immich.write_key("some-other-key-0123456789abcdefghij")
    else:
        immich.fake.fail[("POST", "/api/albums")] = 403
    _item, record_id = immich.keep()

    assert immich.settle() == ["unavailable"]
    assert immich.receipts()[record_id]["error_code"] == error_code
    immich.write_key(API_KEY)  # read again each time: no restart needed
    immich.fake.fail.clear()
    assert immich.settle() == ["done", "idle"]
    assert len(immich.fake.assets) == 1


def test_a_trashed_copy_is_reported_not_counted_as_kept(immich) -> None:
    asset_id = immich.fake.add_asset(original(), trashed=True)
    _item, record_id = immich.keep()

    assert immich.settle() == ["failed"]

    assert immich.receipts()[record_id]["error_code"] == "immich_asset_trashed"
    immich.fake.assets[asset_id]["trashed"] = False  # restored in Immich
    assert immich.settle(seconds=900) == ["done", "idle"]
    assert immich.receipts()[record_id]["status"] == "duplicate"


def test_a_redirect_is_not_followed_so_the_key_goes_nowhere_else(immich) -> None:
    other = FakeImmich()
    try:
        immich.fake.redirect_to = other.url
        immich.keep()

        assert immich.settle() == ["unavailable"]
        assert other.requests == []
    finally:
        other.close()


@pytest.mark.parametrize("missing", ["url", "key"])
def test_without_configuration_keepers_wait_and_nothing_is_sent(tmp_path, clock, missing) -> None:
    immich = Immich(tmp_path, clock)
    try:
        if missing == "key":
            immich.write_key("")  # the installer's empty placeholder
        else:
            immich.rig.close()
            immich.rig = Rig(tmp_path / "unset", clock, immich_key_file=immich.key_file)
            immich.rig.pair()
            immich.uploader = immich.rig.gateway.uploader()
        immich.keep()

        assert immich.settle() == ["unconfigured"]
        assert immich.fake.requests == []
        assert immich.rig.gateway.store.status()["immich_waiting"] == 1
        if missing == "key":
            immich.write_key(API_KEY)
            assert immich.settle() == ["done", "idle"]
    finally:
        immich.close()


def test_a_key_that_is_not_one_line_of_text_is_never_sent(immich, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    immich.key_file.write_text(f"{API_KEY}\nX-Evil: 1\n", encoding="utf-8")
    immich.keep()

    assert immich.settle() == ["unconfigured"]
    assert immich.fake.requests == [] and API_KEY not in caplog.text


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes")
def test_a_key_other_users_can_read_is_not_used(immich) -> None:
    immich.key_file.chmod(0o640)
    immich.keep()

    assert immich.settle() == ["unconfigured"]
    assert immich.fake.requests == []


@pytest.mark.parametrize(
    ("url", "host", "port"),
    [
        ("http://[fd00::5]", "fd00::5", 80),
        ("https://immich.lan/api/", "immich.lan", 443),
        ("http://10.0.0.2:2283/photos", "10.0.0.2", 2283),
    ],
)
def test_the_immich_address_is_taken_apart_correctly(url, host, port) -> None:
    from review_gateway.immich import ImmichClient

    client = ImmichClient(url, API_KEY.encode())

    assert (client.host, client.port) == (host, port)


def test_an_asset_immich_will_not_add_does_not_hold_up_the_others(immich) -> None:
    immich.fake.unshareable.add(immich.fake.add_asset(original("one")))
    _item, first = immich.keep("one")
    _other, second = immich.keep("two")

    assert immich.settle() == ["failed"]
    assert immich.receipts()[first]["error_code"] == "immich_album_refused"
    assert immich.settle(seconds=1) == ["done", "idle"]
    assert immich.receipts()[second]["status"] == "uploaded"


def test_a_refused_item_goes_to_the_back_of_the_queue(immich) -> None:
    immich.fake.add_album("20261126_080000_other")
    immich.fake.fail[("POST", "/api/albums")] = 403  # only the item that needs a new album
    immich.keep("one")
    _other, second = immich.keep("two", run_id="20261126_080000_other")

    assert immich.settle() == ["unavailable"]
    assert immich.settle(seconds=30) == ["done", "unavailable"]
    assert immich.receipts()[second]["status"] == "uploaded"


def test_a_favorite_whose_reply_was_lost_can_still_be_taken_back(immich) -> None:
    immich.fake.lose_favorite_reply = True
    item, _record = immich.keep(favorite=True)
    assert immich.settle() == ["unavailable"]
    assert immich.only_asset()[1]["favorite"] is True

    immich.fake.lose_favorite_reply = False
    immich.rig.outbox()
    immich.decide(item)  # not a favorite after all
    assert immich.settle() == ["done", "idle"]

    assert immich.only_asset()[1]["favorite"] is False


# --- retention (D4) -------------------------------------------------------------------------------------------------


def test_a_kept_original_is_not_purged_until_immich_has_it(immich) -> None:
    immich.fake.down = True
    item, record_id = immich.keep()
    immich.rig.outbox()
    immich.rig.acknowledge(record_id, "applied")

    immich.clock.advance(days=30)
    assert immich.rig.gateway.retention()["items_purged"] == 0
    immich.fake.down = False
    assert immich.settle() == ["done", "idle"]

    assert immich.rig.gateway.retention()["items_purged"] == 1
    assert immich.rig.publish() == item  # answered "purged": nothing is uploaded again
    assert immich.settle() == ["idle"]


# --- the receipts route ---------------------------------------------------------------------------------------------


def test_receipts_are_paged_after_a_cursor_the_pc_keeps(immich, monkeypatch) -> None:
    from review_gateway import upload_queue

    monkeypatch.setattr(upload_queue, "RECEIPT_PAGE", 2)
    records = [immich.keep(name)[1] for name in ("one", "two", "three")]
    immich.settle()

    first = immich.page()
    second = immich.page(first["next_cursor"])
    last = immich.page(second["next_cursor"])

    assert first["schema_version"] == "stablenew.review-gateway-sync.v1"
    assert first["type"] == "immich_receipt_page"
    seen = [receipt["record_id"] for receipt in first["receipts"] + second["receipts"]]
    assert sorted(seen) == sorted(records) and len(first["receipts"]) == 2
    assert last["receipts"] == [] and last["next_cursor"] is None


def test_a_cursor_from_another_gateway_database_replays_everything(immich) -> None:
    immich.keep()
    immich.settle()

    assert len(immich.page("0123456789abcdef:999")["receipts"]) == 1
    for bad in ("999", "x:y", "0123456789abcdef:-1"):
        response = immich.rig.sync.get(f"/sync/v1/immich-receipts?cursor={bad}")
        assert response.status_code == 400 and response.json() == {"error": "invalid_cursor"}


def test_receipts_need_the_sync_secret_and_are_not_on_the_phone_app(immich) -> None:
    anonymous = immich.rig.client(immich.rig.gateway.sync_app())

    assert anonymous.get("/sync/v1/immich-receipts").status_code == 401
    assert immich.rig.phone.get("/sync/v1/immich-receipts").status_code == 404


# --- S5: the key ----------------------------------------------------------------------------------------------------


def test_the_key_is_never_logged_reported_or_stored(immich, caplog, tmp_path, capsys) -> None:
    caplog.set_level(logging.DEBUG)
    immich.fake.fail[("POST", "/api/assets")] = 500  # the fake echoes the key in error bodies
    immich.keep("one")
    immich.settle()
    immich.fake.fail = {("POST", "/api/assets"): 400}
    immich.settle(seconds=900)
    immich.fake.fail = {("GET", "/api/server/version"): 500}
    immich.settle(seconds=900)
    immich.fake.fail = {}
    immich.fake.down = True
    immich.settle(seconds=900)
    immich.fake.down = False
    immich.write_key("wrong-" + API_KEY)
    immich.settle(seconds=900)
    immich.write_key(API_KEY)
    assert immich.settle(seconds=900) == ["done", "idle"]
    path = config_file(
        tmp_path,
        f'schema_file = "{SCHEMA_PATH.as_posix()}"\n'
        f'immich_url = "{immich.fake.url}"\n'
        f'immich_key_file = "{immich.key_file.as_posix()}"\n',
    )
    assert main(["--config", str(path), "status"]) == 0
    assert main(["--config", str(path), "immich-check"]) == 0
    output = capsys.readouterr()

    assert caplog.records, "the failures above are logged"
    assert API_KEY not in caplog.text and SECRET not in caplog.text
    assert API_KEY not in output.out + output.err
    assert API_KEY not in str(immich.page())
    assert API_KEY not in repr(immich.rig.settings) + repr(immich.uploader.client())
    data = b"".join(
        file.read_bytes() for file in immich.rig.settings.data_dir.iterdir() if file.is_file()
    )
    assert API_KEY.encode() not in data


def test_the_owner_can_check_the_key_and_its_permissions(immich, tmp_path, capsys) -> None:
    path = config_file(
        tmp_path,
        f'immich_url = "{immich.fake.url}"\nimmich_key_file = "{immich.key_file.as_posix()}"\n',
    )
    command = ["--config", str(path), "immich-check"]

    assert main(command) == 0
    assert "3.4.2" in capsys.readouterr().out

    immich.fake.permissions = ["asset.upload", "asset.delete"]
    assert main(command) == 1
    output = capsys.readouterr().out
    assert "missing: album.create, album.read, albumAsset.create, asset.update" in output
    assert "not needed: asset.delete" in output

    immich.fake.permissions = ["all"]
    assert main(command) == 1
    assert "all" in capsys.readouterr().out
    assert immich.fake.assets == {} and immich.fake.albums == {}  # a check changes nothing

    immich.write_key("")
    assert main(command) == 1
    assert "not configured" in capsys.readouterr().out


@pytest.mark.parametrize(
    "url", ["ftp://immich.lan", "http://user:pw@immich.lan", "immich.lan:2283", "http://a/?k=1"]
)
def test_an_immich_address_that_could_leak_the_key_is_refused(tmp_path, capsys, url) -> None:
    path = config_file(tmp_path, f'immich_url = "{url}"\n')

    assert main(["--config", str(path), "check-config"]) == 2
    assert "immich_url" in capsys.readouterr().err


# --- the worker -----------------------------------------------------------------------------------------------------


def test_the_worker_loop_uploads_and_stops_when_asked(immich) -> None:
    immich.keep()
    immich.clock.advance(seconds=SETTLE)
    stop = threading.Event()
    worker = threading.Thread(target=immich.uploader.run, args=(stop,))
    worker.start()
    try:
        for _ in range(500):
            if immich.rig.gateway.store.status()["immich_uploaded"]:
                break
            stop.wait(0.02)
    finally:
        stop.set()
        worker.join(timeout=5)

    assert not worker.is_alive() and len(immich.fake.assets) == 1
