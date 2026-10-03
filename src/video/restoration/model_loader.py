"""Load restoration/upscale checkpoints through Spandrel (StableNew-owned seam).

Spandrel recognises the architecture, normalises the checkpoint state dict and builds the
network. Everything else (face detection/alignment/paste-back, tiling, colour handling, device
and memory management) stays owned by StableNew's adapters.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class RestorationRuntimeError(RuntimeError):
    """A restoration model could not be loaded or does not match the requested method."""


def select_device() -> Any:
    """CUDA when available, otherwise CPU (the same choice the legacy worker made)."""

    import torch

    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def load_image_model(
    weight_path: str | Path,
    *,
    expected_architecture: str,
    device: Any,
    half: bool = False,
) -> Any:
    """Return an eval-mode Spandrel image-model descriptor on ``device``.

    ``expected_architecture`` is Spandrel's architecture id (``"ESRGAN"`` for RealESRGAN/RRDB
    checkpoints, ``"CodeFormer"``). A checkpoint of another architecture is rejected rather
    than silently run as the wrong method.
    """

    path = Path(weight_path).expanduser()
    if not path.is_file():
        raise RestorationRuntimeError(f"Model weight file not found: {path}")

    import spandrel

    if expected_architecture == "CodeFormer":
        import spandrel_extra_arches

        spandrel_extra_arches.install()

    descriptor = spandrel.ModelLoader().load_from_file(path)
    architecture = str(getattr(descriptor.architecture, "id", descriptor.architecture))
    if architecture != expected_architecture:
        raise RestorationRuntimeError(
            f"{path.name} is a {architecture} checkpoint; {expected_architecture} was requested"
        )
    descriptor.to(device)
    descriptor.eval()
    if half:
        descriptor.half()
    return descriptor
