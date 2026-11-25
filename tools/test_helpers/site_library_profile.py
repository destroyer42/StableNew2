"""Compare native Output Library baselines using temporary synthetic files.

Run this script from either checkout directory with its Python environment.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
import time
import tracemalloc
from contextlib import contextmanager
from pathlib import Path
from threading import Event
from unittest.mock import patch

from PIL import Image
from PIL.PngImagePlugin import PngInfo

SOURCES = ("Pipeline", "Learning", "movie_clips", "SVD", "Reprocess", "Other")
SEARCH = {"field": "all", "kind": "image", "query": "", "offset": 0, "refresh": False}


def timing(action, repeat=20):
    durations = []
    for _ in range(repeat):
        start = time.perf_counter()
        result = action()
        durations.append(1000 * (time.perf_counter() - start))
    durations.sort()
    return {
        "median_ms": round(statistics.median(durations), 2),
        "p95_ms": round(durations[max(0, (len(durations) * 95 + 99) // 100 - 1)], 2),
        "json_bytes": len(json.dumps(result, default=str)),
    }


def fixture(root, count, video):
    from src.utils.image_metadata import build_contract_kv

    variants = []
    for i, size in enumerate(((40, 30), (30, 40), (64, 64))):
        path = root / f".sample-{i}.png"
        info = PngInfo()
        if i != 2:
            kv = build_contract_kv(
                {
                    "generation": {"prompt": "forest", "model": f"Fixture {i}", "seed": i},
                    "model_family": ("sdxl", "sd15")[i],
                },
                job_id="fixture",
                run_id="fixture",
                stage="txt2img",
                created_utc="2023-11-14T22:13:20Z",
            )
            for key, value in kv.items():
                info.add_itxt(key, value)
        Image.new("RGB", size, (i * 70, 10, 100)).save(path, pnginfo=info)
        variants.append(path.read_bytes())
    for j in range(60):
        folder = root / SOURCES[j % 6] / str(j // 6)
        folder.mkdir(parents=True)
        for i in range(j, count, 60):
            is_video = (i + j // 6) % 5 == 0
            path = folder / f"{i // 60:05d}{'.mp4' if is_video else '.png'}"
            raw = b""
            if i < 120:
                raw = video if is_video else variants[(i // 6) % 3]
            path.write_bytes(raw)
            stamp = 1_700_000_000 + (i * 2039) % count
            os.utime(path, (stamp, stamp))
    return variants


@contextmanager
def measure_media(module):
    counters = {"opens": 0, "full_reads": 0, "bytes": 0, "pillow_open": 0, "encode": 0}
    original_open, original_image, original_save = module.open_scoped, Image.open, Image.Image.save

    class Measured:
        def __init__(self, stream):
            self.stream = stream

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def read(self, size=-1):
            data = self.stream.read(size)
            counters["bytes"] += len(data)
            if data and self.stream.tell() == len(data) == os.fstat(self.stream.fileno()).st_size:
                counters["full_reads"] += 1
            return data

    @contextmanager
    def opened(*args):
        with original_open(*args) as stream:
            counters["opens"] += 1
            yield Measured(stream)

    def image(*args, **kwargs):
        counters["pillow_open"] += 1
        return original_image(*args, **kwargs)

    def encode(*args, **kwargs):
        counters["encode"] += 1
        return original_save(*args, **kwargs)

    with (
        patch.object(module, "open_scoped", opened),
        patch.object(Image, "open", image),
        patch.object(Image.Image, "save", encode),
    ):
        yield counters


def thumbnail_probe(library, ids, counters, result):
    counters.update(dict.fromkeys(counters, 0))
    result["first_thumbnails"] = timing(lambda: library.thumbnails(ids), repeat=1)
    result["first_thumb_work"] = counters.copy()
    counters.update(dict.fromkeys(counters, 0))
    result["repeat_thumbnails"] = timing(lambda: library.thumbnails(ids))
    result["repeat_thumb_work"] = counters.copy()


def baseline(root, *_):
    from src.app import site_output_library as module

    library = module.OutputLibrary(root, "fixture", lambda: None)
    metrics = {}
    publish, inventory = library._publish, library._inventory

    def observed_publish(*args, **kwargs):
        publish(*args, **kwargs)
        metrics.setdefault("first_page_ms", round((time.perf_counter() - started) * 1000, 2))

    def observed_inventory(*args, **kwargs):
        result = inventory(*args, **kwargs)
        metrics.setdefault("inventory_ms", round((time.perf_counter() - started) * 1000, 2))
        return result

    library._publish, library._inventory = observed_publish, observed_inventory
    with measure_media(module) as counters:
        started = time.perf_counter()
        library._scan(Event())
        metrics["complete_ms"] = round((time.perf_counter() - started) * 1000, 2)
        metrics["scan_work"] = counters.copy()
        metrics["workers"] = 1
        library._started = True
        metrics["warm_query"] = timing(lambda: library.search(SEARCH))
        metrics["filter_query"] = timing(
            lambda: library.search(dict(SEARCH, query="00", source="pipeline"))
        )
        ids = [
            key
            for key, item in library.index.items.items()
            if item.width and item.source == "pipeline"
        ][:8]
        thumbnail_probe(library, ids, counters, metrics)
    tracemalloc.start()
    library._inventory(Event())
    metrics["inventory_peak_python_bytes"] = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    return metrics


def indexed(root, size, media):
    from src.app import site_output_library as module
    from src.app.site_library_reconcile import Reconciliation, key_for
    from src.app.site_output_catalog import SiteOutputCatalog

    metrics = {}
    catalog = SiteOutputCatalog(root)
    library = catalog.library
    inventory = Reconciliation.inventory
    original_start = library.start

    def observed_inventory(self, *args, **kwargs):
        state = inventory(self, *args, **kwargs)
        metrics.setdefault("inventory_ms", round((time.perf_counter() - started) * 1000, 2))
        return state

    started = time.perf_counter()
    with (
        patch.object(module, "_WARM_COUNT", 0),
        patch.object(Reconciliation, "inventory", observed_inventory),
    ):
        with measure_media(module) as counters:
            while True:
                page = library.search({"kind": "all"}, indexed=True)
                if page["items"]:
                    metrics.setdefault(
                        "first_page_ms", round((time.perf_counter() - started) * 1000, 2)
                    )
                if page["total"] == size and not page["partial"]:
                    break
                if time.perf_counter() - started > 180:
                    raise RuntimeError(
                        f"Inventory did not settle: {page['state']}, {page['total']}"
                    )
                time.sleep(0.025)
            metrics["complete_ms"] = round((time.perf_counter() - started) * 1000, 2)
            metrics["scan_work"] = counters.copy()
            metrics["workers"] = int(library.store.thread is not None)
            metrics["warm_query"] = timing(lambda: library.search(SEARCH))
            metrics["filter_query"] = timing(
                lambda: library.search(dict(SEARCH, query="00", source="pipeline"))
            )
            metrics["indexed_filter_sort"] = timing(
                lambda: library.search(
                    {"query": "00", "filters": {"source": "pipeline"}, "sort": "filename_desc"},
                    indexed=True,
                )
            )
            with library.store.connection() as db:
                rows = db.execute(
                    "SELECT key FROM media WHERE source = 'pipeline' AND width IS NOT NULL"
                    " AND kind = 'image' ORDER BY timestamp DESC, key LIMIT 8"
                ).fetchall()
            ids = [library._registered(row["key"]) for row in rows]
            thumbnail_probe(library, ids, counters, metrics)

            new = root / "Pipeline" / "native-published.png"
            start_publication = time.perf_counter()
            new.write_bytes(media[0])
            query = {"field": "name", "query": "native-published"}
            while not library.search(query, indexed=True)["items"]:
                if time.perf_counter() - start_publication > 20:
                    raise RuntimeError("New artifact was not discovered")
                time.sleep(0.025)
            metrics["discovery_ms"] = round((time.perf_counter() - start_publication) * 1000, 2)

            worker = library.store.thread
            catalog.revoke()
            assert worker is not None
            worker.join(5)
            assert not worker.is_alive()
            reopened = SiteOutputCatalog(root)
            try:
                metrics["first_warm_page"] = timing(
                    lambda: reopened.library.search(SEARCH), repeat=1
                )
                workers = reopened.library.store.thread
            finally:
                reopened.revoke()
            if workers:
                workers.join(5)

    # Inventory memory is measured on unchanged files, outside the latency run.
    library.start = original_start
    scan = Reconciliation(library.store)
    tracemalloc.start()
    scan.inventory(Event(), lambda: None, library._basic, full=True)
    metrics["inventory_peak_python_bytes"] = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    with library.store.connection() as db:
        assert db.execute(
            "SELECT 1 FROM media WHERE key = ?", (key_for(new.relative_to(root).as_posix()),)
        ).fetchone()
    return metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("implementation", choices=("baseline", "indexed"))
    parser.add_argument("--sizes", nargs="+", type=int, default=[1000, 10000, 50000])
    parser.add_argument("--temp-dir", type=Path, required=True)
    parser.add_argument("--video-fixture", type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(Path.cwd()))
    video = args.video_fixture.read_bytes() if args.video_fixture else b""
    run = baseline if args.implementation == "baseline" else indexed
    for size in args.sizes:
        with tempfile.TemporaryDirectory(prefix="stablenew-library-", dir=args.temp_dir) as folder:
            base = Path(folder)
            root = base / "output"
            root.mkdir()
            with patch.dict(os.environ, {"STABLENEW_SITE_LIBRARY_CACHE_DIR": str(base / "cache")}):
                media = fixture(root, size, video)
                result = run(root, size, media)
                print(json.dumps({"rows": size, **result}), flush=True)


if __name__ == "__main__":
    main()
