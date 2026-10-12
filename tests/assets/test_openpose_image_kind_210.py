"""AssetRegistry OpenPose image kind (PR-IMG-CNET-210): per-kind extension filtering and unchanged weight scanning."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from src.assets import AssetKind, AssetRegistry
from tests.conditioning.openpose_fixtures_210 import jpeg_bytes, make_library, png_bytes


def _registry(root: Path) -> AssetRegistry:
    return AssetRegistry(root, cache_path=root / "cache" / "registry.json")


def _names(registry: AssetRegistry, kind: AssetKind) -> list[str]:
    return sorted(
        location.path.relative_to(location.root).as_posix()
        for record in registry.snapshot.records_for(kind)
        for location in record.locations
        if location.kind is kind
    )


def test_the_openpose_library_is_a_registered_root(tmp_path: Path) -> None:
    roots = dict(_registry(tmp_path).supported_roots())

    assert roots[AssetKind.OPENPOSE_IMAGE] == tmp_path / "models" / "OpenPose"
    assert AssetKind.OPENPOSE_IMAGE is not AssetKind.CONTROLNET  # reference images are not model weights


def test_images_are_discovered_recursively_with_relative_identity_and_byte_hash(tmp_path: Path) -> None:
    standing = png_bytes(128, 160)
    make_library(
        tmp_path,
        {
            "Standing/relaxed.png": standing,
            "Standing/hands_on_hips.PNG": png_bytes(128, 160, (5, 5, 5)),
            "Walking/forward.jpg": jpeg_bytes(),
            "Sitting/seated.webp": b"RIFF....WEBPVP8 ",  # name-based discovery; validity is checked at use
            "notes.txt": b"not an image",
            "weights.safetensors": b"not an image either",
        },
    )
    registry = _registry(tmp_path)

    result = registry.refresh(kinds={AssetKind.OPENPOSE_IMAGE})

    assert _names(registry, AssetKind.OPENPOSE_IMAGE) == [
        "Sitting/seated.webp",
        "Standing/hands_on_hips.PNG",
        "Standing/relaxed.png",
        "Walking/forward.jpg",
    ]
    record = next(
        item
        for item in result.snapshot.records_for(AssetKind.OPENPOSE_IMAGE)
        if item.locations[0].path.name == "relaxed.png"
    )
    assert record.sha256 == hashlib.sha256(standing).hexdigest()
    assert record.compatibility is None and record.embedded_metadata == {}
    assert record.locations[0].sidecar_path is None


def test_image_files_elsewhere_are_never_indexed_as_model_weights(tmp_path: Path) -> None:
    for folder in ("Stable-diffusion", "Lora", "ControlNet", "VAE"):
        target = tmp_path / "models" / folder
        target.mkdir(parents=True)
        (target / "preview.png").write_bytes(png_bytes())
        (target / "preview.jpg").write_bytes(jpeg_bytes())
    (tmp_path / "embeddings").mkdir()
    (tmp_path / "embeddings" / "thumb.png").write_bytes(png_bytes())
    registry = _registry(tmp_path)

    registry.refresh()

    assert registry.snapshot.records == ()


def test_weight_files_in_the_openpose_folder_are_not_images_and_weight_scanning_is_unchanged(tmp_path: Path) -> None:
    (tmp_path / "models" / "Lora").mkdir(parents=True)
    (tmp_path / "models" / "Lora" / "style.safetensors").write_bytes(b"lora-bytes")
    (tmp_path / "models" / "ControlNet").mkdir(parents=True)
    (tmp_path / "models" / "ControlNet" / "pose_sdxl.safetensors").write_bytes(b"cn-bytes")
    make_library(tmp_path, {"a.png": png_bytes(), "stray.safetensors": b"stray"})
    registry = _registry(tmp_path)

    registry.refresh()

    assert _names(registry, AssetKind.LORA) == ["style.safetensors"]
    assert _names(registry, AssetKind.CONTROLNET) == ["pose_sdxl.safetensors"]
    assert _names(registry, AssetKind.OPENPOSE_IMAGE) == ["a.png"]


def test_a_second_refresh_reuses_fingerprinted_identity_and_the_cache_survives_a_new_instance(tmp_path: Path) -> None:
    make_library(tmp_path, {"a.png": png_bytes(), "b.png": png_bytes(color=(1, 1, 1))})
    registry = _registry(tmp_path)
    first = registry.refresh(kinds={AssetKind.OPENPOSE_IMAGE})
    second = registry.refresh(kinds={AssetKind.OPENPOSE_IMAGE})

    assert (first.hashes_computed, first.hash_cache_hits) == (2, 0)
    assert (second.hashes_computed, second.hash_cache_hits) == (0, 2)
    reopened = _registry(tmp_path)
    assert _names_from(reopened.cached_snapshot()) == ["a.png", "b.png"]


def _names_from(snapshot) -> list[str]:
    return sorted(
        location.path.name
        for record in snapshot.records_for(AssetKind.OPENPOSE_IMAGE)
        for location in record.locations
    )


def test_a_removed_image_leaves_the_snapshot_on_refresh(tmp_path: Path) -> None:
    library = make_library(tmp_path, {"a.png": png_bytes(), "b.png": png_bytes(color=(1, 1, 1))})
    registry = _registry(tmp_path)
    registry.refresh(kinds={AssetKind.OPENPOSE_IMAGE})

    (library / "a.png").unlink()
    registry.refresh(kinds={AssetKind.OPENPOSE_IMAGE})

    assert _names(registry, AssetKind.OPENPOSE_IMAGE) == ["b.png"]


def test_a_file_link_out_of_the_library_is_not_indexed(tmp_path: Path) -> None:
    library = make_library(tmp_path, {"a.png": png_bytes()})
    outside = tmp_path / "outside.png"
    outside.write_bytes(png_bytes(color=(99, 0, 0)))
    try:
        os.symlink(outside, library / "escape.png")
    except (OSError, NotImplementedError):
        pytest.skip("file symlinks are unavailable")
    registry = _registry(tmp_path)

    registry.refresh(kinds={AssetKind.OPENPOSE_IMAGE})

    assert _names(registry, AssetKind.OPENPOSE_IMAGE) == ["a.png"]
