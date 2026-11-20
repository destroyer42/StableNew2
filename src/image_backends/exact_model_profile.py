"""Small dispatch seam for two independent immutable model contracts, not a new registry."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.image_backends.comfy_qwen_image_profile import (
    QwenImageProfile,
    QwenImageProfileError,
    qwen_image_profile_for_model,
    qwen_image_profile_for_reference,
    validate_qwen_image_config,
    validate_qwen_image_njr,
)
from src.image_backends.diffusers_ideogram4_profile import (
    IDEOGRAM4_PROFILE_V1,
    Ideogram4Profile,
    Ideogram4ProfileError,
    is_ideogram4_model_name,
    validate_ideogram4_config,
    validate_ideogram4_njr,
)
from src.image_backends.forge_flux1_profile import (
    FLUX1_PROFILE_ID,
    Flux1Profile,
    resolve_flux1_reference,
    validate_flux1_intent,
)
from src.image_backends.forge_klein_profile import (
    KleinProfile,
    validate_klein_intent,
)
from src.image_backends.forge_klein_profile import (
    model_profile_for_model as klein_reference,
)
from src.image_backends.forge_klein_profile import (
    resolve_model_profile as resolve_klein,
)
from src.image_backends.forge_zimage_profile import (
    ZIMAGE_PROFILE_V1,
    ZImageProfile,
    ZImageProfileError,
    is_zimage_transformer_name,
    validate_zimage_config,
    validate_zimage_njr,
)

#: Profiles that run on the WebUI-family Forge backend (the Forge code paths are typed against exactly these).
#: ``Flux1Profile`` is a family profile (structural transformer identity, PR-IMG-FLUX-130), not a whole-file one.
ForgeExactModelProfile = KleinProfile | ZImageProfile | Flux1Profile
#: Every exact profile, on any backend (PR-IMG-120 adds Ideogram 4 on Diffusers; PR-IMG-COMFY-100 adds the two
#: Qwen-Image 2.1 profiles on the Comfy still-image backend).
ExactModelProfile = ForgeExactModelProfile | Ideogram4Profile | QwenImageProfile


def model_profile_for_model(name: str | None) -> dict[str, Any] | None:
    if is_ideogram4_model_name(name):
        return IDEOGRAM4_PROFILE_V1.reference()
    qwen = qwen_image_profile_for_model(name)
    if qwen is not None:
        return qwen.reference()
    return ZIMAGE_PROFILE_V1.reference() if is_zimage_transformer_name(name) else klein_reference(name)


def resolve_model_profile(options: Any) -> ExactModelProfile | None:
    image = options.get("image") if isinstance(options, Mapping) else None
    reference = image.get("model_profile") if isinstance(image, Mapping) else None
    if isinstance(reference, Mapping) and reference.get("id") == ZIMAGE_PROFILE_V1.profile_id:
        if type(reference.get("version")) is not int or reference != ZIMAGE_PROFILE_V1.reference():
            raise ZImageProfileError("Unsupported Z-Image profile reference; only immutable v1 is supported")
        return ZIMAGE_PROFILE_V1
    if isinstance(reference, Mapping) and reference.get("id") == IDEOGRAM4_PROFILE_V1.profile_id:
        if type(reference.get("version")) is not int or reference != IDEOGRAM4_PROFILE_V1.reference():
            raise Ideogram4ProfileError("Unsupported Ideogram 4 profile reference; only immutable v1 is supported")
        return IDEOGRAM4_PROFILE_V1
    qwen = qwen_image_profile_for_reference(reference)
    if qwen is not None:
        return qwen
    if isinstance(reference, Mapping) and reference.get("id") == FLUX1_PROFILE_ID:
        return resolve_flux1_reference(reference)
    return resolve_klein(options)


def validate_profile_njr(njr: Any) -> None:
    """The pure exact-profile NJR admission check the NJR builders already apply (a no-op for every other model).

    Callers that freeze work outside those builders (Learning's Model Comparison arms) reuse it so a refusal surfaces
    before JobService admission. Klein's NJR validation needs live backend evidence and stays with the backend.
    """
    validate_zimage_njr(njr)
    validate_ideogram4_njr(njr)
    validate_qwen_image_njr(njr)


def profile_prompt_refusal(profile: ExactModelProfile | None, text: str) -> str | None:
    """The exact profile's own refusal of one *executable* positive prompt, or ``None``.

    Reuses the profile validator the compiler applies (never a second parser). Only Z-Image validates prompt text
    purely; Klein's inline-token decisions need LoRA evidence and stay with the compiler/backend.
    """
    if isinstance(profile, QwenImageProfile):
        return None  # plain natural-language text; nothing in it is profile-owned
    if isinstance(profile, Ideogram4Profile):
        try:
            validate_ideogram4_config({}, prompt=text)
        except Ideogram4ProfileError as exc:
            return str(exc)
        return None
    if not isinstance(profile, ZImageProfile):
        return None
    try:
        validate_zimage_config({}, prompt=text)
    except ZImageProfileError as exc:
        return str(exc)
    return None


def validate_profile_intent(profile: ExactModelProfile, **intent: Any) -> str:
    if isinstance(profile, KleinProfile):
        return validate_klein_intent(profile, **intent)
    if isinstance(profile, QwenImageProfile):
        if intent["backend_id"] != profile.backend_id or tuple(intent["stage_names"]) != profile.modes:
            raise QwenImageProfileError(
                f"{profile.display_name} supports only txt2img on the '{profile.backend_id}' backend"
            )
        if intent.get("unsupported_features"):
            raise QwenImageProfileError(
                f"{profile.display_name} unsupported features: " + "; ".join(intent["unsupported_features"])
            )
        validate_qwen_image_config(
            profile,
            {"model": intent["model_name"], "sampler_name": intent.get("sampler"),
             "scheduler": intent.get("scheduler"), "steps": intent.get("steps"),
             "cfg_scale": intent.get("cfg_scale"), "width": intent.get("width"), "height": intent.get("height")},
            negative=str(intent.get("negative_prompt") or ""),
        )  # fmt: skip
        return "txt2img"
    if isinstance(profile, Flux1Profile):
        return validate_flux1_intent(profile, **intent)
    if isinstance(profile, Ideogram4Profile):
        if intent["backend_id"] != profile.backend_id or tuple(intent["stage_names"]) != profile.modes:
            raise Ideogram4ProfileError(f"{profile.display_name} supports only txt2img on the '{profile.backend_id}' backend")
        if intent.get("unsupported_features"):
            raise Ideogram4ProfileError(
                f"{profile.display_name} unsupported features: " + "; ".join(intent["unsupported_features"])
            )
        validate_ideogram4_config({"model": intent["model_name"], "steps": intent["steps"], "width": intent["width"],
                                   "height": intent["height"]}, negative=str(intent.get("negative_prompt") or ""))
        return "txt2img"
    if intent["backend_id"] != profile.backend_id or tuple(intent["stage_names"]) != profile.modes:
        raise ZImageProfileError("Z-Image supports only Forge txt2img")
    if intent.get("unsupported_features"):
        raise ZImageProfileError("Z-Image unsupported features: " + "; ".join(intent["unsupported_features"]))
    validate_zimage_config({"model": intent["model_name"], "sampler_name": intent["sampler"],
                            "scheduler": intent["scheduler"], "steps": intent["steps"],
                            "cfg_scale": intent["cfg_scale"], "width": intent["width"], "height": intent["height"]},
                           negative=str(intent.get("negative_prompt") or ""))
    if any(intent[key] is None for key in ("sampler", "scheduler", "steps", "cfg_scale", "width", "height")) or not is_zimage_transformer_name(intent["model_name"]):
        raise ZImageProfileError("Z-Image immutable sampling and model values are required")
    return "txt2img"
