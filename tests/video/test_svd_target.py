from __future__ import annotations

import pytest
from PIL import Image

from src.video.svd_config import SVDPreprocessConfig
from src.video.svd_preprocess import prepare_svd_input
from src.video.svd_target import (
    SVD_AUTO_TARGET_PIXEL_CEILING,
    SVD_TARGET_SIZES,
    SVD_TARGET_STRIDE,
    select_svd_target_size,
)


@pytest.mark.parametrize(
    ("source_size", "expected"),
    [
        ((1024, 576), (1024, 576)),
        ((576, 1024), (576, 1024)),
        ((832, 1216), (640, 960)),
        ((896, 1152), (704, 896)),
        ((1024, 1024), (768, 768)),
        ((1152, 896), (896, 704)),
    ],
)
def test_select_svd_target_size_matches_nearest_policy_ratio(source_size, expected) -> None:
    assert select_svd_target_size(*source_size) == expected


def test_select_svd_target_size_is_deterministic_for_arbitrary_nearby_dimensions() -> None:
    source_size = (1001, 601)

    assert select_svd_target_size(*source_size) == select_svd_target_size(*source_size)


def test_auto_targets_are_stride_safe_and_within_pixel_budget() -> None:
    assert all(
        width % SVD_TARGET_STRIDE == 0 and height % SVD_TARGET_STRIDE == 0
        for width, height in SVD_TARGET_SIZES
    )
    assert all(width * height <= SVD_AUTO_TARGET_PIXEL_CEILING for width, height in SVD_TARGET_SIZES)
    assert SVD_AUTO_TARGET_PIXEL_CEILING <= 704 * 896


def test_center_crop_preserves_existing_aspect_preprocessing_authority(tmp_path) -> None:
    source_path = tmp_path / "wide.png"
    image = Image.new("RGB", (256, 64), "blue")
    image.paste("red", (0, 0, 96, 64))
    image.paste("green", (96, 0, 160, 64))
    image.save(source_path)

    result = prepare_svd_input(
        source_path=source_path,
        config=SVDPreprocessConfig(target_width=64, target_height=64, resize_mode="center_crop"),
        temp_dir=tmp_path / "prepared",
    )

    with Image.open(result.prepared_path) as prepared:
        assert prepared.size == (64, 64)
        assert prepared.getpixel((0, 0)) == (0, 128, 0)
        assert prepared.getpixel((63, 63)) == (0, 128, 0)


@pytest.mark.parametrize("dimensions", [(0, 100), (100, 0), (-1, 100), (100, -1)])
def test_select_svd_target_size_rejects_non_positive_dimensions(dimensions) -> None:
    with pytest.raises(ValueError, match="positive"):
        select_svd_target_size(*dimensions)
