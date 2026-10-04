"""Frozen identities and cases for IMG-115 (no I/O beyond hashing; deterministic)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FORGE_SHA = "d70373ebcf1a96d210b78cd6f77196459e783e2a"
SEEDS = {"A": 424242, "B": 424243, "C": 424244, "D": 424245}
STEPS = 4
GUIDANCE = 1.0  # distilled Klein: CFG 1.0 (pinned Forge preset klein: Euler / Beta / 4 steps / CFG 1.0)
SAMPLER = "Euler"
SCHEDULER = "Beta"
NEGATIVE_PROMPT = ""
STITCH_SCRIPT = "ImageStitch Integrated"  # Forge's built-in reference mechanism (references via alwayson_scripts)
STITCH_MAX_DIM = 1024
EDIT_ENDPOINT = "/sdapi/v1/img2img"  # Klein edit: init image = reference 1 (Forge ini_latent), denoise 1.0
T2I_ENDPOINT = "/sdapi/v1/txt2img"
EDIT_DENOISE = 1.0


@dataclass(frozen=True)
class Asset:
    role: str
    repo: str
    revision: str
    remote_path: str
    filename: str
    size: int
    sha256: str
    models_subdir: str


ASSETS: dict[str, Asset] = {
    "transformer": Asset(
        "FLUX.2 Klein 4B FP8 transformer", "black-forest-labs/FLUX.2-klein-4b-fp8",
        "5b4408e59397a4a37ccb46afe426d8ed86379441", "flux-2-klein-4b-fp8.safetensors",
        "flux-2-klein-4b-fp8.safetensors", 4_070_624_520,
        "97ed34fe0567e436200f2faee3939b88f2b5d99f8af2a4dc16532c4245c0ccb6", "Stable-diffusion",
    ),
    "text_encoder": Asset(
        "Qwen3 4B text encoder (single file, BFL FLUX.2-klein-4B text_encoder structure)",
        "Comfy-Org/vae-text-encorder-for-flux-klein-4b", "5f526678002e43af5551dadb73ce2e8c91b43afe",
        "split_files/text_encoders/qwen_3_4b.safetensors", "qwen_3_4b.safetensors", 8_044_982_048,
        "6c671498573ac2f7a5501502ccce8d2b08ea6ca2f661c458e708f36b36edfc5a", "text_encoder",
    ),
    "vae": Asset(
        "FLUX.2 VAE (Forge LDM layout)", "Comfy-Org/vae-text-encorder-for-flux-klein-4b",
        "5f526678002e43af5551dadb73ce2e8c91b43afe", "split_files/vae/flux2-vae.safetensors",
        "flux2-vae.safetensors", 336_211_292,
        "868fe7b343cc8f3a19dbcfcafbc3d5f888802be3f89bd81b65b3621a066ce8f3", "VAE",
    ),
}

# Names (case-insensitive fragments) that mean a substitution of the frozen baseline stack.
FORBIDDEN_FRAGMENTS = ("bf16", "base", "9b", "gguf", "nvfp4", "fp4", "sdnq", "uncensored", "8b", "mistral", "flux1", "ae.safetensors")

_COMMON = {"steps": STEPS, "cfg_scale": GUIDANCE, "sampler_name": SAMPLER, "scheduler": SCHEDULER, "negative_prompt": NEGATIVE_PROMPT}

CASES: dict[str, dict[str, Any]] = {
    "A": {"kind": "txt2img", "width": 768, "height": 1024, "seed": SEEDS["A"], "references": [],
          "prompt": ("Photorealistic editorial portrait of an adult woman standing beside a weathered blue vintage "
                     "motorcycle on a rain-wet city street at dusk, head to knees visible, both hands clearly visible, "
                     "natural skin texture, dark green field jacket, cinematic 50mm photography, realistic proportions, "
                     "sharp eyes, readable neon sign in the background saying NORTH.")},
    "B": {"kind": "txt2img", "width": 1024, "height": 1024, "seed": SEEDS["B"], "references": [],
          "prompt": ("Studio product photograph of a red vintage motorcycle with a white fuel-tank stripe, black leather "
                     "seat, brass headlamp, three-quarter view, neutral gray background, crisp mechanical detail, realistic "
                     "materials and lighting.")},
    "C": {"kind": "edit", "width": 768, "height": 1024, "seed": SEEDS["C"], "references": ["A"],
          "prompt": ("Keep the same adult person, face, pose, framing, hands, motorcycle, lighting and background. Change "
                     "only the field jacket from dark green to deep red leather. Preserve identity and composition.")},
    "D": {"kind": "edit", "width": 768, "height": 1024, "seed": SEEDS["D"], "references": ["A", "B"],
          "prompt": ("Use the same person, face, pose, camera framing and street from reference 1. Replace the motorcycle "
                     "with the red motorcycle design and white fuel-tank stripe from reference 2. Preserve the person's "
                     "identity, hands and overall lighting.")},
}
for _case in CASES.values():
    _case.update(_COMMON)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def reject_substitution(selected: dict[str, str]) -> None:
    """``selected`` maps role -> file name. Only the frozen baseline stack is accepted."""

    if set(selected) != set(ASSETS):
        raise ValueError(f"The baseline stack is exactly {sorted(ASSETS)}; got {sorted(selected)}")
    for role, name in selected.items():
        if name != ASSETS[role].filename:
            lowered = name.lower()
            hit = [fragment for fragment in FORBIDDEN_FRAGMENTS if fragment in lowered]
            raise ValueError(f"{role} {name!r} is not the frozen {ASSETS[role].filename!r}" + (f" (substitution marker: {hit})" if hit else ""))


def verify_asset(role: str, path: Path) -> dict[str, Any]:
    """Exact size and SHA-256 or a ValueError; nothing else is accepted."""

    asset, path = ASSETS[role], Path(path)
    if path.name != asset.filename:
        reject_substitution({**{r: a.filename for r, a in ASSETS.items()}, role: path.name})
    if not path.is_file():
        raise ValueError(f"{role} missing: {path}")
    if path.stat().st_size != asset.size:
        raise ValueError(f"{role} size {path.stat().st_size} != frozen {asset.size}")
    actual = sha256_file(path)
    if actual != asset.sha256:
        raise ValueError(f"{role} sha256 {actual} != frozen {asset.sha256}")
    return {"role": role, "path": str(path), "bytes": asset.size, "sha256": actual, "repo": asset.repo, "revision": asset.revision}
