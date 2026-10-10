"""PR-IMG-MODELS-153, read-only feasibility phase: can the exact installed Z-Image-Turbo FP8-scaled candidate be qualified safely
on the pinned managed Forge (Neo ``d70373eb``) and this workstation?

Qualification-only, never production code. Like PR-IMG-MODELS-151 it answers from evidence, without loading a model,
launching or restarting Forge, writing to any runtime, downloading, copying a weight or changing any setting:

    NO_GO_RESOURCE_RISK | NO_GO_PINNED_FORGE | MISSING_DEPENDENCY | IDENTITY_PENDING | INCONCLUSIVE |
    ELIGIBLE_FOR_OWNER_AUTHORIZATION

Facts are kept apart as *measured* (headers, sizes, SHA-256, host telemetry, pinned source text), *documented* (upstream
model card, PR-IMG-115 record), *estimated* (derived) and *assumed* (stated policy). It reuses the PR-IMG-MODELS-150/152
header-only evidence, the PR-IMG-MODELS-151 allow-listed read-only telemetry collectors, and never writes the asset
registry or any hash cache. Hashing (``--hash``) only reads the three named files.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.assets.checkpoint_structure import read_tensor_table  # noqa: E402
from src.assets.component_evidence import ComponentEvidence, inspect_component_file  # noqa: E402
from tools.qualification.img151 import feasibility as base  # noqa: E402
from tools.qualification.img151.feasibility import (  # noqa: E402
    ASSUMED,
    DOCUMENTED,
    ELIGIBLE,
    ESTIMATED,
    GIB,
    IDENTITY_PENDING,
    IMG115_BASELINE,
    INCONCLUSIVE,
    KNOWN_GPU_RISK_CONTEXT,
    MEASURED,
    MISSING_DEPENDENCY,
    NO_GO_PINNED_FORGE,
    NO_GO_RESOURCE_RISK,
    VERDICTS,
    Finding,
    HostTelemetry,
    collect_telemetry,
    sha256_file,
)

PINNED_REVISION = base.PINNED_REVISION
TRANSFORMER_NAME = "zImageTurboQuantized_fp8ScaledE4m3fnKJ.safetensors"
ENCODER_NAME = "qwen3_4b_2964436.safetensors"
VAE_NAME = "flux1AE_v10.safetensors"
Z_IMAGE_DIM = 3840  # the pinned detector's Z-Image discriminator (``dit_config["dim"] == 3840``)
QWEN3_4B_HIDDEN = 2560
FLUX1_AE_LATENT = 16

#: PR-IMG-115 qualified this exact encoder (same size and SHA-256) as the Klein 4B text encoder on this machine class.
IMG115_ENCODER_SHA256 = "6c671498573ac2f7a5501502ccce8d2b08ea6ca2f661c458e708f36b36edfc5a"

#: Upstream guidance (documented; the Tongyi-MAI/Z-Image-Turbo model card). Supporting context, never proof for the pin.
OFFICIAL_TURBO_GUIDANCE = {
    "source": "Tongyi-MAI/Z-Image-Turbo model card (read-only)",
    "variant": "Z-Image-Turbo (distilled, 6B)",
    "num_inference_steps": 9,
    "dit_forward_passes": 8,
    "guidance_scale": 0.0,
    "resolution_example": "1024x1024",
    "dtype": "bfloat16",
    "note": "Guidance should be 0 for the Turbo models. The foundation Z-Image uses 50 steps with CFG; Turbo settings do not transfer to it.",
    "vram_claim": "fits within 16 GB VRAM consumer devices (vendor claim; this host has 12 GB)",
}

SCALE_KEY_RE = re.compile(r"\.scale_weight$")

CORE_TOPOLOGY_KEYS = ("cap_embedder.1.weight", "noise_refiner.0.attention.k_norm.weight")


# ---------------------------------------------------------------------------------------------------- data model


@dataclass(frozen=True)
class ScaleAnalysis:
    """What the transformer header says about its FP8 scale convention (never guessed)."""

    convention: str = "none"  # comfy_scaled_fp8_marker | comfy_quant_per_layer | none | unknown
    fp8_weights: int = 0
    matched_scales: int = 0
    fp8_without_scale: int = 0
    scales_without_fp8: int = 0
    marker_present: bool = False
    marker_elements: int | None = None
    other_quantized_dtypes: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ZImageFacts:
    """Header-only facts about the transformer, derived from the one bounded parser."""

    present: bool = False
    error: str | None = None
    dim: int | None = None
    cap_feat_dim: int | None = None
    layers: int | None = None
    forge_detectable: bool = False
    missing_detection_keys: tuple[str, ...] = ()
    dtype_histogram: Mapping[str, int] = field(default_factory=dict)
    metadata_model_type: str | None = None
    scales: ScaleAnalysis = field(default_factory=ScaleAnalysis)


@dataclass(frozen=True)
class CandidateFile:
    role: str
    name: str
    present: bool
    size_bytes: int | None = None
    evidence: ComponentEvidence | None = None
    sha256: str | None = None
    keys: Mapping[str, Any] = field(default_factory=dict)  # facts the pinned loader keys on

    def fact(self, key: str, default: Any = None) -> Any:
        return self.evidence.fact(key, default) if self.evidence else default


@dataclass(frozen=True)
class CandidateSet:
    transformer: CandidateFile
    text_encoder: CandidateFile
    vae: CandidateFile
    zimage: ZImageFacts = field(default_factory=ZImageFacts)
    alternates: tuple[CandidateFile, ...] = ()


@dataclass(frozen=True)
class PinEvidence:
    expected_revision: str = PINNED_REVISION
    marker_revision: str | None = None
    marker_status: str | None = None
    source_scanned: bool = False
    defines_zimage: bool | None = None
    zimage_dim: int | None = None
    zimage_dtypes: tuple[str, ...] = ()
    zimage_memory_factor: float | None = None
    zimage_clip_target: str | None = None
    loader_has_zimage_transformer: bool | None = None
    loader_has_qwen3_4b: bool | None = None
    detects_via_cap_embedder: bool | None = None
    converts_scaled_fp8: bool | None = None
    supports_fp8_e4m3_layer: bool | None = None
    preset: Mapping[str, Any] = field(default_factory=dict)
    hf_skeleton: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Assumptions:
    """Stated policy numbers (assumptions, not measurements); changing one changes the verdict transparently."""

    host_reserve_bytes: int = 4 * GIB
    vram_activation_reserve_bytes: int = int(2.5 * GIB)


@dataclass(frozen=True)
class FeasibilityReport:
    verdict: str
    findings: tuple[Finding, ...]
    next_recommendation: str
    measured: Mapping[str, Any]
    estimated: Mapping[str, Any]
    assumptions: Mapping[str, Any]
    candidate: Mapping[str, Any] = field(default_factory=dict)
    pin: Mapping[str, Any] = field(default_factory=dict)
    context: Mapping[str, Any] = field(default_factory=dict)
    evidence_gaps: tuple[str, ...] = ()
    preconditions: tuple[str, ...] = ()

    @property
    def reason_codes(self) -> tuple[str, ...]:
        return tuple(item.code for item in self.findings)

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "reason_codes": list(self.reason_codes),
            "findings": [asdict(item) for item in self.findings],
            "evidence_gaps": list(self.evidence_gaps),
            "preconditions_for_any_future_qualification": list(self.preconditions),
            "next_recommendation": self.next_recommendation,
            "measured": dict(self.measured),
            "estimated": dict(self.estimated),
            "assumptions": dict(self.assumptions),
            "candidate": dict(self.candidate),
            "pin": dict(self.pin),
            "official_guidance": dict(OFFICIAL_TURBO_GUIDANCE),
            "context": dict(self.context),
        }


# ---------------------------------------------------------------------------------------------------- header analysis


def analyze_scales(
    shapes: Mapping[str, list[int]], dtypes: Mapping[str, str], metadata: Mapping[str, Any]
) -> ScaleAnalysis:
    """Classify the FP8 scale convention from tensor names/dtypes only; anything unrecognized stays ``unknown``."""

    fp8 = [
        name
        for name, dtype in dtypes.items()
        if dtype in ("F8_E4M3", "F8_E5M2") and len(shapes.get(name, [])) >= 2
    ]
    marker = next((name for name in shapes if name.endswith("scaled_fp8")), None)
    scale_names = {name for name in shapes if SCALE_KEY_RE.search(name)}
    comfy_quant = [name for name in shapes if name.endswith(".comfy_quant")]
    other = tuple(sorted({d for d in dtypes.values() if d in ("U8", "I8", "F8_E5M2")}))
    notes: list[str] = []
    layers = {name[: -len(".weight")] for name in fp8 if name.endswith(".weight")}
    matched = sum(1 for layer in layers if f"{layer}.scale_weight" in scale_names)
    without = len(layers) - matched
    orphan_scales = sum(
        1 for name in scale_names if f"{name[: -len('.scale_weight')]}.weight" not in set(fp8)
    )
    if "_quantization_metadata" in metadata:
        notes.append("embedded _quantization_metadata present")
    if not fp8 and not scale_names and not comfy_quant:
        convention = "none"
    elif comfy_quant:
        convention = "comfy_quant_per_layer"
    elif (
        marker
        and scale_names
        and matched == len(layers)
        and not orphan_scales
        and not other
        and "_quantization_metadata" not in metadata
    ):
        convention = "comfy_scaled_fp8_marker"
    else:
        convention = "unknown"
        if fp8 and not scale_names:
            notes.append("FP8 weights without any recognized scale tensors")
        if without:
            notes.append(f"{without} FP8 weight(s) lack a matching .scale_weight")
        if orphan_scales:
            notes.append(f"{orphan_scales} scale tensor(s) without a matching FP8 weight")
        if other:
            notes.append("additional quantized dtypes are present: " + ", ".join(other))
    marker_elements = None
    if marker:
        count = 1
        for dim in shapes[marker]:
            count *= dim
        marker_elements = count
    return ScaleAnalysis(
        convention,
        len(layers),
        matched,
        without,
        orphan_scales,
        marker is not None,
        marker_elements,
        other,
        tuple(notes),
    )


def inspect_transformer(path: Path) -> ZImageFacts:
    try:
        shapes, dtypes, metadata = read_tensor_table(path)
    except (OSError, ValueError, TypeError, UnicodeDecodeError):
        return ZImageFacts(True, "malformed, truncated or unreadable safetensors header")
    keys = set(shapes)
    missing = tuple(key for key in CORE_TOPOLOGY_KEYS if key not in keys)
    embed = shapes.get("cap_embedder.1.weight")
    dim, cap = (embed[0], embed[1]) if embed and len(embed) == 2 else (None, None)
    layer_ids = {int(m.group(1)) for k in keys for m in [re.match(r"layers\.(\d+)\.", k)] if m}
    histogram: dict[str, int] = {}
    for dtype in dtypes.values():
        histogram[dtype] = histogram.get(dtype, 0) + 1
    return ZImageFacts(
        True,
        None,
        dim,
        cap,
        len(layer_ids),
        not missing and dim == Z_IMAGE_DIM,
        missing,
        dict(sorted(histogram.items())),
        str(metadata.get("model_type")) if metadata.get("model_type") else None,
        analyze_scales(shapes, dtypes, metadata),
    )


def _loader_keys(role: str, path: Path) -> dict[str, Any]:
    """Facts the pinned ``replace_state_dict`` branches on for the encoder/VAE (header-only)."""

    try:
        shapes, _dtypes, _meta = read_tensor_table(path)
    except (OSError, ValueError, TypeError, UnicodeDecodeError):
        return {}
    if role == "text_encoder":
        norm = shapes.get("model.layers.0.post_attention_layernorm.weight")
        return {
            "qwen3_branch": "model.layers.0.post_attention_layernorm.weight" in shapes
            and "model.layers.0.self_attn.q_norm.weight" in shapes
            and "model.layers.0.self_attn.k_proj.bias" not in shapes
            and not any(k.startswith("model.visual") for k in shapes),
            "norm_width": norm[0] if norm else None,
        }
    if role == "vae":
        return {
            "native_decoder_keys": "decoder.conv_in.weight" in shapes
            and "decoder.mid.block_1.conv1.weight" in shapes,
            "diffusers_decoder_keys": "decoder.up_blocks.0.resnets.0.norm1.weight" in shapes,
            "qwen_image_vae": "decoder.middle.0.residual.0.gamma" in shapes,
            "has_batch_norm_stats": "bn.running_mean" in shapes,
        }
    return {}


# ---------------------------------------------------------------------------------------------------- pinned source


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def collect_pin(install_dir: Path, *, expected: str = PINNED_REVISION) -> PinEvidence:
    """Read-only inspection of the managed Forge marker and the pinned source's Z-Image handling."""

    marker: dict[str, Any] = {}
    try:
        marker = json.loads(
            (install_dir / ".stablenew-managed-forge.json").read_text(encoding="utf-8-sig")
        )
    except (OSError, ValueError):
        pass
    source = install_dir / "source"
    guess = _read(source / "modules_forge" / "packages" / "huggingface_guess" / "model_list.py")
    loader = _read(source / "backend" / "loader.py")
    detection = _read(source / "modules_forge" / "packages" / "huggingface_guess" / "detection.py")
    state = _read(source / "backend" / "state_dict.py")
    quant = _read(source / "backend" / "quant_ops.py")
    presets = _read(source / "modules_forge" / "presets.py")
    if guess is None or loader is None:
        return PinEvidence(expected, marker.get("revision"), marker.get("status"))
    block = re.search(r"class ZImage\(.*?(?=\nclass |\Z)", guess, re.S)
    text = block.group(0) if block else ""
    dim = re.search(r'"dim":\s*(\d+)', text)
    factor = re.search(r"memory_usage_factor\s*=\s*([0-9.]+)", text)
    clip = re.search(r'return\s*\{\s*"([a-z0-9_.]+)"\s*:\s*"text_encoder"', text)
    dtypes = tuple(re.findall(r"torch\.(bfloat16|float16|float32)", text))
    preset: dict[str, Any] = {}
    if presets:
        for name in ("SAMPLERS", "SCHEDULERS", "STEPS", "CFG", "SHIFT"):
            found = re.search(rf"{name}\s*=\s*\{{(.*?)\n\}}", presets, re.S)
            row = re.search(r"PresetArch\.zit:\s*([^,\n]+)", found.group(1)) if found else None
            if row:
                preset[name.lower()] = row.group(1).strip().strip('"')
    skeleton: dict[str, Any] = {}
    hf = source / "backend" / "huggingface" / "Tongyi-MAI" / "Z-Image-Turbo"
    index, te_cfg, vae_cfg = (
        _read(hf / "model_index.json"),
        _read(hf / "text_encoder" / "config.json"),
        _read(hf / "vae" / "config.json"),
    )
    try:
        skeleton = {
            "pipeline": json.loads(index).get("_class_name") if index else None,
            "text_encoder_hidden_size": json.loads(te_cfg).get("hidden_size") if te_cfg else None,
            "vae_latent_channels": json.loads(vae_cfg).get("latent_channels") if vae_cfg else None,
        }
    except ValueError:
        skeleton = {}
    return PinEvidence(
        expected,
        marker.get("revision"),
        marker.get("status"),
        True,
        bool(block),
        int(dim.group(1)) if dim else None,
        dtypes,
        float(factor.group(1)) if factor else None,
        clip.group(1) if clip else None,
        "ZImageTransformer2DModel" in loader,
        "Qwen3_4B" in loader and "== 2560" in loader,
        bool(
            detection
            and "cap_embedder.1.weight" in detection
            and "noise_refiner.0.attention.k_norm.weight" in detection
        ),
        bool(
            state
            and 'endswith("scaled_fp8")' in state
            and ".scale_weight" in state
            and "weight_scale" in state
        ),
        bool(quant and '"float8_e4m3fn"' in quant and "TensorCoreFP8E4M3Layout" in quant),
        preset,
        skeleton,
    )


# ---------------------------------------------------------------------------------------------------- evaluator


def _gib(value: int | float | None) -> float | None:
    return None if value is None else round(float(value) / GIB, 2)


def evaluate(
    candidate: CandidateSet,
    pin: PinEvidence,
    telemetry: HostTelemetry,
    assumptions: Assumptions | None = None,
) -> FeasibilityReport:
    """Pure verdict. Precedence: MISSING_DEPENDENCY > NO_GO_PINNED_FORGE > NO_GO_RESOURCE_RISK > INCONCLUSIVE >
    IDENTITY_PENDING > ELIGIBLE_FOR_OWNER_AUTHORIZATION. Non-blocking findings are always reported alongside."""

    policy = assumptions or Assumptions()
    findings: list[Finding] = []
    missing: list[Finding] = []
    nogo_pin: list[Finding] = []
    nogo_resource: list[Finding] = []
    inconclusive: list[Finding] = []
    identity: list[Finding] = []
    gaps: list[str] = []
    preconditions: list[str] = []
    t, e, v, z = candidate.transformer, candidate.text_encoder, candidate.vae, candidate.zimage

    # -- 1. exact files and dependency relationships (measured) -------------------------------------------------------
    for item in (t, e, v):
        if not item.present:
            missing.append(
                Finding(
                    f"{item.role.upper()}_FILE_MISSING",
                    MEASURED,
                    f"{item.name} is not installed.",
                    True,
                )
            )
    if t.present:
        if z.error:
            missing.append(
                Finding(
                    "TRANSFORMER_HEADER_UNREADABLE",
                    MEASURED,
                    f"Transformer header: {z.error}.",
                    True,
                )
            )
        elif not z.forge_detectable:
            reason = (
                f"missing detection keys {', '.join(z.missing_detection_keys)}"
                if z.missing_detection_keys
                else f"cap_embedder.1.weight gives dim {z.dim}, not the Z-Image {Z_IMAGE_DIM}"
            )
            missing.append(
                Finding(
                    "TRANSFORMER_NOT_FORGE_ZIMAGE_LAYOUT",
                    MEASURED,
                    f"The pinned detector would not classify this as Z-Image: {reason}.",
                    True,
                )
            )
        elif (
            e.present
            and e.fact("hidden_size") is not None
            and z.cap_feat_dim != e.fact("hidden_size")
        ):
            missing.append(
                Finding(
                    "ENCODER_HIDDEN_SIZE_MISMATCH",
                    MEASURED,
                    f"The transformer's caption width is {z.cap_feat_dim} but the encoder hidden size is "
                    f"{e.fact('hidden_size')}; no other encoder is substituted.",
                    True,
                )
            )
        elif z.cap_feat_dim != QWEN3_4B_HIDDEN:
            missing.append(
                Finding(
                    "TRANSFORMER_CAPTION_WIDTH_NOT_QWEN3_4B",
                    MEASURED,
                    f"Caption width {z.cap_feat_dim} is not the Qwen3 4B class ({QWEN3_4B_HIDDEN}).",
                    True,
                )
            )
    if e.present:
        ev = e.evidence
        if ev is None or ev.error or ev.architecture != "qwen3":
            missing.append(
                Finding(
                    "ENCODER_NOT_QWEN3_STRUCTURE",
                    MEASURED,
                    "The encoder is not a Qwen3 text encoder.",
                    True,
                )
            )
        elif e.fact("quantized"):
            missing.append(
                Finding(
                    "ENCODER_QUANTIZED",
                    MEASURED,
                    "A quantized encoder is not the plain candidate.",
                    True,
                )
            )
        elif e.fact("hidden_size") != QWEN3_4B_HIDDEN:
            missing.append(
                Finding(
                    "ENCODER_NOT_QWEN3_4B",
                    MEASURED,
                    f"Encoder hidden size {e.fact('hidden_size')} is not the Qwen3 4B class ({QWEN3_4B_HIDDEN}); "
                    "an 8B encoder never substitutes.",
                    True,
                )
            )
        elif not e.keys.get("qwen3_branch"):
            missing.append(
                Finding(
                    "ENCODER_KEYS_NOT_PINNED_QWEN3_BRANCH",
                    MEASURED,
                    "The encoder tensors do not select the pinned Qwen3 loader branch.",
                    True,
                )
            )
    if v.present:
        ev = v.evidence
        if ev is None or ev.error or ev.role != "vae":
            missing.append(
                Finding("VAE_NOT_RECOGNIZED", MEASURED, "The VAE header is not recognized.", True)
            )
        elif v.fact("latent_channels") != FLUX1_AE_LATENT or v.fact("vae_family") != "flux1_ae":
            missing.append(
                Finding(
                    "VAE_NOT_FLUX1_AE_16",
                    MEASURED,
                    f"VAE family {v.fact('vae_family')} with {v.fact('latent_channels')} latent channels is "
                    "not a FLUX.1-style 16-channel autoencoder; channel count alone is never accepted.",
                    True,
                )
            )
        elif (
            v.keys.get("qwen_image_vae")
            or v.keys.get("diffusers_decoder_keys")
            or not v.keys.get("native_decoder_keys")
        ):
            missing.append(
                Finding(
                    "VAE_KEY_LAYOUT_NOT_NATIVE",
                    MEASURED,
                    "The named VAE is not the native-key layout the exact candidate specifies.",
                    True,
                )
            )
    if candidate.alternates:
        findings.append(
            Finding(
                "ALTERNATE_COMPONENT_FILES_PRESENT",
                MEASURED,
                "Other encoder/VAE files exist ("
                + ", ".join(sorted(a.name for a in candidate.alternates))
                + "); they are different assets and are never substituted.",
            )
        )

    # -- 2. FP8 scale convention (measured vs unknown) ----------------------------------------------------------------
    sc = z.scales
    if t.present and not z.error:
        if sc.convention == "comfy_scaled_fp8_marker":
            findings.append(
                Finding(
                    "FP8_SCALE_CONVENTION_COMFY_SCALED_FP8",
                    MEASURED,
                    f"A scaled_fp8 marker tensor ({sc.marker_elements} element(s)) plus {sc.matched_scales} per-layer .scale_weight "
                    f"tensors match all {sc.fp8_weights} FP8 weights (none orphaned). The marker's two elements select "
                    "full_precision_matrix_mult in the pinned converter.",
                )
            )
        elif sc.convention == "comfy_quant_per_layer":
            findings.append(
                Finding(
                    "FP8_SCALE_CONVENTION_COMFY_QUANT",
                    MEASURED,
                    "Per-layer comfy_quant records are present; the pinned loader reads them directly.",
                )
            )
        elif (
            sc.convention == "none"
            and z.dtype_histogram
            and not set(z.dtype_histogram) & {"F8_E4M3", "F8_E5M2"}
        ):
            missing.append(
                Finding(
                    "TRANSFORMER_NOT_FP8_SCALED",
                    MEASURED,
                    "No FP8 tensors are present; this is not the FP8-scaled candidate.",
                    True,
                )
            )
        else:
            inconclusive.append(
                Finding(
                    "FP8_SCALE_CONVENTION_UNKNOWN",
                    MEASURED,
                    "The FP8 scale convention is not one the pinned converter is known to read: "
                    + "; ".join(sc.notes or ("unrecognized",))
                    + ". It is treated as unknown, not guessed.",
                    True,
                )
            )
            gaps.append("FP8 scale convention could not be identified from the header")
        if z.metadata_model_type:
            findings.append(
                Finding(
                    "SELF_DECLARED_MODEL_TYPE",
                    MEASURED,
                    f"The file declares model_type {z.metadata_model_type!r} (a claim, not proof of variant).",
                )
            )

    # -- 3. byte identity vs official provenance ------------------------------------------------------------------------
    for item in (t, e, v):
        if item.present and not item.sha256:
            identity.append(
                Finding(
                    f"{item.role.upper()}_SHA256_PENDING",
                    MEASURED,
                    f"No byte identity (SHA-256) was computed for {item.name}.",
                    True,
                )
            )
    if e.sha256 and e.sha256 == IMG115_ENCODER_SHA256:
        findings.append(
            Finding(
                "ENCODER_BYTES_MATCH_IMG115_QUALIFIED_ENCODER",
                MEASURED,
                "The text encoder is byte-identical (SHA-256) to the Qwen3 4B encoder PR-IMG-115 ran on this machine class, so its "
                "load path and host-memory behavior are a same-bytes baseline for 8.04 GB of the 14.5 GB. This is not an "
                "attribution of the encoder to Z-Image beyond the pinned loader's own dimension rule.",
            )
        )
    gaps.append(
        "official-source provenance of all three files is unverified (no official hash available offline); the "
        "qualification would freeze the exact SHA-256, so provenance is not a blocker"
    )
    findings.append(
        Finding(
            "OFFICIAL_PROVENANCE_UNVERIFIED",
            ASSUMED,
            "Equality with the official Tongyi-MAI/Black Forest Labs weights is not established. The transformer is a third-party "
            "FP8-scaled conversion whose derivation is not stated by the file; the VAE carries a self-declared modelspec hash that "
            "is a claim, not a verified digest. Verified byte identity (SHA-256 of the installed files) is kept separate.",
        )
    )

    # -- 4. pinned Forge compatibility ------------------------------------------------------------------------------
    if pin.marker_revision != pin.expected_revision or pin.marker_status != "verified":
        nogo_pin.append(
            Finding(
                "PIN_NOT_VERIFIED",
                MEASURED,
                f"Managed Forge marker revision {pin.marker_revision!r} / status {pin.marker_status!r} does not "
                f"verify the pinned {pin.expected_revision[:8]}.",
                True,
            )
        )
    if not pin.source_scanned:
        inconclusive.append(
            Finding(
                "PIN_SOURCE_NOT_READ",
                MEASURED,
                "The pinned Forge source could not be inspected.",
                True,
            )
        )
        gaps.append("pinned Forge source unreadable")
    else:
        lacks = {
            "PIN_LACKS_ZIMAGE_MODEL": pin.defines_zimage is False,
            "PIN_LACKS_ZIMAGE_TRANSFORMER_LOADER": pin.loader_has_zimage_transformer is False,
            "PIN_LACKS_QWEN3_4B_LOADER": pin.loader_has_qwen3_4b is False,
            "PIN_LACKS_ZIMAGE_DETECTION": pin.detects_via_cap_embedder is False,
        }
        for code, absent in lacks.items():
            if absent:
                nogo_pin.append(
                    Finding(
                        code,
                        MEASURED,
                        "The pinned Forge source does not provide this Z-Image path.",
                        True,
                    )
                )
        if sc.convention == "comfy_scaled_fp8_marker" and pin.converts_scaled_fp8 is False:
            nogo_pin.append(
                Finding(
                    "PIN_LACKS_SCALED_FP8_CONVERTER",
                    MEASURED,
                    "The pinned Forge has no converter for the scaled_fp8 marker + .scale_weight convention.",
                    True,
                )
            )
        if (
            sc.convention in ("comfy_scaled_fp8_marker", "comfy_quant_per_layer")
            and pin.supports_fp8_e4m3_layer is False
        ):
            nogo_pin.append(
                Finding(
                    "PIN_LACKS_FP8_E4M3_LAYER",
                    MEASURED,
                    "The pinned Forge has no float8_e4m3fn layer implementation.",
                    True,
                )
            )
        if pin.zimage_dim is not None and pin.zimage_dim != Z_IMAGE_DIM:
            nogo_pin.append(
                Finding(
                    "PIN_ZIMAGE_DIM_MISMATCH",
                    MEASURED,
                    f"The pinned Z-Image definition uses dim {pin.zimage_dim}, not {Z_IMAGE_DIM}.",
                    True,
                )
            )
        if all(
            value is True
            for value in (
                pin.defines_zimage,
                pin.loader_has_zimage_transformer,
                pin.loader_has_qwen3_4b,
                pin.detects_via_cap_embedder,
            )
        ):
            findings.append(
                Finding(
                    "PIN_SUPPORTS_ZIMAGE_SOFTWARE",
                    MEASURED,
                    f"The pinned source defines ZImage (dim {pin.zimage_dim}, memory_usage_factor {pin.zimage_memory_factor}, "
                    f"clip target {pin.zimage_clip_target}), loads ZImageTransformer2DModel through NextDiT, selects Qwen3_4B for "
                    f"hidden size {QWEN3_4B_HIDDEN} and detects it from cap_embedder.1.weight / noise_refiner keys. Software support "
                    "exists; this says nothing about resource fit or output quality.",
                )
            )
        if pin.converts_scaled_fp8 and pin.supports_fp8_e4m3_layer:
            findings.append(
                Finding(
                    "PIN_CONVERTS_SCALED_FP8",
                    MEASURED,
                    "backend/state_dict.py converts a scaled_fp8 marker plus .scale_weight into weight_scale + comfy_quant records "
                    "(float8_e4m3fn); backend/quant_ops.py implements that layer. FP8 compute needs compute capability >= 8.9; the "
                    "RTX 4070 Ti is Ada (8.9, documented), and a lack of FP8 compute falls back to full-precision matmul.",
                )
            )
        if pin.preset:
            findings.append(
                Finding(
                    "PINNED_ZIT_PRESET",
                    MEASURED,
                    "Pinned Forge Z-Image-Turbo preset: "
                    + ", ".join(f"{k}={pin.preset[k]}" for k in sorted(pin.preset))
                    + ". Official guidance is 9 steps (8 DiT forwards) at guidance 0; these are documented, not changed here.",
                )
            )
        gaps.append(
            "pinned loading is established from source only; it has never been exercised by a model load on this "
            "workstation (no load was performed)"
        )

    # -- 5. resource feasibility ----------------------------------------------------------------------------------------
    sizes = [item.size_bytes for item in (t, e, v) if item.size_bytes]
    weights = sum(sizes) if len(sizes) == 3 else None
    estimated: dict[str, Any] = {}
    for name, value in {
        "total_ram_bytes": telemetry.total_ram_bytes,
        "vram_total_bytes": telemetry.vram_total_bytes,
        "pagefile_allocated_bytes": telemetry.pagefile_allocated_bytes,
    }.items():
        if value is None:
            inconclusive.append(
                Finding(
                    f"TELEMETRY_{name.upper()}_MISSING",
                    MEASURED,
                    f"{name} could not be measured; resource fit cannot be decided.",
                    True,
                )
            )
            gaps.append(f"{name} unavailable")
    base_weights = int(cast("int", IMG115_BASELINE["weights_bytes"]))
    base_peak = int(cast("float", IMG115_BASELINE["forge_tree_private_peak_gib"]) * GIB)
    if weights is not None:
        estimated["weights_bytes"] = weights
        estimated["weights_vs_img115_baseline"] = round(weights / base_weights, 3)
        estimated["host_peak_best_case_bytes"] = (
            weights  # each file resident once, no process overhead
        )
        # Two crude analogues from the only physical baseline; a range, never a prediction.
        estimated["host_peak_projection_low_bytes"] = base_peak + max(0, weights - base_weights)
        estimated["host_peak_projection_high_bytes"] = int(base_peak * weights / base_weights)
    if weights is not None and telemetry.total_ram_bytes is not None:
        usable = telemetry.total_ram_bytes - policy.host_reserve_bytes
        estimated["usable_physical_bytes"] = usable
        if weights > usable:
            nogo_resource.append(
                Finding(
                    "HOST_RESIDENT_WEIGHTS_EXCEED_PHYSICAL",
                    ESTIMATED,
                    f"The three files total {_gib(weights)} GiB; only {_gib(usable)} GiB of physical RAM is usable after the reserve.",
                    True,
                )
            )
    if (
        weights is not None
        and telemetry.total_ram_bytes is not None
        and telemetry.pagefile_allocated_bytes is not None
    ):
        capacity = (
            telemetry.total_ram_bytes
            + telemetry.pagefile_allocated_bytes
            - policy.host_reserve_bytes
        )
        estimated["quiesced_commit_capacity_bytes"] = capacity
        low, high = (
            estimated["host_peak_projection_low_bytes"],
            estimated["host_peak_projection_high_bytes"],
        )
        if low > capacity:
            nogo_resource.append(
                Finding(
                    "HOST_PEAK_PROJECTION_EXCEEDS_COMMIT_CAPACITY",
                    ESTIMATED,
                    f"Even the optimistic analogue of the PR-IMG-115 Forge-tree peak ({_gib(low)} GiB) exceeds the quiesced commit "
                    f"capacity ({_gib(capacity)} GiB = RAM + pagefile - reserve).",
                    True,
                )
            )
        elif high > capacity:
            findings.append(
                Finding(
                    "HOST_PEAK_UPPER_PROJECTION_EXCEEDS_CAPACITY",
                    ESTIMATED,
                    f"The pessimistic projection ({_gib(high)} GiB) exceeds the quiesced commit capacity "
                    f"({_gib(capacity)} GiB); the optimistic one ({_gib(low)} GiB) fits.",
                )
            )
        else:
            findings.append(
                Finding(
                    "HOST_PEAK_PROJECTIONS_FIT_QUIESCED_CAPACITY",
                    ESTIMATED,
                    f"Both crude analogues of the PR-IMG-115 tree peak ({_gib(low)}-{_gib(high)} GiB, from {_gib(base_peak)} GiB at "
                    f"{_gib(base_weights)} GiB of weights) fit the quiesced commit capacity ({_gib(capacity)} GiB). This is a range "
                    "from one baseline, not a peak-memory claim.",
                )
            )
        if telemetry.commit_headroom_bytes is not None and telemetry.commit_headroom_bytes < high:
            preconditions.append(
                f"Commit headroom measured at launch must be at least {_gib(high)} GiB (it was {_gib(telemetry.commit_headroom_bytes)} "
                "GiB during this measurement, with the development session running); close competing workloads first."
            )
            findings.append(
                Finding(
                    "CURRENT_COMMIT_HEADROOM_BELOW_PROJECTION",
                    MEASURED,
                    f"Commit headroom right now is {_gib(telemetry.commit_headroom_bytes)} GiB, below the projection; it is a momentary, "
                    "workload-dependent reading and is therefore a launch precondition, not a verdict input.",
                )
            )
        elif telemetry.commit_headroom_bytes is None:
            inconclusive.append(
                Finding(
                    "TELEMETRY_COMMIT_HEADROOM_MISSING",
                    MEASURED,
                    "System commit headroom could not be measured.",
                    True,
                )
            )
    if t.size_bytes and telemetry.vram_total_bytes is not None:
        resident_limit = telemetry.vram_total_bytes - policy.vram_activation_reserve_bytes
        estimated["vram_resident_limit_bytes"] = resident_limit
        if t.size_bytes > resident_limit:
            nogo_resource.append(
                Finding(
                    "VRAM_TRANSFORMER_EXCEEDS_DEDICATED",
                    ESTIMATED,
                    f"The FP8 transformer ({_gib(t.size_bytes)} GiB) cannot be resident in {_gib(telemetry.vram_total_bytes)} GiB.",
                    True,
                )
            )
        base_vram = int(cast("int", IMG115_BASELINE["dedicated_vram_peak_mib"]) * 1024 * 1024)
        delta = max(0, t.size_bytes - 4_070_624_520)  # Klein 4B FP8 transformer in the baseline
        estimated["vram_peak_low_bytes"] = (
            base_vram  # text-encoder phase unchanged (identical encoder bytes)
        )
        estimated["vram_peak_high_bytes"] = (
            base_vram + delta
        )  # denoise phase grows by the larger FP8 transformer
        high_v = estimated["vram_peak_high_bytes"]
        if estimated["vram_peak_low_bytes"] > telemetry.vram_total_bytes:
            nogo_resource.append(
                Finding(
                    "VRAM_PEAK_PROJECTION_EXCEEDS_DEDICATED",
                    ESTIMATED,
                    "Even the optimistic dedicated-VRAM analogue exceeds the card.",
                    True,
                )
            )
        elif high_v > telemetry.vram_total_bytes * 0.95:
            findings.append(
                Finding(
                    "VRAM_MARGIN_THIN_IN_UPPER_PROJECTION",
                    ESTIMATED,
                    f"Dedicated VRAM analogue {_gib(base_vram)}-{_gib(high_v)} GiB against {_gib(telemetry.vram_total_bytes)} GiB "
                    "(totals include the desktop's share); the upper bound leaves little margin. Pinned Forge's own "
                    f"memory_usage_factor for Z-Image is {pin.zimage_memory_factor} versus 14.6 for Klein 4B (documented in source), "
                    "which points to smaller activations, but is not a measurement.",
                )
            )
            preconditions.append(
                "Dedicated VRAM in use before launch should be at or below the PR-IMG-115 level (about 2 GiB of desktop use)."
            )
    if telemetry.forge_endpoint_listening:
        findings.append(
            Finding(
                "FORGE_ENDPOINT_ALREADY_LISTENING",
                MEASURED,
                "A Forge-class endpoint is already listening; a qualification could not own its lifecycle.",
            )
        )
        preconditions.append(
            "No other Forge/WebUI endpoint may be listening; the qualification owns the only managed lifecycle."
        )
    if telemetry.available_ram_bytes is not None:
        findings.append(
            Finding(
                "AVAILABLE_RAM_RECORDED",
                MEASURED,
                f"{_gib(telemetry.available_ram_bytes)} GiB physical RAM was available at measurement time (observational).",
            )
        )
    findings.append(
        Finding(
            "IMG115_BASELINE_COMPARABILITY",
            DOCUMENTED,
            f"PR-IMG-115 ran Klein 4B FP8 + the identical Qwen3 4B encoder on the pinned Forge: tree private peak "
            f"{IMG115_BASELINE['forge_tree_private_peak_gib']} GiB, available RAM down to {IMG115_BASELINE['min_host_ram_available_gb']} GB, "
            f"dedicated VRAM peak {IMG115_BASELINE['dedicated_vram_peak_mib']} MiB, no OOM. The Z-Image transformer is a different model "
            "(6B, single-stream) with 1.17x the total weights; the baseline bounds the pattern, it does not transfer a result.",
        )
    )
    findings.append(
        Finding("KNOWN_GPU_RISK_CONTEXT", DOCUMENTED, KNOWN_GPU_RISK_CONTEXT["summary"])
    )
    findings.append(
        Finding(
            "TURBO_NOT_FOUNDATION",
            DOCUMENTED,
            "Official Turbo guidance is 9 steps (8 DiT forwards) at guidance 0 at 1024x1024; the foundation Z-Image uses 50 steps with "
            "CFG. The installed file declares model_type z-image-turbo, but the file cannot prove it is the distilled variant "
            "(structure is shared); no sampler or step is set here.",
        )
    )

    # -- 6. verdict ------------------------------------------------------------------------------------------------------
    if missing:
        verdict = MISSING_DEPENDENCY
        nxt = "Install/identify the missing or mismatched exact components; nothing is substituted. No further action here."
    elif nogo_pin:
        verdict = NO_GO_PINNED_FORGE
        nxt = "Close as no-go for the pinned Forge; a Forge pin change is a separate architecture decision."
    elif nogo_resource:
        verdict = NO_GO_RESOURCE_RISK
        nxt = "Close PR-IMG-MODELS-153 as a documented no-go for this workstation; no model load, no generation."
    elif inconclusive:
        verdict = INCONCLUSIVE
        nxt = "Re-run with complete telemetry and a readable pinned Forge source, or resolve the unknown scale convention."
    elif identity:
        verdict = IDENTITY_PENDING
        nxt = "Compute SHA-256 for the three exact files (--hash) before any owner authorization."
    else:
        verdict = ELIGIBLE
        nxt = (
            "Stop and obtain a separate explicit owner authorization for one controlled physical qualification of this exact "
            "stack on a quiesced host, with the stated preconditions and abort thresholds. No profile or production change "
            "follows from this verdict."
        )

    findings = [*missing, *nogo_pin, *nogo_resource, *inconclusive, *identity, *findings]
    measured = {
        "candidate_sizes_bytes": {i.role: i.size_bytes for i in (t, e, v)},
        "candidate_sha256": {i.role: i.sha256 for i in (t, e, v)},
        "transformer_dtype_histogram": dict(z.dtype_histogram),
        "telemetry": {k: val for k, val in asdict(telemetry).items() if k != "competing_processes"},
        "competing_processes_top_working_set": [
            {"name": n, "working_set_gib": _gib(b)} for n, b in telemetry.competing_processes
        ],
    }
    return FeasibilityReport(
        verdict,
        tuple(findings),
        nxt,
        measured,
        estimated,
        {**asdict(policy), "baseline": dict(IMG115_BASELINE)},
        {
            "transformer": _describe(t),
            "text_encoder": _describe(e),
            "vae": _describe(v),
            "transformer_scales": asdict(z.scales),
            "forge_detectable": z.forge_detectable,
            "dim": z.dim,
            "caption_width": z.cap_feat_dim,
            "layers": z.layers,
        },
        asdict(pin),
        {"known_gpu_risk": dict(KNOWN_GPU_RISK_CONTEXT)},
        tuple(dict.fromkeys(gaps)),
        tuple(dict.fromkeys(preconditions)),
    )


def _describe(item: CandidateFile) -> dict[str, Any]:
    return {
        "name": item.name,
        "present": item.present,
        "size_bytes": item.size_bytes,
        "sha256": item.sha256,
        "role": item.evidence.role if item.evidence else None,
        "architecture": item.evidence.architecture if item.evidence else None,
        "facts": dict(item.evidence.facts) if item.evidence else {},
        "loader_keys": dict(item.keys),
        "error": item.evidence.error if item.evidence else None,
    }


# ---------------------------------------------------------------------------------------------------- collectors


def _candidate_file(role: str, path: Path, *, hash_it: bool) -> CandidateFile:
    if not path.is_file():
        return CandidateFile(role, path.name, present=False)
    return CandidateFile(
        role,
        path.name,
        True,
        path.stat().st_size,
        inspect_component_file(path),
        sha256_file(path) if hash_it else None,
        _loader_keys(role, path),
    )


def collect_candidate(webui_root: Path, *, hash_files: bool = False) -> CandidateSet:
    models = webui_root / "models"
    transformer_path = models / "Stable-diffusion" / TRANSFORMER_NAME
    transformer = _candidate_file("transformer", transformer_path, hash_it=hash_files)
    zimage = inspect_transformer(transformer_path) if transformer.present else ZImageFacts()
    # a transformer-only checkpoint classifies as a bundled/transformer signature for this role; the Z-Image facts above are authoritative
    encoder = _candidate_file(
        "text_encoder", models / "text_encoder" / ENCODER_NAME, hash_it=hash_files
    )
    vae = _candidate_file("vae", models / "VAE" / VAE_NAME, hash_it=hash_files)
    alternates: list[CandidateFile] = []
    for folder, role in ((models / "text_encoder", "text_encoder"), (models / "VAE", "vae")):
        for path in sorted(folder.glob("*.safetensors")) if folder.is_dir() else []:
            if path.name not in (ENCODER_NAME, VAE_NAME):
                alternates.append(CandidateFile(role, path.name, True, path.stat().st_size))
    return CandidateSet(transformer, encoder, vae, zimage, tuple(alternates))


# ---------------------------------------------------------------------------------------------------- CLI


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--webui-root", type=Path, required=True)
    parser.add_argument(
        "--install-dir",
        type=Path,
        required=True,
        help="the managed Forge neo-<rev8> directory (read only)",
    )
    parser.add_argument(
        "--hash",
        action="store_true",
        help="read the three named files once to compute SHA-256 (no writes)",
    )
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    candidate = collect_candidate(args.webui_root, hash_files=args.hash)
    report = evaluate(candidate, collect_pin(args.install_dir), collect_telemetry())
    args.report.write_text(
        json.dumps(report.as_dict(), indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    print(f"verdict: {report.verdict}")
    print("reason codes: " + ", ".join(report.reason_codes))
    return 0 if report.verdict in VERDICTS else 1


if __name__ == "__main__":
    raise SystemExit(main())
