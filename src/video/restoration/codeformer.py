"""CodeFormer face restoration: Spandrel network + the isolated legacy face helper.

Division of labour:
- Spandrel (via spandrel-extra-arches) recognises and builds the CodeFormer network, with output
  bit-identical to the legacy BasicSR architecture for the same checkpoint;
- the face helper (``legacy_face_helper``) detects faces, aligns/crops them and pastes restored
  faces back. It is the one retained legacy component, isolated and documented there;
- this module owns tensor conversion, per-face inference and failure behaviour;
- ``temporal`` (optional, PR-VID-POST-304) keeps the landmarks and the restoration residual
  smooth across the frames of one clip; without it every frame is restored independently.
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
from src.video.restoration.runtime import WORKER_WARNING_PREFIX
from src.video.restoration.temporal import TemporalFaceStabilizer, TrackedFace

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
        temporal: TemporalFaceStabilizer | None = None,
    ) -> None:
        self.device = device if device is not None else select_device()
        self.temporal = temporal
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
        tracked = self._smooth_landmarks(image)
        helper.align_warp_face()
        if not helper.cropped_faces:
            return image.convert("RGB")

        for index, cropped_face in enumerate(helper.cropped_faces):
            restored_face, network_ran = self._restore_face(cropped_face, fidelity)
            if tracked:
                restored_face = self._smooth_face(
                    tracked[index], cropped_face, restored_face, network_ran=network_ran
                )
            helper.add_restored_face(restored_face.astype("uint8"), cropped_face)

        helper.get_inverse_affine(None)
        restored = helper.paste_faces_to_input_image(upsample_img=None, draw_box=False)
        return Image.fromarray(cv2.cvtColor(restored, cv2.COLOR_BGR2RGB)).convert("RGB")

    def _smooth_landmarks(self, image: Any) -> list[TrackedFace]:
        """Replace this frame's detected landmarks with their smoothed track, before the crop is aligned.

        The helper derives each face's affine transform (crop and paste-back) from
        ``all_landmarks_5``, so smoothing them smooths the transform. Returns the tracked faces in
        helper order, or an empty list when temporal smoothing is off or no face was found.
        """

        stabilizer = self.temporal
        if stabilizer is None:
            return []
        import numpy as np

        stabilizer.begin_frame(image)
        tracked = stabilizer.track(list(getattr(self.helper, "all_landmarks_5", [])))
        if tracked:
            self.helper.all_landmarks_5 = [
                np.asarray(face.landmarks, dtype=np.float32) for face in tracked
            ]
        return tracked

    def _smooth_face(
        self, face: TrackedFace, cropped_face: Any, restored_face: Any, *, network_ran: bool
    ) -> Any:
        stabilizer = self.temporal
        if stabilizer is None:
            return restored_face
        if not network_ran:
            # An unrestored face carries no residual; do not let old history half-restore it.
            stabilizer.forget(face.track_id)
            return restored_face
        return stabilizer.blend(face.track_id, cropped_face, restored_face)

    def _restore_face(self, cropped_face: Any, fidelity: float) -> tuple[Any, bool]:
        """Return the restored BGR crop and whether the network actually ran for it."""

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
            sys.stderr.write(
                f"{WORKER_WARNING_PREFIX}CodeFormer inference failed for one face; "
                f"left unrestored: {exc}\n"
            )
            return _tensor_to_bgr(tensor, np, cv2), False
        return _tensor_to_bgr(output, np, cv2), True


def _tensor_to_bgr(tensor: Any, np: Any, cv2: Any) -> Any:
    """Map a [-1, 1] RGB tensor to an 8-bit BGR image (BasicSR ``tensor2img`` semantics)."""

    value = tensor.squeeze(0).float().detach().cpu().clamp_(-1, 1)
    value = (value - -1) / (1 - -1)
    image = value.numpy().transpose(1, 2, 0)
    image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    return (image * 255.0).round().astype(np.uint8)
