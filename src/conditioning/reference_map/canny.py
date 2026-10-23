"""Canny edge map: a deterministic CPU adapter (PR-IMG-CNET-230).

Every parameter that shapes the output is frozen here and recorded with the map: integer Rec.601 luma, a 5x5 Gaussian
blur (sigma 1.4, reflect-101 border), hysteresis thresholds 100/200 with a 3x3 Sobel aperture and the L1 gradient, no
resize (the map has the oriented source's dimensions), white edges on black, replicated into three RGB channels. OpenCV is
imported lazily and its version is part of the recorded runtime; the edge detector is injectable so the surrounding
geometry and bounds checks are testable without it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np

from src.conditioning.reference_map.contracts import (
    CODE_INFERENCE,
    MethodIdentity,
    ProviderUnavailable,
    ReferenceMapError,
)

METHOD_ID = "canny-edge"
METHOD_VERSION = 1
CONFIG: dict[str, Any] = {
    "gray": "rec601_integer",
    "blur": {"kernel": 5, "sigma": 1.4, "border": "reflect101"},
    "low_threshold": 100,
    "high_threshold": 200,
    "aperture": 3,
    "l2_gradient": False,
    "resize": "none",
    "polarity": "white_edges_on_black",
    "channels": "rgb_replicated",
}

EdgeDetector = Callable[[np.ndarray], np.ndarray]


def identity() -> MethodIdentity:
    return MethodIdentity(METHOD_ID, METHOD_VERSION, dict(CONFIG))


def luma(rgb: np.ndarray) -> np.ndarray:
    """Rec.601 luma with integer arithmetic, so it is identical on every platform."""

    r = rgb[..., 0].astype(np.uint32)
    g = rgb[..., 1].astype(np.uint32)
    b = rgb[..., 2].astype(np.uint32)
    return ((299 * r + 587 * g + 114 * b + 500) // 1000).astype(np.uint8)


def runtime_versions() -> dict[str, str]:
    import cv2

    return {"opencv": str(cv2.__version__), "numpy": str(np.__version__)}


def availability() -> tuple[str, ...]:
    """Reason codes that make Canny unavailable (empty when it can run)."""

    import importlib.util

    return () if importlib.util.find_spec("cv2") is not None else ("runtime_missing:opencv",)


def opencv_edges(gray: np.ndarray) -> np.ndarray:
    try:
        import cv2
    except ImportError as exc:
        raise ProviderUnavailable(
            "Canny needs OpenCV, which is not installed in this environment.",
            reasons=("runtime_missing:opencv",),
        ) from exc
    blur = CONFIG["blur"]
    kernel = int(blur["kernel"])
    softened = cv2.GaussianBlur(
        gray, (kernel, kernel), float(blur["sigma"]), borderType=cv2.BORDER_REFLECT_101
    )
    return np.asarray(
        cv2.Canny(
            softened,
            float(CONFIG["low_threshold"]),
            float(CONFIG["high_threshold"]),
            apertureSize=int(CONFIG["aperture"]),
            L2gradient=bool(CONFIG["l2_gradient"]),
        )
    )


def canny_map(rgb: np.ndarray, *, detect: EdgeDetector = opencv_edges) -> np.ndarray:
    """``(height, width, 3)`` ``uint8`` map whose pixels are only 0 or 255 and whose size is the source's."""

    if rgb.ndim != 3 or rgb.shape[2] != 3 or rgb.dtype != np.uint8:
        raise ReferenceMapError(CODE_INFERENCE, "Canny expects an RGB8 image.")
    edges = np.asarray(detect(luma(rgb)))
    if edges.shape != rgb.shape[:2]:
        raise ReferenceMapError(CODE_INFERENCE, "The edge detector returned an unexpected size.")
    binary = np.where(edges > 0, 255, 0).astype(np.uint8)
    return np.ascontiguousarray(np.repeat(binary[..., None], 3, axis=2))


__all__ = [
    "CONFIG",
    "METHOD_ID",
    "METHOD_VERSION",
    "availability",
    "canny_map",
    "identity",
    "luma",
    "opencv_edges",
    "runtime_versions",
]
