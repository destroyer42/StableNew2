"""OpenPose input/modality feedback; no inference, mutation or model loading (PR-IMG-CNET-211)."""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class PoseModelHint:
    status: str
    source: str
    detail: str


def pose_model_hint(name: str) -> PoseModelHint:
    """Name hints are explicitly distinct from architecture evidence and weight qualification.

    Only these known, incompatible model identities are refused. Unrecognized/renamed weights remain unverified;
    an OpenPose-looking name is not proof of training modality. No fuzzy negative substring gate.
    """

    from src.assets.controlnet_structure import name_key

    key = name_key(name)
    known_other = {
        "diffusers_xl_depth_full": "depth",
        "ttplanetsdxlcontrolnet_v20fp16": "tile",
    }
    if key in known_other:
        return PoseModelHint("incompatible", "known_model_name", known_other[key])
    if "openpose" in key:
        return PoseModelHint(
            "unverified",
            "model_name_hint",
            "name suggests OpenPose; tensor widths do not prove modality",
        )
    return PoseModelHint("unverified", "none", "OpenPose training modality is unverified")


def input_image_facts(data: bytes) -> dict[str, Any]:
    """Facts about already validated bytes, read off Tk. Never normalize or rewrite conditioning intent."""

    from PIL import Image

    with Image.open(io.BytesIO(data)) as image:
        image.load()
        transparent = False
        if "A" in image.getbands() or "transparency" in image.info:
            transparent = image.convert("RGBA").getchannel("A").getextrema()[0] < 255
        return {
            "width": image.width,
            "height": image.height,
            "format": image.format,
            "has_transparency": transparent,
        }


def geometry_feedback(
    width: int, height: int, resize_mode: str, *, target: tuple[int, int] | None = None
) -> str:
    semantics = {
        "Just Resize": "stretches the pose to the target; body proportions can change",
        "Crop and Resize": "fills the target and crops edges; hands or feet can be removed",
        "Resize and Fill": "fits the pose and pads borders; subject scale can change",
    }
    text = f"Pose canvas {width}x{height}. {resize_mode} {semantics[resize_mode]}."
    if target is not None and target[0] > 0 and target[1] > 0:
        text += f" Target {target[0]}x{target[1]}."
        if width * target[1] != height * target[0]:
            text += " Aspect ratios differ; inspect the pose framing before running."
    return text
