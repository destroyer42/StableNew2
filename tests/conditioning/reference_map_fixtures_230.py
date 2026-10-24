"""Hosted-CI-safe stand-ins for PR-IMG-CNET-230 tests: no OpenCV, torch, transformers or onnxruntime required."""

from __future__ import annotations

import numpy as np

from src.conditioning.reference_map import canny, providers
from src.conditioning.reference_map.service import ReferenceMapService


def gradient_edges(gray: np.ndarray) -> np.ndarray:
    """A pure-numpy edge detector (any positive pixel is an edge); deterministic and dependency-free."""

    wide = gray.astype(np.int16)
    edges = np.zeros(gray.shape, dtype=np.uint8)
    edges[:, 1:] |= (np.abs(np.diff(wide, axis=1)) > 40).astype(np.uint8)
    edges[1:, :] |= (np.abs(np.diff(wide, axis=0)) > 40).astype(np.uint8)
    return edges * 255


class PureCannyProvider(providers.CannyProvider):
    """The real Canny seam (luma, binarization, size checks) around a pure detector, so tests need no OpenCV."""

    def availability(self) -> tuple[str, ...]:
        return ()

    def produce(self, source, context):
        context.check()
        rgb = canny.canny_map(source.rgb, detect=gradient_edges)
        context.check()
        return providers.Produced(rgb, canny.identity(), runtime={"numpy": str(np.__version__)})


def pure_service(registry, **extra) -> ReferenceMapService:
    chosen = {"canny": PureCannyProvider(), **extra.pop("providers", {})}
    return ReferenceMapService(lambda: registry, providers=chosen, **extra)
