"""PR-IMG-MODELS-155: one immutable Z-Image bundle; pure intent and wire contracts.

One observed generation, not full hardware qualification. No experimental coordinator,
runtime ownership, profile registry, I/O or GPU work lives here.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from src.image_backends.forge_klein_profile import KleinAsset, KleinProfileError, _model_key


class ZImageProfileError(KleinProfileError):
    """Immutable Z-Image intent is outside its limited v1 envelope."""


@dataclass(frozen=True, slots=True)
class ZImageProfile:
    profile_id: str = "z_image_turbo_fp8_scaled"
    version: int = 1
    display_name: str = "Z-Image-Turbo FP8 (limited support)"
    backend_id: str = "forge_webui"
    forge_revision: str = "d70373ebcf1a96d210b78cd6f77196459e783e2a"
    transformer: KleinAsset = KleinAsset(
        "transformer", "zImageTurboQuantized_fp8ScaledE4m3fnKJ.safetensors", 6_158_115_074,
        "59610861d46ae8d5d1d371ab7b2532ce64c0835052b395551a8550fa0e3eb3cf",
        "Stable-diffusion", "", "",
    )
    text_encoder: KleinAsset = KleinAsset(
        "text_encoder", "qwen3_4b_2964436.safetensors", 8_044_982_048,
        "6c671498573ac2f7a5501502ccce8d2b08ea6ca2f661c458e708f36b36edfc5a",
        "text_encoder", "", "",
    )
    vae: KleinAsset = KleinAsset(
        "vae", "flux1AE_v10.safetensors", 335_304_388,
        "afc8e28272cd15db3919bacdb6918ce9c1ed22e96cb12c4d5ed0fba823529e38",
        "VAE", "", "",
    )
    sampler: str = "Euler"
    scheduler: str = "Beta"
    steps: int = 9
    cfg_scale: float = 1.0
    distilled_cfg_scale: float = 9.0
    geometries: tuple[tuple[int, int], ...] = ((1024, 1024),)
    modes: tuple[str, ...] = ("txt2img",)
    min_total_ram_bytes: int = 32_000_000_000
    max_loras: int = 0

    @property
    def modules(self) -> tuple[KleinAsset, KleinAsset]:
        return self.text_encoder, self.vae

    @property
    def assets(self) -> tuple[KleinAsset, ...]:
        return self.transformer, *self.modules

    def reference(self) -> dict[str, Any]:
        return {"id": self.profile_id, "version": self.version}


ZIMAGE_PROFILE_V1 = ZImageProfile()

# Pinned Forge defaults reconciled in PR-154B; observe, never change server options.
SAMPLING_OPTIONS = MappingProxyType({
    "beta_dist_alpha": 0.6, "beta_dist_beta": 0.6, "sigma_min": 0.0, "sigma_max": 0.0,
    "rho": 0.0, "s_churn": 0.0, "s_tmin": 0.0, "s_tmax": 0.0, "s_noise": 1.0,
    "skip_early_cond": 0.0, "s_min_uncond": 0.0, "s_min_uncond_all": False,
    "always_discard_next_to_last_sigma": False, "sgm_noise_multiplier": False,
    "eta_noise_seed_delta": 0, "randn_source": "CPU", "use_dynamic_shifting": False,
    "face_restoration": False, "tiling": False, "forge_unet_storage_dtype": "Automatic",
})


def is_zimage_transformer_name(name: str | None) -> bool:
    return bool(name) and _model_key(str(name)) == _model_key(ZIMAGE_PROFILE_V1.transformer.filename)


def _sections(config: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    stage = config.get("txt2img")
    return (config, stage) if isinstance(stage, Mapping) else (config,)


def zimage_selected(config: Mapping[str, Any]) -> bool:
    return any(is_zimage_transformer_name(str(section.get(key) or ""))
               for section in _sections(config)
               for key in ("model", "model_name", "base_model", "sd_model_checkpoint"))


def validate_zimage_config(config: Mapping[str, Any], *, prompt: str = "", negative: str = "") -> None:
    """Reject every represented conflict before projection/adaptation; missing values get v1 defaults."""
    p = ZIMAGE_PROFILE_V1
    problems: list[str] = []
    fixed = {
        "sampler": p.sampler, "sampler_name": p.sampler, "scheduler": p.scheduler,
        "steps": p.steps, "cfg_scale": p.cfg_scale, "width": 1024, "height": 1024,
        "shift": p.distilled_cfg_scale, "distilled_cfg_scale": p.distilled_cfg_scale,
        "batch_size": 1, "n_iter": 1, "images_per_prompt": 1, "loop_count": 1,
        "subseed_strength": 0, "clip_skip": 1,
        "apply_global_positive_txt2img": False, "apply_global_negative_txt2img": False,
    }
    for section in (*_sections(config), config.get("pipeline") or {}):
        if not isinstance(section, Mapping):
            continue
        for key, expected in fixed.items():
            value = section.get(key)
            if value is not None and value != expected:
                problems.append(f"{key} {value!r} conflicts with fixed {expected!r}")
        for key in ("model", "model_name", "base_model", "sd_model_checkpoint"):
            if section.get(key) and not is_zimage_transformer_name(str(section[key])):
                problems.append(f"conflicting checkpoint {section[key]}")
        if section.get("sd_model") and not is_zimage_transformer_name(str(section["sd_model"])):
            problems.append("conflicting effective checkpoint")
        for key in ("seed_resize_from_h", "seed_resize_from_w"):
            if section.get(key) not in (None, -1, 0):
                problems.append(f"{key} is unsupported")
        seed = section.get("seed")
        if seed is not None and (type(seed) is not int or not -1 <= seed <= 4_294_967_295):
            problems.append("seed must be an integer from -1 through 4294967295")
        for key in ("vae", "sd_vae", "vae_name"):
            value = str(section.get(key) or "").strip()
            if value.lower() not in {"", "none", "automatic", "no vae (model default)"} and _model_key(value) != _model_key(p.vae.filename):
                problems.append(f"conflicting VAE {value}")
        for key in ("negative_prompt", "global_positive_prompt", "global_negative_prompt"):
            if str(section.get(key) or "").strip():
                problems.append(f"{key} is unsupported")
        for key in ("additional_modules", "forge_additional_modules"):
            modules = section.get(key)
            if modules is not None and (not isinstance(modules, (list, tuple)) or
                    sorted(_model_key(str(x)) for x in modules) != sorted(_model_key(a.filename) for a in p.modules)):
                problems.append("conflicting additional modules")
        for key in ("enable_hr", "use_refiner", "refiner_enabled", "adetailer_enabled", "upscale_enabled",
                    "img2img_enabled", "restore_faces", "tiling", "styles", "alwayson_scripts",
                    "lora_strengths", "positive_embeddings", "negative_embeddings", "adaptive_refinement"):
            if section.get(key):
                problems.append(f"{key} is unsupported")
        if section.get("hypernetworks") or section.get("override_settings") or section.get("aesthetic_enabled"):
            problems.append("hypernetwork/override/aesthetic modifiers are unsupported")
        if section.get("stages") and tuple(section["stages"]) != ("txt2img",):
            problems.append("only the txt2img stage is supported")
        for key in ("prompt_optimizer", "hires_fix", "refiner", "adetailer", "upscale", "img2img",
                    "aesthetic", "style_lora", "animatediff", "video_workflow"):
            value = section.get(key)
            if isinstance(value, Mapping) and value.get("enabled"):
                problems.append(f"{key} is unsupported")
        for key, value in section.items():
            if "controlnet" in str(key).lower() and value:
                problems.append("ControlNet is unsupported")
        if str(section.get("hypernetwork") or "none").lower() not in {"", "none"}:
            problems.append("hypernetwork is unsupported")
    if negative.strip():
        problems.append("negative prompt is unsupported")
    text = prompt or str(config.get("prompt") or _sections(config)[-1].get("prompt") or "")
    if text and (not text.strip() or len(text) > 10_000 or re.search(r"<|>|\([^)]*:\s*[\d.]+\)|\[|\]|embedding:", text, re.I)):
        problems.append("use a natural-language positive prompt without weighted syntax or adapter/embedding tokens")
    if problems:
        raise ZImageProfileError(f"{p.display_name} cannot run this work: " + "; ".join(dict.fromkeys(problems)))


def apply_zimage_compile_policy(config: dict[str, Any]) -> dict[str, Any]:
    if not zimage_selected(config):
        return config
    validate_zimage_config(config)
    p = ZIMAGE_PROFILE_V1
    from src.image_backends.image_backend_types import (
        normalize_image_backend_options,
        resolve_image_backend_id,
    )

    options = normalize_image_backend_options(config.get("backend_options"), model_name=p.transformer.filename)
    from src.image_backends.exact_model_profile import resolve_model_profile

    if resolve_image_backend_id(options) != p.backend_id or resolve_model_profile(options) is not p:
        raise ZImageProfileError("Z-Image requires Forge and its exact v1 profile; no backend switch or profile upgrade")
    config["backend_options"] = options
    stage = config.setdefault("txt2img", {})
    defaults = {"model": p.transformer.filename, "sampler": p.sampler, "sampler_name": p.sampler,
                "scheduler": p.scheduler, "steps": p.steps, "cfg_scale": p.cfg_scale,
                "width": 1024, "height": 1024, "distilled_cfg_scale": p.distilled_cfg_scale,
                "negative_prompt": "", "prompt_optimizer": {"enabled": False}, "clip_skip": 1}
    for target in (config, stage):
        for key, value in defaults.items():
            if target.get(key) is None:
                target[key] = value
    config.setdefault("prompt_optimizer", {"enabled": False})
    config["global_prompt_policy_source"] = "frozen_njr"
    config.setdefault("global_positive_prompt", "")
    config.setdefault("global_negative_prompt", "")
    pipeline = dict(config.get("pipeline") or {})
    pipeline.update(apply_global_positive_txt2img=False, apply_global_negative_txt2img=False)
    config["pipeline"] = pipeline
    return config


def validate_zimage_njr(njr: Any, stage_names: list[str] | None = None) -> None:
    """Pure compiler/admission check; persisted/replayed work must already carry v1 values."""
    from src.image_backends.image_backend_types import resolve_image_backend_id

    p = ZIMAGE_PROFILE_V1
    options = njr.backend_options
    reference = (options.get("image") or {}).get("model_profile")
    if not is_zimage_transformer_name(njr.base_model) and not (isinstance(reference, Mapping) and reference.get("id") == p.profile_id):
        return
    stages = stage_names if stage_names is not None else [s.stage_type for s in njr.stage_chain if s.enabled]
    if reference != p.reference() or resolve_image_backend_id(options) != p.backend_id or stages != ["txt2img"]:
        raise ZImageProfileError("Z-Image requires its frozen v1 Forge txt2img profile")
    validate_zimage_config(njr.config, prompt=njr.positive_prompt, negative=njr.negative_prompt)
    from src.image_backends.exact_model_profile import validate_profile_intent

    validate_profile_intent(p, backend_id=resolve_image_backend_id(options), stage_names=stages,
                           model_name=njr.base_model, sampler=njr.sampler_name, scheduler=njr.scheduler,
                           steps=njr.steps, cfg_scale=njr.cfg_scale, width=njr.width, height=njr.height,
                           negative_prompt=njr.negative_prompt)
    validate_zimage_config({"model": njr.base_model, "sampler_name": njr.sampler_name, "scheduler": njr.scheduler,
                            "steps": njr.steps, "cfg_scale": njr.cfg_scale, "width": njr.width, "height": njr.height,
                            "seed": njr.seed, "images_per_prompt": njr.images_per_prompt})
    if not str(njr.positive_prompt or "").strip() or njr.input_image_paths or njr.lora_tags or njr.positive_embeddings or njr.negative_embeddings:
        raise ZImageProfileError("Z-Image requires a positive natural-language prompt and no input images/LoRA/embeddings")
    for stage in njr.stage_chain:
        if stage.enabled:
            validate_zimage_config(stage.extra or {})
            validate_zimage_config({k: getattr(stage, k, None) for k in
                                   ("model", "sampler_name", "scheduler", "steps", "cfg_scale")})


def project_zimage_wire_payload(config: Mapping[str, Any], payload: dict[str, Any], *, prompt: str) -> dict[str, Any]:
    """Profile-specific projection at the real executor boundary; ordinary payloads are untouched."""
    from src.image_backends.exact_model_profile import resolve_model_profile

    profile = resolve_model_profile(config.get("backend_options"))
    if not isinstance(profile, ZImageProfile):
        if is_zimage_transformer_name(str(payload.get("sd_model") or "")):
            raise ZImageProfileError("Z-Image cannot dispatch without its exact frozen profile")
        return payload
    validate_zimage_config(config, prompt=prompt)
    validate_zimage_config(payload, prompt=str(payload.get("prompt") or ""), negative=str(payload.get("negative_prompt") or ""))
    if payload.get("prompt") != prompt:
        raise ZImageProfileError("Z-Image prompt changed after admission")
    if "shift" in payload:
        raise ZImageProfileError("shift is not a Forge API field; distilled_cfg_scale is required")
    # Neutral executor defaults are omitted so pinned Forge uses the reconciled API defaults.
    keys = ("prompt", "negative_prompt", "seed", "steps", "sampler_name", "scheduler", "cfg_scale",
            "width", "height", "batch_size", "n_iter")
    result = {key: payload[key] for key in keys}
    result.update(distilled_cfg_scale=profile.distilled_cfg_scale, send_images=True, save_images=False)
    return result


def verify_zimage_dispatch_state(config: Mapping[str, Any], client: Any) -> dict[str, Any] | None:
    """Final readback immediately before the actual POST; no server-option normalization."""
    from src.image_backends.exact_model_profile import resolve_model_profile

    p = resolve_model_profile(config.get("backend_options"))
    if not isinstance(p, ZImageProfile):
        return None
    options = client.get_options()
    if not isinstance(options, Mapping):
        raise ZImageProfileError("Z-Image sampling options are unavailable")
    for key, expected in SAMPLING_OPTIONS.items():
        if key not in options or options[key] != expected:
            raise ZImageProfileError(f"Z-Image requires pinned sampling option {key}={expected!r}")
    if not is_zimage_transformer_name(str(options.get("sd_model_checkpoint") or "")):
        raise ZImageProfileError("Z-Image checkpoint selection drifted before dispatch")
    modules = options.get("forge_additional_modules")
    if not isinstance(modules, list) or sorted(_model_key(str(x)) for x in modules) != sorted(_model_key(a.filename) for a in p.modules):
        raise ZImageProfileError("Z-Image module selection is unconfirmed or drifted before dispatch")
    return {"checkpoint": p.transformer.filename, "modules": [a.filename for a in p.modules],
            "sampling_options": dict(SAMPLING_OPTIONS), "verified_before_dispatch": True}
