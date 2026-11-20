"""FLUX.1 [dev] family profile for the existing ``forge_webui`` backend (PR-IMG-FLUX-130).

A *family* profile, the one owner-approved exception to whole-file identity (decision Q4, 2026-11-20): the diffusion
transformer is admitted by its **structural layout** (``src/assets/flux_variant.py``: a transformer-only FLUX.1 [dev]-class
file, so fine-tunes of the same layout run under the same envelope), while the CLIP-L and T5-XXL encoders and the FLUX.1
VAE are **pinned by size and SHA-256**. The transformer's own SHA-256 is computed at dispatch and recorded as evidence; it
is never an admission rule, and a file whose digest differs from the recommended download is labelled a derivative.

Like the Klein profile this is one immutable, versioned contract: the NJR persists only
``backend_options.image.model_profile = {"id", "version"}``. A published version never changes. It is not physically
qualified (STATUS.md): nothing here claims hardware or output quality.

Everything in this module is pure at import (no I/O, no hashing, no network). The one optional evidence seam is
``install_variant_lookup``: the application entry point installs a registry-snapshot lookup so the compiler can see a
checkpoint's structural variant; when nothing is installed (tests, CLI) the compiler stamps nothing and the backend's
dependency gate refuses the unprofiled transformer instead. Never a guess.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from src.assets.flux_variant import (
    VARIANT_FLUX1_DEV,
    VARIANT_FLUX1_SCHNELL,
    VARIANT_FLUX2_KLEIN_4B,
    VARIANT_FLUX2_KLEIN_9B,
    VARIANT_FLUX_UNRECOGNIZED,
)
from src.image_backends.forge_klein_profile import KleinAsset, KleinProfileError
from src.image_backends.image_backend_types import FORGE_IMAGE_BACKEND_ID

FLUX1_PROFILE_ID = "flux1_dev_gguf"
FLUX1_DISPLAY_NAME = "FLUX.1 [dev] (GGUF family profile)"
FLUX1_PROVENANCE_KEY = "flux1_profile"
MODE_TXT2IMG = "txt2img"
T2I_STAGE_CHAIN = ("txt2img",)
FIXED_CLIP_SKIP = 1

_COMFY_ENCODERS = "comfyanonymous/flux_text_encoders"


class Flux1ProfileError(KleinProfileError):
    """Outside the FLUX.1 [dev] envelope or unverifiable (one ``except KleinProfileError`` catches every profile)."""


@dataclass(frozen=True, slots=True)
class Flux1Profile:
    profile_id: str
    version: int
    display_name: str
    backend_id: str
    forge_revision: str
    #: The structural layout class the transformer must have (transformer-only; a bundled checkpoint is not admitted).
    transformer_variant: str
    #: Admitted transformer precisions: GGUF declared quantizations and safetensors precision classes.
    transformer_precisions: tuple[str, ...]
    #: The owner-selected download (decision Q1). Guidance and derivative labelling only, never an admission pin.
    recommended_transformer: KleinAsset
    clip_l: KleinAsset
    t5xxl: KleinAsset
    vae: KleinAsset
    sampler: str
    scheduler: str
    steps: int
    cfg_scale: float
    distilled_cfg_scale: float
    geometries: tuple[tuple[int, int], ...]
    modes: tuple[str, ...]
    min_total_ram_bytes: int
    max_loras: int = 0

    @property
    def modules(self) -> tuple[KleinAsset, KleinAsset, KleinAsset]:
        """Forge ``forge_additional_modules``: the pinned CLIP-L, T5-XXL and VAE, in that order."""

        return (self.clip_l, self.t5xxl, self.vae)

    @property
    def assets(self) -> tuple[KleinAsset, ...]:
        """The byte-pinned assets (the transformer is admitted by structure, so it is not one of them)."""

        return self.modules

    def reference(self) -> dict[str, Any]:
        return {"id": self.profile_id, "version": self.version}


FLUX1_DEV_PROFILE_V1 = Flux1Profile(
    profile_id=FLUX1_PROFILE_ID,
    version=1,
    display_name=FLUX1_DISPLAY_NAME,
    backend_id=FORGE_IMAGE_BACKEND_ID,
    forge_revision="d70373ebcf1a96d210b78cd6f77196459e783e2a",
    transformer_variant=VARIANT_FLUX1_DEV,
    transformer_precisions=("Q4_K_S", "Q5_K_S", "Q6_K", "Q8_0", "fp8_scaled"),
    # SHA-256 as published on the Hugging Face file page on 2026-11-20 (LFS); size from the repository metadata.
    recommended_transformer=KleinAsset(
        "transformer", "flux1-dev-Q4_K_S.gguf", 6_805_988_640,
        "75bb19459b5240c9f373b5af527584af15b675867fa142efadf7478d6abbf62b",
        "Stable-diffusion", "city96/FLUX.1-dev-gguf", "7e7853bc830591271db10c7aed520321d45c070e",
    ),
    clip_l=KleinAsset(
        "text_encoder", "clip_l.safetensors", 246_144_152,
        "660c6f5b1abae9dc498ac2d21e1347d2abdb0cf6c0c0c8576cd796491d9a6cdd",
        "text_encoder", _COMFY_ENCODERS, "168aff54c7de740a8946f19cf87b2eda743c6342",
    ),
    t5xxl=KleinAsset(
        "text_encoder_2", "t5xxl_fp8_e4m3fn.safetensors", 4_893_934_904,
        "7d330da4816157540d6bb7838bf63a0f02f573fc48ca4d8de34bb0cbfd514f09",
        "text_encoder", _COMFY_ENCODERS, "2f74b39c0606dae3b2196d79c18c2a40b71f3250",
    ),
    # The installed FLUX.1 autoencoder, byte-identical to the asset the Z-Image profile already pins.
    vae=KleinAsset(
        "vae", "flux1AE_v10.safetensors", 335_304_388,
        "afc8e28272cd15db3919bacdb6918ce9c1ed22e96cb12c4d5ed0fba823529e38",
        "VAE", "", "",
    ),
    sampler="Euler",
    scheduler="Simple",
    steps=20,
    cfg_scale=1.0,
    distilled_cfg_scale=3.5,
    geometries=((1024, 1024), (896, 1152), (1152, 896), (832, 1216), (1216, 832)),
    modes=(MODE_TXT2IMG,),
    min_total_ram_bytes=32_000_000_000,
)

_PROFILES: dict[tuple[str, int], Flux1Profile] = {(FLUX1_PROFILE_ID, 1): FLUX1_DEV_PROFILE_V1}
_LATEST = FLUX1_DEV_PROFILE_V1

#: Operator-facing refusal per FLUX layout class that has no executable profile (the gate and the GUI both use it).
FLUX_VARIANT_REFUSALS: Mapping[str, str] = {
    VARIANT_FLUX2_KLEIN_9B: (
        "FLUX.2 Klein 9B is NO-GO on this workstation (PR-IMG-MODELS-151; kept by the owner on 2026-11-18 and 2026-11-20), "
        "in every precision including FP8 and GGUF. StableNew refuses it before any module write or generation."
    ),
    VARIANT_FLUX2_KLEIN_4B: (
        "Only the exact qualified flux-2-klein-4b-fp8.safetensors runs under the FLUX.2 Klein 4B profile. This file has "
        "the Klein 4B layout but is not that file, so it is refused before generation."
    ),
    VARIANT_FLUX1_SCHNELL: (
        "FLUX.1 [schnell] has no StableNew execution profile yet, so it is refused before generation."
    ),
    VARIANT_FLUX_UNRECOGNIZED: (
        "This FLUX transformer's layout matches no StableNew profile, so it is refused before generation."
    ),
}

FLUX1_UNPROFILED_HINT = (
    "A FLUX.1 [dev]-class transformer runs only under the FLUX.1 [dev] family profile (flux1_dev_gguf v1). The job was "
    "built without it, usually because the model inventory had not recorded this file's structure yet: refresh the model "
    "inventory, then build the job again."
)


def flux_variant_refusal(variant: str | None) -> str:
    return FLUX_VARIANT_REFUSALS.get(str(variant or ""), "")


def latest_flux1_profile() -> Flux1Profile:
    return _LATEST


def resolve_flux1_reference(reference: Mapping[str, Any]) -> Flux1Profile:
    """Exact ``{"id", "version"}`` (int version, no extra keys) or a ``Flux1ProfileError``; never reinterpreted."""

    version = reference.get("version")
    profile = _PROFILES.get((str(reference.get("id")), version)) if type(version) is int else None
    if profile is None or dict(reference) != profile.reference():
        raise Flux1ProfileError(
            f"Unsupported FLUX.1 profile reference {dict(reference)}; supported: "
            f"{sorted(f'{pid}@v{ver}' for pid, ver in _PROFILES)}"
        )
    return profile


# -- structural selection (the one optional evidence seam) --------------------------------------------------------

#: model name -> ``(variant, bundled)`` from the registry snapshot, or ``None`` when nothing is recorded.
VariantLookup = Callable[[str], "tuple[str, bool] | None"]
_variant_lookup: VariantLookup | None = None


def install_variant_lookup(lookup: VariantLookup | None) -> VariantLookup | None:
    """Install (or clear, with ``None``) the structural variant lookup; returns the previous one (for tests)."""

    global _variant_lookup
    previous, _variant_lookup = _variant_lookup, lookup
    return previous


def variant_for_model(model_name: str | None) -> tuple[str, bool] | None:
    name = str(model_name or "").strip()
    if not name or _variant_lookup is None:
        return None
    try:
        return _variant_lookup(name)
    except Exception:  # noqa: BLE001 - an unreadable snapshot is absent evidence, never a guess
        return None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def frozen_profile_is_flux1(backend_options: Any) -> bool:
    reference = _mapping(_mapping(backend_options).get("image")).get("model_profile")
    return isinstance(reference, Mapping) and reference.get("id") == FLUX1_PROFILE_ID


def selected_model_name(config: Mapping[str, Any] | None) -> str:
    data = config if isinstance(config, Mapping) else {}
    for source in (_mapping(data.get("txt2img")), data):
        for key in ("model", "model_name", "sd_model_checkpoint", "base_model"):
            if str(source.get(key) or "").strip():
                return str(source[key]).strip()
    return ""


def flux1_selected(config: Mapping[str, Any] | None) -> bool:
    """Whether a merged run config selects a transformer-only FLUX.1 [dev]-class checkpoint (registry evidence)."""

    return variant_for_model(selected_model_name(config)) == (VARIANT_FLUX1_DEV, False)


# -- intent validation ---------------------------------------------------------------------------------------------


def validate_flux1_intent(
    profile: Flux1Profile,
    *,
    backend_id: str,
    stage_names: Iterable[str],
    model_name: str | None = None,
    sampler: str | None,
    scheduler: str | None,
    steps: int | float | None,
    cfg_scale: float | None,
    width: int | None,
    height: int | None,
    negative_prompt: str | None,
    unsupported_features: Iterable[str] = (),
) -> str:
    """Reject anything outside the envelope (one error listing every conflict); return the mode.

    The transformer's identity is structural and is checked at dispatch against the served file's header, not here.
    """

    problems: list[str] = []
    if backend_id != profile.backend_id:
        problems.append(
            f"backend '{backend_id}' is not supported (the profile requires '{profile.backend_id}'; StableNew never "
            "switches the configured backend for you)"
        )
    stages = tuple(str(stage) for stage in stage_names)
    if stages != T2I_STAGE_CHAIN:
        problems.append(f"stage chain {list(stages)} is not supported (only {list(T2I_STAGE_CHAIN)}; no img2img, "
                        "ADetailer, upscale, hires or ControlNet)")
    if not str(model_name or "").strip():
        problems.append("a checkpoint must be selected")
    if str(sampler or "") != profile.sampler:
        problems.append(f"sampler '{sampler}' conflicts with fixed '{profile.sampler}'")
    if str(scheduler or "") != profile.scheduler:
        problems.append(f"scheduler '{scheduler}' conflicts with fixed '{profile.scheduler}'")
    if steps is None or float(steps) != float(profile.steps):
        problems.append(f"steps {steps} conflicts with fixed {profile.steps}")
    if cfg_scale is None or float(cfg_scale) != profile.cfg_scale:
        problems.append(f"CFG {cfg_scale} conflicts with fixed {profile.cfg_scale}")
    if (width, height) not in profile.geometries:
        allowed = ", ".join(f"{w}x{h}" for w, h in profile.geometries)
        problems.append(f"geometry {width}x{height} is not supported (supported: {allowed})")
    if str(negative_prompt or "").strip():
        problems.append("a negative prompt is not supported (CFG 1.0 ignores negative text)")
    problems.extend(f"{feature} is not supported" for feature in unsupported_features)
    if problems:
        raise Flux1ProfileError(
            f"{profile.display_name} (profile v{profile.version}) cannot run this work: " + "; ".join(problems)
        )
    return MODE_TXT2IMG


def distilled_cfg_conflicts(config: Mapping[str, Any] | None, profile: Flux1Profile) -> list[str]:
    """A ``distilled_cfg_scale`` anywhere in the config must be the profile's own value (never rewritten here)."""

    data = config if isinstance(config, Mapping) else {}
    found: list[str] = []
    for source in (data, _mapping(data.get("txt2img"))):
        value = source.get("distilled_cfg_scale")
        if value is not None and float(value) != profile.distilled_cfg_scale:
            found.append(f"distilled CFG {value} (the profile fixes {profile.distilled_cfg_scale:g})")
    return found


# -- compile policy ------------------------------------------------------------------------------------------------


def apply_flux1_compile_policy(config: dict[str, Any]) -> dict[str, Any]:
    """Freeze the profile's own values into a merged txt2img config (in place; returns it).

    Fixes sampler, scheduler, steps, CFG, distilled guidance and CLIP skip; clears negative and global prompt text; turns
    the prompt optimizer off; stamps the profile reference. Geometry, counts, stages, LoRA and optional features are left
    for the fail-closed validators, so a conflict is refused, never rewritten. A frozen reference is never upgraded.
    """

    options = dict(config.get("backend_options") or {})
    image = dict(_mapping(options.get("image")))
    reference = image.get("model_profile")
    profile = (
        resolve_flux1_reference(reference) if isinstance(reference, Mapping) and reference.get("id") == FLUX1_PROFILE_ID
        else latest_flux1_profile()
    )
    if isinstance(reference, Mapping) and reference.get("id") not in (None, FLUX1_PROFILE_ID):
        raise Flux1ProfileError(
            f"The selected checkpoint is a FLUX.1 [dev]-class transformer, but the work is frozen to profile "
            f"{reference.get('id')!r}; rebuild the job"
        )
    owned = {
        "vae": "",
        "sampler_name": profile.sampler,
        "scheduler": profile.scheduler,
        "steps": profile.steps,
        "cfg_scale": profile.cfg_scale,
        "distilled_cfg_scale": profile.distilled_cfg_scale,
        "clip_skip": FIXED_CLIP_SKIP,
        "negative_prompt": "",
    }
    txt2img = config.setdefault("txt2img", {})
    if not isinstance(txt2img, dict):
        txt2img = {}
        config["txt2img"] = txt2img
    txt2img.update(
        owned,
        prompt_optimizer={"enabled": False},
        global_positive_prompt="",
        global_negative_prompt="",
        global_prompt_policy_source="frozen_njr",
    )
    for key, value in (*owned.items(), ("sampler", profile.sampler)):
        if key in config:
            config[key] = value
    optimizer = config.get("prompt_optimizer")
    config["prompt_optimizer"] = {**_mapping(optimizer), "enabled": False}
    pipeline = dict(config.get("pipeline") or {})
    for key in (
        "apply_global_positive_txt2img",
        "apply_global_negative_txt2img",
        "apply_global_negative_img2img",
        "apply_global_negative_adetailer",
        "apply_global_negative_upscale",
    ):
        pipeline[key] = False
    config["pipeline"] = pipeline
    config["global_positive_prompt"] = ""
    config["global_negative_prompt"] = ""
    config["global_prompt_policy_source"] = "frozen_njr"
    image["model_profile"] = profile.reference()
    options["image"] = image
    config["backend_options"] = options
    return config


# -- wire seam and evidence ------------------------------------------------------------------------------------------


def project_flux1_wire_payload(config: Mapping[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """At the real executor boundary: send the profile's distilled guidance; ordinary payloads are untouched."""

    from src.image_backends.exact_model_profile import resolve_model_profile

    profile = resolve_model_profile(config.get("backend_options"))
    if not isinstance(profile, Flux1Profile):
        return payload
    if float(payload.get("cfg_scale", profile.cfg_scale)) != profile.cfg_scale or str(payload.get("negative_prompt") or ""):
        raise Flux1ProfileError("FLUX.1 [dev] CFG or negative text changed after admission")
    payload["distilled_cfg_scale"] = profile.distilled_cfg_scale
    return payload


def flux1_provenance(profile: Flux1Profile, *, model_name: str) -> dict[str, Any]:
    """Durable, machine-path-free evidence recorded with the stage result."""

    return {
        "model_profile": profile.reference(),
        "family": "flux1",
        "backend_id": profile.backend_id,
        "mode": MODE_TXT2IMG,
        "forge_revision": profile.forge_revision,
        "identity_rule": "transformer by structural layout; encoders and VAE by size and SHA-256",
        "transformer": {"name": model_name, "required_variant": profile.transformer_variant},
        "modules": [{"name": a.filename, "size": a.size, "sha256": a.sha256} for a in profile.modules],
        "sampler": profile.sampler,
        "scheduler": profile.scheduler,
        "steps": profile.steps,
        "cfg_scale": profile.cfg_scale,
        "distilled_cfg_scale": profile.distilled_cfg_scale,
        "qualification_status": "not physically qualified",
    }


__all__ = [
    "FIXED_CLIP_SKIP",
    "FLUX1_DEV_PROFILE_V1",
    "FLUX1_DISPLAY_NAME",
    "FLUX1_PROFILE_ID",
    "FLUX1_PROVENANCE_KEY",
    "FLUX1_UNPROFILED_HINT",
    "FLUX_VARIANT_REFUSALS",
    "Flux1Profile",
    "Flux1ProfileError",
    "VariantLookup",
    "apply_flux1_compile_policy",
    "distilled_cfg_conflicts",
    "flux1_provenance",
    "flux1_selected",
    "flux_variant_refusal",
    "frozen_profile_is_flux1",
    "install_variant_lookup",
    "latest_flux1_profile",
    "project_flux1_wire_payload",
    "resolve_flux1_reference",
    "selected_model_name",
    "validate_flux1_intent",
    "variant_for_model",
]
