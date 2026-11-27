"""RG-140 slice 2: the canvas extension that gives an image another aspect ratio (outpainting only adds space)."""

from __future__ import annotations

import pytest

from src.pipeline.outpaint_canvas import (
    ALIGNMENT,
    Extents,
    extents_for_aspect,
    has_aspect,
    plan_geometry,
)


@pytest.mark.parametrize(
    "size, ratio, expected",
    [
        ((1024, 1024), (2, 3), Extents(top=256, bottom=256)),  # taller: space above and below
        ((1024, 1024), (16, 9), Extents(left=398, right=402)),  # wider; aligned on the right
        ((832, 1216), (1, 1), Extents(left=192, right=192)),
        ((1216, 832), (4, 5), Extents(top=344, bottom=344)),
    ],
)
def test_space_is_added_evenly_and_aligned(size, ratio, expected):
    extents = extents_for_aspect(size, ratio)

    assert extents == expected
    width = size[0] + extents.left + extents.right
    height = size[1] + extents.top + extents.bottom
    assert width % ALIGNMENT == 0 and height % ALIGNMENT == 0
    assert abs(width / height - ratio[0] / ratio[1]) < 0.01
    plan_geometry(size, extents)  # within the documented limits


@pytest.mark.parametrize(
    "size, ratio", [((1024, 1024), (1, 1)), ((1024, 1536), (2, 3)), ((1024, 1530), (2, 3))]
)
def test_an_image_that_already_has_the_ratio_needs_nothing(size, ratio):
    assert has_aspect(size, ratio)
    assert extents_for_aspect(size, ratio) is None


def test_a_near_ratio_is_not_the_ratio():
    assert not has_aspect((832, 1216), (2, 3))  # SDXL's 832 x 1216 is 2.6% from 2:3


def test_a_canvas_beyond_the_limit_is_left_to_plan_geometry_to_refuse():
    extents = extents_for_aspect((4096, 1024), (4, 5))

    assert extents == Extents(top=2048, bottom=2048)
    with pytest.raises(ValueError):
        plan_geometry((4096, 1024), extents)


def test_sizes_and_ratios_must_be_positive():
    with pytest.raises(ValueError):
        extents_for_aspect((0, 10), (1, 1))
    with pytest.raises(ValueError):
        extents_for_aspect((10, 10), (0, 1))
