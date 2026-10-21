"""Choose the RealESRGAN weights for an upscale request (PR-VID-POST-304).

The standard ``RealESRGAN_x4plus`` weights always produced four times the pixels; a 2x request
was served by running that network and Lanczos-downsampling the result, which costs a full 4x
inference to throw three quarters of it away and softens the detail. When native 2x weights are
available they are used for a 2x request instead. Otherwise the 4x weights still run and the
fallback is recorded, never silent.

Pure path logic: nothing here imports a model library or reads a weight.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# The file name the Real-ESRGAN project publishes its 2x checkpoint under.
X2_WEIGHT_NAME = "RealESRGAN_x2plus.pth"
_TWO_TIMES_TOLERANCE = 1e-6

SOURCE_CONFIGURED_X2 = "configured_x2"
SOURCE_BESIDE_MODEL = "beside_model"
SOURCE_MODEL_PATH = "model_path"


@dataclass(frozen=True)
class UpscaleModelSelection:
    """Which weights an upscale stage will load, and why."""

    model_path: str
    requested_scale: float
    #: ``configured_x2`` and ``beside_model`` are native 2x weights; ``model_path`` is the general model.
    source: str
    #: The scale the chosen weights are expected to produce natively (``None`` when not known by name).
    expected_native_scale: int | None
    #: Set only when a 2x request could not use native 2x weights; says why the 4x path ran instead.
    fallback_reason: str = ""

    @property
    def model_name(self) -> str:
        return Path(self.model_path).name

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "model_name": self.model_name}


def requests_two_times(scale: float) -> bool:
    return abs(float(scale) - 2.0) < _TWO_TIMES_TOLERANCE


def resolve_upscale_model(
    *, scale: float, model_path: str | None, model_path_x2: str | None
) -> UpscaleModelSelection | None:
    """Return the weights to load for ``scale``, or ``None`` when no usable weights exist.

    A 2x request prefers native 2x weights: ``model_path_x2`` when it exists, else the standard
    2x file beside ``model_path``. Every other scale, and a 2x request with no 2x weights, uses
    ``model_path`` (the stage resizes when the network's native scale differs from the request).
    """

    fallback_reason = ""
    if requests_two_times(scale):
        configured = (model_path_x2 or "").strip()
        if configured and Path(configured).is_file():
            return UpscaleModelSelection(configured, float(scale), SOURCE_CONFIGURED_X2, 2)
        beside = Path(model_path).parent / X2_WEIGHT_NAME if model_path else None
        if beside is not None and beside.is_file():
            return UpscaleModelSelection(str(beside), float(scale), SOURCE_BESIDE_MODEL, 2)
        fallback_reason = (
            f"configured 2x weights not found ({configured}); using the general model and resizing"
            if configured
            else f"no native 2x weights ({X2_WEIGHT_NAME}) configured or beside the general model; "
            "using the general model and resizing"
        )
    if model_path and Path(model_path).is_file():
        return UpscaleModelSelection(
            model_path, float(scale), SOURCE_MODEL_PATH, None, fallback_reason
        )
    return None
