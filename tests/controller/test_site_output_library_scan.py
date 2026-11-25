from __future__ import annotations

import base64
import hashlib
import io
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from time import monotonic, sleep

import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from src.app import (
    site_library_reconcile,
    site_library_video,
    site_output_library,
    site_video_playback,
)
from src.app.site_library_reconcile import Reconciliation
from src.app.site_media_files import SiteOutputError
from src.app.site_output_catalog import SiteOutputCatalog
from src.app.site_output_routes import OUTPUT_LIBRARY, OUTPUT_STATUS, read
from src.app.site_phone_connector import _desktop_call
from src.utils.image_metadata import ImageMetadataContractV26
from tests.controller.test_site_output_library import _library, _png


@pytest.fixture(autouse=True)
def quick_reconciliation(monkeypatch):
    monkeypatch.setattr(site_output_library, "_POLL_SECONDS", 0.05)
    monkeypatch.setattr(site_library_reconcile, "_SETTLE_NS", 0)


def browse(catalog, **query):
    return _library(catalog, "query_v2", **query)


def wait_for(action, predicate, timeout=4):
    end = monotonic() + timeout
    while True:
        result = action()
        if predicate(result):
            return result
        if monotonic() >= end:
            pytest.fail(f"Condition did not settle: {result!r}")
        sleep(0.02)


def complete(catalog):
    return wait_for(
        lambda: browse(catalog), lambda page: page["state"] == "complete" and not page["partial"]
    )


def test_cold_snapshot_progress_and_single_worker_with_warm_reopen(tmp_path, monkeypatch):
    for source in ("Learning", "Pipeline", "movie_clips"):
        folder = tmp_path / source
        folder.mkdir()
        _png(folder / "image.png", metadata=True)
    allow_metadata = Event()
    first = SiteOutputCatalog(tmp_path, preview_idle=lambda: False)
    second = SiteOutputCatalog(tmp_path, preview_idle=lambda: False)
    original = site_output_library.OutputLibrary._metadata

    def held(self, *args, **kw):
        assert allow_metadata.wait(3)
        return original(self, *args, **kw)

    monkeypatch.setattr(site_output_library.OutputLibrary, "_metadata", held)
    try:
        partial = wait_for(lambda: browse(first), lambda page: page["total"] == 3)
        assert partial["partial"] and partial["scanning"]
        other = browse(second)
        assert first.library.store is second.library.store
        assert first.library.store.thread is not None
        assert other["items"][0]["id"] != partial["items"][0]["id"]
    finally:
        allow_metadata.set()
    complete(second)
    store = first.library.store
    worker = store.thread
    first.revoke()
    second.revoke()
    assert worker is not None
    worker.join(3)
    assert not worker.is_alive()
    original_inventory = Reconciliation.inventory
    release_scan = Event()

    def held_inventory(self, *args, **kw):
        assert release_scan.wait(3)
        return original_inventory(self, *args, **kw)

    monkeypatch.setattr(Reconciliation, "inventory", held_inventory)
    try:
        rebound = SiteOutputCatalog(tmp_path, preview_idle=lambda: False)
        warm = browse(rebound)
        assert warm["total"] == 3
        assert warm["items"][0]["width"] == 40
    finally:
        release_scan.set()
    assert read(rebound, OUTPUT_STATUS)["library_index_v2"]
    rebound.revoke()


def test_combined_filters_global_sorts_facets_and_query_bound_pages(tmp_path, monkeypatch):
    monkeypatch.setattr(
        site_library_video, "probe", lambda *_: {"width": 1536, "height": 2048, "fps": 12.0}
    )
    dirs = [tmp_path / name for name in ("Pipeline", "Learning", "movie_clips")]
    for folder in dirs:
        folder.mkdir()
    for i in range(30):
        path = dirs[i % 2] / "same.png" if i < 2 else dirs[i % 2] / f"{i:02}.png"
        Image.new("RGB", (768, 1024) if i == 0 else (16, 12), "red").save(path)
        os.utime(path, (1_700_000_000, 1_700_000_000 + i))
    movie = dirs[2] / "clip.mp4"
    movie.write_bytes(b"fixture media stub")
    os.utime(movie, (1_700_000_000, 1_700_010_000))
    manifest = dirs[0] / "manifests"
    manifest.mkdir()
    source = dirs[0] / "same.png"
    native_fields = PngInfo()
    native_fields.add_itxt(ImageMetadataContractV26.KEY_SCHEMA, ImageMetadataContractV26.SCHEMA)
    native_fields.add_itxt(ImageMetadataContractV26.KEY_CREATED_UTC, "2025-01-01T02:00:00Z")
    Image.new("RGB", (768, 1024), "red").save(source, pnginfo=native_fields)
    os.utime(source, (1_700_000_000, 1_700_000_000))
    (manifest / "same.json").write_text(
        json.dumps(
            {
                "generation": {"prompt": "forest", "model": "Model A", "seed": 0},
                "artifact": {
                    "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    "artifact_id": "abc",
                },
                "timestamp": "20250101_020000",
                "model_family": "sdxl",
                "workflow_id": "workflow-a",
            }
        ),
        encoding="utf-8",
    )
    catalog = SiteOutputCatalog(tmp_path)
    page = complete(catalog)
    assert page["total"] == 31 and len(page["items"]) == 24
    assert [item["name"] for item in page["items"][:2]] == ["same.png", "clip.mp4"]
    assert page["items"][0]["timestamp_basis"] == "recorded"
    assert page["items"][0]["provenance"] == "manifest"
    assert page["items"][1]["fps"] == 12.0
    assert browse(catalog, sort="oldest")["items"][0]["source"] == "learning"
    assert browse(catalog, sort="filename_asc")["items"][0]["name"] == "02.png"
    desc = browse(catalog, sort="filename_desc")
    ties = desc["items"][:2]
    assert [item["name"] for item in ties] == ["same.png", "same.png"]
    assert len({item["id"] for item in ties}) == 2
    assert [item["id"] for item in browse(catalog, sort="filename_desc")["items"][:2]] == [
        item["id"] for item in ties
    ]
    second = browse(catalog, offset=24, revision=page["revision"])
    assert {x["id"] for x in page["items"]}.isdisjoint(x["id"] for x in second["items"])
    assert len(second["items"]) == 7
    with pytest.raises(SiteOutputError, match="stale_library_page"):
        browse(catalog, offset=24, revision=page["revision"], sort="oldest")
    assert browse(catalog, filters={"aspect_ratio": "6:8"})["total"] == 2
    assert browse(catalog, filters={"dimensions": [1024, 768]})["total"] == 0
    assert (
        browse(
            catalog,
            filters={
                "dimensions": [768, 1024],
                "orientation": "portrait",
                "source": "pipeline",
                "model_family": "sdxl",
                "model": "Model A",
                "workflow": "workflow-a",
                "after": "2025-01-01T03:00:00+01:00",
                "before": "2025-01-01T02:00:01Z",
            },
            field="model",
            query="model a",
        )["total"]
        == 1
    )
    assert browse(catalog, filters={"before": "2025-01-01T02:00:00Z"})["total"] == 30
    assert browse(catalog, filters={"model": None})["total"] == 30
    assert browse(catalog, field="seed", query="000")["total"] == 1
    facets = _library(catalog, "facets_v2", filters={"model_family": "sdxl"})["facets"]
    assert facets["dimensions"]["values"] == [{"value": [768, 1024], "count": 1}]
    for filter in (
        {"source": "../secret"},
        {"after": "2025-01-01T02:00:00"},
        {"aspect_ratio": "0:3"},
        {"dimensions": [True, 8]},
        {"model_family": {}},
        {"surprise": 2},
    ):
        with pytest.raises(SiteOutputError, match="invalid_library_request"):
            browse(catalog, filters=filter)
    with pytest.raises(SiteOutputError, match="invalid_library_request"):
        _library(catalog, "thumbnails", ids=[], filters={})
    assert (
        _desktop_call(
            catalog, "POST", OUTPUT_LIBRARY, {"scope": catalog.scope, "action": "query_v2"}, False
        ).status
        == 200
    )


def test_external_change_rename_removal_and_sidecar_revision(tmp_path):
    image = tmp_path / "old.png"
    _png(image)
    catalog = SiteOutputCatalog(tmp_path)
    first = complete(catalog)
    old_id = first["items"][0]["id"]
    sidecars = tmp_path / "manifests"
    sidecars.mkdir()
    (sidecars / "old.json").write_text(
        json.dumps(
            {
                "artifact_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                "generation": {"prompt": "search me"},
            }
        ),
        encoding="utf-8",
    )
    wait_for(
        lambda: browse(catalog, field="prompt", query="search me"), lambda page: page["total"] == 1
    )
    image.rename(tmp_path / "renamed.png")
    renamed = wait_for(
        lambda: browse(catalog),
        lambda page: page["total"] == 1
        and len(page["items"]) == 1
        and page["items"][0]["name"] == "renamed.png",
    )
    assert renamed["revision"] != first["revision"]
    assert not _library(catalog, "previews_v2", ids=[old_id])["previews"]
    (tmp_path / "renamed.png").unlink()
    wait_for(lambda: browse(catalog), lambda page: page["total"] == 0)
    _png(tmp_path / "do-not-show.tmp.png")
    _png(tmp_path / "added.png")
    added = wait_for(lambda: browse(catalog), lambda page: bool(page["items"]))
    assert [record["name"] for record in added["items"]] == ["added.png"]


def test_partial_or_cancelled_scan_does_not_prune_existing_records(tmp_path, monkeypatch):
    output = tmp_path / "output"
    output.mkdir()
    path = output / "kept.png"
    _png(path)
    catalog = SiteOutputCatalog(output)
    complete(catalog)
    worker = catalog.library.store.thread
    catalog.revoke()
    assert worker is not None
    worker.join(3)
    scan = Reconciliation(catalog.library.store)
    cancelled = Event()
    cancelled.set()
    assert (
        scan.inventory(cancelled, lambda: None, catalog.library._basic, full=True) == "incomplete"
    )
    monkeypatch.setattr(site_library_reconcile, "_ENTRY_LIMIT", 0)
    assert scan.inventory(Event(), lambda: None, catalog.library._basic, full=True) == "incomplete"
    with catalog.library.store.connection() as db:
        assert db.execute("SELECT count(*) FROM media").fetchone()[0] == 1


@pytest.mark.parametrize("corrupt", (False, True))
def test_rebuilds_incompatible_or_corrupt_derived_index(tmp_path, corrupt):
    _png(tmp_path / "kept.png")
    catalog = SiteOutputCatalog(tmp_path)
    complete(catalog)
    store = catalog.library.store
    worker = store.thread
    catalog.revoke()
    assert worker is not None
    worker.join(3)
    if corrupt:
        store.database.write_bytes(b"truncated fixture")
    else:
        with store.connection() as db:
            db.execute("PRAGMA user_version=999")
    del worker, catalog, store
    rebound = SiteOutputCatalog(tmp_path)
    assert complete(rebound)["total"] == 1
    assert (tmp_path / "kept.png").is_file()


def test_preview_cache_reuse_replacement_corruption_and_permission(tmp_path, monkeypatch):
    image = tmp_path / "fixture.png"
    Image.new("RGB", (640, 480), "blue").save(image)
    catalog = SiteOutputCatalog(tmp_path, preview_idle=lambda: False)
    item = complete(catalog)["items"][0]
    first_id = item["id"]
    openings, encodes = [], []
    open_scoped = site_output_library.open_scoped
    encode = site_output_library.OutputLibrary._encode_preview

    def observed_open(*args):
        openings.append(args[-1])
        return open_scoped(*args)

    def observed_encode(*args, **kwargs):
        encodes.append(1)
        return encode(*args, **kwargs)

    monkeypatch.setattr(site_output_library, "open_scoped", observed_open)
    monkeypatch.setattr(
        site_output_library.OutputLibrary, "_encode_preview", staticmethod(observed_encode)
    )

    def preview():
        return _library(catalog, "previews_v2", ids=[first_id])["previews"][first_id]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: preview(), range(2)))
    assert results[0] == results[1] == preview()
    assert len(openings) == len(encodes) == 1
    data = results[0]
    assert data["mime"] in {"image/webp", "image/jpeg"}
    with Image.open(io.BytesIO(base64.b64decode(data["image"]))) as small:
        assert small.size == (320, 240)
    with catalog.library.store.previews.connection() as db:
        db.execute("UPDATE preview SET data = ?", (b"damaged",))
    assert preview() == data
    assert len(openings) == len(encodes) == 2
    rebound = SiteOutputCatalog(tmp_path, preview_idle=lambda: False)
    rebound_id = browse(rebound)["items"][0]["id"]
    assert not _library(rebound, "previews_v2", ids=[first_id, "../fixture.png"])["previews"]
    assert _library(rebound, "previews_v2", ids=[rebound_id])["previews"][rebound_id] == data
    assert len(encodes) == 2
    replacement = tmp_path / "replacement.png"
    Image.new("RGB", (640, 480), "green").save(replacement)
    replacement.replace(image)
    assert not _library(catalog, "previews_v2", ids=[first_id])["previews"]
    current = complete_after_refresh(catalog)["items"][0]["id"]
    assert current != first_id
    assert (
        _library(catalog, "previews_v2", ids=[current])["previews"][current]["image"]
        != data["image"]
    )
    rebound.revoke()
    with pytest.raises(SiteOutputError, match="output_folder_not_shared"):
        _library(rebound, "previews_v2", ids=[rebound_id])


def complete_after_refresh(catalog):
    browse(catalog, refresh=True)
    return complete(catalog)


def test_video_foreground_poster_and_placeholder_with_global_lru(tmp_path, monkeypatch):
    monkeypatch.setenv("STABLENEW_SITE_LIBRARY_CACHE_BYTES", "1300")
    root, other = tmp_path / "output", tmp_path / "different"
    root.mkdir()
    other.mkdir()
    (root / "movie.mp4").write_bytes(b"movie fixture")
    (other / "bad.mp4").write_bytes(b"bad fixture")
    png = io.BytesIO()
    Image.new("RGB", (16, 12), "red").save(png, "JPEG")
    calls = []
    monkeypatch.setattr(site_library_video, "probe", lambda *_: {"width": 16, "height": 12})
    running = Event()

    def make_poster(stream, *_args):
        calls.append(Path(stream.name))
        assert running.wait(3)
        return png.getvalue() if b"movie" in stream.read() else b""

    monkeypatch.setattr(site_library_video, "poster", make_poster)
    catalog = SiteOutputCatalog(root, preview_idle=lambda: False)
    rebound = SiteOutputCatalog(other, preview_idle=lambda: False)

    def video_id(scope):
        return wait_for(lambda: browse(scope, kind="video"), lambda page: page["total"] == 1)[
            "items"
        ][0]["id"]

    def preview(scope, key):
        return _library(scope, "previews_v2", ids=[key])["previews"].get(key, {})

    try:
        first, second = video_id(catalog), video_id(rebound)
        assert preview(catalog, first)["state"] == "pending"
        assert preview(rebound, first) == {}
    finally:
        running.set()
    assert (
        wait_for(lambda: preview(catalog, first), lambda value: value.get("state") == "ready")[
            "mime"
        ]
        == "image/jpeg"
    )
    assert (
        wait_for(
            lambda: preview(rebound, second), lambda value: value.get("state") == "placeholder"
        )["kind"]
        == "video"
    )
    assert len(calls) == 2
    assert catalog.library.store.previews is rebound.library.store.previews
    with catalog.library.store.previews.connection() as db:
        assert db.execute("SELECT size FROM preview_size").fetchone()[0] <= 1300
    assert (root / "movie.mp4").read_bytes() == b"movie fixture"
    assert (other / "bad.mp4").read_bytes() == b"bad fixture"


def test_cache_declines_an_unowned_directory(tmp_path, monkeypatch):
    directory = tmp_path / "shared-data"
    directory.mkdir()
    foreign = directory / "previews.sqlite3"
    foreign.write_bytes(b"unrelated local data")
    output = tmp_path / "output"
    output.mkdir()
    monkeypatch.setenv("STABLENEW_SITE_LIBRARY_CACHE_DIR", str(directory))
    catalog = SiteOutputCatalog(output)
    with pytest.raises(SiteOutputError, match="library_cache_unavailable"):
        catalog.library.store.initialize()
    assert foreign.read_bytes() == b"unrelated local data"
    assert list(directory.iterdir()) == [foreign]


def test_oversized_video_is_rejected_before_poster_lookup(tmp_path, monkeypatch):
    (tmp_path / "large.mp4").write_bytes(b"simulated oversized file")
    assert site_library_video.VIDEO_LIMIT == site_video_playback.VIDEO_LIMIT
    monkeypatch.setattr(site_library_video, "VIDEO_LIMIT", 4)
    monkeypatch.setattr(site_video_playback, "VIDEO_LIMIT", 4)
    monkeypatch.setattr(site_library_video, "poster", lambda *_: pytest.fail("oversized poster"))
    monkeypatch.setattr(site_library_video, "probe", lambda *_: pytest.fail("oversized probe"))
    catalog = SiteOutputCatalog(tmp_path)
    identifier = complete(catalog)["items"][0]["id"]
    preview = _library(catalog, "previews_v2", ids=[identifier])["previews"][identifier]
    assert preview == {"kind": "video", "state": "placeholder"}
    with pytest.raises(SiteOutputError, match="media_too_large"):
        catalog.open_video(identifier, library=True)


def test_speculative_preparation_prioritizes_recency_and_yields_to_generation(
    tmp_path, monkeypatch
):
    idle = Event()
    names = []
    for index in range(4):
        file = tmp_path / f"{index}.png"
        _png(file)
        os.utime(file, (1_700_000_000, 1_700_000_000 + index))

    def warm(_library, item, *, warm, cancel):
        assert warm and not cancel.is_set()
        names.append(item.path)
        return site_output_library.Preview("", b"")

    monkeypatch.setattr(site_output_library, "_WARM_COUNT", 2)
    monkeypatch.setattr(site_output_library.OutputLibrary, "_preview", warm)
    catalog = SiteOutputCatalog(tmp_path, preview_idle=idle.is_set)
    complete(catalog)
    assert not names
    idle.set()
    wait_for(lambda: list(names), lambda current: len(current) == 2)
    catalog.revoke()
    assert names == ["3.png", "2.png"]


def test_spawn_failure_keeps_an_explicit_error(tmp_path, monkeypatch):
    from src.utils.thread_registry import get_thread_registry

    def unavailable(*_args, **_options):
        raise RuntimeError("Thread startup fixture")

    monkeypatch.setattr(type(get_thread_registry()), "spawn", unavailable)
    catalog = SiteOutputCatalog(tmp_path)
    page = browse(catalog)
    assert page["partial"] and page["scan_error"] and page["state"] == "error"
