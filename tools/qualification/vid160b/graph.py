"""Frozen minimal Wan2.2-Animate-14B GGUF Move-mode resource-probe graph (stock nodes only).

Deliberately smaller than a real Move-mode graph: no ``pose_video``/``face_video``/
``background_video``/``character_mask`` inputs, so no ``comfyui_controlnet_aux``, ``KJNodes`` or
``SAM2`` custom node is required. ``WanAnimateToVideo`` accepts all of those as optional; omitting
them still forces the full 14B transformer load, text encoder, CLIP Vision reference-image path,
VAE encode/decode, and a complete ``KSampler`` denoise loop -- the dominant cost of a real run --
so a PASS establishes only a resource floor, not Move-mode motion-transfer feasibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

Workflow = dict[str, dict[str, Any]]

# Already present in the target Comfy installation; reused rather than re-downloaded.
CLIP_FILENAME = "umt5_xxl_fp8_e4m3fn_scaled.safetensors"
VAE_FILENAME = "wan_2.1_vae.safetensors"

# Frozen for this probe (Phase D / Phase B assets).
UNET_GGUF_FILENAME = "Wan2.2-Animate-14B-Q3_K_M.gguf"
CLIP_VISION_FILENAME = "clip_vision_h.safetensors"


@dataclass(frozen=True)
class ProbeSpec:
    reference_image: str  # server-side uploaded filename
    width: int = 256
    height: int = 256
    length: int = 13  # 1 + 4k latent frames -> 4 latent frames
    steps: int = 4
    cfg: float = 5.0
    shift: float = 8.0
    seed: int = 1733123036
    sampler: str = "uni_pc"
    scheduler: str = "simple"
    positive_prompt: str = "a person"
    negative_prompt: str = ""
    fps: float = 8.0
    prefix: str = "vid160b_probe"


def build_probe_graph(spec: ProbeSpec) -> Workflow:
    """The one frozen graph submitted by this probe: stock nodes + ``UnetLoaderGGUF`` only."""

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
        "WanAnimateToVideo",
        "KSampler",
        "TrimVideoLatent",
        "VAEDecode",
        "CreateVideo",
        "SaveVideo",
    }
)


def validate_graph(graph: Workflow) -> list[str]:
    """Structural problems: unknown node class, or a link to a missing node id."""

    problems: list[str] = []
    for node_id, node in graph.items():
        if node["class_type"] not in REQUIRED_NODE_CLASSES:
            problems.append(f"node {node_id}: non-frozen class {node['class_type']}")
        for value in node["inputs"].values():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                if value[0] not in graph:
                    problems.append(f"node {node_id}: dangling link to missing node {value[0]}")
    return problems
