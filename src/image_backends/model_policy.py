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

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from src.image_backends.forge_klein_profile import (
    KLEIN_PROFILE_ID,
    KleinProfile,
    apply_klein_compile_policy,
    is_klein_transformer_name,
    klein_selected,
    latest_klein_profile,
    resolve_model_profile,
)
from src.image_backends.image_backend_types import A1111_IMAGE_BACKEND_ID, FORGE_IMAGE_BACKEND_ID

# -- broad model families (concept B) ---------------------------------------------------------------------------
FAMILY_SDXL = "sdxl"
FAMILY_FLUX2_KLEIN = "flux2_klein"
FAMILY_UNKNOWN = "unknown"

EVIDENCE_PROFILE = "exact_profile"
EVIDENCE_REGISTRY = "registry_evidence"
EVIDENCE_NONE = "no_evidence"
EVIDENCE_UNKNOWN = "unknown_evidence"
EVIDENCE_CONFLICTING = "conflicting_evidence"

POLICY_ID_SDXL = "sdxl"
POLICY_ID_UNVERIFIED = "unverified_generic"

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

    def control(self, name: str) -> ControlPolicy:
        return self.controls.get(name, _CONFIGURABLE)

    def feature(self, name: str) -> FeaturePolicy:
        return self.features.get(name, _UNVERIFIED)

    @property
    def qualified(self) -> bool:
        """True only for an exact, versioned, qualified profile (a family label is never a qualification)."""

        return self.profile_ref is not None

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


def policy_for_profile(profile: KleinProfile) -> ModelPolicy:
    """The policy of one exact qualified profile version (v1 admits no LoRA, v2 admits one)."""

    fixed = ControlMode.FIXED
    lora = (
        FeaturePolicy(Support.SUPPORTED, limit=profile.max_loras, compatibility_policy=LORA_POLICY_KLEIN_4B_EXPLICIT)
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
    )


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


def resolve_model_policy(model_name: str | None, *, family_lookup: FamilyLookup | None = None) -> ModelPolicy:
    """The policy for a selected checkpoint: exact qualified profile, else registry evidence, else unverified.

    The exact Klein identity (whole-name match, never a substring) is consulted before any family inference.
    ``family_lookup`` is optional and must be cheap and non-scanning (the registry's persisted snapshot).
    """

    if is_klein_transformer_name(model_name):
        return policy_for_profile(latest_klein_profile())
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
    family = getattr(compat, "family", None)
    if status != "resolved" or family is None:
        return _unverified_policy(FAMILY_UNKNOWN, EVIDENCE_UNKNOWN)
    family_value = str(getattr(family, "value", family))
    if family_value == FAMILY_SDXL:
        return _sdxl_policy(EVIDENCE_REGISTRY)
    return _unverified_policy(family_value, EVIDENCE_REGISTRY)  # sd1/sd2/sd3/flux: labelled, never qualified


def _model_key(name: str) -> str:
    base = os.path.basename(str(name or "").strip().replace("\\", "/"))
    if base.endswith("]") and " [" in base:
        base = base[: base.rindex(" [")]
    lowered = base.strip().lower()
    for ext in (".safetensors", ".sft", ".ckpt", ".pt", ".pth"):
        if lowered.endswith(ext):
            return lowered[: -len(ext)]
    return lowered


class RegistryFamilyLookup:
    """Family evidence from ``AssetRegistry``'s persisted snapshot only (no scan, no hashing; safe on a UI thread).

    A checkpoint is matched by file name. Names that match records with different compatibility outcomes are
    reported as conflicting rather than resolved by picking one.
    """

    def __init__(self, registry: Any | None = None) -> None:
        self._registry = registry

    def _get_registry(self) -> Any:
        if self._registry is None:
            from src.assets import AssetRegistry

            self._registry = AssetRegistry()
        return self._registry

    def __call__(self, model_name: str) -> Any:
        from src.assets import AssetKind
        from src.assets.compatibility import CompatibilityProfile, CompatibilityStatus

        registry = self._get_registry()
        if getattr(registry, "webui_root", None) is None:
            return None
        key = _model_key(model_name)
        found = []
        for record in registry.cached_snapshot().records_for(AssetKind.CHECKPOINT):
            if record.compatibility is None:
                continue
            if any(
                _model_key(location.path.name) == key
                for location in record.locations
                if location.kind is AssetKind.CHECKPOINT
            ):
                found.append(record.compatibility)
        if not found:
            return None
        outcomes = {(item.status, item.family) for item in found}
        if len(outcomes) > 1:
            return CompatibilityProfile(CompatibilityStatus.CONFLICTING, None, ())
        return found[0]


# -- compiler seam ----------------------------------------------------------------------------------------------

_COMPILE_POLICIES: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    KLEIN_PROFILE_ID: apply_klein_compile_policy,
}


def apply_model_compile_policy(config: dict[str, Any]) -> dict[str, Any]:
    """Freeze the exact qualified profile semantics of the selected model into a merged run config (in place).

    The compiler consumes the same exact-profile authority the GUI projects and never trusts the GUI: this is the
    one compile-time entry point, a no-op for every model that has no qualified profile (ordinary SDXL work is
    untouched). The per-profile rules live with the immutable profile and are unchanged.
    """

    if klein_selected(config):
        return _COMPILE_POLICIES[KLEIN_PROFILE_ID](config)
    return config


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
    "EVIDENCE_UNKNOWN",
    "FAMILY_FLUX2_KLEIN",
    "FAMILY_SDXL",
    "FAMILY_UNKNOWN",
    "FEATURES",
    "FeaturePolicy",
    "ModelPolicy",
    "RegistryFamilyLookup",
    "Support",
    "VALUE_CONTROLS",
    "apply_model_compile_policy",
    "policy_for_model_profile_reference",
    "policy_for_profile",
    "resolve_model_policy",
]
