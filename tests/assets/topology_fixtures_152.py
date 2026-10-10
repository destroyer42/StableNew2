"""Tiny synthetic safetensors/GGUF/WebUI-tree fixtures for the PR-IMG-MODELS-152 topology tests.

Only headers are real; tensor payloads are sparse zero bytes. No model, weight, GPU, network or backend is involved.
"""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path

DTYPE_BYTES = {"F32": 4, "F16": 2, "BF16": 2, "F8_E4M3": 1, "U8": 1}


def safetensors(
    path: Path, tensors: dict[str, tuple[str, list[int]]], metadata: dict | None = None
) -> Path:
    header: dict = {}
    if metadata is not None:
        header["__metadata__"] = metadata
    offset = 0
    for name, (dtype, shape) in tensors.items():
        end = offset + math.prod(shape) * DTYPE_BYTES[dtype]
        header[name] = {"dtype": dtype, "shape": shape, "data_offsets": [offset, end]}
        offset = end
    encoded = json.dumps(header).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        stream.write(struct.pack("<Q", len(encoded)) + encoded)
        stream.truncate(8 + len(encoded) + offset)
    return path


def raw_file(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


# ------------------------------------------------------------------------------------------- component families


def flux2_native(hidden: int = 4096, *, dtype: str = "BF16", quantized: bool = False) -> dict:
    """FLUX.2 DiT, native keys: ``txt_in`` is three stacked encoder states; ``img_in`` is 4 x 32 latent channels.

    Only ``img_in`` rows carry the hidden size; other tensors stay small except the quantized blocks, which are sized so
    that quantized bytes dominate while scale/norm tensors dominate by *count* (the shape of a real FP8 checkpoint).
    """

    block = ("F8_E4M3", [512, 512]) if quantized else (dtype, [4, 4])
    tensors = {
        "img_in.weight": (dtype, [hidden, 128]),
        "txt_in.weight": (dtype, [1, hidden * 3]),
        "double_stream_modulation_img.lin.weight": (dtype, [4, 4]),
    }
    for index in range(8):
        tensors[f"double_blocks.{index}.img_attn.qkv.weight"] = block
        if quantized:
            tensors[f"double_blocks.{index}.img_attn.qkv.weight_scale"] = ("F32", [1])
    for index in range(24):
        tensors[f"single_blocks.{index}.linear1.weight"] = block
        tensors[f"single_blocks.{index}.norm.scale"] = ("F32" if quantized else dtype, [1])
        if quantized:
            tensors[f"single_blocks.{index}.linear1.weight_scale"] = ("F32", [1])
    return tensors


def flux2_diffusers_shard(part: int) -> dict:
    """One half of a Diffusers-key FLUX.2 transformer (``x_embedder`` / ``context_embedder`` live in shard 1)."""

    if part == 1:
        return {
            "x_embedder.weight": ("BF16", [64, 128]),
            "context_embedder.weight": ("BF16", [64, 12288]),
            "double_stream_modulation_img.linear.weight": ("BF16", [4, 4]),
            "transformer_blocks.0.attn.to_q.weight": ("BF16", [4, 4]),
            "transformer_blocks.7.attn.to_q.weight": ("BF16", [4, 4]),
        }
    return {
        f"single_transformer_blocks.{index}.attn.to_q.weight": ("BF16", [4, 4])
        for index in range(24)
    }


def qwen3_encoder(hidden: int, *, quantized: bool = False, layers: int = 36) -> dict:
    tensors = {"model.embed_tokens.weight": ("BF16", [16, hidden])}
    for index in range(layers):
        tensors[f"model.layers.{index}.self_attn.q_norm.weight"] = ("BF16", [4])
        if quantized and index == 0:
            tensors[f"model.layers.{index}.mlp.up_proj.weight"] = ("F8_E4M3", [4, 4])
            tensors[f"model.layers.{index}.mlp.up_proj.weight_scale"] = ("F32", [1])
    return tensors


def vae(latent: int, *, key_format: str = "native", batch_norm: bool = False) -> dict:
    tensors = {
        "decoder.conv_in.weight": ("F16", [16, latent, 3, 3]),
        "decoder.conv_out.weight": ("F16", [3, 16, 3, 3]),
    }
    mid = (
        "decoder.mid_block.resnets.0.conv1.weight"
        if key_format == "diffusers"
        else "decoder.mid.block_1.conv1.weight"
    )
    tensors[mid] = ("F16", [4, 4, 3, 3])
    if batch_norm:
        tensors["bn.running_mean"] = ("F32", [4])
    return tensors


def qwen_image_vae() -> dict:
    return {
        "decoder.conv1.weight": ("F16", [8, 16, 1, 3, 3]),
        "encoder.conv1.weight": ("F16", [8, 3, 1, 3, 3]),
        "decoder.upsamples.0.residual.0.gamma": ("F16", [4]),
        "decoder.head.2.weight": ("F16", [3, 8, 1, 3, 3]),
    }


def z_image_dit(*, text_width: int = 2560, quantized: bool = False) -> dict:
    tensors = {
        "layers.0.attention.qkv.weight": ("F8_E4M3" if quantized else "BF16", [192, 64]),
        "layers.0.adaLN_modulation.0.weight": ("BF16", [4, 4]),
        "cap_embedder.0.weight": ("BF16", [text_width]),
    }
    if quantized:
        tensors["layers.0.attention.qkv.scale_weight"] = ("F32", [1])
    return tensors


def qwen_image_dit() -> dict:
    return {
        "img_in.weight": ("F8_E4M3", [16, 64]),
        "txt_in.weight": ("F8_E4M3", [16, 3584]),
        "txt_norm.weight": ("BF16", [4]),
        "transformer_blocks.0.attn.add_q_proj.weight": ("F8_E4M3", [4, 4]),
        "transformer_blocks.0.attn.add_q_proj.scale_weight": ("F32", [1]),
    }


def unet_bundle(kind: str = "sdxl") -> dict:
    """LDM-layout UNet checkpoint headers. ``kind``: sdxl | inpaint | sd1."""

    prefix = "model.diffusion_model."
    if kind == "sd1":
        shapes = {
            "input_blocks.0.0.weight": [320, 4, 3, 3],
            "input_blocks.4.1.transformer_blocks.0.attn2.to_k.weight": [640, 768],
            "out.2.weight": [4, 320, 3, 3],
        }
    else:
        shapes = {
            "input_blocks.0.0.weight": [320, 9 if kind == "inpaint" else 4, 3, 3],
            "label_emb.0.0.weight": [1280, 2816],
            "input_blocks.4.1.transformer_blocks.0.attn2.to_k.weight": [640, 2048],
            "input_blocks.7.1.transformer_blocks.9.attn2.to_k.weight": [1280, 2048],
            "out.2.weight": [4, 320, 3, 3],
        }
    tensors = {prefix + name: ("F16", shape) for name, shape in shapes.items()}
    tensors["first_stage_model.decoder.conv_in.weight"] = ("F16", [4, 4, 3, 3])
    return tensors


def kohya_lora(width: int = 2048, *, te2: bool = False) -> dict:
    tensors = {
        "lora_unet_down_blocks_1_attn2_to_k.lora_down.weight": ("F16", [8, width]),
        "lora_unet_down_blocks_1_attn2_to_k.lora_up.weight": ("F16", [width, 8]),
    }
    if te2:
        tensors["lora_te2_text_model_encoder_layers_0_self_attn_k_proj.lora_down.weight"] = (
            "F16",
            [8, 1280],
        )
    return tensors


def flux_lora(hidden: int = 4096) -> dict:
    return {
        "diffusion_model.double_blocks.0.img_attn.qkv.lora_A.weight": ("BF16", [8, hidden]),
        "diffusion_model.double_blocks.0.img_attn.qkv.lora_B.weight": ("BF16", [hidden * 3, 8]),
    }


def vae_like_in_lora() -> dict:
    return {
        "Decoder.Chain_1.Conv2d.weight": ("F16", [4, 4, 3, 3]),
        "Decoder.Chain_1.Conv2d.bias": ("F16", [4]),
        "Encoder.Conv2d.weight": ("F16", [4, 3, 3, 3]),
    }


def sdxl_embedding() -> dict:
    return {"clip_l": ("F16", [2, 768]), "clip_g": ("F16", [2, 1280])}


def sd1_embedding() -> dict:
    return {"emb_params": ("F16", [3, 768])}


# ------------------------------------------------------------------------------------------- containers


def gguf(
    path: Path,
    *,
    file_type: int | None = 18,
    architecture: str = "flux",
    truncate_at: int | None = None,
) -> Path:
    def string(text: str) -> bytes:
        raw = text.encode()
        return struct.pack("<Q", len(raw)) + raw

    pairs = [string("general.architecture") + struct.pack("<I", 8) + string(architecture)]
    if file_type is not None:
        pairs.append(
            string("general.file_type") + struct.pack("<I", 4) + struct.pack("<I", file_type)
        )
    data = b"GGUF" + struct.pack("<IQQ", 3, 201, len(pairs)) + b"".join(pairs)
    return raw_file(path, data if truncate_at is None else data[:truncate_at])


def shard_pair(
    directory: Path,
    *,
    drop_second: bool = False,
    escape: bool = False,
    stray: bool = False,
    wrong_total: bool = False,
    config: bool = True,
) -> Path:
    """A two-shard Diffusers FLUX.2 package with its index (and optionally defects). Returns the index path."""

    first = safetensors(
        directory / "diffusion_pytorch_model-00001-of-00002.safetensors", flux2_diffusers_shard(1)
    )
    second = directory / "diffusion_pytorch_model-00002-of-00002.safetensors"
    if not drop_second:
        safetensors(second, flux2_diffusers_shard(2))
    weight_map = dict.fromkeys(flux2_diffusers_shard(1), first.name)
    weight_map.update(dict.fromkeys(flux2_diffusers_shard(2), second.name))
    if escape:
        weight_map["transformer_blocks.0.attn.to_q.weight"] = "../elsewhere.safetensors"
    total = 0
    for shard in (first, second):
        if shard.exists():
            header_len = struct.unpack("<Q", shard.read_bytes()[:8])[0]
            total += shard.stat().st_size - 8 - header_len
    if stray:
        safetensors(
            directory / "diffusion_pytorch_model-00003-of-00003.safetensors",
            {"extra.weight": ("BF16", [2])},
        )
    index = directory / "diffusion_pytorch_model.safetensors.index.json"
    index.write_text(
        json.dumps(
            {
                "metadata": {"total_size": total + (7 if wrong_total else 0)},
                "weight_map": weight_map,
            }
        ),
        encoding="utf-8",
    )
    if config:
        (directory / "config.json").write_text(
            json.dumps(
                {
                    "_class_name": "Flux2Transformer2DModel",
                    "hidden_size": 4096,
                    "secret_note": "do not echo",
                }
            ),
            encoding="utf-8",
        )
    return index


# ------------------------------------------------------------------------------------------- a WebUI tree


def webui_tree(root: Path) -> Path:
    """The minimal Windows-like WebUI layout the registry observes (all directories exist, mostly empty)."""

    for relative in (
        "models/Stable-diffusion/Not Working",
        "models/text_encoder",
        "models/transformer",
        "models/VAE",
        "models/Lora",
        "models/LyCORIS",
        "embeddings",
        "models/embeddings",
    ):
        (root / relative).mkdir(parents=True, exist_ok=True)
    return root
