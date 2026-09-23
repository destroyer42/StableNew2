"""Frozen PR-VID-170 characterization graph: the same node shape as PR-VID-160C's pose-driven
graph (``UnetLoaderGGUF`` -> ... -> ``WanAnimateToVideo`` -> ``KSampler`` -> ``VAEDecode`` ->
``SaveVideo``, with ``LoadVideo``/``GetVideoComponents`` feeding ``pose_video``), but with sampling
settings replaced by the official Wan2.2-Animate-14B defaults (see PR-VID-170 report, Phase A) in
place of PR-VID-160B/C's resource-testing settings. ``face_video`` remains absent.

Sourced directly from ``Wan-Video/Wan2.2``'s ``wan/configs/wan_animate_14B.py``:
``sample_steps=20``, ``sample_shift=5.0``, ``sample_guide_scale=1.0``, default ``prompt``
(quoted verbatim below); and ``generate.py``'s ``--sample_solver`` default ``'unipc'`` (not
``'dpm++'``, which is only the other available choice), which maps directly and unambiguously to
the already-used local Comfy ``uni_pc`` sampler -- no inference/ambiguous mapping was needed.
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
    "OFFICIAL_DEFAULT_PROMPT",
    "CharacterizationSpec",
    "build_characterization_graph",
    "validate_graph",
    "REQUIRED_NODE_CLASSES",
]

# The official Wan2.2-Animate-14B default prompt (wan/configs/wan_animate_14B.py: prompt =
# '视频中的人在做动作', "the person in the video is performing an action"), used verbatim and
# unchanged across all three cases: Animate is motion-driven via pose_video, not text-driven, so a
# minimal neutral content prompt -- the model's own documented default -- is preferred over
# attempting to steer motion through text.
OFFICIAL_DEFAULT_PROMPT = "视频中的人在做动作"


@dataclass(frozen=True)
class CharacterizationSpec:
    reference_image: str  # server-side uploaded filename (identical across all cases)
    pose_video_file: str  # server-side staged video filename (Comfy input dir); only this differs
    width: int = 256
    height: int = 256
    length: int = 13
    steps: int = 20  # official sample_steps
    cfg: float = 1.0  # official sample_guide_scale
    shift: float = 5.0  # official sample_shift
    seed: int = 1733123036
    sampler: str = "uni_pc"  # official sample_solver 'unipc', direct mapping
    scheduler: str = "simple"
    positive_prompt: str = OFFICIAL_DEFAULT_PROMPT
    negative_prompt: str = ""
    fps: float = 8.0
    prefix: str = "vid170_probe"


def build_characterization_graph(spec: CharacterizationSpec) -> Workflow:
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
