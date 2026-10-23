"""Relative depth map: pure normalization of a model's prediction (PR-IMG-CNET-230).

The model (Depth Anything V2 Small, run in the contained worker) predicts relative inverse depth: larger values are
nearer. This module turns that prediction into the map ControlNet depth units expect, with a stated convention:

* the prediction is resized (bicubic) to the oriented source's exact dimensions, so the restored size is exact;
* NaN or infinity anywhere refuses the map (a broken inference is never repaired silently);
* a map with no variation refuses (flat conditioning is not a depth map);
* otherwise the minimum maps to 0 and the maximum to 255 linearly, rounding half up: nearest is brightest;
* the three RGB channels are identical.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from src.conditioning.reference_map.contracts import (
    CODE_DEPTH_FLAT,
    CODE_DEPTH_NON_FINITE,
    CODE_INFERENCE,
    MethodIdentity,
    ReferenceMapError,
)

METHOD_ID = "depth-anything-v2-small-hf"
METHOD_VERSION = 1
CONFIG: dict[str, Any] = {
    "model": "depth-anything/Depth-Anything-V2-Small-hf",
    "inference": "transformers_cpu_float32",
    "trust_remote_code": False,
    "use_safetensors": True,
    "convention": "relative_inverse_depth_near_bright",
    "resize": "bicubic_to_oriented_source",
    "normalization": "min_max_linear_round_half_up",
    "nan_inf": "refuse",
    "constant_map": "refuse",
    "channels": "rgb_replicated",
}
#: A prediction whose range is below this (relative to its magnitude) is treated as constant.
FLAT_EPSILON = 1e-6


def identity() -> MethodIdentity:
    return MethodIdentity(METHOD_ID, METHOD_VERSION, dict(CONFIG))


def prediction_to_map(prediction: Any, width: int, height: int) -> np.ndarray:
    """``(height, width, 3)`` ``uint8`` depth map from a 2-D (or leading-singleton) float prediction."""

    from PIL import Image

    array = np.asarray(prediction, dtype=np.float32)
    while array.ndim > 2 and array.shape[0] == 1:
        array = array[0]
    if array.ndim != 2 or min(array.shape) < 1:
        raise ReferenceMapError(CODE_INFERENCE, "The depth model returned an unexpected shape.")
    if not np.isfinite(array).all():
        raise ReferenceMapError(
            CODE_DEPTH_NON_FINITE,
            "The depth model produced invalid values (NaN or infinity); no map was created.",
        )
    lower, upper = float(array.min()), float(array.max())
    if array.shape != (height, width):
        resized = np.asarray(
            Image.fromarray(np.ascontiguousarray(array)).resize((width, height), Image.BICUBIC),
            dtype=np.float32,
        )
        array = np.clip(resized, lower, upper)
    low, high = float(array.min()), float(array.max())
    if not high - low > FLAT_EPSILON * max(1.0, abs(low), abs(high)):
        raise ReferenceMapError(
            CODE_DEPTH_FLAT,
            "The depth model found no depth variation in this image; no map was created.",
        )
    scaled = (array.astype(np.float64) - low) / (high - low)
    gray = np.floor(scaled * 255.0 + 0.5).clip(0, 255).astype(np.uint8)
    return np.ascontiguousarray(np.repeat(gray[..., None], 3, axis=2))


__all__ = ["CONFIG", "METHOD_ID", "METHOD_VERSION", "identity", "prediction_to_map"]
