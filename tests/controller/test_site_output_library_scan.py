from __future__ import annotations

from threading import Event

import pytest

from src.app import site_output_library as module
from src.app.site_media_files import SiteOutputError
from src.app.site_output_catalog import SiteOutputCatalog
from src.app.site_output_routes import OUTPUT_LIBRARY, OUTPUT_STATUS, post, read
from tests.controller.test_site_output_library import _library, _png, _search


def test_inventory_is_browsable_before_metadata_and_prioritizes_pipeline(tmp_path, monkeypatch):
    for source in ("Learning", "Reprocess", "Pipeline", "movie_clips", "SVD"):
        folder = tmp_path / source
        folder.mkdir()
        _png(folder / "image.png", metadata=True)
        (folder / "clip.mp4").write_bytes(b"video fixture")
    catalog = SiteOutputCatalog(tmp_path)
    library = catalog.library
    enrich = library._metadata
    monkeypatch.setattr(
        library, "_metadata", lambda *_: pytest.fail("Inventory read image metadata")
    )
    inventory, limited, error = library._inventory(Event())
    assert not limited and not error
    library._publish(inventory, scanning=True, limited=False, error=False)
    library._started = True
    images = _library(catalog, "search", **_query())
    assert images["scanning"]
    assert [item["source"] for item in images["items"]] == [
        "pipeline",
        "learning",
        "reprocess",
        "movie_clips",
        "svd",
    ]
    videos = _library(catalog, "search", **_query(kind="video"))
    assert [item["source"] for item in videos["items"]] == [
        "movie_clips",
        "svd",
        "reprocess",
        "pipeline",
        "learning",
    ]
    first = images["items"][0]["id"]
    assert _library(catalog, "thumbnails", ids=[first])["thumbnails"][first]["image"]
    monkeypatch.setattr(library, "_metadata", enrich)
    inspected = _library(catalog, "inspect", id=first)
    assert inspected["item"]["width"] == 40
    assert inspected["item"]["height"] == 30
    assert "distant forest" in inspected["prompt"]
    assert read(catalog, OUTPUT_STATUS)["library_sources"] is True


def _query(**overrides):
    return {
        "field": "all",
        "kind": "image",
        "query": "",
        "offset": 0,
        "revision": "",
        "refresh": False,
        **overrides,
    }


def test_scan_publishes_first_page_before_inventory_finishes(tmp_path, monkeypatch):
    folder = tmp_path / "Pipeline"
    folder.mkdir()
    for index in range(30):
        _png(folder / f"{index:02d}.png")
    library = SiteOutputCatalog(tmp_path).library
    published = []
    original = library._publish

    def capture(items, **options):
        original(items, **options)
        published.append(library.index)

    monkeypatch.setattr(library, "_publish", capture)
    library._scan(Event())
    assert len(published[0].items) == 24
    assert published[0].scanning
    assert all(item.width == 0 for item in published[0].items.values())
    assert len(library.index.items) == 30
    assert not library.index.scanning
    assert all(item.width == 40 for item in library.index.items.values())
    assert published[1].revision == library.index.revision


def test_folder_filter_is_optional_and_cannot_select_outside_output(tmp_path):
    for source in ("Pipeline", "Learning", "Reprocess", "movie_clips", "SVD", "Other"):
        folder = tmp_path / source
        folder.mkdir()
        _png(folder / "fixture.png")
    catalog = SiteOutputCatalog(tmp_path)
    assert _search(catalog)["total"] == 6
    for source in ("pipeline", "learning", "reprocess", "movie_clips", "svd", "other"):
        page = _search(catalog, source=source)
        assert page["total"] == 1
        assert page["items"][0]["source"] == source
    for invalid in ("../private", "/etc", ["pipeline"]):
        with pytest.raises(SiteOutputError, match="invalid_library_request"):
            _library(catalog, "search", **_query(source=invalid))
    with pytest.raises(SiteOutputError, match="invalid_library_request"):
        post(
            catalog,
            OUTPUT_LIBRARY,
            {
                "scope": catalog.scope,
                "action": "albums",
                "source": "pipeline",
            },
        )


def test_metadata_budget_keeps_inventory_and_videos_available(tmp_path, monkeypatch):
    for index in range(3):
        _png(tmp_path / f"{index}.png", metadata=True)
    (tmp_path / "last.mp4").write_bytes(b"video fixture")
    monkeypatch.setattr(module, "_METADATA_BUDGET", 1)
    catalog = SiteOutputCatalog(tmp_path)
    page = _search(catalog)
    assert page["total"] == 3
    assert not page["limited"]
    assert page["metadata_limited"]
    assert _search(catalog, kind="video")["total"] == 1
    assert _library(catalog, "inspect", id=page["items"][0]["id"])["item"]["width"] == 40


def test_inventory_covers_outputs_larger_than_the_old_limit(tmp_path, monkeypatch):
    folder = tmp_path / "Pipeline"
    folder.mkdir()
    fixture = folder / "fixture.png"
    _png(fixture)
    info = fixture.lstat()
    monkeypatch.setattr(
        module.os,
        "walk",
        lambda *_args, **_kwargs: iter(
            [
                (str(folder), [], [f"{index}.png" for index in range(25_001)]),
            ]
        ),
    )
    monkeypatch.setattr(module.Path, "lstat", lambda *_args, **_kwargs: info)
    # Directory containment is tested separately with real paths and junctions.
    monkeypatch.setattr(module, "inside", lambda _root, path: path)
    inventory, limited, error = SiteOutputCatalog(tmp_path).library._inventory(Event())
    assert len(inventory) == 25_001
    assert not limited and not error
    assert module._SEARCH_LIMIT >= 60_000


def test_unexpected_scan_failure_clears_scanning_and_allows_retry(tmp_path, monkeypatch, caplog):
    library = SiteOutputCatalog(tmp_path).library
    completed = Event()
    from src.utils.thread_registry import get_thread_registry

    registry = get_thread_registry()
    spawn = registry.spawn

    def record_spawn(*, target, **options):
        def run():
            try:
                target()
            finally:
                completed.set()

        return spawn(target=run, **options)

    def broken(_cancel):
        raise ValueError("Unreadable metadata fixture")

    monkeypatch.setattr(registry, "spawn", record_spawn)
    monkeypatch.setattr(library, "_scan", broken)
    library.start()
    assert completed.wait(3)
    assert not library.index.scanning
    assert library.index.error
    assert "Output library indexing failed" in caplog.text

    def recover(_cancel):
        library._publish({}, scanning=False, limited=False, error=False)

    monkeypatch.setattr(library, "_scan", recover)
    completed.clear()
    library.start(refresh=True)
    assert completed.wait(3)
    assert not library.index.scanning
    assert not library.index.error


def test_spawn_failure_clears_scanning(tmp_path, monkeypatch):
    from src.utils.thread_registry import get_thread_registry

    def unavailable(**_options):
        raise RuntimeError("Thread startup fixture")

    monkeypatch.setattr(get_thread_registry(), "spawn", unavailable)
    library = SiteOutputCatalog(tmp_path).library
    library.start()
    assert not library.index.scanning
    assert library.index.error


def test_completed_worker_does_not_clear_a_new_refresh(tmp_path, monkeypatch):
    library = SiteOutputCatalog(tmp_path).library
    first_published, second_started = Event(), Event()
    release_first, release_second = Event(), Event()
    first_finished = Event()
    workers = []
    from src.utils.thread_registry import get_thread_registry

    registry = get_thread_registry()
    spawn = registry.spawn

    def record_spawn(*, target, **options):
        def run():
            target()
            if len(workers) == 2:
                first_finished.set()

        worker = spawn(target=run, **options)
        workers.append(worker)
        return worker

    def controlled_scan(_cancel):
        if not first_published.is_set():
            library._publish({}, scanning=False, limited=False, error=False)
            first_published.set()
            assert release_first.wait(3)
        else:
            second_started.set()
            assert release_second.wait(3)
            library._publish({}, scanning=False, limited=False, error=False)

    monkeypatch.setattr(registry, "spawn", record_spawn)
    monkeypatch.setattr(library, "_scan", controlled_scan)
    try:
        library.start()
        assert first_published.wait(3)
        library.start(refresh=True)
        assert second_started.wait(3)
        release_first.set()
        assert first_finished.wait(3)
        assert library.index.scanning
        assert not library.index.error
    finally:
        release_first.set()
        release_second.set()
        for worker in workers:
            worker.join(3)
    assert not library.index.scanning
