"""Stock-node ComfyUI API workflows for the qualification lanes (never registered in src/).

Both builders use only nodes shipped with ComfyUI 0.3.65; every dependency file is a
named parameter so the exact revision under test is recorded with the run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

Workflow = dict[str, dict[str, Any]]

LANE_A_FILES = {
    "diffusion_models": ["wan2.2_ti2v_5B_fp16.safetensors"],
    "text_encoders": ["umt5_xxl_fp8_e4m3fn_scaled.safetensors"],
    "vae": ["wan2.2_vae.safetensors"],
}
LANE_B_FILES = {
    "diffusion_models": ["wan2.1_vace_1.3B_fp16.safetensors"],
    "text_encoders": ["umt5_xxl_fp8_e4m3fn_scaled.safetensors"],
    "vae": ["wan_2.1_vae.safetensors"],
}
STOCK_NODE_CLASSES = frozenset(
    {
        "UNETLoader",
        "CLIPLoader",
        "VAELoader",
        "ModelSamplingSD3",
        "CLIPTextEncode",
        "LoadImage",
        "LoadVideo",
        "GetVideoComponents",
        "ImageScale",
        "Canny",
        "Wan22ImageToVideoLatent",
        "WanVaceToVideo",
        "KSampler",
        "TrimVideoLatent",
        "VAEDecode",
        "CreateVideo",
        "SaveVideo",
    }
)
DEFAULT_NEGATIVE = (
    "static, still image, blurry, low quality, worst quality, extra limbs, extra fingers, "
    "deformed hands, distorted body, cropped, watermark, subtitles"
)


@dataclass(frozen=True)
class GenerationSpec:
    prompt: str
    negative: str = DEFAULT_NEGATIVE
    width: int = 832
    height: int = 480
    length: int = 49  # 1 + 4k latent frames
    fps: float = 24.0
    steps: int = 20
    cfg: float = 5.0
    shift: float = 8.0
    seed: int = 12345
    sampler: str = "uni_pc"
    scheduler: str = "simple"


def _text_encoders(spec: GenerationSpec) -> Workflow:
    return {
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": spec.prompt, "clip": ["2", 0]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": spec.negative, "clip": ["2", 0]}},
    }


def _loaders(unet: str, clip: str, vae: str) -> Workflow:
    return {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": unet, "weight_dtype": "default"},
        },
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": clip, "type": "wan"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": vae}},
    }


def _tail(
    spec: GenerationSpec, prefix: str, *, sampler_latent: list[Any], trim: list[Any] | None
) -> Workflow:
    graph: Workflow = {
        "9": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["4", 0],
                "seed": spec.seed,
                "steps": spec.steps,
                "cfg": spec.cfg,
                "sampler_name": spec.sampler,
                "scheduler": spec.scheduler,
                "positive": ["5", 0] if trim is None else ["20", 0],
                "negative": ["6", 0] if trim is None else ["20", 1],
                "latent_image": sampler_latent,
                "denoise": 1.0,
            },
        }
    }
    decode_source: list[Any] = ["9", 0]
    if trim is not None:
        graph["21"] = {
            "class_type": "TrimVideoLatent",
            "inputs": {"samples": ["9", 0], "trim_amount": trim},
        }
        decode_source = ["21", 0]
    graph["10"] = {"class_type": "VAEDecode", "inputs": {"samples": decode_source, "vae": ["3", 0]}}
    graph["11"] = {"class_type": "CreateVideo", "inputs": {"images": ["10", 0], "fps": spec.fps}}
    graph["12"] = {
        "class_type": "SaveVideo",
        "inputs": {
            "video": ["11", 0],
            "filename_prefix": prefix,
            "format": "auto",
            "codec": "auto",
        },
    }
    return graph


def build_lane_a(
    spec: GenerationSpec, source_image: str | None, *, prefix: str = "vid110/laneA"
) -> Workflow:
    """Wan2.2 TI2V-5B through stock native nodes: image-to-video, or text-to-video when
    ``source_image`` is None (used only to make a neutral owned source still)."""

    files = LANE_A_FILES
    graph = _loaders(files["diffusion_models"][0], files["text_encoders"][0], files["vae"][0])
    graph.update(_text_encoders(spec))
    graph["4"] = {
        "class_type": "ModelSamplingSD3",
        "inputs": {"model": ["1", 0], "shift": spec.shift},
    }
    latent_inputs: dict[str, Any] = {
        "vae": ["3", 0],
        "width": spec.width,
        "height": spec.height,
        "length": spec.length,
        "batch_size": 1,
    }
    if source_image is not None:
        graph["7"] = {"class_type": "LoadImage", "inputs": {"image": source_image}}
        latent_inputs["start_image"] = ["7", 0]
    graph["8"] = {"class_type": "Wan22ImageToVideoLatent", "inputs": latent_inputs}
    graph.update(_tail(spec, prefix, sampler_latent=["8", 0], trim=None))
    return graph


def build_lane_b(
    spec: GenerationSpec,
    reference_image: str,
    control_video: str | None,
    *,
    strength: float = 1.0,
    control: str = "canny",
    prefix: str = "vid110/laneB",
) -> Workflow:
    """Wan2.1 VACE-1.3B with a reference image and, when given, a control video.

    ``control="canny"`` edge-detects the driving frames (stock ``Canny``); ``control="raw"``
    feeds the video as-is, for a pre-rendered pose-skeleton video that carries no scene RGB.

    ``control_video=None`` is the reference-image + prompt (no motion-transfer) variant.
    """

    files = LANE_B_FILES
    graph = _loaders(files["diffusion_models"][0], files["text_encoders"][0], files["vae"][0])
    graph.update(_text_encoders(spec))
    graph["4"] = {
        "class_type": "ModelSamplingSD3",
        "inputs": {"model": ["1", 0], "shift": spec.shift},
    }
    graph["7"] = {"class_type": "LoadImage", "inputs": {"image": reference_image}}
    vace_inputs: dict[str, Any] = {
        "positive": ["5", 0],
        "negative": ["6", 0],
        "vae": ["3", 0],
        "width": spec.width,
        "height": spec.height,
        "length": spec.length,
        "batch_size": 1,
        "strength": strength,
        "reference_image": ["7", 0],
    }
    if control_video is not None:
        graph["14"] = {"class_type": "LoadVideo", "inputs": {"file": control_video}}
        graph["15"] = {"class_type": "GetVideoComponents", "inputs": {"video": ["14", 0]}}
        graph["16"] = {
            "class_type": "ImageScale",
            "inputs": {
                "image": ["15", 0],
                "upscale_method": "lanczos",
                "width": spec.width,
                "height": spec.height,
                "crop": "center",
            },
        }
        if control == "canny":
            graph["17"] = {
                "class_type": "Canny",
                "inputs": {"image": ["16", 0], "low_threshold": 0.2, "high_threshold": 0.6},
            }
            vace_inputs["control_video"] = ["17", 0]
        else:
            vace_inputs["control_video"] = ["16", 0]
    graph["20"] = {"class_type": "WanVaceToVideo", "inputs": vace_inputs}
    graph.update(_tail(spec, prefix, sampler_latent=["20", 2], trim=["20", 3]))
    return graph


def validate_graph(graph: Workflow) -> list[str]:
    """Structural problems: dangling links, unknown/non-stock node classes."""

    problems: list[str] = []
    for node_id, node in graph.items():
        if node["class_type"] not in STOCK_NODE_CLASSES:
            problems.append(f"node {node_id}: non-stock class {node['class_type']}")
        for name, value in node["inputs"].items():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                if value[0] not in graph:
                    problems.append(f"node {node_id}.{name} links to missing node {value[0]}")
    return problems
