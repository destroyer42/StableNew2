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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.assets.checkpoint_structure import read_tensor_table

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
    facts: dict[str, Any] = {
        "latent_channels": conv_in[1],
        "key_format": mid,
        "dtype": _dominant_dtype(dtypes),
        "tensor_count": len(shapes),
        "has_batch_norm_stats": "bn.running_mean" in shapes,
    }
    return ComponentEvidence(ROLE_VAE, ARCH_FLUX_VAE if conv_in[1] in (16, 32) else "vae", facts)


def classify_tensor_table(shapes: Mapping[str, list[int]], dtypes: Mapping[str, str]) -> ComponentEvidence:
    """Classify an already-validated header. First matching structural signature wins; otherwise unrecognized."""

    for classify in (_flux_transformer, _qwen3, _vae):
        found = classify(shapes, dtypes)
        if found is not None:
            return found
    if _prefixed(shapes, "model.diffusion_model.input_blocks.") and _prefixed(shapes, "first_stage_model."):
        return ComponentEvidence(ROLE_BUNDLED, ARCH_SDXL_UNET, {"tensor_count": len(shapes)})
    return ComponentEvidence(facts={"tensor_count": len(shapes)})


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
    "ARCH_SDXL_UNET",
    "COMPONENT_CONTRACT",
    "ComponentEvidence",
    "ROLE_BUNDLED",
    "ROLE_TEXT_ENCODER",
    "ROLE_TRANSFORMER",
    "ROLE_UNRECOGNIZED",
    "ROLE_VAE",
    "classify_tensor_table",
    "inspect_component_file",
]
