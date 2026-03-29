from __future__ import annotations

import re
from pathlib import Path

_MODEL_HASH_PATTERN = re.compile(r"(?:\s*\[[^\]]+\])+\s*$")
_NO_VAE_DISPLAY = "no vae (model default)"
_VAE_EXTENSIONS = (".safetensors", ".ckpt", ".pt", ".pth", ".bin")


def strip_webui_resource_suffix(raw: object) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    return _MODEL_HASH_PATTERN.sub("", text).strip()


def normalize_vae_config_value(raw: object) -> str:
    text = strip_webui_resource_suffix(raw)
    if not text:
        return ""
    lowered = text.lower()
    if lowered in {"automatic", "none", _NO_VAE_DISPLAY}:
        return ""
    try:
        path_name = Path(text).name
    except Exception:
        path_name = text
    return path_name.strip()


def canonicalize_vae_lookup_key(raw: object) -> str:
    normalized = normalize_vae_config_value(raw)
    if not normalized:
        return "automatic"
    lowered = normalized.lower()
    for extension in _VAE_EXTENSIONS:
        if lowered.endswith(extension):
            lowered = lowered[: -len(extension)]
            break
    return lowered


def vae_names_match(left: object, right: object) -> bool:
    return canonicalize_vae_lookup_key(left) == canonicalize_vae_lookup_key(right)


__all__ = [
    "canonicalize_vae_lookup_key",
    "normalize_vae_config_value",
    "strip_webui_resource_suffix",
    "vae_names_match",
]
