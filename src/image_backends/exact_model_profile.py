"""Small dispatch seam for two independent immutable model contracts, not a new registry."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

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
)

ExactModelProfile = KleinProfile | ZImageProfile


def model_profile_for_model(name: str | None) -> dict[str, Any] | None:
    return ZIMAGE_PROFILE_V1.reference() if is_zimage_transformer_name(name) else klein_reference(name)


def resolve_model_profile(options: Any) -> ExactModelProfile | None:
    image = options.get("image") if isinstance(options, Mapping) else None
    reference = image.get("model_profile") if isinstance(image, Mapping) else None
    if isinstance(reference, Mapping) and reference.get("id") == ZIMAGE_PROFILE_V1.profile_id:
        if type(reference.get("version")) is not int or reference != ZIMAGE_PROFILE_V1.reference():
            raise ZImageProfileError("Unsupported Z-Image profile reference; only immutable v1 is supported")
        return ZIMAGE_PROFILE_V1
    return resolve_klein(options)


def validate_profile_intent(profile: ExactModelProfile, **intent: Any) -> str:
    if isinstance(profile, KleinProfile):
        return validate_klein_intent(profile, **intent)
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
