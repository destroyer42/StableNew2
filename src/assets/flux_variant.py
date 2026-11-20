"""FLUX family taxonomy from header-only structural evidence (PR-IMG-FLUX-130).

One pure answer to "which FLUX layout is this file?", derived from a ``ComponentEvidence`` that
``component_evidence`` already produced from a bounded safetensors header or GGUF tensor table. It reads nothing itself,
and a file name, size or Forge listing is never evidence of a variant.

A variant is a **layout class**, not an identity: structure cannot tell an official checkpoint from a fine-tune or a merge
with the same layout, nor FLUX.2 Klein *base* from *distilled*. Every variant therefore carries ``identity_pinned = False``
unless a caller compares the bytes with a pinned digest; the operator label says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.assets.component_evidence import (
    ARCH_FLUX2_DIT,
    ARCH_FLUX_DIT,
    ARCH_FLUX_GGUF_UNREAD,
    ROLE_BUNDLED,
    ROLE_TRANSFORMER,
    ComponentEvidence,
)

VARIANT_FLUX1_DEV = "flux1_dev"
VARIANT_FLUX1_SCHNELL = "flux1_schnell"
VARIANT_FLUX2_KLEIN_4B = "flux2_klein_4b"
VARIANT_FLUX2_KLEIN_9B = "flux2_klein_9b"
VARIANT_FLUX_UNRECOGNIZED = "flux_unrecognized"

#: Suffix of the architecture id recorded for a FLUX layout that bundles its own encoders/VAE (an all-in-one checkpoint).
BUNDLED_SUFFIX = "_bundled"

VARIANTS = (
    VARIANT_FLUX1_DEV,
    VARIANT_FLUX1_SCHNELL,
    VARIANT_FLUX2_KLEIN_4B,
    VARIANT_FLUX2_KLEIN_9B,
    VARIANT_FLUX_UNRECOGNIZED,
)

#: Every architecture id ``architecture_id`` can produce (transformer-only and bundled forms).
ARCHITECTURE_IDS = frozenset({*VARIANTS, *(f"{variant}{BUNDLED_SUFFIX}" for variant in VARIANTS)})

_LABELS = {
    VARIANT_FLUX1_DEV: "FLUX.1 [dev]-class",
    VARIANT_FLUX1_SCHNELL: "FLUX.1 [schnell]-class",
    VARIANT_FLUX2_KLEIN_4B: "FLUX.2 Klein 4B-class",
    VARIANT_FLUX2_KLEIN_9B: "FLUX.2 Klein 9B-class",
    VARIANT_FLUX_UNRECOGNIZED: "FLUX (unrecognized layout)",
}

#: (hidden, double blocks, single blocks, latent input channels) of the FLUX.1 12B transformer.
_FLUX1 = (3072, 19, 38, 64)
#: (hidden, double, single, required encoder hidden, VAE latent channels) per FLUX.2 Klein size.
_KLEIN = {
    VARIANT_FLUX2_KLEIN_4B: (3072, 5, 20, 2560, 32),
    VARIANT_FLUX2_KLEIN_9B: (4096, 8, 24, 4096, 32),
}
_T5_XXL_HIDDEN = 4096
_CLIP_L_POOLED = 768


@dataclass(frozen=True, slots=True)
class FluxVariant:
    """One file's FLUX layout class and the orthogonal facts the operator sees."""

    variant: str
    bundled: bool
    container: str  # "safetensors" | "gguf"
    precision: str  # bf16 / fp16 / fp32 / fp8_scaled / int8_scaled / the GGUF quantization / unknown
    #: Never True from structure alone; only a byte comparison with a pinned digest establishes identity.
    identity_pinned: bool = False

    @property
    def architecture_id(self) -> str:
        return f"{self.variant}{BUNDLED_SUFFIX}" if self.bundled else self.variant

    @property
    def label(self) -> str:
        parts = [_LABELS.get(self.variant, self.variant)]
        detail = self.precision if self.container == "safetensors" else f"GGUF {self.precision}"
        if detail and detail != "unknown":
            parts.append(detail)
        if self.bundled:
            parts.append("bundled encoders")
        text = ", ".join(parts)
        return text if self.identity_pinned else f"{text}, identity not pinned"


def _precision(facts: Any) -> str:
    if facts.get("container") == "gguf":
        return str(facts.get("gguf_quantization") or "unknown")
    layout = str(facts.get("precision_layout") or "")
    quantized = tuple(facts.get("quantized_dtypes") or ())
    if layout == "mixed_scaled" and any(dtype.startswith("F8") for dtype in quantized):
        return "fp8_scaled"
    if layout == "mixed_scaled" and any(dtype in ("I8", "U8") for dtype in quantized):
        return "int8_scaled"
    dominant = str(facts.get("dominant_dtype_by_bytes") or "")
    return {"BF16": "bf16", "F16": "fp16", "F32": "fp32"}.get(dominant, "unknown") if not quantized else "unknown"


def _variant(evidence: ComponentEvidence) -> str:
    facts = evidence.facts
    shape = (facts.get("hidden_size"), facts.get("double_blocks"), facts.get("single_blocks"))
    if evidence.architecture == ARCH_FLUX_DIT:
        channels = facts.get("input_channels")
        latent_channels = channels // 4 if isinstance(channels, int) else None
        if (
            shape == _FLUX1[:3]
            and latent_channels == _FLUX1[3] // 4
            and facts.get("joint_input_dim") == _T5_XXL_HIDDEN
            and facts.get("vector_input_dim") == _CLIP_L_POOLED
        ):
            return VARIANT_FLUX1_DEV if facts.get("guidance_embedding") else VARIANT_FLUX1_SCHNELL
        return VARIANT_FLUX_UNRECOGNIZED
    for variant, (hidden, doubles, singles, encoder, latent) in _KLEIN.items():
        if (
            shape == (hidden, doubles, singles)
            and facts.get("required_text_encoder_hidden_size") == encoder
            and facts.get("required_vae_latent_channels") == latent
        ):
            return variant
    return VARIANT_FLUX_UNRECOGNIZED


def classify_flux_variant(evidence: ComponentEvidence | None) -> FluxVariant | None:
    """The FLUX layout class of one file, or ``None`` when its evidence is not a FLUX transformer.

    A GGUF that declares ``flux`` but whose tensor table was unreadable is ``flux_unrecognized`` (still FLUX, still a
    transformer). Unreadable or non-FLUX evidence is ``None``: never a guess.
    """

    if evidence is None or evidence.error or evidence.role not in (ROLE_TRANSFORMER, ROLE_BUNDLED):
        return None
    container = "gguf" if evidence.fact("container") == "gguf" else "safetensors"
    if evidence.architecture == ARCH_FLUX_GGUF_UNREAD:
        return FluxVariant(VARIANT_FLUX_UNRECOGNIZED, False, "gguf", _precision(evidence.facts))
    if evidence.architecture not in (ARCH_FLUX_DIT, ARCH_FLUX2_DIT):
        return None
    return FluxVariant(
        _variant(evidence),
        bool(evidence.fact("bundled_text_encoder_or_vae")),
        container,
        _precision(evidence.facts),
    )


def variant_from_architecture(architecture: str | None) -> tuple[str, bool] | None:
    """``(variant, bundled)`` for an architecture id the registry persisted, else ``None``."""

    value = str(architecture or "")
    if value not in ARCHITECTURE_IDS:
        return None
    if value.endswith(BUNDLED_SUFFIX):
        return value[: -len(BUNDLED_SUFFIX)], True
    return value, False


def variant_label(variant: str) -> str:
    return _LABELS.get(variant, variant)


__all__ = [
    "ARCHITECTURE_IDS",
    "BUNDLED_SUFFIX",
    "FluxVariant",
    "VARIANTS",
    "VARIANT_FLUX1_DEV",
    "VARIANT_FLUX1_SCHNELL",
    "VARIANT_FLUX2_KLEIN_4B",
    "VARIANT_FLUX2_KLEIN_9B",
    "VARIANT_FLUX_UNRECOGNIZED",
    "classify_flux_variant",
    "variant_from_architecture",
    "variant_label",
]
