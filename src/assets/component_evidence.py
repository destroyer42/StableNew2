"""Bounded structural evidence for multi-component image models (PR-IMG-MODELS-150).

Some image checkpoints (FLUX-style transformers) contain only the diffusion transformer: the text encoder and the VAE are
separate files that the serving runtime must load alongside them. This module answers, from a safetensors *header only*
(never a weight, a hash or a scan; the one parser is ``checkpoint_structure.read_tensor_table``):

* is this file a **dependency-bearing transformer** (a FLUX-style DiT that bundles neither a text encoder nor a VAE), and
  what does its header say it needs (the text-encoder hidden size, the VAE latent channels)?
* is this file structurally a Qwen3 text encoder, or a FLUX-family VAE, and how are its tensors stored?

All of it is observational: a structural match is never a qualification, never proof that a file loads, and never
interchangeable with another dtype/quantization. Anything the header does not establish stays ``unrecognized``/``None``.
Diagnostics omit local paths.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from src.assets.checkpoint_structure import (
    _DTYPE_BYTES,
    classify_checkpoint_shapes,
    read_tensor_table,
)

COMPONENT_CONTRACT = "component_evidence/1"

ROLE_TRANSFORMER = "transformer"  # diffusion transformer without a bundled text encoder/VAE (dependency-bearing)
ROLE_TEXT_ENCODER = "text_encoder"
ROLE_VAE = "vae"
ROLE_BUNDLED = "bundled_checkpoint"  # a self-contained checkpoint (for example an SDXL UNet checkpoint)
ROLE_UNRECOGNIZED = "unrecognized"

ARCH_FLUX2_DIT = "flux2_dit"
ARCH_FLUX_DIT = "flux_dit"
ARCH_QWEN3 = "qwen3"
ARCH_FLUX_VAE = "flux_vae"
ARCH_SDXL_UNET = "sdxl_unet_bundle"
ARCH_UNET_BUNDLE_UNRECOGNIZED = "unet_bundle_unrecognized"
ARCH_Z_IMAGE_DIT = "z_image_dit"
ARCH_QWEN_IMAGE_DIT = "qwen_image_dit"
ARCH_QWEN_IMAGE_VAE = "qwen_image_vae"

#: Qwen3 hidden size -> published size label (only when the layer count also matches, see ``_qwen3``).
_QWEN3_SIZES = {2560: "qwen3_4b", 4096: "qwen3_8b"}
_QWEN3_LAYERS = 36
#: FLUX.2-style transformers condition on three stacked encoder hidden states.
_JOINT_STACK = 3
#: FLUX-style DiTs patchify the latent 2x2, so the transformer input is ``4 x latent_channels``.
_PATCH_FACTOR = 4

_BUNDLED_TEXT_ENCODER_PREFIXES = ("cond_stage_model.", "conditioner.", "text_encoders.", "text_encoder.")
_BUNDLED_VAE_PREFIXES = ("first_stage_model.", "vae.")
_QUANTIZED_DTYPES = frozenset({"F8_E4M3", "F8_E5M2", "U8", "I8"})


@dataclass(frozen=True)
class ComponentEvidence:
    """What one safetensors header establishes about a model component."""

    role: str = ROLE_UNRECOGNIZED
    architecture: str = "unrecognized"
    #: Scalar structural facts (hidden size, layer counts, latent channels, dtype ...); no paths.
    facts: Mapping[str, Any] = field(default_factory=dict)
    #: A transformer that needs a separately supplied text encoder and VAE.
    dependency_bearing: bool = False
    error: str | None = None

    def fact(self, name: str, default: Any = None) -> Any:
        return self.facts.get(name, default)


def _prefixed(shapes: Mapping[str, Any], prefix: str) -> bool:
    return any(name.startswith(prefix) for name in shapes)


def _tensor_elements(shape: list[int]) -> int:
    count = 1
    for dimension in shape:
        count *= dimension
    return count


def precision_facts(shapes: Mapping[str, list[int]], dtypes: Mapping[str, str]) -> dict[str, Any]:
    """Every observed dtype with its tensor count and byte share, scale/quantization evidence and a layout verdict.

    A single dominant dtype is never the layout: an FP8-quantized transformer stores most *tensors* as small F32 scales
    and norms and most *bytes* as FP8, so both dominants are reported under their own names. The layout is
    ``plain`` (one float dtype, no scale keys), ``mixed_float`` (several float dtypes, no quantization evidence),
    ``mixed_scaled`` (quantized dtypes plus scale keys) or ``unknown`` (quantized dtypes without scales, or nothing).
    """

    histogram = Counter(dtypes.values())
    by_bytes: Counter[str] = Counter()
    for name, dtype in dtypes.items():
        by_bytes[dtype] += _tensor_elements(shapes.get(name, [])) * _DTYPE_BYTES.get(dtype, 0)
    scale_keys = sum(1 for name in shapes if "scale" in name or "comfy_quant" in name)
    quantized = sorted(dtype for dtype in histogram if dtype in _QUANTIZED_DTYPES)
    floats = {dtype for dtype in histogram if dtype in ("BF16", "F16", "F32")}
    if quantized and scale_keys:
        layout = "mixed_scaled"
    elif quantized:
        layout = "unknown"
    elif len(floats) == 1 and len(histogram) == 1:
        layout = "plain"
    elif len(floats) > 1:
        layout = "mixed_float"
    else:
        layout = "unknown"
    return {
        "dtype_histogram": dict(sorted(histogram.items())),
        "dtype_bytes": {k: int(v) for k, v in sorted(by_bytes.items())},
        "dominant_dtype_by_tensor_count": histogram.most_common(1)[0][0] if histogram else "",
        "dominant_dtype_by_bytes": by_bytes.most_common(1)[0][0] if by_bytes else "",
        "scale_key_count": scale_keys,
        "quantized_dtypes": quantized,
        "precision_layout": layout,
    }


def _dominant_dtype(dtypes: Mapping[str, str]) -> str:
    return Counter(dtypes.values()).most_common(1)[0][0] if dtypes else ""


def _indices(shapes: Mapping[str, Any], pattern: str) -> int:
    matches = {int(m.group(1)) for name in shapes for m in [re.search(pattern, name)] if m}
    return len(matches)


def _strip_transformer_prefix(shapes: Mapping[str, list[int]]) -> dict[str, list[int]]:
    prefix = "model.diffusion_model."
    if any(name.startswith(prefix + "double_blocks.") or name.startswith(prefix + "transformer_blocks.") for name in shapes):
        return {name[len(prefix):] if name.startswith(prefix) else name: shape for name, shape in shapes.items()}
    return dict(shapes)


def _flux_transformer(shapes: Mapping[str, list[int]], dtypes: Mapping[str, str]) -> ComponentEvidence | None:
    table = _strip_transformer_prefix(shapes)
    native = "img_in.weight" in table and "txt_in.weight" in table and _prefixed(table, "double_blocks.")
    diffusers = (
        "x_embedder.weight" in table
        and "context_embedder.weight" in table
        and _prefixed(table, "transformer_blocks.")
    )
    if not native and not diffusers:
        return None
    if native:
        hidden, in_channels = table["img_in.weight"][:2] if len(table["img_in.weight"]) == 2 else (None, None)
        joint = table["txt_in.weight"][1] if len(table["txt_in.weight"]) == 2 else None
        doubles = _indices(table, r"^double_blocks\.(\d+)\.")
        singles = _indices(table, r"^single_blocks\.(\d+)\.")
        flux2 = "double_stream_modulation_img.lin.weight" in table
        key_format = "native"
    else:
        shape = table["x_embedder.weight"]
        hidden, in_channels = (shape[0], shape[1]) if len(shape) == 2 else (None, None)
        joint = table["context_embedder.weight"][1] if len(table["context_embedder.weight"]) == 2 else None
        doubles = _indices(table, r"^transformer_blocks\.(\d+)\.")
        singles = _indices(table, r"^single_transformer_blocks\.(\d+)\.")
        flux2 = "double_stream_modulation_img.linear.weight" in table
        key_format = "diffusers"
    bundled = any(_prefixed(shapes, prefix) for prefix in _BUNDLED_TEXT_ENCODER_PREFIXES + _BUNDLED_VAE_PREFIXES)
    facts: dict[str, Any] = {
        "key_format": key_format,
        "hidden_size": hidden,
        "double_blocks": doubles,
        "single_blocks": singles,
        "input_channels": in_channels,
        "joint_input_dim": joint,
        "dtype": _dominant_dtype(dtypes),
        "tensor_count": len(shapes),
        "bundled_text_encoder_or_vae": bundled,
    }
    if isinstance(joint, int) and flux2 and joint % _JOINT_STACK == 0:
        facts["required_text_encoder_hidden_size"] = joint // _JOINT_STACK
    if isinstance(in_channels, int) and in_channels % _PATCH_FACTOR == 0:
        facts["required_vae_latent_channels"] = in_channels // _PATCH_FACTOR
    return ComponentEvidence(
        ROLE_TRANSFORMER if not bundled else ROLE_BUNDLED,
        ARCH_FLUX2_DIT if flux2 else ARCH_FLUX_DIT,
        facts,
        dependency_bearing=not bundled,
    )


def _z_image_dit(shapes: Mapping[str, list[int]], dtypes: Mapping[str, str]) -> ComponentEvidence | None:
    qkv = shapes.get("layers.0.attention.qkv.weight")
    if not qkv or len(qkv) != 2 or not _prefixed(shapes, "layers.0.adaLN_modulation") or "cap_embedder.0.weight" not in shapes:
        return None
    bundled = any(_prefixed(shapes, prefix) for prefix in _BUNDLED_TEXT_ENCODER_PREFIXES + _BUNDLED_VAE_PREFIXES)
    facts: dict[str, Any] = {
        "hidden_size": qkv[1],
        "layers": _indices(shapes, r"^layers\.(\d+)\."),
        "tensor_count": len(shapes),
        "bundled_text_encoder_or_vae": bundled,
    }
    caption = shapes["cap_embedder.0.weight"]
    if len(caption) == 1:
        facts["required_text_encoder_hidden_size"] = caption[0]  # the caption embedder's input width
    return ComponentEvidence(
        ROLE_TRANSFORMER if not bundled else ROLE_BUNDLED, ARCH_Z_IMAGE_DIT, facts, dependency_bearing=not bundled
    )


def _qwen_image_dit(shapes: Mapping[str, list[int]], dtypes: Mapping[str, str]) -> ComponentEvidence | None:
    img_in, txt_in = shapes.get("img_in.weight"), shapes.get("txt_in.weight")
    if (
        not img_in or not txt_in or len(img_in) != 2 or len(txt_in) != 2
        or "txt_norm.weight" not in shapes
        or "transformer_blocks.0.attn.add_q_proj.weight" not in shapes
    ):
        return None
    bundled = any(_prefixed(shapes, prefix) for prefix in _BUNDLED_TEXT_ENCODER_PREFIXES + _BUNDLED_VAE_PREFIXES)
    facts: dict[str, Any] = {
        "hidden_size": img_in[0],
        "layers": _indices(shapes, r"^transformer_blocks\.(\d+)\."),
        "input_channels": img_in[1],
        "joint_input_dim": txt_in[1],
        "required_text_encoder_hidden_size": txt_in[1],
        "tensor_count": len(shapes),
        "bundled_text_encoder_or_vae": bundled,
    }
    if img_in[1] % _PATCH_FACTOR == 0:
        facts["required_vae_latent_channels"] = img_in[1] // _PATCH_FACTOR
    return ComponentEvidence(
        ROLE_TRANSFORMER if not bundled else ROLE_BUNDLED, ARCH_QWEN_IMAGE_DIT, facts, dependency_bearing=not bundled
    )


def _qwen_image_vae(shapes: Mapping[str, list[int]], dtypes: Mapping[str, str]) -> ComponentEvidence | None:
    decoder_in = shapes.get("decoder.conv1.weight")
    encoder_in = shapes.get("encoder.conv1.weight")
    if (
        not decoder_in or not encoder_in or len(decoder_in) != 5 or len(encoder_in) != 5
        or not _prefixed(shapes, "decoder.upsamples.") or "decoder.head.2.weight" not in shapes
    ):
        return None
    facts: dict[str, Any] = {
        "latent_channels": decoder_in[1],
        "key_format": "3d_video_vae",
        "vae_family": "qwen_image_vae",
        "tensor_count": len(shapes),
    }
    return ComponentEvidence(ROLE_VAE, ARCH_QWEN_IMAGE_VAE, facts)


def _qwen3(shapes: Mapping[str, list[int]], dtypes: Mapping[str, str]) -> ComponentEvidence | None:
    embed = shapes.get("model.embed_tokens.weight") or shapes.get("embed_tokens.weight")
    if not embed or len(embed) != 2 or not any(".self_attn.q_norm.weight" in name for name in shapes):
        return None  # q/k norm tensors distinguish Qwen3 from earlier Qwen decoders
    layers = _indices(shapes, r"layers\.(\d+)\.")
    vocab, hidden = embed
    quantized = any(dtype in _QUANTIZED_DTYPES for dtype in dtypes.values()) or any(
        "scale" in name or "comfy_quant" in name for name in shapes
    )
    facts: dict[str, Any] = {
        "hidden_size": hidden,
        "vocab_size": vocab,
        "layers": layers,
        "dtype": _dominant_dtype(dtypes),
        "quantized": quantized,
        "tensor_count": len(shapes),
    }
    label = _QWEN3_SIZES.get(hidden) if layers == _QWEN3_LAYERS else None
    if label:
        facts["size_label"] = label
    return ComponentEvidence(ROLE_TEXT_ENCODER, ARCH_QWEN3, facts)


def _vae(shapes: Mapping[str, list[int]], dtypes: Mapping[str, str]) -> ComponentEvidence | None:
    conv_in = shapes.get("decoder.conv_in.weight")
    if not conv_in or len(conv_in) != 4 or "decoder.conv_out.weight" not in shapes:
        return None
    mid = "native" if _prefixed(shapes, "decoder.mid.") else "diffusers" if _prefixed(shapes, "decoder.mid_block.") else "unknown"
    latent = conv_in[1]
    has_bn = "bn.running_mean" in shapes
    # The family comes from the layout evidence, never from the channel count alone: several families share 4 channels.
    family = "flux2_vae" if latent == 32 and has_bn else "flux1_ae" if latent == 16 and not has_bn else (
        "ldm_kl_4ch" if latent == 4 else "unknown_vae"
    )
    facts: dict[str, Any] = {
        "latent_channels": latent,
        "key_format": mid,
        "vae_family": family,
        "dtype": _dominant_dtype(dtypes),
        "tensor_count": len(shapes),
        "has_batch_norm_stats": has_bn,
    }
    return ComponentEvidence(ROLE_VAE, ARCH_FLUX_VAE if conv_in[1] in (16, 32) else "vae", facts)


def classify_tensor_table(shapes: Mapping[str, list[int]], dtypes: Mapping[str, str]) -> ComponentEvidence:
    """Classify an already-validated header. First matching structural signature wins; otherwise unrecognized."""

    precision = precision_facts(shapes, dtypes)
    for classify in (_flux_transformer, _z_image_dit, _qwen_image_dit, _qwen3, _qwen_image_vae, _vae):
        found = classify(shapes, dtypes)
        if found is not None:
            return replace(found, facts={**found.facts, **precision})
    if _prefixed(shapes, "model.diffusion_model.input_blocks.") and _prefixed(shapes, "first_stage_model."):
        shape_architecture, _error = classify_checkpoint_shapes(dict(shapes))
        architecture = (
            ARCH_SDXL_UNET if shape_architecture == "sdxl_base"
            else ARCH_UNET_BUNDLE_UNRECOGNIZED if shape_architecture == "unrecognized"
            else shape_architecture  # sd1 / sd2 / sdxl_inpaint / sdxl_refiner: never mislabelled as ordinary SDXL
        )
        return ComponentEvidence(
            ROLE_BUNDLED, architecture,
            {"tensor_count": len(shapes), "checkpoint_architecture": shape_architecture, **precision},
        )
    return ComponentEvidence(facts={"tensor_count": len(shapes), **precision})


def inspect_component_file(path: Path | str) -> ComponentEvidence:
    """Header-only evidence for one local file; never raises, never hashes, never loads tensors."""

    target = Path(path)
    if target.suffix.lower() != ".safetensors":
        return ComponentEvidence(error="unsupported format for structural recognition")
    try:
        shapes, dtypes, _metadata = read_tensor_table(target)
    except (OSError, ValueError, TypeError, UnicodeDecodeError):
        return ComponentEvidence(error="malformed, truncated or unreadable safetensors header")
    return classify_tensor_table(shapes, dtypes)


__all__ = [
    "ARCH_FLUX2_DIT",
    "ARCH_FLUX_DIT",
    "ARCH_FLUX_VAE",
    "ARCH_QWEN3",
    "ARCH_QWEN_IMAGE_DIT",
    "ARCH_QWEN_IMAGE_VAE",
    "ARCH_SDXL_UNET",
    "ARCH_UNET_BUNDLE_UNRECOGNIZED",
    "ARCH_Z_IMAGE_DIT",
    "COMPONENT_CONTRACT",
    "ComponentEvidence",
    "ROLE_BUNDLED",
    "ROLE_TEXT_ENCODER",
    "ROLE_TRANSFORMER",
    "ROLE_UNRECOGNIZED",
    "ROLE_VAE",
    "classify_tensor_table",
    "inspect_component_file",
    "precision_facts",
]
