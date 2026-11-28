"""The phone listener: inbox, decisions, receipts, media, and the S6/S7 headers."""

from __future__ import annotations

import re
import uuid
from html.parser import HTMLParser

import pytest
from review_gateway.contract import Contract

from tests.review_gateway_service.conftest import GATEWAY_ROOT, SCHEMA_PATH

RUN = "20261125_101500_pack"
STATIC = GATEWAY_ROOT / "review_gateway" / "static"
CSP_DIRECTIVES = (
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    "object-src 'none'",
    "base-uri 'none'",
    "frame-ancestors 'none'",
)


def items(rig, run: str = RUN) -> list[dict]:
    response = rig.phone.get(f"/api/runs/{run}")
    assert response.status_code == 200, response.text
    return response.json()["items"]


def media(item: dict, variant: str) -> str:
    return f"/media/{item['library_id']}/{item['sha256']}/{variant}"


def test_the_inbox_groups_items_by_run_newest_first_with_counts(rig) -> None:
    kept = rig.publish("kept")
    rig.publish("open")
    removed = rig.publish("gone")
    rig.publish("later", run_id="20261126_090000_second run")
    rig.pair()
    rig.decide(kept, "keep", favorite=True)
    record = rig.decide(removed, "delete").json()["record_id"]
    rig.outbox()
    rig.acknowledge(record, "refused", reason_code="digest_mismatch")

    runs = rig.phone.get("/api/runs").json()["runs"]

    assert [run["run_id"] for run in runs] == ["20261126_090000_second run", RUN]
    assert [(run["kind"], run["name"]) for run in runs] == [("run", None), ("run", None)]
    counts = {
        key: runs[1][key] for key in runs[1] if key not in ("run_id", "covers", "kind", "name")
    }
    assert counts == {
        "total": 3,
        "undecided": 1,
        "keep": 1,
        "delete": 0,  # the PC refused it, so the item is not deleted and needs another look
        "favorite": 1,
        "pending": 1,
        "applied": 0,
        "refused": 1,
        "rework": 0,
    }
    assert {cover["library_id"] for cover in runs[1]["covers"]} <= {
        i["library_id"] for i in items(rig)
    }


BATCH = {
    "batch_id": "5b0c4f8e-2a1d-4e3b-9c7a-1f2e3d4c5b6a",
    "name": "2026-11-26 portraits +1 x 2 models",
    "cell": {"pack": "portraits", "model": "juggernautXL.safetensors"},
}


def test_the_inbox_groups_a_named_batch_across_run_folders(rig) -> None:
    """N5: a batch spans many run folders; the phone groups it by its name, and anything else by run folder."""

    first = rig.publish("cell-a", run_id="20261126_100000_portraits", batch=BATCH)
    other_cell = {**BATCH, "cell": {"pack": "landscapes", "model": "ponyXL.safetensors"}}
    second = rig.publish("cell-b", run_id="20261126_101500_landscapes", batch=other_cell)
    rig.clock.advance(minutes=5)
    loose = rig.publish("loose", run_id="20261126_103000_manual")
    rig.pair()
    rig.decide(first, "keep")

    runs = rig.phone.get("/api/runs").json()["runs"]

    assert [(run["kind"], run["name"]) for run in runs] == [
        ("run", None),
        ("batch", BATCH["name"]),
    ]
    assert runs[0]["run_id"] == "20261126_103000_manual"
    group = runs[1]
    assert group["run_id"] == f"batch:{BATCH['batch_id']}"
    assert (group["total"], group["undecided"], group["keep"]) == (2, 1, 1)
    response = rig.phone.get(f"/api/runs/{group['run_id']}")
    assert response.status_code == 200, response.text
    assert response.json()["name"] == BATCH["name"]
    listed = response.json()["items"]
    assert [item["library_id"] for item in listed] == [first["library_id"], second["library_id"]]
    assert [item["batch"] for item in listed] == [BATCH, other_cell]
    [plain] = items(rig, "20261126_103000_manual")
    assert plain["library_id"] == loose["library_id"] and plain["batch"] is None
    assert (
        items(rig, "20261126_100000_portraits") == []
    )  # a batched item is listed under its batch only


def test_a_republished_item_moves_into_its_batch(rig) -> None:
    """A manifest is idempotent by item: publishing it again with a batch moves it out of its run folder group."""

    rig.publish("again", run_id="20261126_100000_portraits")
    rig.publish("again", run_id="20261126_100000_portraits", batch=BATCH)
    rig.pair()

    [group] = rig.phone.get("/api/runs").json()["runs"]
    assert (group["kind"], group["total"]) == ("batch", 1)


def test_an_unknown_batch_group_lists_nothing(rig) -> None:
    rig.publish("one", batch=BATCH)
    rig.pair()

    assert items(rig, "batch:00000000-0000-4000-8000-000000000000") == []
    assert items(rig, "batch:not-a-uuid") == []


@pytest.mark.parametrize(
    "batch",
    [
        {"batch_id": "not-a-uuid", "name": "x"},
        {"batch_id": BATCH["batch_id"], "name": ""},
        {"batch_id": BATCH["batch_id"]},
        {**BATCH, "path": "C:\\\\output"},
        {**BATCH, "cell": {"pack": "p", "folder": "x"}},
    ],
)
def test_a_batch_the_contract_does_not_allow_is_refused(rig, batch) -> None:
    manifest, _blobs = rig.manifest("bad", batch=batch)

    assert rig.sync.post("/sync/v1/items", json=manifest).status_code == 422


def test_an_inbox_made_before_batches_gains_them(rig, tmp_path, clock) -> None:
    from tests.review_gateway_service.conftest import Rig

    rig.publish("old")
    with rig.gateway.store.write() as database:
        database.execute("DROP INDEX IF EXISTS item_batch")
        database.execute("ALTER TABLE item DROP COLUMN batch")
        database.execute("ALTER TABLE item DROP COLUMN batch_id")
    rig.close()

    reopened = Rig(tmp_path, clock)
    try:
        reopened.pair()
        [group] = reopened.phone.get("/api/runs").json()["runs"]
        assert (group["kind"], group["run_id"], group["total"]) == ("run", RUN, 1)
        reopened.publish("new", batch=BATCH)
        assert {run["kind"] for run in reopened.phone.get("/api/runs").json()["runs"]} == {
            "run",
            "batch",
        }
    finally:
        reopened.close()


def test_a_run_name_with_spaces_opens(rig) -> None:
    rig.publish("later", run_id="20261126_090000_second run")
    rig.pair()

    assert len(items(rig, "20261126_090000_second%20run")) == 1


def test_an_item_reports_its_variants_display_text_and_receipt_state(rig) -> None:
    rig.publish("clip", kind="video")
    rig.pair()

    [item] = items(rig)

    assert item["kind"] == "video"
    assert item["variants"] == ["original", "thumb", "video"]
    assert item["state"] == "undecided"
    assert item["decision"] is None
    assert item["duration_s"] == 5.0
    assert item["display"] == {
        "model": "juggernaut",
        "prompt_excerpt": "a <b>lighthouse</b>",
        "seed": "42",
    }


def test_a_large_seed_reaches_the_phone_without_losing_digits(rig) -> None:
    manifest, blobs = rig.manifest("seed")
    manifest["display"]["seed"] = 18446744073709551615
    rig.sync.post("/sync/v1/items", json=manifest)
    for digest, data in blobs.items():
        rig.sync.put(f"/sync/v1/media/{digest}", content=data)
    rig.pair()

    assert items(rig)[0]["display"]["seed"] == "18446744073709551615"


def test_a_decision_becomes_a_valid_outbox_record_and_follows_the_receipt(rig) -> None:
    item = rig.publish()
    device_id = rig.pair()

    response = rig.decide(item, "keep", favorite=True, tags=("needs_fix", "hands"))

    assert response.status_code == 200
    assert response.json()["state"] == "pending"
    [record] = rig.outbox()["records"]
    Contract(SCHEMA_PATH).validate("outbox_record", record)
    assert record["record_id"] == response.json()["record_id"]
    assert record["device_id"] == device_id
    assert record["target"] == item
    assert record["kind"] == "decision"
    assert record["decision"] == {
        "verdict": "keep",
        "favorite": True,
        "tags": ["needs_fix", "hands"],
    }
    assert items(rig)[0]["state"] == "pending"
    rig.acknowledge(record["record_id"])
    [shown] = items(rig)
    assert shown["state"] == "applied"
    assert shown["decision"]["verdict"] == "keep"


@pytest.mark.parametrize(
    ("outcome", "fields", "state", "reason"),
    [
        ("refused", {"reason_code": "archive_failed"}, "refused", "archive_failed"),
        ("duplicate", {}, "applied", None),
    ],
)
def test_the_phone_sees_what_the_pc_answered(rig, outcome, fields, state, reason) -> None:
    item = rig.publish()
    rig.pair()
    record_id = rig.decide(item, "delete").json()["record_id"]

    rig.acknowledge(record_id, outcome, **fields)

    [shown] = items(rig)
    assert (shown["state"], shown["reason_code"]) == (state, reason)


def test_resending_a_decision_does_not_create_a_second_record(rig) -> None:
    item = rig.publish()
    rig.pair()
    key = str(uuid.uuid4())

    first = rig.decide(item, key=key)
    again = rig.decide(item, key=key)
    different = rig.decide(item, "delete", key=key)

    assert first.json()["record_id"] == again.json()["record_id"]
    assert different.status_code == 409
    assert different.json() == {"error": "idempotency_conflict"}
    assert len(rig.outbox()["records"]) == 1


def test_changing_your_mind_before_the_pc_looks_replaces_the_record(rig) -> None:
    item = rig.publish()
    rig.pair()
    rig.decide(item, "delete")

    second = rig.decide(item, "keep").json()["record_id"]

    assert [r["record_id"] for r in rig.outbox()["records"]] == [second]


def test_changing_your_mind_after_the_pc_looked_adds_a_record_in_order(rig) -> None:
    item = rig.publish()
    rig.pair()
    first = rig.decide(item, "delete").json()["record_id"]
    rig.outbox()

    second = rig.decide(item, "keep").json()["record_id"]

    assert [r["record_id"] for r in rig.outbox()["records"]] == [first, second]
    assert items(rig)[0]["decision"]["verdict"] == "keep"


@pytest.mark.parametrize(
    "change",
    [
        {"verdict": "archive"},
        {"verdict": "delete", "favorite": True},
        {"verdict": "delete", "tags": ["needs_fix"]},
        {"tags": ["stars"]},
        {"tags": ["face", "face"]},
        {"favorite": "yes"},
        {"idempotency_key": "short"},
        {"path": "C:/output/a.png"},
        {"library_id": "../../etc/passwd"},
    ],
)
def test_a_decision_the_contract_does_not_allow_is_refused(rig, change) -> None:
    item = rig.publish()
    rig.pair()
    body = {**item, "verdict": "keep", "favorite": False, "tags": [], "idempotency_key": "k" * 20}

    response = rig.phone.post("/api/decisions", json={**body, **change})

    assert response.status_code == 422, response.text
    assert rig.outbox()["records"] == []


def test_a_decision_on_an_unknown_item_is_refused(rig) -> None:
    rig.pair()

    response = rig.decide({"library_id": "lib-unknown1", "sha256": "a" * 64})

    assert response.status_code == 404
    assert response.json() == {"error": "unknown_item"}


@pytest.mark.parametrize("path", ["/api/runs", "/api/session"])
def test_json_apis_require_the_custom_header(rig, path) -> None:
    rig.pair()
    del rig.phone.headers["X-Review-Gateway"]

    response = rig.phone.get(path)

    assert response.status_code == 403
    assert response.json() == {"error": "missing_header"}


@pytest.mark.parametrize("path", ["/api/pair", "/api/decisions"])
def test_a_cross_site_form_post_cannot_reach_the_api(rig, path) -> None:
    del rig.phone.headers["X-Review-Gateway"]

    response = rig.phone.post(
        path, content=b'{"code":"K7QF2M9D"}', headers={"Content-Type": "text/plain"}
    )

    assert response.status_code == 403


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/static/app.js",
        "/static/queued.js",
        "/static/app.css",
        "/api/session",
        "/nowhere",
        "/sync/v1/health",
    ],
)
def test_every_phone_response_carries_the_security_headers(rig, path) -> None:
    headers = rig.phone.get(path).headers

    policy = headers["content-security-policy"]
    for directive in CSP_DIRECTIVES:
        assert directive in policy
    assert "unsafe" not in policy and "http" not in policy
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["referrer-policy"] == "no-referrer"


def test_media_is_served_with_its_declared_type_and_cache_rules(rig) -> None:
    item = rig.publish()
    rig.pair()

    thumb = rig.phone.get(media(item, "thumb"))
    original = rig.phone.get(media(item, "original"))

    assert thumb.content == b"thumb-one"
    assert thumb.headers["content-type"] == "image/jpeg"
    assert thumb.headers["cache-control"] == "private, max-age=604800, immutable"
    rendition = rig.phone.get(f"/media/{item['library_id']}/{item['sha256']}/preview")
    assert rendition.headers["cache-control"] == "private, max-age=604800, immutable"
    assert original.headers["content-type"] == "image/png"
    assert original.headers["cache-control"] == "private, no-store"
    assert original.headers["content-security-policy"]


def test_video_supports_range_requests_for_playback(rig) -> None:
    item = rig.publish("clip", kind="video")
    rig.pair()

    response = rig.phone.get(media(item, "video"), headers={"Range": "bytes=10-19"})

    assert response.status_code == 206
    assert response.content == bytes(range(10, 20))
    assert response.headers["content-type"] == "video/mp4"


@pytest.mark.parametrize(
    "path",
    [
        "/media/lib-one_____/{sha}/video",  # an image has no mobile video
        "/media/lib-one_____/{sha}/sidecar",
        "/media/lib-one_____/{other}/thumb",
        "/media/..%2F..%2F/{sha}/thumb",
        "/media/{sha}",
        "/static/../app.py",
        "/static/%2e%2e/config.py",
        "/static/",
    ],
)
def test_nothing_else_is_downloadable(rig, path) -> None:
    item = rig.publish()
    rig.pair()

    assert rig.phone.get(path.format(sha=item["sha256"], other="a" * 64)).status_code == 404


class _Markup(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.problems: list[str] = []
        self.sources: list[str] = []
        self._inline: str | None = None

    def handle_starttag(self, tag, attrs):
        names = dict(attrs)
        self.problems += [
            f"{tag} {name}" for name in names if name.startswith("on") or name == "style"
        ]
        self.sources += [names[a] for a in ("src", "href") if names.get(a)]
        if tag == "style" or (tag == "script" and not names.get("src")):
            self._inline = tag
            self.problems.append(f"inline {tag}")


def test_the_page_has_no_inline_script_or_style_and_loads_only_bundled_files(rig) -> None:
    page = _Markup()
    page.feed(rig.phone.get("/").text)

    assert page.problems == []
    assert page.sources
    for source in page.sources:
        assert source.startswith(("/static/", "#")), source
        if source.startswith("/static/"):
            assert rig.phone.get(source).status_code == 200


def test_the_script_renders_metadata_only_as_text_and_calls_no_other_host() -> None:
    script = "".join(
        (STATIC / name).read_text(encoding="utf-8")
        for name in ("app.js", "moreinfo.js", "rating.js", "queued.js")
    )

    for forbidden in (
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.write",
        "eval(",
        "Function(",
    ):
        assert forbidden not in script, forbidden
    for name in ("app.js", "moreinfo.js", "queued.js", "app.css", "index.html"):
        text = (STATIC / name).read_text(encoding="utf-8")
        assert not re.search(r"(https?:)?//[a-z0-9-]+\.[a-z]", text, re.IGNORECASE), name


def test_the_script_sends_the_header_the_api_requires() -> None:
    assert '"X-Review-Gateway": "1"' in (STATIC / "app.js").read_text(encoding="utf-8")


def test_resending_a_withdrawn_decision_reports_the_decision_that_replaced_it(rig) -> None:
    item = rig.publish()
    rig.pair()
    key = str(uuid.uuid4())
    rig.decide(item, "delete", key=key)
    latest = rig.decide(item, "keep").json()["record_id"]
    rig.acknowledge(latest, "refused", reason_code="unknown_item")

    resent = rig.decide(item, "delete", key=key)

    assert resent.json()["state"] == "refused"  # never "applied" for a choice nobody applied
