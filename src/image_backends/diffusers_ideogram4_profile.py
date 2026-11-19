"""PR-IMG-120: the one immutable Ideogram 4 NF4 (Diffusers) profile; pure intent contracts.

The envelope is exactly what PR-IMG-110R measured on the RTX 4070 Ti 12 GB (PASS - CONSTRAINED): the official presets,
sides of at most 1024, txt2img only, under the explicit residency policy that ``diffusers_residency`` implements. This
module holds no runtime ownership, I/O, GPU or model work; the backend (``diffusers_backend``) and its contained child do
that. Not a qualification: no physical run of this product code has been made.
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.image_backends.forge_klein_profile import KleinProfileError, _model_key
from src.image_backends.ideogram4_caption import CaptionError, resolve_caption

DIFFUSERS_BACKEND_ID = "diffusers"


class Ideogram4ProfileError(KleinProfileError):
    """Ideogram 4 intent is outside its v1 envelope."""


@dataclass(frozen=True, slots=True)
class Ideogram4Preset:
    name: str
    steps: int
    #: Guidance in the OFFICIAL loop-index order (index 0 is the LAST sampling step).
    official_guidance: tuple[float, ...]
    mu: float
    std: float
    label: str

    def diffusers_guidance(self) -> tuple[float, ...]:
        """Diffusers' ``guidance_schedule`` is first-step-first: the official order reversed."""

        return tuple(reversed(self.official_guidance))


@dataclass(frozen=True, slots=True)
class Ideogram4Component:
    subfolder: str
    filename: str


@dataclass(frozen=True, slots=True)
class Ideogram4Residency:
    """Fail-closed floors and caps of the 110R residency policy (section 7.2 of the PR-IMG-120 record)."""

    #: Driver-visible free VRAM required before launch (parent, ``nvidia-smi``).
    min_free_vram_mib: int = 10_700
    #: Torch caching-allocator ceiling applied in the child (110R cap).
    allocator_cap_mib: int = 11_200
    #: Below this applied cap the child refuses (110R Diffusers swap peak reserved, 10.2 GiB).
    min_allocator_cap_mib: int = 10_445
    #: Margin kept free under the driver-visible free memory when the cap is computed in the child.
    cap_margin_mib: int = 256
    #: Host RAM required before launch (parent, ``psutil``).
    min_available_host_ram_bytes: int = 16 * 1024**3
    #: Commit ceiling of the child's whole process tree (job object).
    child_memory_limit_mb: int = 36_864
    #: Wall-clock timeout: base + images x steps x per-step budget.
    timeout_base_seconds: float = 300.0
    timeout_per_step_seconds: float = 20.0
    #: Text tokens above this are refused (Diffusers' default ``max_sequence_length``).
    max_text_tokens: int = 2048

    def timeout_seconds(self, steps: int, images: int) -> float:
        return (
            self.timeout_base_seconds
            + max(1, images) * max(1, steps) * self.timeout_per_step_seconds
        )


_PRESETS = (
    Ideogram4Preset("V4_TURBO_12", 12, (3.0,) * 1 + (7.0,) * 11, 0.5, 1.75, "Turbo (12 steps)"),
    Ideogram4Preset("V4_DEFAULT_20", 20, (3.0,) * 2 + (7.0,) * 18, 0.0, 1.75, "Default (20 steps)"),
    Ideogram4Preset("V4_QUALITY_48", 48, (3.0,) * 3 + (7.0,) * 45, 0.0, 1.5, "Quality (48 steps)"),
)


@dataclass(frozen=True, slots=True)
class Ideogram4Profile:
    profile_id: str = "ideogram4_nf4_diffusers"
    version: int = 1
    display_name: str = "Ideogram 4 NF4 (Diffusers)"
    family: str = "ideogram4"
    backend_id: str = DIFFUSERS_BACKEND_ID
    #: The one model identity StableNew offers and persists (whole-name match only).
    model_name: str = "ideogram-4-nf4-diffusers@1874bc70"
    repo_id: str = "ideogram-ai/ideogram-4-nf4-diffusers"
    revision: str = "1874bc70267ba2c823a7239e1d70dd308c8d64dc"
    components: tuple[Ideogram4Component, ...] = (
        Ideogram4Component("", "model_index.json"),
        Ideogram4Component("scheduler", "scheduler_config.json"),
        Ideogram4Component("tokenizer", "tokenizer.json"),
        Ideogram4Component("tokenizer", "tokenizer_config.json"),
        Ideogram4Component("tokenizer", "chat_template.jinja"),
        Ideogram4Component("text_encoder", "config.json"),
        Ideogram4Component("text_encoder", "model.safetensors"),
        Ideogram4Component("transformer", "config.json"),
        Ideogram4Component("transformer", "diffusion_pytorch_model.safetensors"),
        Ideogram4Component("unconditional_transformer", "config.json"),
        Ideogram4Component("unconditional_transformer", "diffusion_pytorch_model.safetensors"),
        Ideogram4Component("vae", "config.json"),
        Ideogram4Component("vae", "diffusion_pytorch_model.safetensors"),
    )
    presets: tuple[Ideogram4Preset, ...] = _PRESETS
    default_steps: int = 20
    geometries: tuple[tuple[int, int], ...] = (
        (1024, 1024),
        (768, 1024),
        (1024, 768),
        (768, 768),
        (512, 512),
    )
    max_images: int = 4
    modes: tuple[str, ...] = ("txt2img",)
    #: Fixed, display-only values: the official flow-matching sampler and logit-normal schedule are not selectable.
    sampler: str = "Ideogram 4 flow (Euler)"
    scheduler: str = "Ideogram 4 logit-normal"
    cfg_scale: float = 7.0
    max_loras: int = 0
    residency: Ideogram4Residency = Ideogram4Residency()
    #: Python packages the contained child imports (checked by spec only, never imported in the parent).
    runtime_packages: tuple[str, ...] = (
        "torch",
        "diffusers",
        "transformers",
        "accelerate",
        "bitsandbytes",
    )

    def reference(self) -> dict[str, Any]:
        return {"id": self.profile_id, "version": self.version}

    @property
    def allowed_steps(self) -> tuple[int, ...]:
        return tuple(preset.steps for preset in self.presets)

    def preset_for_steps(self, steps: Any) -> Ideogram4Preset:
        for preset in self.presets:
            if type(steps) is int and steps == preset.steps:
                return preset
        raise Ideogram4ProfileError(
            f"{self.display_name} steps must be one of {list(self.allowed_steps)} "
            "(12 Turbo, 20 Default, 48 Quality); got " + repr(steps)
        )


IDEOGRAM4_PROFILE_V1 = Ideogram4Profile()

_MODEL_KEYS = ("model", "model_name", "base_model", "sd_model_checkpoint")
_FIXED_EMPTY = ("negative_prompt", "global_positive_prompt", "global_negative_prompt")
_UNSUPPORTED_FLAGS = (
    "enable_hr",
    "use_refiner",
    "refiner_enabled",
    "adetailer_enabled",
    "upscale_enabled",
    "img2img_enabled",
    "restore_faces",
    "tiling",
    "styles",
    "alwayson_scripts",
    "lora_strengths",
    "positive_embeddings",
    "negative_embeddings",
    "adaptive_refinement",
    "hypernetworks",
    "override_settings",
    "aesthetic_enabled",
    "apply_global_positive_txt2img",
    "apply_global_negative_txt2img",
)
_UNSUPPORTED_SECTIONS = (
    "prompt_optimizer",
    "hires_fix",
    "refiner",
    "adetailer",
    "upscale",
    "img2img",
    "aesthetic",
    "style_lora",
    "animatediff",
    "video_workflow",
)
_NO_VAE = {"", "none", "automatic", "no vae (model default)"}
#: Values whose txt2img-stage setting overrides a differing flat mirror when the profile is frozen.
_STAGE_AUTHORITATIVE = frozenset({"steps", "width", "height"})


def is_ideogram4_model_name(name: str | None) -> bool:
    return bool(name) and _model_key(str(name)) == _model_key(IDEOGRAM4_PROFILE_V1.model_name)


def _sections(config: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    stage = config.get("txt2img")
    return (config, stage) if isinstance(stage, Mapping) else (config,)


def ideogram4_selected(config: Mapping[str, Any]) -> bool:
    return any(
        is_ideogram4_model_name(str(section.get(key) or ""))
        for section in _sections(config)
        for key in _MODEL_KEYS
    )


def frozen_profile_is_ideogram4(backend_options: Any) -> bool:
    image = backend_options.get("image") if isinstance(backend_options, Mapping) else None
    reference = image.get("model_profile") if isinstance(image, Mapping) else None
    return isinstance(reference, Mapping) and reference.get("id") == IDEOGRAM4_PROFILE_V1.profile_id


def validate_ideogram4_config(
    config: Mapping[str, Any], *, prompt: str = "", negative: str = ""
) -> None:
    """Reject every represented conflict with the v1 envelope; missing values take v1 defaults."""

    p = IDEOGRAM4_PROFILE_V1
    problems: list[str] = []
    pipeline = config.get("pipeline")
    for section in (*_sections(config), pipeline if isinstance(pipeline, Mapping) else {}):
        for key in _MODEL_KEYS:
            if section.get(key) and not is_ideogram4_model_name(str(section[key])):
                problems.append(f"conflicting model {section[key]}")
        for key in ("sampler", "sampler_name"):
            if section.get(key) not in (None, "", p.sampler):
                problems.append(f"{key} {section[key]!r} conflicts with the fixed {p.sampler!r}")
        if section.get("scheduler") not in (None, "", p.scheduler):
            problems.append(
                f"scheduler {section['scheduler']!r} conflicts with the fixed {p.scheduler!r}"
            )
        if section.get("cfg_scale") is not None and section["cfg_scale"] != p.cfg_scale:
            problems.append(
                f"cfg_scale {section['cfg_scale']!r} conflicts with the preset guidance ({p.cfg_scale:g})"
            )
        steps = section.get("steps")
        if steps is not None and (type(steps) is not int or steps not in p.allowed_steps):
            problems.append(f"steps {steps!r} must be one of {list(p.allowed_steps)}")
        width, height = section.get("width"), section.get("height")
        if width is not None and height is not None and (width, height) not in p.geometries:
            problems.append(f"size {width}x{height} is outside the tested sizes")
        for key in ("width", "height"):
            value = section.get(key)
            if value is not None and (
                type(value) is not int or value not in {w for g in p.geometries for w in g}
            ):
                problems.append(f"{key} {value!r} is outside the tested sizes")
        for key in ("images_per_prompt", "batch_size"):
            value = section.get(key)
            if value is not None and (type(value) is not int or not 1 <= value <= p.max_images):
                problems.append(f"{key} must be 1-{p.max_images}")
        if section.get("n_iter") not in (None, 1):
            problems.append("n_iter must be 1 (use images per prompt, up to 4)")
        if section.get("subseed_strength") not in (None, 0, 0.0):
            problems.append("variation seeds are unsupported")
        seed = section.get("seed")
        if seed is not None and (type(seed) is not int or not -1 <= seed <= 4_294_967_295):
            problems.append("seed must be an integer from -1 through 4294967295")
        for key in ("vae", "sd_vae", "vae_name"):
            if str(section.get(key) or "").strip().lower() not in _NO_VAE:
                problems.append(f"{key} is unsupported (the model loads its own VAE)")
        for key in _FIXED_EMPTY:
            if str(section.get(key) or "").strip():
                problems.append(f"{key} is unsupported")
        for key in _UNSUPPORTED_FLAGS:
            if section.get(key):
                problems.append(f"{key} is unsupported")
        for key in _UNSUPPORTED_SECTIONS:
            value = section.get(key)
            if isinstance(value, Mapping) and value.get("enabled"):
                problems.append(f"{key} is unsupported")
        for key, value in section.items():
            if "controlnet" in str(key).lower() and value:
                problems.append("ControlNet is unsupported")
        if str(section.get("hypernetwork") or "none").strip().lower() not in {"", "none"}:
            problems.append("hypernetwork is unsupported")
        stages = section.get("stages")
        if stages and tuple(stages) != ("txt2img",):
            problems.append("only the txt2img stage is supported")
    if str(negative or "").strip():
        problems.append(
            "a negative prompt is unsupported (the model's unconditional branch takes no text)"
        )
    if prompt:
        try:
            resolve_caption(prompt)
        except CaptionError as exc:
            problems.append(str(exc))
    if problems:
        raise Ideogram4ProfileError(
            f"{p.display_name} cannot run this work: " + "; ".join(dict.fromkeys(problems))
        )


def _clear_unsupported(config: dict[str, Any]) -> None:
    """Clear values a generic/PromptPack baseline merely carries for another model (the Klein/Z-Image precedent).

    Negative text, global prompt terms, the prompt optimizer, sampling labels and VAE are owned by the profile; clearing
    them is recorded by the shared prompt adaptation. Geometry, counts, seeds, stages and optional features are never
    touched here, so ``validate_ideogram4_config`` still refuses a genuine conflict.
    """

    p = IDEOGRAM4_PROFILE_V1
    sections = [config, *(s for s in (config.get("txt2img"),) if isinstance(s, dict))]
    for section in sections:
        for key in _FIXED_EMPTY:
            if key in section:
                section[key] = ""
        for key in ("vae", "sd_vae", "vae_name"):
            if key in section:
                section[key] = ""
        for key, value in (
            ("sampler", p.sampler),
            ("sampler_name", p.sampler),
            ("scheduler", p.scheduler),
            ("cfg_scale", p.cfg_scale),
        ):
            if key in section:
                section[key] = value
        for key in ("apply_global_positive_txt2img", "apply_global_negative_txt2img"):
            if key in section:
                section[key] = False
        optimizer = section.get("prompt_optimizer")
        if isinstance(optimizer, dict):
            section["prompt_optimizer"] = {**optimizer, "enabled": False}
    pipeline = config.get("pipeline")
    if isinstance(pipeline, dict):
        for key in list(pipeline):
            if key.startswith("apply_global_positive_") or key.startswith("apply_global_negative_"):
                pipeline[key] = False


def apply_ideogram4_compile_policy(config: dict[str, Any]) -> dict[str, Any]:
    """Freeze the v1 profile into a merged run configuration (in place); a no-op unless Ideogram 4 is selected."""

    if not ideogram4_selected(config):
        if frozen_profile_is_ideogram4(config.get("backend_options")):
            raise Ideogram4ProfileError(
                "The frozen Ideogram 4 profile requires its exact model selection"
            )
        return config
    p = IDEOGRAM4_PROFILE_V1
    _clear_unsupported(config)
    validate_ideogram4_config(config)
    from src.image_backends.exact_model_profile import resolve_model_profile
    from src.image_backends.image_backend_types import (
        normalize_image_backend_options,
        resolve_image_backend_id,
    )

    options = normalize_image_backend_options(
        config.get("backend_options"), model_name=p.model_name
    )
    if resolve_image_backend_id(options) != p.backend_id or resolve_model_profile(options) is not p:
        raise Ideogram4ProfileError(
            f"{p.display_name} runs only on the '{p.backend_id}' image backend with its exact v1 profile; "
            "StableNew never switches or falls back between backends"
        )
    config["backend_options"] = options
    stage = config.setdefault("txt2img", {})
    width, height = p.geometries[0]
    defaults: dict[str, Any] = {
        "model": p.model_name,
        "sampler_name": p.sampler,
        "scheduler": p.scheduler,
        "steps": p.default_steps,
        "cfg_scale": p.cfg_scale,
        "width": width,
        "height": height,
        "negative_prompt": "",
        "vae": "",
        "prompt_optimizer": {"enabled": False},
    }
    for key, default in defaults.items():
        # The txt2img stage value is the one the runner dispatches; the flat mirror follows it.
        value = next((t[key] for t in (stage, config) if t.get(key) is not None), default)
        for target in (stage, config):
            if target.get(key) is None or (target is config and key in _STAGE_AUTHORITATIVE):
                target[key] = dict(value) if isinstance(value, dict) else value
    config["global_prompt_policy_source"] = "frozen_njr"
    config["global_positive_prompt"] = ""
    config["global_negative_prompt"] = ""
    pipeline = dict(config.get("pipeline") or {})
    pipeline.update(apply_global_positive_txt2img=False, apply_global_negative_txt2img=False)
    config["pipeline"] = pipeline
    return config


def validate_ideogram4_njr(njr: Any, stage_names: list[str] | None = None) -> None:
    """Pure admission check of a persisted/replayed NJR (a no-op for every other model)."""

    from src.image_backends.image_backend_types import resolve_image_backend_id

    p = IDEOGRAM4_PROFILE_V1
    options = getattr(njr, "backend_options", None) or {}
    selected = is_ideogram4_model_name(getattr(njr, "base_model", None))
    if not selected and not frozen_profile_is_ideogram4(options):
        return
    image = options.get("image") if isinstance(options, Mapping) else None
    reference = image.get("model_profile") if isinstance(image, Mapping) else None
    stages = (
        list(stage_names)
        if stage_names is not None
        else [
            s.stage_type
            for s in getattr(njr, "stage_chain", None) or ()
            if getattr(s, "enabled", False)
        ]
    )
    if (
        not selected
        or reference != p.reference()
        or resolve_image_backend_id(options) != p.backend_id
    ):
        raise Ideogram4ProfileError(
            f"{p.display_name} requires its frozen v1 profile on the '{p.backend_id}' backend"
        )
    if stages != ["txt2img"]:
        raise Ideogram4ProfileError(f"{p.display_name} supports only txt2img")
    if (
        getattr(njr, "input_image_paths", None)
        or getattr(njr, "lora_tags", None)
        or getattr(njr, "positive_embeddings", None)
        or getattr(njr, "negative_embeddings", None)
    ):
        raise Ideogram4ProfileError(f"{p.display_name} takes no input images, LoRAs or embeddings")
    validate_ideogram4_config(
        getattr(njr, "config", None) or {},
        prompt=str(getattr(njr, "positive_prompt", "") or ""),
        negative=str(getattr(njr, "negative_prompt", "") or ""),
    )
    validate_ideogram4_config(
        {
            "steps": getattr(njr, "steps", None),
            "width": getattr(njr, "width", None),
            "height": getattr(njr, "height", None),
            "seed": getattr(njr, "seed", None),
            "images_per_prompt": getattr(njr, "images_per_prompt", None),
        }
    )


@dataclass(frozen=True, slots=True)
class Ideogram4Plan:
    """The resolved, executable values of one job (what the child receives)."""

    preset: Ideogram4Preset
    width: int
    height: int
    seeds: tuple[int, ...]
    requested_seed: int | None


def resolve_plan(
    *, steps: Any, width: Any, height: Any, seed: Any, images: Any, rng: random.Random | None = None
) -> Ideogram4Plan:
    """Resolve preset, geometry and per-image seeds; a missing/-1 seed is drawn once and recorded."""

    p = IDEOGRAM4_PROFILE_V1
    steps = p.default_steps if steps in (None, 0) else steps
    preset = p.preset_for_steps(steps)
    default_w, default_h = p.geometries[0]
    size = (width or default_w, height or default_h)
    if size not in p.geometries:
        raise Ideogram4ProfileError(
            f"{p.display_name} size {size[0]}x{size[1]} is outside the tested sizes"
        )
    count = images if images not in (None, 0) else 1
    if type(count) is not int or not 1 <= count <= p.max_images:
        raise Ideogram4ProfileError(f"{p.display_name} generates 1-{p.max_images} images per job")
    requested = seed if type(seed) is int else None
    if requested is not None and not -1 <= requested <= 4_294_967_295:
        raise Ideogram4ProfileError("seed must be an integer from -1 through 4294967295")
    base = (
        requested
        if requested is not None and requested >= 0
        else (rng or random.SystemRandom()).randrange(2**32)
    )
    seeds = tuple((base + index) % 2**32 for index in range(count))
    return Ideogram4Plan(preset, int(size[0]), int(size[1]), seeds, requested)


__all__ = [
    "DIFFUSERS_BACKEND_ID",
    "IDEOGRAM4_PROFILE_V1",
    "Ideogram4Plan",
    "Ideogram4Preset",
    "Ideogram4Profile",
    "Ideogram4ProfileError",
    "Ideogram4Residency",
    "apply_ideogram4_compile_policy",
    "frozen_profile_is_ideogram4",
    "ideogram4_selected",
    "is_ideogram4_model_name",
    "resolve_plan",
    "validate_ideogram4_config",
    "validate_ideogram4_njr",
]
