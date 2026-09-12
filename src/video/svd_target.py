"""Source-aware target geometry policy for the native SVD XT path."""

from __future__ import annotations

from typing import Final

SVD_TARGET_SIZES: Final[tuple[tuple[int, int], ...]] = (
    (576, 1024),
    (640, 960),
    (704, 896),
    (768, 768),
    (896, 704),
    (960, 640),
    (1024, 576),
)
SVD_TARGET_STRIDE: Final[int] = 64
SVD_AUTO_TARGET_PIXEL_CEILING: Final[int] = max(width * height for width, height in SVD_TARGET_SIZES)


def select_svd_target_size(source_width: int, source_height: int) -> tuple[int, int]:
    """Select the closest vetted target aspect ratio for a source image.

    All policy targets are stride-safe for the current SVD/VAE path and remain
    within the accepted approximately 0.6 MP working-set class. Ties retain
    the stable order in ``SVD_TARGET_SIZES``.
    """

    width = int(source_width)
    height = int(source_height)
    if width <= 0 or height <= 0:
        raise ValueError("source dimensions must be positive")
    source_ratio = width / height
    return min(
        SVD_TARGET_SIZES,
        key=lambda target: abs((target[0] / target[1]) - source_ratio),
    )


__all__ = [
    "SVD_AUTO_TARGET_PIXEL_CEILING",
    "SVD_TARGET_SIZES",
    "SVD_TARGET_STRIDE",
    "select_svd_target_size",
]
