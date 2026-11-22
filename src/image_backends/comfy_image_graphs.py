"""PR-IMG-COMFY-100: the frozen Comfy still-image graph catalog (pure; no I/O and no Comfy import).

Each graph is one immutable version of an API-format Comfy prompt. Only typed slots are substituted (prompt, seed,
width, height, the output filename prefix and, for structural profiles, verified loader names); every node, link and other value is fixed. Any change is a new
version. ``template_sha256`` hashes the canonical graph with neutral slot values, so a test can pin each version and
catch an accidental edit.

The graphs mirror the official Qwen-Image 2.1 templates with the prompt enhancer removed:
``image_qwen_image_2_1_t2i.json`` (shipped in the pinned managed Comfy's template package) and
``image_qwen_image_2_1_turbo_t2i.json`` (Comfy-Org/workflow_templates). This catalog is separate from the video
``WorkflowRegistry`` on purpose (PR-IMG-100 item 29).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from src.image_backends.comfy_qwen_image_profile import (
    QWEN_IMAGE_20B_FP8_PROFILE_V1,
    QWEN_IMAGE_21_PROFILE_V1,
    QWEN_IMAGE_21_TURBO_PROFILE_V1,
    QwenImageProfile,
)

#: The node whose ``images`` output is the job's one generated image.
SAVE_NODE_ID = "9"
#: The official Turbo sigma schedule (8 steps), verbatim from the template.
QWEN_IMAGE_21_TURBO_SIGMAS = (
    "1.0, 0.978453, 0.95418, 0.926626, 0.89508, 0.845148, 0.704534, 0.414568, 0"
)


class ComfyImageGraphError(ValueError):
    """A graph request is outside the frozen graph's typed slots."""


@dataclass(frozen=True, slots=True)
class GraphSlots:
    prompt: str
    seed: int
    width: int
    height: int
    filename_prefix: str
    diffusion_model: str = ""
    vae: str = ""


def _common_nodes(profile: QwenImageProfile, slots: GraphSlots) -> dict[str, dict[str, Any]]:
    return {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": profile.diffusion_model.filename, "weight_dtype": "default"},
        },
        "2": {
            "class_type": "QwenImage21Cache",
            "inputs": {"model": ["1", 0], "device": "auto", "dtype": "default"},
        },
        "3": {
            "class_type": "CLIPLoader",
            "inputs": {
                "clip_name": profile.text_encoder.filename,
                "type": "qwen_image",
                "device": "default",
            },
        },
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": profile.vae.filename}},
        "5": {
            "class_type": "TextEncodeQwenImage21",
            "inputs": {
                "clip": ["3", 0],
                "prompt": slots.prompt,
                "negative_prompt": "",
                "resolution": 1024,
            },
        },
        "6": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": slots.width, "height": slots.height, "batch_size": 1},
        },
        SAVE_NODE_ID: {
            "class_type": "SaveImage",
            "inputs": {"images": ["8", 0], "filename_prefix": slots.filename_prefix},
        },
    }


def _qwen_image_21_t2i(slots: GraphSlots) -> dict[str, dict[str, Any]]:
    p = QWEN_IMAGE_21_PROFILE_V1
    nodes = _common_nodes(p, slots)
    nodes["7"] = {
        "class_type": "KSampler",
        "inputs": {
            "model": ["2", 0],
            "positive": ["5", 0],
            "negative": ["5", 1],
            "latent_image": ["6", 0],
            "seed": slots.seed,
            "steps": p.steps,
            "cfg": p.cfg_scale,
            "sampler_name": p.sampler,
            "scheduler": p.scheduler,
            "denoise": 1.0,
        },
    }
    nodes["8"] = {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["4", 0]}}
    return nodes


def _qwen_image_21_turbo_t2i(slots: GraphSlots) -> dict[str, dict[str, Any]]:
    p = QWEN_IMAGE_21_TURBO_PROFILE_V1
    nodes = _common_nodes(p, slots)
    nodes["7"] = {"class_type": "RandomNoise", "inputs": {"noise_seed": slots.seed}}
    nodes["10"] = {"class_type": "KSamplerSelect", "inputs": {"sampler_name": p.sampler}}
    nodes["11"] = {"class_type": "ManualSigmas", "inputs": {"sigmas": QWEN_IMAGE_21_TURBO_SIGMAS}}
    nodes["12"] = {
        "class_type": "CFGGuider",
        "inputs": {
            "model": ["2", 0],
            "positive": ["5", 0],
            "negative": ["5", 1],
            "cfg": p.cfg_scale,
        },
    }
    nodes["13"] = {
        "class_type": "SamplerCustomAdvanced",
        "inputs": {
            "noise": ["7", 0],
            "guider": ["12", 0],
            "sampler": ["10", 0],
            "sigmas": ["11", 0],
            "latent_image": ["6", 0],
        },
    }
    nodes["8"] = {"class_type": "VAEDecode", "inputs": {"samples": ["13", 0], "vae": ["4", 0]}}
    return nodes


def _qwen_image_t2i_fp8(slots: GraphSlots) -> dict[str, dict[str, Any]]:
    p = QWEN_IMAGE_20B_FP8_PROFILE_V1
    return {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": slots.diffusion_model or p.model_name,
                "weight_dtype": "fp8_e4m3fn",
            },
        },
        "2": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": 3.1}},
        "3": {
            "class_type": "CLIPLoader",
            "inputs": {
                "clip_name": p.text_encoder.filename,
                "type": "qwen_image",
                "device": "default",
            },
        },
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": slots.vae or p.vae.filename}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["3", 0], "text": slots.prompt}},
        "10": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["3", 0], "text": ""}},
        "6": {
            "class_type": "EmptySD3LatentImage",
            "inputs": {"width": slots.width, "height": slots.height, "batch_size": 1},
        },
        "7": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["2", 0],
                "positive": ["5", 0],
                "negative": ["10", 0],
                "latent_image": ["6", 0],
                "seed": slots.seed,
                "steps": p.steps,
                "cfg": p.cfg_scale,
                "sampler_name": p.sampler,
                "scheduler": p.scheduler,
                "denoise": 1.0,
            },
        },
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["4", 0]}},
        SAVE_NODE_ID: {
            "class_type": "SaveImage",
            "inputs": {"images": ["8", 0], "filename_prefix": slots.filename_prefix},
        },
    }


@dataclass(frozen=True, slots=True)
class SdxlGraphSlots:
    """The typed slots of the SDXL graph (PR-IMG-COMFY-381). Every value is already validated and mapped."""

    checkpoint: str
    positive: str
    negative: str
    seed: int
    steps: int
    cfg: float
    sampler: str
    scheduler: str
    width: int
    height: int
    clip_skip: int
    #: ``(Comfy lora file name, weight)`` pairs, chained in order.
    loras: tuple[tuple[str, float], ...]
    #: A Comfy VAE file name, or ``""`` to decode with the checkpoint's own VAE.
    vae: str
    filename_prefix: str


def _sdxl_t2i(slots: SdxlGraphSlots) -> dict[str, dict[str, Any]]:
    """SDXL txt2img: checkpoint -> LoRA chain -> CLIP skip -> two prompts -> KSampler -> VAE decode -> save.

    Ported from the qualification graph (``tools/qualification/img_backend_qual_100/comfy_graphs.py``) so the comparison
    and production run the same node layout. Node ids are stable: ``1`` checkpoint, ``20+`` LoRAs, ``30`` VAE.
    """

    nodes: dict[str, dict[str, Any]] = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": slots.checkpoint}},
    }
    model: list[Any] = ["1", 0]
    clip: list[Any] = ["1", 1]
    for index, (lora_name, weight) in enumerate(slots.loras):
        node_id = str(20 + index)
        nodes[node_id] = {
            "class_type": "LoraLoader",
            "inputs": {
                "model": model,
                "clip": clip,
                "lora_name": lora_name,
                "strength_model": float(weight),
                "strength_clip": float(weight),
            },
        }
        model, clip = [node_id, 0], [node_id, 1]
    nodes["3"] = {
        "class_type": "CLIPSetLastLayer",
        "inputs": {"clip": clip, "stop_at_clip_layer": -int(slots.clip_skip)},
    }
    nodes["4"] = {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": slots.positive, "clip": ["3", 0]},
    }
    nodes["5"] = {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": slots.negative, "clip": ["3", 0]},
    }
    nodes["6"] = {
        "class_type": "EmptyLatentImage",
        "inputs": {"width": slots.width, "height": slots.height, "batch_size": 1},
    }
    nodes["7"] = {
        "class_type": "KSampler",
        "inputs": {
            "model": model,
            "seed": slots.seed,
            "steps": slots.steps,
            "cfg": float(slots.cfg),
            "sampler_name": slots.sampler,
            "scheduler": slots.scheduler,
            "positive": ["4", 0],
            "negative": ["5", 0],
            "latent_image": ["6", 0],
            "denoise": 1.0,
        },
    }
    vae: list[Any] = ["1", 2]
    if slots.vae:
        nodes["30"] = {"class_type": "VAELoader", "inputs": {"vae_name": slots.vae}}
        vae = ["30", 0]
    nodes["8"] = {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": vae}}
    nodes[SAVE_NODE_ID] = {
        "class_type": "SaveImage",
        "inputs": {"images": ["8", 0], "filename_prefix": slots.filename_prefix},
    }
    return nodes


def canonical_sha256(graph: dict[str, Any]) -> str:
    text = json.dumps(graph, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ComfyImageGraph:
    graph_id: str
    version: str
    profile: QwenImageProfile
    builder: Callable[[GraphSlots], dict[str, dict[str, Any]]]
    #: The ``CLIPLoader`` type the pinned runtime must offer.
    clip_type: str = "qwen_image"
    #: The runtime policy the backend applies after the job (the owned Comfy is stopped on every exit path).
    release_owned_runtime_after_job: bool = True

    def build(
        self,
        *,
        prompt: str,
        seed: int,
        width: int,
        height: int,
        filename_prefix: str,
        diffusion_model: str = "",
        vae: str = "",
    ) -> dict[str, Any]:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ComfyImageGraphError(f"{self.profile.display_name} needs a non-empty prompt")
        if type(seed) is not int or not 0 <= seed < 2**32:
            raise ComfyImageGraphError(
                "seed must be resolved to an integer from 0 through 4294967295"
            )
        if (width, height) not in self.profile.geometries:
            raise ComfyImageGraphError(f"size {width}x{height} is not one of the supported sizes")
        prefix = str(filename_prefix or "")
        if (
            not prefix
            or ".." in prefix.split("/")
            or prefix.startswith(("/", "\\"))
            or ":" in prefix
        ):
            raise ComfyImageGraphError("the output filename prefix must be a relative name")
        return self.builder(GraphSlots(prompt, seed, width, height, prefix, diffusion_model, vae))

    @property
    def required_node_classes(self) -> tuple[str, ...]:
        template = self._template()
        return tuple(sorted({str(node["class_type"]) for node in template.values()}))

    @property
    def template_sha256(self) -> str:
        return canonical_sha256(self._template())

    def _template(self) -> dict[str, Any]:
        width, height = self.profile.geometries[0]
        return self.builder(GraphSlots("<prompt>", 0, width, height, "<prefix>"))

    def reference(self) -> dict[str, str]:
        return {
            "graph_id": self.graph_id,
            "version": self.version,
            "template_sha256": self.template_sha256,
        }


def _valid_prefix(prefix: str) -> bool:
    return (
        bool(prefix)
        and ".." not in prefix.split("/")
        and not prefix.startswith(("/", "\\"))
        and ":" not in prefix
    )


@dataclass(frozen=True, slots=True)
class ComfySdxlGraph:
    """The frozen SDXL txt2img graph version (profile-free: the checkpoint is an operator choice, not a pinned asset)."""

    graph_id: str
    version: str
    builder: Callable[[SdxlGraphSlots], dict[str, dict[str, Any]]]
    #: The runtime policy the backend applies after the job (the owned Comfy is stopped on every exit path).
    release_owned_runtime_after_job: bool = True

    def build(self, slots: SdxlGraphSlots) -> dict[str, Any]:
        if not isinstance(slots.positive, str) or not slots.positive.strip():
            raise ComfyImageGraphError("SDXL needs a non-empty prompt")
        if type(slots.seed) is not int or not 0 <= slots.seed < 2**32:
            raise ComfyImageGraphError(
                "seed must be resolved to an integer from 0 through 4294967295"
            )
        if not _valid_prefix(str(slots.filename_prefix or "")):
            raise ComfyImageGraphError("the output filename prefix must be a relative name")
        return self.builder(slots)

    @property
    def required_node_classes(self) -> tuple[str, ...]:
        return tuple(sorted({str(node["class_type"]) for node in self._template().values()}))

    @property
    def template_sha256(self) -> str:
        return canonical_sha256(self._template())

    def _template(self) -> dict[str, Any]:
        # One LoRA and a VAE loader so the pinned template covers every node class the graph can contain.
        return self.builder(
            SdxlGraphSlots(
                "<checkpoint>", "<positive>", "<negative>", 0, 20, 7.0, "euler", "normal", 1024, 1024, 1,
                (("<lora>", 1.0),), "<vae>", "<prefix>",
            )
        )  # fmt: skip

    def reference(self) -> dict[str, str]:
        return {
            "graph_id": self.graph_id,
            "version": self.version,
            "template_sha256": self.template_sha256,
        }


SDXL_T2I = ComfySdxlGraph("sdxl_t2i", "1.0.0", _sdxl_t2i)

QWEN_IMAGE_21_T2I = ComfyImageGraph(
    "qwen_image_21_t2i", "1.0.0", QWEN_IMAGE_21_PROFILE_V1, _qwen_image_21_t2i
)
QWEN_IMAGE_21_TURBO_T2I = ComfyImageGraph(
    "qwen_image_21_turbo_t2i", "1.0.0", QWEN_IMAGE_21_TURBO_PROFILE_V1, _qwen_image_21_turbo_t2i
)
QWEN_IMAGE_20B_FP8_T2I = ComfyImageGraph(
    "qwen_image_20b_fp8_t2i", "1.0.0", QWEN_IMAGE_20B_FP8_PROFILE_V1, _qwen_image_t2i_fp8
)
_GRAPHS = {
    (g.graph_id, g.version): g
    for g in (QWEN_IMAGE_21_T2I, QWEN_IMAGE_21_TURBO_T2I, QWEN_IMAGE_20B_FP8_T2I)
}


def graph_for_profile(profile: QwenImageProfile) -> ComfyImageGraph:
    graph = _GRAPHS.get((profile.graph_id, profile.graph_version))
    if graph is None or graph.profile is not profile:
        raise ComfyImageGraphError(
            f"No frozen graph {profile.graph_id} v{profile.graph_version} for {profile.display_name}"
        )
    return graph


__all__ = [
    "QWEN_IMAGE_21_T2I",
    "QWEN_IMAGE_21_TURBO_SIGMAS",
    "QWEN_IMAGE_21_TURBO_T2I",
    "SAVE_NODE_ID",
    "SDXL_T2I",
    "ComfyImageGraph",
    "ComfyImageGraphError",
    "ComfySdxlGraph",
    "GraphSlots",
    "SdxlGraphSlots",
    "canonical_sha256",
    "graph_for_profile",
]
