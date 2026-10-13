"""OpenPose library listing for the editor (PR-IMG-CNET-210): registry-backed, cached, searchable, bounded."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.assets import AssetRegistry
from src.conditioning import openpose_catalog as catalog
from tests.conditioning.openpose_fixtures_210 import make_library, png_bytes


def _registry(root: Path | None, cache: Path) -> AssetRegistry:
    return AssetRegistry(root, cache_path=cache)


def test_refresh_lists_nested_images_by_relative_identity(tmp_path: Path) -> None:
    make_library(
        tmp_path,
        {
            "Standing/relaxed.png": png_bytes(),
            "Standing/hands_on_hips.png": png_bytes(color=(1, 2, 3)),
            "Walking/walking_forward.png": png_bytes(color=(4, 5, 6)),
            "readme.txt": b"ignored",
        },
    )
    registry = _registry(tmp_path, tmp_path / "cache.json")

    listing = catalog.refresh_listing(registry)

    assert [entry.identity for entry in listing.entries] == [
        "Standing/hands_on_hips.png",
        "Standing/relaxed.png",
        "Walking/walking_forward.png",
    ]
    assert listing.configured and listing.folder_exists
    assert all(len(entry.sha256) == 64 and entry.size > 0 for entry in listing.entries)
    assert listing.entries[0].folder == "Standing"


def test_cached_listing_never_scans(tmp_path: Path) -> None:
    make_library(tmp_path, {"a.png": png_bytes()})
    registry = _registry(tmp_path, tmp_path / "cache.json")

    assert catalog.cached_listing(registry).entries == ()  # nothing scanned yet, nothing discovered

    catalog.refresh_listing(registry)
    reopened = _registry(tmp_path, tmp_path / "cache.json")

    assert [e.identity for e in catalog.cached_listing(reopened).entries] == ["a.png"]


def test_search_is_case_insensitive_and_matches_folders_and_names(tmp_path: Path) -> None:
    make_library(tmp_path, {"Standing/Relaxed.png": png_bytes(), "Walking/forward.png": png_bytes(color=(9, 9, 9))})
    entries = catalog.refresh_listing(_registry(tmp_path, tmp_path / "c.json")).entries

    assert [e.identity for e in catalog.filter_entries(entries, "relax")] == ["Standing/Relaxed.png"]
    assert [e.identity for e in catalog.filter_entries(entries, "WALKING forward")] == ["Walking/forward.png"]
    assert len(catalog.filter_entries(entries, "")) == 2
    assert catalog.filter_entries(entries, "nothing") == []


def test_a_missing_library_or_unconfigured_root_is_reported_not_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = catalog.refresh_listing(_registry(tmp_path, tmp_path / "c.json"))
    assert (missing.configured, missing.folder_exists, missing.entries) == (True, False, ())

    monkeypatch.setenv("STABLENEW_WEBUI_ROOT", "")
    monkeypatch.setattr("src.config.app_config.STABLENEW_WEBUI_ROOT", "")
    unconfigured = catalog.refresh_listing(AssetRegistry(None, cache_path=tmp_path / "c2.json"))
    assert (unconfigured.configured, unconfigured.entries) == (False, ())


def test_a_deleted_image_disappears_after_refresh(tmp_path: Path) -> None:
    library = make_library(tmp_path, {"a.png": png_bytes(), "b.png": png_bytes(color=(1, 1, 1))})
    registry = _registry(tmp_path, tmp_path / "c.json")
    assert len(catalog.refresh_listing(registry).entries) == 2

    (library / "a.png").unlink()

    assert [e.identity for e in catalog.refresh_listing(registry).entries] == ["b.png"]


def test_the_controlnet_folder_is_the_registrys_existing_weight_root(tmp_path: Path) -> None:
    registry = _registry(tmp_path, tmp_path / "c.json")

    assert catalog.controlnet_folder(registry) == tmp_path / "models" / "ControlNet"
