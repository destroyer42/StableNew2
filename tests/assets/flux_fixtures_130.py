"""Synthetic header-only FLUX fixtures for PR-IMG-FLUX-130 (no weights, no model bytes, nothing loaded).

Tensor tables carry the *real* FLUX shapes (so the classifier sees the true signatures) but only a few representative tensors
per block. A GGUF fixture is a bounded header plus tensor-info table with no tensor data at all; a safetensors fixture is a
dict pair handed straight to ``classify_tensor_table`` (real-size safetensors files would be gigabytes).
"""

from __future__ import annotations

import struct
from pathlib import Path

#: ggml tensor type ids used below.
GGML_F32, GGML_F16, GGML_Q4_K, GGML_Q6_K, GGML_Q8_0, GGML_BF16 = 0, 1, 12, 14, 8, 30
#: llama.cpp file types (``general.file_type``).
FTYPE_Q4_K_S, FTYPE_Q6_K, FTYPE_Q8_0, FTYPE_F16 = 14, 18, 7, 1


def flux1_table(
    *,
    guidance: bool = True,
    prefix: str = "",
    hidden: int = 3072,
    doubles: int = 19,
    singles: int = 38,
    bundled: bool = False,
) -> dict[str, list[int]]:
    """The FLUX.1 12B transformer layout (dev when ``guidance``; schnell without the guidance embedding)."""

    table: dict[str, list[int]] = {
        "img_in.weight": [hidden, 64],
        "txt_in.weight": [hidden, 4096],
        "time_in.in_layer.weight": [hidden, 256],
        "vector_in.in_layer.weight": [hidden, 768],
        "final_layer.linear.weight": [64, hidden],
    }
    if guidance:
        table["guidance_in.in_layer.weight"] = [hidden, 256]
    for index in range(doubles):
        table[f"double_blocks.{index}.img_attn.qkv.weight"] = [hidden * 3, hidden]
    for index in range(singles):
        table[f"single_blocks.{index}.linear1.weight"] = [hidden * 7, hidden]
    table = {prefix + name: shape for name, shape in table.items()}
    if bundled:
        table["text_encoders.clip_l.transformer.text_model.embeddings.token_embedding.weight"] = [
            49408,
            768,
        ]
        table["vae.decoder.conv_in.weight"] = [512, 16, 3, 3]
    return table


def klein_table(size: str) -> dict[str, list[int]]:
    """FLUX.2 Klein 4B or 9B native layout."""

    hidden, doubles, singles, encoder = {"4b": (3072, 5, 20, 2560), "9b": (4096, 8, 24, 4096)}[size]
    table: dict[str, list[int]] = {
        "img_in.weight": [hidden, 128],
        "txt_in.weight": [hidden, encoder * 3],
        "double_stream_modulation_img.lin.weight": [hidden * 6, hidden],
        "final_layer.linear.weight": [128, hidden],
    }
    for index in range(doubles):
        table[f"double_blocks.{index}.img_attn.qkv.weight"] = [hidden * 3, hidden]
    for index in range(singles):
        table[f"single_blocks.{index}.linear1.weight"] = [hidden * 9, hidden]
    return table


def unrecognized_dit_table() -> dict[str, list[int]]:
    """A transformer-only DiT no pinned runtime knows (the shape of the installed flux3Klein file)."""

    table: dict[str, list[int]] = {
        "txt_in.weight": [3072, 7680],
        "time_in.in_layer.weight": [3072, 256],
        "x_in.weight": [3072, 128],
    }
    for index in range(4):
        table[f"single_blocks.{index}.linear1.weight"] = [3072 * 9, 3072]
    return table


def qwen3_vl_table() -> dict[str, list[int]]:
    table: dict[str, list[int]] = {
        "model.language_model.embed_tokens.weight": [151936, 2560],
        "model.visual.patch_embed.proj.weight": [1024, 3, 2, 16, 16],
    }
    for index in range(4):
        table[f"model.language_model.layers.{index}.self_attn.q_norm.weight"] = [128]
    return table


def dtypes_of(table: dict[str, list[int]], dtype: str = "BF16") -> dict[str, str]:
    return dict.fromkeys(table, dtype)


def fp8_scaled(table: dict[str, list[int]]) -> tuple[dict[str, list[int]], dict[str, str]]:
    """The same layout stored FP8 with per-tensor scales (``mixed_scaled``)."""

    shapes = dict(table)
    dtypes = dict.fromkeys(table, "F8_E4M3")
    for name in list(table):
        if name.endswith(".weight"):
            scale = name[: -len(".weight")] + ".scale_weight"
            shapes[scale] = [1]
            dtypes[scale] = "F32"
    return shapes, dtypes


def _string(text: str) -> bytes:
    raw = text.encode("utf-8")
    return struct.pack("<Q", len(raw)) + raw


def write_gguf(
    path: Path,
    table: dict[str, list[int]],
    *,
    tensor_type: int = GGML_Q4_K,
    file_type: int | None = FTYPE_Q4_K_S,
    architecture: str = "flux",
) -> Path:
    """A GGUF v3 header + tensor-info table (dims stored fastest first) with no tensor data."""

    pairs = [_string("general.architecture") + struct.pack("<I", 8) + _string(architecture)]
    if file_type is not None:
        pairs.append(
            _string("general.file_type") + struct.pack("<I", 4) + struct.pack("<I", file_type)
        )
    infos = []
    for offset, (name, shape) in enumerate(table.items()):
        dims = list(reversed(shape))
        infos.append(
            _string(name)
            + struct.pack("<I", len(dims))
            + b"".join(struct.pack("<Q", d) for d in dims)
            + struct.pack("<IQ", tensor_type, offset * 32)
        )
    data = (
        b"GGUF" + struct.pack("<IQQ", 3, len(table), len(pairs)) + b"".join(pairs) + b"".join(infos)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path
