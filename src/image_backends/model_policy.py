"""Model-family capability / operator-policy registry (PR-IMG-130A).

One pure, GUI-free answer to "what may StableNew present and accept for this image model?". It keeps four
concepts distinct and is none of them:

* **backend/runtime identity** (``forge_webui`` / ``a1111_webui``): configuration, never inferred here;
* **model family** (``sdxl``, ``flux2_klein``, ``unknown`` ...): from the exact qualified profile first, else from
  ``AssetRegistry`` compatibility evidence (the single local family-evidence authority). Unknown and conflicting
  evidence stay unknown/conflicting; nothing is guessed, in particular nothing unclassified is labelled SDXL;
* **exact qualified executable profile** (``flux2_klein_4b_fp8@v2``): the immutable, versioned profile in
  ``forge_klein_profile``. A persisted reference resolves to the version it froze; this module only *projects* it;
* **capability / operator policy** (``ModelPolicy``): which controls are configurable, supported-but-fixed or
  unsupported, which optional features are supported, and read-only hooks for prompt dialect and Learning.

This is not a second executor, compiler, scanner or hash authority. The compiler still freezes and rejects exact
semantics through the profile (``apply_model_compile_policy`` dispatches to the existing Klein compile policy); the GUI
projects the same policy but is advisory. Nothing here performs I/O at import; the optional family lookup reads only
the registry's persisted snapshot (no scan, no hashing, no network). ``src/learning/model_profiles.py`` is a different,
older concept (learning/style priors) and is deliberately not merged with this one.
"""

from __future__ import annotations

import copy
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.assets.flux_variant import (
    VARIANT_FLUX1_DEV,
    VARIANT_FLUX1_SCHNELL,
    VARIANT_FLUX2_KLEIN_4B,
    VARIANT_FLUX2_KLEIN_9B,
    variant_from_architecture,
    variant_label,
)
from src.image_backends.comfy_qwen_image_profile import (
    QwenImageProfile,
    apply_qwen_image_compile_policy,
    frozen_qwen_image_profile,
    qwen_image_profile_for_model,
    qwen_image_selected,
)
from src.image_backends.diffusers_ideogram4_profile import (
    IDEOGRAM4_PROFILE_V1,
    Ideogram4Profile,
    apply_ideogram4_compile_policy,
    frozen_profile_is_ideogram4,
    ideogram4_selected,
    is_ideogram4_model_name,
)
from src.image_backends.exact_model_profile import ExactModelProfile, resolve_model_profile
from src.image_backends.forge_flux1_profile import (
    FLUX1_DEV_PROFILE_V1,
    Flux1Profile,
    apply_flux1_compile_policy,
    flux1_selected,
    flux_variant_refusal,
    frozen_profile_is_flux1,
)
from src.image_backends.forge_klein_profile import (
    KLEIN_PROFILE_ID,
    apply_klein_compile_policy,
    is_klein_transformer_name,
    klein_selected,
    latest_klein_profile,
)
from src.image_backends.forge_zimage_profile import (
    FIXED_CLIP_SKIP,
    ZIMAGE_PROFILE_V1,
    ZImageProfile,
    ZImageProfileError,
    apply_zimage_compile_policy,
    is_zimage_transformer_name,
    project_shared_baseline,
    validate_zimage_config,
    zimage_selected,
)
from src.image_backends.image_backend_types import (
    A1111_IMAGE_BACKEND_ID,
    FORGE_IMAGE_BACKEND_ID,
    normalize_image_backend_options,
    resolve_image_backend_id,
)

# -- broad model families (concept B) ---------------------------------------------------------------------------
FAMILY_SDXL = "sdxl"
FAMILY_FLUX2_KLEIN = "flux2_klein"
FAMILY_IDEOGRAM4 = "ideogram4"
FAMILY_QWEN_IMAGE = "qwen_image"
#: FLUX.1 (dev/schnell) layouts (PR-IMG-FLUX-130); the coarse registry family stays ``flux``.
FAMILY_FLUX1 = "flux1"
FAMILY_FLUX = "flux"
FAMILY_UNKNOWN = "unknown"

EVIDENCE_PROFILE = "exact_profile"
EVIDENCE_REGISTRY = "registry_evidence"
EVIDENCE_NONE = "no_evidence"
EVIDENCE_UNKNOWN = "unknown_evidence"
EVIDENCE_CONFLICTING = "conflicting_evidence"
#: A family profile admitted by the checkpoint's structural layout (PR-IMG-FLUX-130): a real profile, but never an
#: exact-identity authority (Model Comparison and other exact-identity consumers keep refusing it).
EVIDENCE_STRUCTURAL = "structural_profile"

POLICY_ID_SDXL = "sdxl"
POLICY_ID_UNVERIFIED = "unverified_generic"

#: Registry-evidenced (ordinary-checkpoint) policies whose capabilities an owner has qualified for studies that
#: compare models. A family with evidence but no entry here (sd1, sd2, sd3, flux ...) stays labelled-but-unqualified;
#: qualifying one means authoring its ``ModelPolicy`` and adding its id here, in this module, with owner approval.
QUALIFIED_REGISTRY_POLICY_IDS: frozenset[str] = frozenset({POLICY_ID_SDXL})

#: ``prompt_dialect`` hook values (guidance for later prompt packages; nothing rewrites a prompt here).
DIALECT_WEIGHTED_TAGS = "sdxl_weighted_tags"
DIALECT_NATURAL_LANGUAGE = "natural_language"
DIALECT_UNSPECIFIED = "unspecified"

#: Names of the existing per-profile LoRA compatibility policy a ``FeaturePolicy`` may point to.
LORA_POLICY_KLEIN_4B_EXPLICIT = "klein_4b_explicit_metadata"

STAGE_TXT2IMG = "txt2img"
STAGE_IMG2IMG = "img2img"
STAGE_ADETAILER = "adetailer"
STAGE_UPSCALE = "upscale"
GENERIC_IMAGE_STAGES = (STAGE_TXT2IMG, STAGE_IMG2IMG, STAGE_ADETAILER, STAGE_UPSCALE)

#: Value controls a policy governs (Base Generation panel).
CONTROL_SAMPLER = "sampler"
CONTROL_SCHEDULER = "scheduler"
CONTROL_STEPS = "steps"
CONTROL_CFG = "cfg_scale"
CONTROL_VAE = "vae"
CONTROL_GEOMETRY = "geometry"
VALUE_CONTROLS = (CONTROL_SAMPLER, CONTROL_SCHEDULER, CONTROL_STEPS, CONTROL_CFG, CONTROL_VAE, CONTROL_GEOMETRY)

#: Optional features a policy states a position on.
FEATURES = (
    "negative_prompt", "prompt_optimizer", "embeddings", "lora", "hires", "refiner", "adetailer", "controlnet", "upscale",
)


class ControlMode(str, Enum):
    CONFIGURABLE = "configurable"
    FIXED = "fixed"  # supported at exactly one authoritative value
    UNSUPPORTED = "unsupported"


class Support(str, Enum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    #: StableNew's generic WebUI path still allows it as before, but no qualification claims it for this model.
    UNVERIFIED = "unverified"


@dataclass(frozen=True, slots=True)
class ControlPolicy:
    mode: ControlMode = ControlMode.CONFIGURABLE
    #: The authoritative value when ``FIXED``.
    value: Any = None
    #: Restricted choices (geometry: qualified (width, height) pairs; the first is the default); empty = unrestricted.
    allowed: tuple[Any, ...] = ()


@dataclass(frozen=True, slots=True)
class FeaturePolicy:
    support: Support = Support.SUPPORTED
    #: Upper bound where one exists (for example one LoRA); ``None`` means no bound.
    limit: int | None = None
    #: Reference to an existing, separately owned compatibility policy (LoRA); never a copy of its rules.
    compatibility_policy: str = ""
    #: Empty means every model-supported stage; otherwise support is stage-local.
    stages: tuple[str, ...] = ()

    @property
    def supported(self) -> bool:
        return self.support is Support.SUPPORTED


_CONFIGURABLE = ControlPolicy()
_SUPPORTED = FeaturePolicy()
_UNSUPPORTED = FeaturePolicy(Support.UNSUPPORTED)
_UNVERIFIED = FeaturePolicy(Support.UNVERIFIED)


@dataclass(frozen=True, slots=True)
class ModelPolicy:
    """Read-only capability/operator policy of one model selection (concept D)."""

    policy_id: str
    family: str
    display_name: str
    #: Where the family came from (``exact_profile``, ``registry_evidence``, ``no_evidence``, ``unknown_evidence``,
    #: ``conflicting_evidence``): an ordinary-model family is evidence, never a qualification.
    evidence: str
    controls: Mapping[str, ControlPolicy]
    features: Mapping[str, FeaturePolicy]
    #: Backend ids this policy may run on; empty means "whatever WebUI-family backend is configured".
    allowed_backends: tuple[str, ...] = ()
    required_backend: str | None = None
    #: The exact qualified executable profile reference (``{"id", "version"}``), when one exists.
    profile_ref: Mapping[str, Any] | None = None
    stages: tuple[str, ...] = GENERIC_IMAGE_STAGES
    #: Qualified generation modes (a profile's named modes); defaults to the stages for generic work.
    modes: tuple[str, ...] = GENERIC_IMAGE_STAGES
    prompt_dialect: str = DIALECT_UNSPECIFIED
    #: Operator-facing explanation of fixed/unsupported behavior (policy-authored; the GUI only shows it).
    note: str = ""
    stage_controls: Mapping[str, Mapping[str, ControlPolicy]] = field(default_factory=dict)
    #: Non-empty when StableNew refuses this model outright (shown as the blocking sentence; the backend refuses
    #: independently). Not part of a frozen Learning policy context.
    refusal: str = ""

    def control(self, name: str, stage: str | None = None) -> ControlPolicy:
        if stage is not None and name in self.stage_controls.get(stage, {}):
            return self.stage_controls[stage][name]
        return self.controls.get(name, _CONFIGURABLE)

    def feature(self, name: str, stage: str | None = None) -> FeaturePolicy:
        feature = self.features.get(name, _UNVERIFIED)
        if stage is not None and feature.stages and stage not in feature.stages:
            return _UNSUPPORTED
        return feature

    @property
    def qualified(self) -> bool:
        """An exact executable profile exists; this never establishes broad hardware qualification."""

        return self.profile_ref is not None

    @property
    def exact_identity_authority(self) -> bool:
        """The canonical exact profile, not a local byte hash, is this selection's checkpoint-identity authority."""

        return self.profile_ref is not None and self.evidence == EVIDENCE_PROFILE

    @property
    def explicit_capabilities(self) -> bool:
        """Whether the policy takes an explicit position on every optional feature.

        False only for the conservative generic projection (``unverified_generic``): a family label backed by evidence,
        but no qualification states what the model can execute, so nothing may be built on it. Derived from the
        policy's own content, so a frozen policy context needs no new field and an old frozen arm resolves exactly as
        it did before.
        """

        return bool(self.features) and all(
            feature.support is not Support.UNVERIFIED for feature in self.features.values()
        )

    @property
    def constrained(self) -> bool:
        """Whether any value control is fixed or unsupported (the Base Generation panel must project it)."""

        return any(
            self.control(name).mode is not ControlMode.CONFIGURABLE or bool(self.control(name).allowed)
            for name in VALUE_CONTROLS
        )

    def learning_variables(self) -> tuple[str, ...]:
        """Settings a Learning experiment may vary for this model (read-only hook for PR-LEARN-130D).

        Derived, never declared: unrestricted configurable value controls, plus the LoRA strength where LoRA is
        supported. Fixed or unsupported controls, qualified-choice geometry and unsupported features are never varied.
        """

        names = [
            name for name in VALUE_CONTROLS
            if self.control(name).mode is ControlMode.CONFIGURABLE and not self.control(name).allowed
        ]
        if self.feature("lora").supported:
            names.append("lora_strength")
        return tuple(names)


def _controls(**overrides: ControlPolicy) -> dict[str, ControlPolicy]:
    return {name: overrides.get(name, _CONFIGURABLE) for name in VALUE_CONTROLS}


def _features(default: FeaturePolicy, **overrides: FeaturePolicy) -> dict[str, FeaturePolicy]:
    return {name: overrides.get(name, default) for name in FEATURES}


# -- policies ---------------------------------------------------------------------------------------------------


def policy_for_profile(profile: ExactModelProfile) -> ModelPolicy:
    """The policy of one exact qualified profile version (v1 admits no LoRA, v2 admits one)."""

    fixed = ControlMode.FIXED
    if isinstance(profile, Ideogram4Profile):
        return _ideogram4_policy(profile)
    if isinstance(profile, QwenImageProfile):
        return _qwen_image_policy(profile)
    if isinstance(profile, Flux1Profile):
        return _flux1_policy(profile)
    if isinstance(profile, ZImageProfile):
        return ModelPolicy(
            policy_id=profile.profile_id, family="z_image", display_name=profile.display_name,
            evidence=EVIDENCE_PROFILE, allowed_backends=(profile.backend_id,), required_backend=profile.backend_id,
            profile_ref=profile.reference(), stages=(STAGE_TXT2IMG,), modes=profile.modes,
            controls=_controls(
                sampler=ControlPolicy(fixed, profile.sampler), scheduler=ControlPolicy(fixed, profile.scheduler),
                steps=ControlPolicy(fixed, profile.steps), cfg_scale=ControlPolicy(fixed, profile.cfg_scale),
                vae=ControlPolicy(fixed, ""), geometry=ControlPolicy(fixed, (1024, 1024), allowed=profile.geometries),
            ),
            features=_features(_UNSUPPORTED), prompt_dialect=DIALECT_NATURAL_LANGUAGE,
            note=("Z-Image-Turbo FP8 limited support: exact three-file bundle, managed pinned Forge, txt2img only; "
                  "one 1024x1024 image, Euler/Beta/9 steps/CFG 1/shift 9 (distilled_cfg_scale). "
                  "PromptPack compilation adapts weighted prose and omits structured LoRAs, embeddings, negative prompts and the "
                  "global negative; PromptPack, generic Pipeline and Model Comparison compilation compose enabled global positive "
                  "terms into the prompt and replace inherited sampling, CLIP skip and prompt-optimizer settings with the "
                  "profile's own (manual prompts are validated, not adapted). "
                  "Saved packs are preserved; adaptation is recorded in the queued job. "
                  "Optional stages/modifiers and unresolved inline adapter/embedding tokens remain unsupported. "
                  "One physical generation was observed; clean-shutdown qualification and repeated-run stability remain incomplete. "
                  "32-GB-class total RAM is required; available RAM/commit are observational, without floors."),
        )
    lora = (
        FeaturePolicy(Support.SUPPORTED, limit=profile.max_loras, compatibility_policy=LORA_POLICY_KLEIN_4B_EXPLICIT,
                      stages=(STAGE_TXT2IMG,))
        if profile.max_loras > 0
        else _UNSUPPORTED
    )
    note = (
        f"{profile.display_name} uses fixed distilled settings ({profile.sampler}, {profile.scheduler}, "
        f"{profile.steps} steps, CFG {profile.cfg_scale:g}) and the qualified 768x1024 / 1024x1024 sizes "
        "only. The qualified distilled path uses no standard negative prompt (CFG 1.0 ignores negative text), "
        "so describe what you want positively instead."
    )
    if profile.max_loras > 0:
        note += (
            f" Up to {profile.max_loras} LoRA is supported, and only one whose metadata explicitly names "
            "FLUX.2 Klein 4B; other adapters are shown as not verified and are rejected before generation."
        )
    return ModelPolicy(
        policy_id=profile.profile_id,
        family=FAMILY_FLUX2_KLEIN,
        display_name=profile.display_name,
        evidence=EVIDENCE_PROFILE,
        allowed_backends=(profile.backend_id,),
        required_backend=profile.backend_id,
        profile_ref=profile.reference(),
        stages=(STAGE_TXT2IMG, STAGE_IMG2IMG),  # img2img only as the single-reference edit mode, never free-form
        modes=tuple(profile.modes),
        controls=_controls(
            sampler=ControlPolicy(fixed, profile.sampler),
            scheduler=ControlPolicy(fixed, profile.scheduler),
            steps=ControlPolicy(fixed, profile.steps),
            cfg_scale=ControlPolicy(fixed, profile.cfg_scale),
            vae=ControlPolicy(fixed, ""),  # the profile loads its own VAE module; no separate selection
            # A restricted choice, not a single value: the qualified sizes are selectable; the first is the default.
            geometry=ControlPolicy(ControlMode.CONFIGURABLE, allowed=tuple(profile.geometries)),
        ),
        features=_features(
            _UNSUPPORTED,
            lora=lora,
        ),
        prompt_dialect=DIALECT_NATURAL_LANGUAGE,
        note=note,
        stage_controls={STAGE_IMG2IMG: {
            "denoise_strength": ControlPolicy(fixed, profile.edit_denoising_strength),
        }},
    )


def _ideogram4_policy(profile: Ideogram4Profile) -> ModelPolicy:
    """Ideogram 4 NF4 via Diffusers (PR-IMG-120): txt2img only, the official presets, the 110R-tested sizes."""

    fixed = ControlMode.FIXED
    return ModelPolicy(
        policy_id=profile.profile_id, family=FAMILY_IDEOGRAM4, display_name=profile.display_name,
        evidence=EVIDENCE_PROFILE, allowed_backends=(profile.backend_id,), required_backend=profile.backend_id,
        profile_ref=profile.reference(), stages=(STAGE_TXT2IMG,), modes=profile.modes,
        controls=_controls(
            sampler=ControlPolicy(fixed, profile.sampler), scheduler=ControlPolicy(fixed, profile.scheduler),
            # A restricted choice: each allowed step count is one official preset (the first listed is the default).
            steps=ControlPolicy(ControlMode.CONFIGURABLE, allowed=(profile.default_steps, *(
                s for s in profile.allowed_steps if s != profile.default_steps))),
            cfg_scale=ControlPolicy(fixed, profile.cfg_scale), vae=ControlPolicy(fixed, ""),
            geometry=ControlPolicy(ControlMode.CONFIGURABLE, allowed=profile.geometries),
        ),
        features=_features(_UNSUPPORTED), prompt_dialect=DIALECT_NATURAL_LANGUAGE,
        note=("Ideogram 4 NF4 runs in its own contained Diffusers process, one job at a time, after StableNew releases "
              "its own Forge/A1111, Comfy and SVD runtimes. Steps choose the official preset: 12 Turbo, 20 Default, "
              "48 Quality; sizes are the tested 1024x1024, 768x1024, 1024x768, 768x768 and 512x512; 1-4 images per job. "
              "Write plain text, or paste an Ideogram JSON caption (checked against the official caption schema before "
              "queueing). No negative prompt, LoRA, embeddings or extra stages. Each job loads the model again "
              "(about 20 s). Non-commercial licence. Not yet physically qualified in StableNew."),
    )


def _flux1_policy(profile: Flux1Profile) -> ModelPolicy:
    """FLUX.1 [dev] family profile (PR-IMG-FLUX-130): txt2img only, fixed distilled settings, the five sizes."""

    fixed = ControlMode.FIXED
    return ModelPolicy(
        policy_id=profile.profile_id, family=FAMILY_FLUX1, display_name=profile.display_name,
        evidence=EVIDENCE_STRUCTURAL, allowed_backends=(profile.backend_id,), required_backend=profile.backend_id,
        profile_ref=profile.reference(), stages=(STAGE_TXT2IMG,), modes=profile.modes,
        controls=_controls(
            sampler=ControlPolicy(fixed, profile.sampler), scheduler=ControlPolicy(fixed, profile.scheduler),
            steps=ControlPolicy(fixed, profile.steps), cfg_scale=ControlPolicy(fixed, profile.cfg_scale),
            vae=ControlPolicy(fixed, ""),
            geometry=ControlPolicy(ControlMode.CONFIGURABLE, allowed=profile.geometries),
        ),
        features=_features(_UNSUPPORTED), prompt_dialect=DIALECT_NATURAL_LANGUAGE,
        note=(f"FLUX.1 [dev]-class transformer on the managed Forge: {profile.sampler} / {profile.scheduler} / "
              f"{profile.steps} steps / CFG {profile.cfg_scale:g} / distilled guidance {profile.distilled_cfg_scale:g}, "
              "one image, txt2img only. Any transformer-only file with the FLUX.1 [dev] layout runs under this profile "
              "(fine-tunes included; its SHA-256 is recorded, not required). CLIP-L, T5-XXL FP8 and the FLUX.1 VAE must be "
              "the exact pinned files. No negative prompt, LoRA, embeddings or extra stages. Non-commercial licence. "
              "Not yet physically qualified in StableNew."),
    )


def _flux_refused_policy(variant: str) -> ModelPolicy:
    """A FLUX layout class with no executable profile: labelled precisely, every feature unsupported, refused."""

    family = FAMILY_FLUX1 if variant == VARIANT_FLUX1_SCHNELL else (
        FAMILY_FLUX2_KLEIN if variant in (VARIANT_FLUX2_KLEIN_4B, VARIANT_FLUX2_KLEIN_9B) else FAMILY_FLUX
    )
    refusal = flux_variant_refusal(variant)
    return ModelPolicy(
        policy_id=f"flux_refused:{variant}",
        family=family,
        display_name=f"{variant_label(variant)} (refused)",
        evidence=EVIDENCE_REGISTRY,
        allowed_backends=(FORGE_IMAGE_BACKEND_ID,),
        controls=_controls(),
        features=_features(_UNSUPPORTED),
        stages=(),
        modes=(),
        prompt_dialect=DIALECT_NATURAL_LANGUAGE,
        note=refusal,
        refusal=refusal,
    )


def _qwen_image_policy(profile: QwenImageProfile) -> ModelPolicy:
    """Qwen-Image 2.1 on the Comfy still-image backend (PR-IMG-COMFY-100): txt2img only, frozen graph values."""

    fixed = ControlMode.FIXED
    return ModelPolicy(
        policy_id=profile.profile_id, family=FAMILY_QWEN_IMAGE, display_name=profile.display_name,
        evidence=EVIDENCE_PROFILE, allowed_backends=(profile.backend_id,), required_backend=profile.backend_id,
        profile_ref=profile.reference(), stages=(STAGE_TXT2IMG,), modes=profile.modes,
        controls=_controls(
            sampler=ControlPolicy(fixed, profile.sampler), scheduler=ControlPolicy(fixed, profile.scheduler),
            steps=ControlPolicy(fixed, profile.steps), cfg_scale=ControlPolicy(fixed, profile.cfg_scale),
            vae=ControlPolicy(fixed, ""), geometry=ControlPolicy(ControlMode.CONFIGURABLE, allowed=profile.geometries),
        ),
        features=_features(_UNSUPPORTED), prompt_dialect=DIALECT_NATURAL_LANGUAGE,
        note=(f"{profile.display_name} runs on StableNew's own managed ComfyUI, one image per job, after StableNew "
              f"releases its own Forge/A1111 and SVD runtimes; ComfyUI is stopped after each job, so each job loads the "
              f"model again. Fixed {profile.steps} steps, cfg {profile.cfg_scale:g}; sizes are the 1-megapixel set "
              "(1024x1024 and six aspect ratios). Plain natural-language prompts only: no negative prompt, LoRA, "
              "embeddings or extra stages. Weights are never downloaded by StableNew. Non-commercial licence (Qwen "
              "Research License). Not yet physically qualified in StableNew."),
    )  # fmt: skip


def _sdxl_policy(evidence: str) -> ModelPolicy:
    """Existing StableNew behavior for an SDXL-family checkpoint: nothing narrowed, nothing newly claimed qualified."""

    return ModelPolicy(
        policy_id=POLICY_ID_SDXL,
        family=FAMILY_SDXL,
        display_name="SDXL",
        evidence=evidence,
        allowed_backends=(FORGE_IMAGE_BACKEND_ID, A1111_IMAGE_BACKEND_ID),
        controls=_controls(),
        features=_features(_SUPPORTED, controlnet=_UNSUPPORTED),  # the image path exposes no ControlNet
        prompt_dialect=DIALECT_WEIGHTED_TAGS,
    )


def _unverified_policy(family: str, evidence: str) -> ModelPolicy:
    """Conservative projection: generic WebUI usability exactly as before, no capability claims, no family guess."""

    return ModelPolicy(
        policy_id=POLICY_ID_UNVERIFIED if family == FAMILY_UNKNOWN else f"{POLICY_ID_UNVERIFIED}:{family}",
        family=family,
        display_name="Unclassified model" if family == FAMILY_UNKNOWN else f"{family.upper()} (unqualified)",
        evidence=evidence,
        allowed_backends=(FORGE_IMAGE_BACKEND_ID, A1111_IMAGE_BACKEND_ID),
        controls=_controls(),
        features=_features(_UNVERIFIED, controlnet=_UNSUPPORTED),
        prompt_dialect=DIALECT_UNSPECIFIED,
    )


# -- resolution -------------------------------------------------------------------------------------------------

#: ``family lookup``: model name -> registry ``CompatibilityProfile`` (or ``None`` when nothing is known).
FamilyLookup = Callable[[str], Any]


def policy_for_model_profile_reference(backend_options: Any) -> ModelPolicy | None:
    """The policy of the exact profile version a persisted NJR froze (``None`` without a profile reference).

    A malformed/unknown reference raises ``KleinProfileError`` exactly as before: it is never reinterpreted.
    """

    profile = resolve_model_profile(backend_options)
    return None if profile is None else policy_for_profile(profile)


def resolve_model_profile_for_policy(policy: ModelPolicy) -> ExactModelProfile | None:
    """The immutable exact profile a policy projects (``None`` for an ordinary or unverified target)."""

    if policy.profile_ref is None:
        return None
    return resolve_model_profile({"image": {"model_profile": dict(policy.profile_ref)}})


def resolve_model_policy(model_name: str | None, *, family_lookup: FamilyLookup | None = None) -> ModelPolicy:
    """The policy for a selected checkpoint: exact qualified profile, else registry evidence, else unverified.

    The exact Klein identity (whole-name match, never a substring) is consulted before any family inference.
    ``family_lookup`` is optional and must be cheap and non-scanning (the registry's persisted snapshot).
    """

    if is_klein_transformer_name(model_name):
        return policy_for_profile(latest_klein_profile())
    if is_zimage_transformer_name(model_name):
        return policy_for_profile(ZIMAGE_PROFILE_V1)
    if is_ideogram4_model_name(model_name):
        return policy_for_profile(IDEOGRAM4_PROFILE_V1)
    qwen = qwen_image_profile_for_model(model_name)
    if qwen is not None:
        return policy_for_profile(qwen)
    if not str(model_name or "").strip() or family_lookup is None:
        return _unverified_policy(FAMILY_UNKNOWN, EVIDENCE_NONE)
    try:
        compat = family_lookup(str(model_name))
    except Exception:  # noqa: BLE001 - an unreadable cache is absent evidence, never a guess
        compat = None
    if compat is None:
        return _unverified_policy(FAMILY_UNKNOWN, EVIDENCE_NONE)
    status = getattr(getattr(compat, "status", None), "value", "")
    if status == "conflicting":
        return _unverified_policy(FAMILY_UNKNOWN, EVIDENCE_CONFLICTING)
    if getattr(compat, "structural_error", None) or getattr(compat, "checkpoint_architecture", None) in (
        "sdxl_refiner", "sdxl_inpaint"
    ):
        return _unverified_policy(FAMILY_UNKNOWN, EVIDENCE_UNKNOWN)
    family = getattr(compat, "family", None)
    if status != "resolved" or family is None:
        return _unverified_policy(FAMILY_UNKNOWN, EVIDENCE_UNKNOWN)
    family_value = str(getattr(family, "value", family))
    if family_value == FAMILY_SDXL:
        return _sdxl_policy(EVIDENCE_REGISTRY)
    if family_value == FAMILY_FLUX:
        # PR-IMG-FLUX-130: a transformer-only FLUX layout class recorded from structure. A bundled (all-in-one) FLUX
        # checkpoint and a filename/metadata-only FLUX label keep the previous labelled-but-unverified projection.
        layout = variant_from_architecture(getattr(compat, "checkpoint_architecture", None))
        if layout is not None and not layout[1]:
            if layout[0] == VARIANT_FLUX1_DEV:
                return policy_for_profile(FLUX1_DEV_PROFILE_V1)
            return _flux_refused_policy(layout[0])
    return _unverified_policy(family_value, EVIDENCE_REGISTRY)  # sd1/sd2/sd3/flux: labelled, never qualified


def _model_key(name: str) -> str:
    base = os.path.basename(str(name or "").strip().replace("\\", "/"))
    if base.endswith("]") and " [" in base:
        base = base[: base.rindex(" [")]
    lowered = base.strip().lower()
    for ext in (".safetensors", ".sft", ".ckpt", ".pt", ".pth", ".gguf"):
        if lowered.endswith(ext):
            return lowered[: -len(ext)]
    return lowered


class RegistryFamilyLookup:
    """Family evidence from ``AssetRegistry``'s persisted snapshot only (no scan, no hashing; safe on a UI thread).

    A checkpoint is matched by file name. Names that match records with different compatibility outcomes are
    reported as conflicting rather than resolved by picking one. Model Comparison
    readiness can instead bind runtime selections to exact served paths; that
    bounded lookup never falls back to another file with the same basename.
    """

    def __init__(self, registry: Any | None = None, *, model_paths: dict[str, Any] | None = None) -> None:
        self._registry = registry
        self._model_paths = model_paths

    def _get_registry(self) -> Any:
        if self._registry is None:
            from src.assets import AssetRegistry

            self._registry = AssetRegistry()
        return self._registry

    def __call__(self, model_name: str) -> Any:
        from src.assets import AssetKind
        from src.assets.compatibility import CompatibilityProfile, CompatibilityStatus

        registry = self._get_registry()
        if self._model_paths is None and getattr(registry, "webui_root", None) is None:
            return None
        from pathlib import Path

        exact = self._model_paths.get(model_name) if self._model_paths is not None else None
        if self._model_paths is not None and exact is None:
            return None
        key = _model_key(model_name)
        found = []
        for record in registry.cached_snapshot().records_for(AssetKind.CHECKPOINT):
            if record.compatibility is None:
                continue
            if any(
                (location.path == Path(exact) if exact is not None else _model_key(location.path.name) == key)
                for location in record.locations
                if location.kind is AssetKind.CHECKPOINT
            ):
                found.append(record.compatibility)
        if not found:
            return None
        outcomes = {(item.status, item.family,
                     item.checkpoint_architecture in ("sdxl_refiner", "sdxl_inpaint"),
                     bool(item.structural_error),
                     # Two same-named files of different FLUX layouts are a conflict, never a pick.
                     variant_from_architecture(item.checkpoint_architecture)) for item in found}
        if len(outcomes) > 1:
            return CompatibilityProfile(CompatibilityStatus.CONFLICTING, None, ())
        return found[0]


def registry_variant_lookup(family_lookup: FamilyLookup) -> Callable[[str], tuple[str, bool] | None]:
    """Adapt a family lookup to the FLUX structural-variant seam ``forge_flux1_profile.install_variant_lookup`` takes.

    Only a resolved FLUX family with a recorded layout answers; conflicting or unknown evidence answers ``None``.
    """

    def lookup(model_name: str) -> tuple[str, bool] | None:
        compat = family_lookup(model_name)
        family = getattr(compat, "family", None)
        if compat is None or getattr(getattr(compat, "status", None), "value", "") != "resolved":
            return None
        if str(getattr(family, "value", family)) != FAMILY_FLUX:
            return None
        return variant_from_architecture(getattr(compat, "checkpoint_architecture", None))

    return lookup


# -- compiler seam ----------------------------------------------------------------------------------------------

_COMPILE_POLICIES: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    KLEIN_PROFILE_ID: apply_klein_compile_policy,
}


def normalize_profile_owned_values(
    config: dict[str, Any], changes: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Replace inherited values the selected exact profile itself owns with the profile's own (in place).

    The one effective-configuration normalization (PR-IMG-MODELS-159): sampling, VAE, CLIP skip, prompt optimizer and
    global prompt terms/flags. Geometry, counts, seed policy, stages, assets and optional features are never touched,
    so ``apply_model_compile_policy`` still refuses a genuine conflict. A no-op for every other model. ``changes``
    optionally receives content-free records of what changed.
    """

    if zimage_selected(config):
        return project_shared_baseline(config, changes)
    return config


def prepare_candidate_baseline(config: dict[str, Any]) -> dict[str, Any]:
    """Independently prepare one candidate's run config from a *shared* comparison baseline (in place).

    Model Comparison starts every arm from one baseline that was authored for some other model. This step replaces
    only the values the exact profile itself owns (sampling, VAE, prompt optimizer, global prompt terms) with the
    profile's own, via the profile's projection; Klein's compile policy already owns those, and an ordinary model is
    untouched. It never changes geometry, counts, seed policy, stages or optional features, so
    ``apply_model_compile_policy`` (run next, unchanged) still refuses a genuine conflict.
    """

    return normalize_profile_owned_values(config)


def apply_model_compile_policy(config: dict[str, Any]) -> dict[str, Any]:
    """Freeze the exact qualified profile semantics of the selected model into a merged run config (in place).

    The compiler consumes the same exact-profile authority the GUI projects and never trusts the GUI: this is the
    one compile-time entry point, a no-op for every model that has no qualified profile (ordinary SDXL work is
    untouched). The per-profile rules live with the immutable profile and are unchanged.
    """

    if zimage_selected(config):
        return apply_zimage_compile_policy(config)
    if isinstance(resolve_model_profile(config.get("backend_options")), ZImageProfile):
        raise ValueError("The frozen Z-Image profile requires its exact selected checkpoint")
    if ideogram4_selected(config) or frozen_profile_is_ideogram4(config.get("backend_options")):
        return apply_ideogram4_compile_policy(config)
    if qwen_image_selected(config) or frozen_qwen_image_profile(config.get("backend_options")):
        return apply_qwen_image_compile_policy(config)
    if klein_selected(config):
        return _COMPILE_POLICIES[KLEIN_PROFILE_ID](config)
    if frozen_profile_is_flux1(config.get("backend_options")) or flux1_selected(config):
        return apply_flux1_compile_policy(config)
    return config


# -- one policy result, two configuration shapes (P4-2G) --------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ModelPolicyResult:
    """The one model compile-policy evaluation of a prepared configuration, and its two projections.

    The PromptPack route needs the exact profile's values in two shapes: on the nested resolved configuration (stage
    chain, ADetailer, randomizer and batch inputs, and the exact-profile refusals that precede the Klein review) and on
    the flat payload a record freezes (``workload.config``), whose flattening drops the profile's ``backend_options``,
    its ``txt2img`` section and some keys. ``compile_model_policy`` evaluates the policy once (the nested application,
    unchanged); the flat shape is a projection of that result onto the payload, not a second application. A result
    exists only after the evaluation passed, so a projection can never run before the refusals the evaluation raises.

    ``project_flat`` follows the payload's own checkpoint selection, exactly as the application it replaces did, and the
    profile values it writes come from the exact profile itself (``ZIMAGE_PROFILE_V1``, ``latest_klein_profile()``).
    A future model family adds its evaluation to ``apply_model_compile_policy`` and its projection here, in this module.
    """

    config: dict[str, Any]

    def project_nested(self) -> dict[str, Any]:
        """The evaluated nested configuration (the mapping ``compile_model_policy`` was given, updated in place)."""

        return self.config

    def project_flat(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Write the exact profile's values onto a flat PromptPack payload (in place; returns it).

        A no-op for every payload that selects no exact profile. For Z-Image it re-checks the payload against the
        profile (the flattening adds the rendered prompt and the per-record seed) before filling it; Klein rewrites the
        mirrored flat keys. Reproduces what applying the policy to the same payload wrote, which the legacy
        ``apply_*_compile_policy`` functions pin in tests.
        """

        if zimage_selected(payload):
            return _project_zimage_flat(payload)
        if isinstance(resolve_model_profile(payload.get("backend_options")), ZImageProfile):
            raise ValueError("The frozen Z-Image profile requires its exact selected checkpoint")
        if ideogram4_selected(payload) or frozen_profile_is_ideogram4(payload.get("backend_options")):
            return apply_ideogram4_compile_policy(payload)
        if qwen_image_selected(payload) or frozen_qwen_image_profile(payload.get("backend_options")):
            return apply_qwen_image_compile_policy(payload)
        if klein_selected(payload):
            return _project_klein_flat(payload)
        if frozen_profile_is_flux1(payload.get("backend_options")) or flux1_selected(payload):
            return apply_flux1_compile_policy(payload)
        return payload


def compile_model_policy(config: dict[str, Any]) -> ModelPolicyResult:
    """Evaluate the model compile policy once on a nested configuration (in place) and return its projections.

    ``apply_model_compile_policy`` is the evaluation; this wraps it so that the nested and the flat shape of one prepared
    configuration are two projections of one result.
    """

    return ModelPolicyResult(apply_model_compile_policy(config))


def _project_zimage_flat(payload: dict[str, Any]) -> dict[str, Any]:
    validate_zimage_config(payload)
    p = ZIMAGE_PROFILE_V1
    options = normalize_image_backend_options(payload.get("backend_options"), model_name=p.transformer.filename)
    if resolve_image_backend_id(options) != p.backend_id or resolve_model_profile(options) is not p:
        raise ZImageProfileError("Z-Image requires Forge and its exact v1 profile; no backend switch or profile upgrade")
    payload["backend_options"] = options
    stage = payload.setdefault("txt2img", {})
    defaults: dict[str, Any] = {
        "model": p.transformer.filename, "sampler": p.sampler, "sampler_name": p.sampler,
        "scheduler": p.scheduler, "steps": p.steps, "cfg_scale": p.cfg_scale,
        "width": p.geometries[0][0], "height": p.geometries[0][1], "distilled_cfg_scale": p.distilled_cfg_scale,
        "negative_prompt": "", "prompt_optimizer": {"enabled": False}, "clip_skip": FIXED_CLIP_SKIP,
    }
    for target in (payload, stage):
        for key, value in defaults.items():
            if target.get(key) is None:
                target[key] = copy.deepcopy(value)
    payload.setdefault("prompt_optimizer", {"enabled": False})
    payload["global_prompt_policy_source"] = "frozen_njr"
    payload.setdefault("global_positive_prompt", "")
    payload.setdefault("global_negative_prompt", "")
    pipeline = dict(payload.get("pipeline") or {})
    pipeline.update(apply_global_positive_txt2img=False, apply_global_negative_txt2img=False)
    payload["pipeline"] = pipeline
    return payload


def _project_klein_flat(payload: dict[str, Any]) -> dict[str, Any]:
    profile = latest_klein_profile()
    txt2img = payload.setdefault("txt2img", {})
    if not isinstance(txt2img, dict):
        txt2img = {}
        payload["txt2img"] = txt2img
    txt2img.update(
        vae="",
        sampler_name=profile.sampler,
        scheduler=profile.scheduler,
        steps=profile.steps,
        cfg_scale=profile.cfg_scale,
        negative_prompt="",
        prompt_optimizer={"enabled": False},
        global_positive_prompt="",
        global_negative_prompt="",
        global_prompt_policy_source="frozen_njr",
    )
    for flat, value in (
        ("sampler_name", profile.sampler),
        ("sampler", profile.sampler),
        ("scheduler", profile.scheduler),
        ("steps", profile.steps),
        ("cfg_scale", profile.cfg_scale),
        ("negative_prompt", ""),
        ("vae", ""),
    ):
        if flat in payload:
            payload[flat] = value
    optimizer = payload.get("prompt_optimizer")
    payload["prompt_optimizer"] = {**(optimizer if isinstance(optimizer, Mapping) else {}), "enabled": False}
    pipeline = dict(payload.get("pipeline") or {})
    pipeline["apply_global_positive_txt2img"] = False
    for key in (
        "apply_global_negative_txt2img",
        "apply_global_negative_img2img",
        "apply_global_negative_adetailer",
        "apply_global_negative_upscale",
    ):
        pipeline[key] = False
    payload["pipeline"] = pipeline
    payload["global_positive_prompt"] = ""
    payload["global_negative_prompt"] = ""
    payload["global_prompt_policy_source"] = "frozen_njr"
    backend_options = dict(payload.get("backend_options") or {})
    image = dict(backend_options.get("image") or {})
    image["model_profile"] = profile.reference()
    backend_options["image"] = image
    payload["backend_options"] = backend_options
    return payload


__all__ = [
    "CONTROL_CFG",
    "CONTROL_GEOMETRY",
    "CONTROL_SAMPLER",
    "CONTROL_SCHEDULER",
    "CONTROL_STEPS",
    "CONTROL_VAE",
    "ControlMode",
    "ControlPolicy",
    "EVIDENCE_CONFLICTING",
    "EVIDENCE_NONE",
    "EVIDENCE_PROFILE",
    "EVIDENCE_REGISTRY",
    "EVIDENCE_STRUCTURAL",
    "EVIDENCE_UNKNOWN",
    "FAMILY_FLUX",
    "FAMILY_FLUX1",
    "FAMILY_FLUX2_KLEIN",
    "FAMILY_IDEOGRAM4",
    "FAMILY_QWEN_IMAGE",
    "FAMILY_SDXL",
    "FAMILY_UNKNOWN",
    "FEATURES",
    "FeaturePolicy",
    "ModelPolicy",
    "ModelPolicyResult",
    "RegistryFamilyLookup",
    "Support",
    "VALUE_CONTROLS",
    "apply_model_compile_policy",
    "compile_model_policy",
    "normalize_profile_owned_values",
    "policy_for_model_profile_reference",
    "policy_for_profile",
    "prepare_candidate_baseline",
    "registry_variant_lookup",
    "resolve_model_policy",
    "resolve_model_profile_for_policy",
]
