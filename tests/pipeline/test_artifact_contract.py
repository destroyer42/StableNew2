from __future__ import annotations

from src.pipeline.artifact_contract import (
    ARTIFACT_SCHEMA_VERSION,
    canonicalize_variant_entry,
    extract_artifact_paths,
)


def test_canonicalize_variant_entry_adds_artifact_block_for_image_result() -> None:
    variant = canonicalize_variant_entry(
        {
            "stage": "txt2img",
            "path": "output/image.png",
            "all_paths": ["output/image.png", "output/image_2.png"],
            "manifest_path": "output/manifests/image.json",
        }
    )

    assert variant["artifact"]["schema"] == ARTIFACT_SCHEMA_VERSION
    assert variant["artifact"]["artifact_type"] == "image"
    assert variant["artifact"]["primary_path"] == "output/image.png"
    assert variant["artifact"]["output_paths"] == ["output/image.png", "output/image_2.png"]


def test_canonicalize_variant_entry_adds_artifact_block_for_video_result() -> None:
    variant = canonicalize_variant_entry(
        {
            "stage": "svd_native",
            "video_path": "output/clip.mp4",
            "manifest_path": "output/manifests/clip.json",
            "thumbnail_path": "output/preview.png",
            "source_image_path": "input/source.png",
        }
    )

    assert variant["artifact"]["artifact_type"] == "video"
    assert variant["artifact"]["primary_path"] == "output/clip.mp4"
    assert variant["artifact"]["manifest_path"] == "output/manifests/clip.json"
    assert variant["artifact"]["thumbnail_path"] == "output/preview.png"


def test_extract_artifact_paths_prefers_canonical_block() -> None:
    paths = extract_artifact_paths(
        {
            "artifact": {
                "schema": ARTIFACT_SCHEMA_VERSION,
                "output_paths": ["a.png", "b.png"],
                "primary_path": "a.png",
            }
        }
    )

    assert paths == ["a.png", "b.png"]
