"""Frozen VID-160C graph: the exact VID-160B backbone graph plus the minimum stock nodes needed
to supply a real ``pose_video`` to ``WanAnimateToVideo`` -- the only material inference-path
difference from PR-VID-160B's ``ANIMATE_BACKBONE_RESOURCE_FLOOR_PASS`` graph. ``face_video``,
``background_video``, and ``character_mask`` remain omitted.

``LoadVideo`` and ``GetVideoComponents`` are the same already-accepted stock nodes
``tools/qualification/vid110/workflows.py`` uses for its VACE control-video lanes; no new custom
node is required.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tools.qualification.vid160b.graph import (
    CLIP_FILENAME,
    CLIP_VISION_FILENAME,
    UNET_GGUF_FILENAME,
    VAE_FILENAME,
)

Workflow = dict[str, dict[str, Any]]

__all__ = [
    "CLIP_FILENAME",
    "CLIP_VISION_FILENAME",
    "UNET_GGUF_FILENAME",
    "VAE_FILENAME",
    "PoseProbeSpec",
    "build_pose_probe_graph",
    "validate_graph",
    "REQUIRED_NODE_CLASSES",
]


@dataclass(frozen=True)
class PoseProbeSpec:
    reference_image: str  # server-side uploaded filename (identical to VID-160B)
    pose_video_file: str  # server-side staged video filename (Comfy input dir)
    width: int = 256
    height: int = 256
    length: int = 13
    steps: int = 4
    cfg: float = 5.0
    shift: float = 8.0
    seed: int = 1733123036
    sampler: str = "uni_pc"
    scheduler: str = "simple"
    positive_prompt: str = "a person"
    negative_prompt: str = ""
    fps: float = 8.0
    prefix: str = "vid160c_pose_probe"


def build_pose_probe_graph(spec: PoseProbeSpec) -> Workflow:
    """The frozen VID-160C graph: VID-160B's graph plus ``LoadVideo``/``GetVideoComponents`` wired
    into ``WanAnimateToVideo.pose_video``. No ``face_video``."""

    if spec.width % 16 or spec.height % 16:
        raise ValueError("width/height must be divisible by 16")
    if (spec.length - 1) % 4:
        raise ValueError("length must be 1 + a multiple of 4")

    graph: Workflow = {
        "1": {
            "class_type": "UnetLoaderGGUF",
            "inputs": {"unet_name": UNET_GGUF_FILENAME},
        },
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": CLIP_FILENAME, "type": "wan"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VAE_FILENAME}},
        "4": {"class_type": "CLIPVisionLoader", "inputs": {"clip_name": CLIP_VISION_FILENAME}},
        "5": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": spec.positive_prompt, "clip": ["2", 0]},
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": spec.negative_prompt, "clip": ["2", 0]},
        },
        "7": {"class_type": "LoadImage", "inputs": {"image": spec.reference_image}},
        "8": {
            "class_type": "CLIPVisionEncode",
            "inputs": {"clip_vision": ["4", 0], "image": ["7", 0], "crop": "center"},
        },
        "9": {
            "class_type": "ModelSamplingSD3",
            "inputs": {"model": ["1", 0], "shift": spec.shift},
        },
        "16": {"class_type": "LoadVideo", "inputs": {"file": spec.pose_video_file}},
        "17": {"class_type": "GetVideoComponents", "inputs": {"video": ["16", 0]}},
        "10": {
            "class_type": "WanAnimateToVideo",
            "inputs": {
                "positive": ["5", 0],
                "negative": ["6", 0],
                "vae": ["3", 0],
                "width": spec.width,
                "height": spec.height,
                "length": spec.length,
                "batch_size": 1,
                "clip_vision_output": ["8", 0],
                "reference_image": ["7", 0],
                "pose_video": ["17", 0],
                "continue_motion_max_frames": 5,
                "video_frame_offset": 0,
            },
        },
        "11": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["9", 0],
                "seed": spec.seed,
                "steps": spec.steps,
                "cfg": spec.cfg,
                "sampler_name": spec.sampler,
                "scheduler": spec.scheduler,
                "positive": ["10", 0],
                "negative": ["10", 1],
                "latent_image": ["10", 2],
                "denoise": 1.0,
            },
        },
        "12": {
            "class_type": "TrimVideoLatent",
            "inputs": {"samples": ["11", 0], "trim_amount": ["10", 3]},
        },
        "13": {"class_type": "VAEDecode", "inputs": {"samples": ["12", 0], "vae": ["3", 0]}},
        "14": {"class_type": "CreateVideo", "inputs": {"images": ["13", 0], "fps": spec.fps}},
        "15": {
            "class_type": "SaveVideo",
            "inputs": {
                "video": ["14", 0],
                "filename_prefix": spec.prefix,
                "format": "auto",
                "codec": "auto",
            },
        },
    }
    return graph


REQUIRED_NODE_CLASSES = frozenset(
    {
        "UnetLoaderGGUF",
        "CLIPLoader",
        "VAELoader",
        "CLIPVisionLoader",
        "CLIPTextEncode",
        "LoadImage",
        "CLIPVisionEncode",
        "ModelSamplingSD3",
        "LoadVideo",
        "GetVideoComponents",
        "WanAnimateToVideo",
        "KSampler",
        "TrimVideoLatent",
        "VAEDecode",
        "CreateVideo",
        "SaveVideo",
    }
)


def validate_graph(graph: Workflow) -> list[str]:
    """Structural checks plus the two VID-160C-specific contract checks: ``pose_video`` present,
    ``face_video`` absent."""

    problems: list[str] = []
    for node_id, node in graph.items():
        if node["class_type"] not in REQUIRED_NODE_CLASSES:
            problems.append(f"node {node_id}: non-frozen class {node['class_type']}")
        for value in node["inputs"].values():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                if value[0] not in graph:
                    problems.append(f"node {node_id}: dangling link to missing node {value[0]}")
    animate = graph.get("10", {}).get("inputs", {})
    if "pose_video" not in animate:
        problems.append("node 10: WanAnimateToVideo missing pose_video input")
    elif animate["pose_video"] != ["17", 0]:
        problems.append("node 10: pose_video not wired to GetVideoComponents images output")
    if "face_video" in animate:
        problems.append("node 10: WanAnimateToVideo must not include face_video")
    return problems
