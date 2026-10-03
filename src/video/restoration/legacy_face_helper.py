"""Isolated legacy face helper for CodeFormer: the ``facelib`` fork shipped in the codeformer wheel.

LEGACY ISOLATED / RETAINED (PR-POSTPROC-100). This is the only module that imports ``facelib``.

Why it is retained: upstream ``facexlib`` 0.3.0's ``FaceRestoreHelper`` is NOT behaviour-equivalent
to this fork (it detects at a different scale and confidence, does not upscale small inputs to
512 px, and pastes back differently). Measured against the accepted output with identical weights
and the same Spandrel network, facexlib changed CodeFormer results materially (PSNR 42-47 dB,
max per-pixel difference up to 147/255). That is a product-quality change, so it needs owner
adjudication and is not made here.

Scope: face detection, landmark alignment, crop and paste-back for CodeFormer. Nothing else.

Removal condition: the owner approves a modern face detection/alignment path (for example facexlib
or StableNew-owned code) after a visual and objective quality review. Then this module, and the
``codeformer`` package from the postprocess profile, can be deleted.

What changed from the old worker: no torchvision compatibility shim (the BasicSR code vendored in
this wheel never needed it), no ``sys.path`` edits, no process working-directory change, and no
copying of weights into site-packages. The weights directory is passed explicitly for the
duration of construction only.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from src.video.restoration.model_loader import RestorationRuntimeError

REQUIRED_FACELIB_FILES = ("detection_Resnet50_Final.pth", "parsing_parsenet.pth")
_FACE_SIZE = 512


def require_facelib_files(model_root: Path) -> None:
    """Verify the weights exist so the helper can never fall back to downloading them."""

    if not model_root.is_dir():
        raise RestorationRuntimeError(f"Face model root not found: {model_root}")
    for name in REQUIRED_FACELIB_FILES:
        if not (model_root / name).is_file():
            raise RestorationRuntimeError(f"Required facelib model not found: {model_root / name}")


@contextmanager
def _weights_root(model_root: Path) -> Iterator[None]:
    """Point facelib's weight lookup at StableNew's model root while the helper is built."""

    import facelib.detection as detection
    import facelib.parsing as parsing

    saved = (detection.WEIGHTS_DIR, parsing.WEIGHTS_DIR)
    detection.WEIGHTS_DIR = parsing.WEIGHTS_DIR = str(model_root)
    try:
        yield
    finally:
        detection.WEIGHTS_DIR, parsing.WEIGHTS_DIR = saved


def build_face_restore_helper(model_root: Path, device: Any) -> Any:
    """Return the facelib ``FaceRestoreHelper`` configured exactly as the legacy worker did."""

    require_facelib_files(model_root)
    with _weights_root(model_root):
        from facelib.utils.face_restoration_helper import FaceRestoreHelper

        return FaceRestoreHelper(
            1,
            face_size=_FACE_SIZE,
            crop_ratio=(1, 1),
            det_model="retinaface_resnet50",
            save_ext="png",
            use_parse=True,
            device=device,
        )
