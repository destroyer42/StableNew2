"""Header-only LoRA and textual-inversion evidence for the observational inventory (PR-IMG-MODELS-152).

Conservative by construction: a family is stated only where tensor names/dimensions establish it, and metadata/sidecar
claims are kept as *claims* beside the tensor evidence. Disagreement between any two sources is reported as a conflict,
never resolved by picking one. None of this admits a LoRA or embedding to any checkpoint: a family-level match is advisory
and the compatibility of a particular pair is only ever ``possible``/``unknown``/``incompatible`` evidence elsewhere.
Nothing here loads a weight, hashes, reads a prompt-bearing metadata field or opens a pickle.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from src.assets.compatibility import embedded_metadata_evidence
from src.assets.component_evidence import ROLE_UNRECOGNIZED, classify_tensor_table

#: The only metadata keys read, and only as short declared labels (never tag frequencies, prompts or training settings).
CLAIM_KEYS = ("ss_base_model_version", "modelspec.architecture", "modelspec.title", "base_model")


@dataclass(frozen=True)
class LoraEvidence:
    style: str = "unrecognized"  # kohya | peft | lokr_loha | unrecognized
    tensor_family: str | None = (
        None  # sd1 | sd2 | sdxl | flux_style_dit, from tensor names/dimensions only
    )
    facts: Mapping[str, Any] = field(default_factory=dict)
    claims: Mapping[str, str] = field(default_factory=dict)  # declared labels, verbatim and short
    claimed_families: Mapping[str, str] = field(
        default_factory=dict
    )  # claim key -> normalized family token
    conflicts: tuple[str, ...] = ()
    suspected_misplaced_as: str | None = None
    declared_klein: str | None = None  # "9b" / "4b" when a claim names it (a claim, never proof)


@dataclass(frozen=True)
class EmbeddingEvidence:
    kind: str = "unrecognized"  # sdxl_clip_l_g | single_vector_table | unrecognized
    suitability: str = "unknown"  # sd1 | sd2 | sdxl | unknown (only from a positive signature)
    vector_count: int | None = None
    dimensions: tuple[int, ...] = ()


def _find(shapes: Mapping[str, list[int]], pattern: str) -> tuple[str, list[int]] | None:
    expression = re.compile(pattern)
    for name in sorted(shapes):
        if expression.search(name):
            return name, shapes[name]
    return None


def _weak_misplacement(names: list[str]) -> str | None:
    """A weak, explicitly *suspected* type mismatch for a non-LoRA tensor set whose key vocabulary is not otherwise known.

    Autoencoder-style (encoder/decoder trunk with convolutions and no LoRA markers) and full-checkpoint-style key sets are
    flagged ``*_like``; this is a hint for the operator, never a classification, and the file is never moved or relabelled.
    """

    if any(n.startswith("model.diffusion_model.") for n in names):
        return "checkpoint_like"
    trunk = {n.split(".", 1)[0].casefold() for n in names}
    if {"encoder", "decoder"} <= trunk and any("conv" in n.casefold() for n in names):
        return "vae_like"
    return None


def classify_lora(
    shapes: Mapping[str, list[int]], dtypes: Mapping[str, str], metadata: Mapping[str, Any]
) -> LoraEvidence:
    names = list(shapes)
    kohya = any(n.startswith(("lora_unet_", "lora_te")) for n in names)
    peft = any(".lora_A." in n or ".lora_B." in n for n in names)
    other = any(
        n.endswith(("hada_w1_a", ".hada_w1_a", "lokr_w1")) or ".hada_" in n or ".lokr_" in n
        for n in names
    )
    style = "kohya" if kohya else "peft" if peft else "lokr_loha" if other else "unrecognized"
    facts: dict[str, Any] = {"tensor_count": len(names)}

    family: str | None = None
    has_te2 = any(n.startswith("lora_te2_") for n in names)
    cross = _find(shapes, r"attn2_to_k\.lora_down\.weight$")
    if has_te2:
        family = "sdxl"
    elif cross is not None and len(cross[1]) == 2:
        facts["cross_attention_width"] = cross[1][1]
        family = {768: "sd1", 1024: "sd2", 2048: "sdxl"}.get(cross[1][1])
    flux = _find(shapes, r"(double_blocks|single_blocks)[._]\d+[._]")
    if family is None and flux is not None:
        family = "flux_style_dit"
        hidden = _find(
            shapes, r"double_blocks[._]0[._]img_attn[._]qkv.*(lora_down|lora_A)\.weight$"
        )
        if hidden is not None and len(hidden[1]) == 2:
            facts["flux_style_hidden_size"] = hidden[1][1]
    rank = _find(shapes, r"lora_down\.weight$") or _find(shapes, r"\.lora_A\.weight$")
    if rank is not None and rank[1]:
        facts["rank"] = rank[1][0]

    claims = {
        key: str(metadata[key])[:80] for key in CLAIM_KEYS if metadata.get(key) not in (None, "")
    }
    claimed: dict[str, str] = {}
    for key in ("ss_base_model_version", "modelspec.architecture"):
        if key in claims:
            found = embedded_metadata_evidence({key: claims[key]})
            if found:
                claimed[key] = found[0].family.value
    conflicts: list[str] = []
    values = set(claimed.values())
    if len(values) > 1:
        conflicts.append(
            "ss_base_model_version and modelspec.architecture declare different families"
        )
    if (
        family
        and values
        and not (values & {family, "flux" if family == "flux_style_dit" else family})
    ):
        conflicts.append(
            f"declared family {sorted(values)} contradicts the tensor evidence ({family})"
        )

    declared = None
    text = " ".join(claims.values()).lower()
    if "klein" in text:
        declared = (
            "9b"
            if re.search(r"(^|[^0-9])9b", text)
            else "4b"
            if re.search(r"(^|[^0-9])4b", text)
            else "unspecified"
        )

    misplaced = None
    if style == "unrecognized":
        component = classify_tensor_table(dict(shapes), dict(dtypes))
        if component.role != ROLE_UNRECOGNIZED:
            misplaced = (
                component.role
            )  # e.g. a VAE-like tensor set sitting in a LoRA folder: flagged, never moved
        else:
            misplaced = _weak_misplacement(names)
    return LoraEvidence(
        style, family, facts, claims, claimed, tuple(conflicts), misplaced, declared
    )


def classify_embedding(
    shapes: Mapping[str, list[int]], dtypes: Mapping[str, str]
) -> EmbeddingEvidence:
    clip_l, clip_g = shapes.get("clip_l"), shapes.get("clip_g")
    if (
        clip_l
        and clip_g
        and len(clip_l) == 2
        and len(clip_g) == 2
        and clip_l[1] == 768
        and clip_g[1] == 1280
    ):
        return EmbeddingEvidence("sdxl_clip_l_g", "sdxl", clip_l[0], (clip_l[1], clip_g[1]))
    table = shapes.get("emb_params")
    if table and len(table) == 2:
        suitability = {768: "sd1", 1024: "sd2"}.get(table[1], "unknown")
        return EmbeddingEvidence("single_vector_table", suitability, table[0], (table[1],))
    return EmbeddingEvidence()


__all__ = ["CLAIM_KEYS", "EmbeddingEvidence", "LoraEvidence", "classify_embedding", "classify_lora"]
