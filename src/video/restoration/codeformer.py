"""CodeFormer face restoration: Spandrel network + the isolated legacy face helper.

Division of labour:
- Spandrel (via spandrel-extra-arches) recognises and builds the CodeFormer network, with output
  bit-identical to the legacy BasicSR architecture for the same checkpoint;
- the face helper (``legacy_face_helper``) detects faces, aligns/crops them and pastes restored
  faces back. It is the one retained legacy component, isolated and documented there;
- this module owns tensor conversion, per-face inference and failure behaviour.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from src.video.restoration.legacy_face_helper import (
    REQUIRED_FACELIB_FILES,
    build_face_restore_helper,
    require_facelib_files,
)
from src.video.restoration.model_loader import load_image_model, select_device

__all__ = ["REQUIRED_FACELIB_FILES", "CodeFormerRestorer", "require_facelib_files"]


class CodeFormerRestorer:
    """Restore every detected face in an RGB frame; frames without faces pass through."""

    def __init__(
        self,
        *,
        weight_path: str,
        facelib_model_root: str,
        device: Any = None,
        helper: Any = None,
        model: Any = None,
    ) -> None:
        self.device = device if device is not None else select_device()
        if helper is None:
            helper = build_face_restore_helper(Path(facelib_model_root).expanduser(), self.device)
        self.helper = helper
        if model is None:
            model = load_image_model(
                weight_path, expected_architecture="CodeFormer", device=self.device
            ).model
        self.model = model

    def restore(self, image: Any, *, fidelity: float) -> Any:
        """Return the restored RGB ``PIL.Image`` (the input, unchanged, when no face is found)."""

        import cv2
        import numpy as np
        from PIL import Image

        helper = self.helper
        helper.clean_all()
        bgr = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)
        helper.read_image(bgr)
        helper.get_face_landmarks_5(only_center_face=False, resize=640, eye_dist_threshold=5)
        helper.align_warp_face()
        if not helper.cropped_faces:
            return image.convert("RGB")

        for cropped_face in helper.cropped_faces:
            restored_face = self._restore_face(cropped_face, fidelity)
            helper.add_restored_face(restored_face.astype("uint8"), cropped_face)

        helper.get_inverse_affine(None)
        restored = helper.paste_faces_to_input_image(upsample_img=None, draw_box=False)
        return Image.fromarray(cv2.cvtColor(restored, cv2.COLOR_BGR2RGB)).convert("RGB")

    def _restore_face(self, cropped_face: Any, fidelity: float) -> Any:
        import cv2
        import numpy as np
        import torch

        tensor = torch.from_numpy(
            cv2.cvtColor((cropped_face / 255.0).astype("float32"), cv2.COLOR_BGR2RGB).transpose(
                2, 0, 1
            )
        ).float()
        tensor = ((tensor - 0.5) / 0.5).unsqueeze(0).to(self.device)
        try:
            with torch.no_grad():
                # Spandrel's CodeFormer takes the fidelity as `weight` (it applies adain itself); a
                # `w=` keyword would be swallowed by **kwargs and silently default to 0.5.
                output = self.model(tensor, weight=fidelity)[0]
        except Exception as exc:
            # Pre-existing behaviour, kept so output does not change: a face that cannot be
            # restored is pasted back unrestored. It is reported instead of being silent.
            sys.stderr.write(f"CodeFormer inference failed for one face; left unrestored: {exc}\n")
            output = tensor
        return _tensor_to_bgr(output, np, cv2)


def _tensor_to_bgr(tensor: Any, np: Any, cv2: Any) -> Any:
    """Map a [-1, 1] RGB tensor to an 8-bit BGR image (BasicSR ``tensor2img`` semantics)."""

    value = tensor.squeeze(0).float().detach().cpu().clamp_(-1, 1)
    value = (value - -1) / (1 - -1)
    image = value.numpy().transpose(1, 2, 0)
    image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    return (image * 255.0).round().astype(np.uint8)
