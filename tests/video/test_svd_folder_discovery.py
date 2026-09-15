from __future__ import annotations

from pathlib import Path

from PIL import Image

from src.video.svd_preprocess import SVD_SUPPORTED_IMAGE_SUFFIXES, discover_svd_folder_sources


def _image(path: Path) -> None:
    Image.new("RGB", (32, 16), color=(1, 2, 3)).save(path)


def test_folder_discovery_uses_supported_authority_and_is_non_recursive(tmp_path: Path) -> None:
    for suffix in sorted(SVD_SUPPORTED_IMAGE_SUFFIXES):
        _image(tmp_path / f"source{suffix}")
    nested = tmp_path / "nested"
    nested.mkdir()
    _image(nested / "hidden.png")
    (tmp_path / "ignored.txt").write_text("not an image")

    result = discover_svd_folder_sources(tmp_path)

    assert [item.path.name for item in result.sources] == sorted(
        [f"source{suffix}" for suffix in SVD_SUPPORTED_IMAGE_SUFFIXES], key=str.casefold
    )
    assert [item.name for item in result.ignored_paths] == ["ignored.txt"]
    assert not result.invalid_candidates


def test_folder_discovery_reports_corrupt_supported_candidate(tmp_path: Path) -> None:
    _image(tmp_path / "valid.png")
    (tmp_path / "broken.jpg").write_bytes(b"not an image")

    result = discover_svd_folder_sources(tmp_path)

    assert [item.path.name for item in result.sources] == ["valid.png"]
    assert result.invalid_candidates[0][0].name == "broken.jpg"
