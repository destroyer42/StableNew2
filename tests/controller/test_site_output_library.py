from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from src.app.site_media_files import SiteOutputError, inside
from src.app.site_output_catalog import SiteOutputCatalog
from src.app.site_output_routes import OUTPUT_CHUNK, OUTPUT_LIBRARY, OUTPUT_PLAY, post


def _png(path: Path, *, metadata: bool = False) -> None:
    data = PngInfo()
    if metadata:
        data.add_itxt("tags", "Éclairage, outdoor")
        data.add_itxt("parameters", "a " * 2500 + "distant forest\nSteps: 12, Seed: 0")
    Image.new("RGB", (40, 30), "#324174").save(path, pnginfo=data)


def _library(catalog: SiteOutputCatalog, action: str, **kwargs):
    return post(catalog, OUTPUT_LIBRARY, {"scope": catalog.scope, "action": action, **kwargs})


def _search(catalog: SiteOutputCatalog, field="all", query="", kind="image", **options):
    args = {
        "field": field,
        "kind": kind,
        "query": query,
        "offset": 0,
        "revision": "",
        "refresh": False,
    }
    options = {**args, **options}
    for _ in range(200):
        page = _library(catalog, "search", **options)
        if not page["scanning"]:
            return page
        options["refresh"] = False
        time.sleep(0.01)
    pytest.fail("Output scan did not finish")


def test_gallery_search_album_order_and_rating_survive_a_new_pairing(tmp_path):
    _png(tmp_path / "first.png", metadata=True)
    (tmp_path / "duplicate.png").write_bytes((tmp_path / "first.png").read_bytes())
    _png(tmp_path / "unknown.png")
    catalog = SiteOutputCatalog(tmp_path)
    page = _search(catalog, "tag", "éCLAIRAGE")
    assert page["total"] == 2
    ids = [item["id"] for item in page["items"]]
    assert len(set(ids)) == 2
    assert _search(catalog, "seed", "0")["total"] == 2
    assert _search(catalog, "prompt", "distant forest")["total"] == 2
    assert _search(catalog, "name", "unknown")["items"][0]["seed"] is None
    assert "distant forest" not in page["items"][0]["prompt"]
    first = _library(catalog, "inspect", id=ids[0])
    assert "distant forest" in first["prompt"]
    original = (tmp_path / first["item"]["name"]).read_bytes()
    rated = _library(
        catalog,
        "rate",
        id=ids[0],
        digest=first["digest"],
        revision=0,
        operation="a" * 32,
        score=4,
        notes="Good contrast",
    )
    assert rated["score"] == 4
    assert _library(catalog, "thumbnails", ids=ids)["thumbnails"][ids[0]]["score"] == 4
    album_id = "b" * 32
    options = {
        "id": album_id,
        "name": "Finalists",
        "items": ids,
        "revision": 0,
        "operation": "c" * 32,
    }
    saved = _library(catalog, "save_album", **options)
    assert _library(catalog, "save_album", **options) == saved
    assert saved["revision"] == 1
    with pytest.raises(SiteOutputError, match="library_conflict"):
        _library(catalog, "save_album", **{**options, "name": "Stale", "operation": "d" * 32})
    assert (tmp_path / first["item"]["name"]).read_bytes() == original
    catalog.revoke()
    with pytest.raises(SiteOutputError, match="output_folder_not_shared"):
        _library(catalog, "album", id=album_id)

    connected = SiteOutputCatalog(tmp_path)
    _search(connected)
    album = _library(connected, "album", id=album_id)
    assert [item["name"] for item in album["items"]] == [item["name"] for item in page["items"]]
    assert _library(connected, "inspect", id=album["items"][0]["id"])["rating"]["score"] == 4
    (tmp_path / album["items"][0]["name"]).unlink()
    assert _library(connected, "album", id=album_id)["items"][0]["unavailable"]
    _library(
        connected,
        "save_album",
        id=album_id,
        name="Reordered",
        items=[1, 0],
        revision=1,
        operation="e" * 32,
    )
    assert _library(connected, "album", id=album_id)["items"][1]["unavailable"]


def test_video_snapshot_supports_bounded_seek_beyond_the_relay_cap(tmp_path):
    clip = tmp_path / "long.mp4"
    far = 33 * 1024 * 1024
    with clip.open("wb") as stream:
        stream.write(b"\x00\x00\x00\x10ftypisom0123")
        stream.seek(far)
        stream.write(b"far side")
    catalog = SiteOutputCatalog(tmp_path)
    item = _search(catalog, kind="video")["items"][0]
    playback = post(catalog, OUTPUT_PLAY, {"id": item["id"], "library": True})
    payload = {"id": playback["id"], "start": far, "length": 8}
    assert playback["size"] == far + 8
    assert post(catalog, OUTPUT_CHUNK, payload) == ("video/mp4", b"far side")
    with pytest.raises(SiteOutputError, match="invalid_range"):
        post(catalog, OUTPUT_CHUNK, {**payload, "start": far + 8})
    catalog.revoke()
    with pytest.raises(SiteOutputError, match="output_folder_not_shared"):
        post(catalog, OUTPUT_CHUNK, payload)


def test_output_rejects_linked_directories(tmp_path):
    root = tmp_path / "output"
    root.mkdir()
    outside = tmp_path / "private"
    outside.mkdir()
    _png(outside / "secret.png")
    linked = root / "linked"
    if sys.platform == "win32":
        subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(linked), str(outside)],
            check=True,
            capture_output=True,
        )
    else:
        linked.symlink_to(outside, target_is_directory=True)
    with pytest.raises(SiteOutputError, match="outside_output_folder"):
        inside(root, linked / "secret.png")
    assert _search(SiteOutputCatalog(root))["total"] == 0
