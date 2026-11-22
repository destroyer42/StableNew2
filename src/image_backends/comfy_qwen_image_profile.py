"""PR-IMG-COMFY-100: the immutable Qwen-Image 2.1 (Comfy) profiles; pure intent contracts.

Two exact variants ship side by side so the owner can compare them (decision 1, 2026-11-19): the base int8 model with
the official 25-step template and the Turbo int8 model with the official 8-step template. Both share the same encoder
and VAE, run ``txt2img`` only, make one image per job and run on the ``comfyui`` image backend. Every value here comes
from public model facts and the official templates; none was measured. This module does no I/O, GPU, model or runtime
work. Not a qualification: no physical run of this product code has been made.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from src.image_backends.forge_klein_profile import KleinProfileError, _model_key
from src.image_backends.image_backend_types import COMFY_IMAGE_BACKEND_ID

QWEN_IMAGE_FAMILY = "qwen_image"
QWEN_IMAGE_REPO_ID = "Comfy-Org/Qwen-Image-2.1"
QWEN_IMAGE_REVISION = "aacf31a6d48e707f352ecba714cee0680da3479b"
QWEN_IMAGE_LICENCE = "Qwen Research License (non-commercial: research or evaluation only)"


class QwenImageProfileError(KleinProfileError):
    """Qwen-Image intent is outside its v1 envelope."""


@dataclass(frozen=True, slots=True)
class ComfyModelAsset:
    """One exact model file in a configured Comfy model folder (never downloaded or moved by StableNew)."""

    role: str
    folder: str
    filename: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class QwenImageResources:
    """Fail-closed floors and the wait cap. Proposals from public facts; physical qualification must confirm them."""

    #: Free VRAM Comfy reports (``system_stats``) before the graph is queued.
    min_free_vram_bytes: int = 10 * 1024**3
    #: Free host RAM Comfy reports before the graph is queued (the weights are paged in from disk).
    min_free_ram_bytes: int = 12 * 1024**3
    #: Longest wait for the one prompt's history entry, including a cold model load.
    history_timeout_seconds: float = 900.0


_TEXT_ENCODER = ComfyModelAsset(
    "text_encoder",
    "text_encoders",
    "qwen3vl_8b_int8_convrot.safetensors",
    9_350_798_360,
    "8bfd0f6e12abf2d2d697ecc888e5e90b0d6741d6708f05799f53afa560452e8f",
)
_VAE = ComfyModelAsset(
    "vae",
    "vae",
    "qwen_image_2.1_vae_bf16.safetensors",
    675_509_688,
    "bb21f7473051e1ac368515dd3f2e15cd44d7a11748ee8823e1ddca3e4876b7c9",
)
#: Half of the official 4 MP aspect table: the templates' 1-megapixel class, every side a multiple of 16.
_GEOMETRIES: tuple[tuple[int, int], ...] = (
    (1024, 1024),
    (1200, 896),
    (896, 1200),
    (1264, 848),
    (848, 1264),
    (1376, 768),
    (768, 1376),
)


@dataclass(frozen=True, slots=True)
class QwenImageProfile:
    profile_id: str
    display_name: str
    #: The pinned diffusion asset, or the published example name for a structural profile.
    diffusion_model: ComfyModelAsset
    #: The frozen graph (``comfy_image_graphs``) this profile runs.
    graph_id: str
    graph_version: str
    steps: int
    sampler: str
    scheduler: str
    cfg_scale: float = 1.0
    version: int = 1
    family: str = QWEN_IMAGE_FAMILY
    backend_id: str = COMFY_IMAGE_BACKEND_ID
    repo_id: str = QWEN_IMAGE_REPO_ID
    revision: str = QWEN_IMAGE_REVISION
    licence: str = QWEN_IMAGE_LICENCE
    text_encoder: ComfyModelAsset = _TEXT_ENCODER
    vae: ComfyModelAsset = _VAE
    geometries: tuple[tuple[int, int], ...] = _GEOMETRIES
    max_images: int = 1
    modes: tuple[str, ...] = ("txt2img",)
    max_loras: int = 0
    resources: QwenImageResources = QwenImageResources()
    structural_transformer: bool = False

    @property
    def model_name(self) -> str:
        return self.diffusion_model.filename

    @property
    def assets(self) -> tuple[ComfyModelAsset, ...]:
        return (self.diffusion_model, self.text_encoder, self.vae)

    def reference(self) -> dict[str, Any]:
        return {"id": self.profile_id, "version": self.version}


QWEN_IMAGE_21_PROFILE_V1 = QwenImageProfile(
    profile_id="qwen_image_21_int8_comfy",
    display_name="Qwen-Image 2.1 int8 (Comfy)",
    diffusion_model=ComfyModelAsset(
        "diffusion_model",
        "diffusion_models",
        "qwen_image_2.1_int8_convrot.safetensors",
        7_256_783_064,
        "cb74113cb03faecd79611b01fd7fd642f0aa60d6f0b95086abee214d75eaa57d",
    ),
    graph_id="qwen_image_21_t2i",
    graph_version="1.0.0",
    steps=25,
    sampler="euler",
    scheduler="simple",
)
QWEN_IMAGE_21_TURBO_PROFILE_V1 = QwenImageProfile(
    profile_id="qwen_image_21_turbo_int8_comfy",
    display_name="Qwen-Image 2.1 Turbo int8 (Comfy)",
    diffusion_model=ComfyModelAsset(
        "diffusion_model",
        "diffusion_models",
        "qwen_image_2.1_turbo_int8_convrot.safetensors",
        7_256_787_829,
        "8144a0182964aa8403ad6dbc011db837304167d235161b9aabaa8532e967314c",
    ),
    graph_id="qwen_image_21_turbo_t2i",
    graph_version="1.0.0",
    steps=8,
    sampler="euler",
    scheduler="Turbo manual sigmas (8 steps)",
)
QWEN_IMAGE_PROFILES: tuple[QwenImageProfile, ...] = (
    QWEN_IMAGE_21_PROFILE_V1,
    QWEN_IMAGE_21_TURBO_PROFILE_V1,
)
QWEN_IMAGE_20B_FP8_PROFILE_V1 = QwenImageProfile(
    profile_id="qwen_image_20b_fp8",
    display_name="Qwen-Image 20B FP8 (Comfy)",
    diffusion_model=ComfyModelAsset(
        "diffusion_model",
        "diffusion_models",
        "qwen_image_fp8_e4m3fn.safetensors",
        0,
        "",
    ),
    graph_id="qwen_image_20b_fp8_t2i",
    graph_version="1.0.0",
    steps=20,
    sampler="euler",
    scheduler="simple",
    cfg_scale=4.0,
    repo_id="Comfy-Org/Qwen-Image",
    revision="25608066f9bf5cdc28020836ce9549587053f346",
    licence="Apache-2.0",
    text_encoder=ComfyModelAsset(
        "text_encoder",
        "text_encoders",
        "qwen_2.5_vl_7b_fp8_scaled.safetensors",
        9_384_670_680,
        "cb5636d852a0ea6a9075ab1bef496c0db7aef13c02350571e388aea959c5c0b4",
    ),
    vae=ComfyModelAsset(
        "vae",
        "vae",
        "qwen_image_vae.safetensors",
        253_806_246,
        "a70580f0213e67967ee9c95f05bb400e8fb08307e017a924bf3441223e023d1f",
    ),
    resources=QwenImageResources(min_free_vram_bytes=11 * 1024**3, min_free_ram_bytes=28 * 1024**3),
    structural_transformer=True,
)
_BY_ID = {
    profile.profile_id: profile for profile in (*QWEN_IMAGE_PROFILES, QWEN_IMAGE_20B_FP8_PROFILE_V1)
}

_structural_lookup: Callable[[str], bool] | None = None


def install_qwen_structure_lookup(
    lookup: Callable[[str], bool] | None,
) -> Callable[[str], bool] | None:
    global _structural_lookup
    previous, _structural_lookup = _structural_lookup, lookup
    return previous


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
_STAGE_AUTHORITATIVE = frozenset({"width", "height"})
_MAX_SEED = 2**32 - 1


def qwen_image_profile_for_model(
    name: str | None, *, structural: bool = True
) -> QwenImageProfile | None:
    """Resolve a pinned name first, then the installed application's structural evidence."""

    if not name:
        return None
    key = _model_key(str(name))
    exact = next((p for p in QWEN_IMAGE_PROFILES if _model_key(p.model_name) == key), None)
    if exact is not None:
        return exact
    if structural and _structural_lookup is not None and _structural_lookup(name):
        return QWEN_IMAGE_20B_FP8_PROFILE_V1
    return None


def qwen_transformer_loader_name(model_name: str) -> str:
    """Normalize a catalog selection while preserving its path relative to a loader root."""

    selection = model_name.rsplit(" [", 1)[0] if model_name.endswith("]") else model_name
    relative = PurePosixPath(selection.replace("\\", "/"))
    if not relative.name or relative.is_absolute() or ".." in relative.parts or ":" in selection:
        return ""
    return str(relative) if relative.suffix.lower() == ".safetensors" else f"{relative}.safetensors"


def qwen_model_matches(profile: QwenImageProfile, name: Any) -> bool:
    """Persisted structural work is checked against the actual loader file at dispatch."""

    if profile.structural_transformer:
        return bool(qwen_transformer_loader_name(str(name or "").strip()))
    return bool(name and _model_key(str(name)) == _model_key(profile.model_name))


def is_qwen_image_model_name(name: str | None) -> bool:
    return qwen_image_profile_for_model(name) is not None


def qwen_image_profile_for_reference(reference: Any) -> QwenImageProfile | None:
    """Resolve a persisted ``{"id", "version"}``; ``None`` if it is not a Qwen-Image id. An unknown version raises."""

    if not isinstance(reference, Mapping):
        return None
    profile = _BY_ID.get(str(reference.get("id") or ""))
    if profile is None:
        return None
    if type(reference.get("version")) is not int or dict(reference) != profile.reference():
        raise QwenImageProfileError(
            f"Unsupported {profile.display_name} profile reference; only immutable v1 is supported"
        )
    return profile


def frozen_qwen_image_profile(backend_options: Any) -> QwenImageProfile | None:
    image = backend_options.get("image") if isinstance(backend_options, Mapping) else None
    reference = image.get("model_profile") if isinstance(image, Mapping) else None
    return qwen_image_profile_for_reference(reference)


def _sections(config: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    stage = config.get("txt2img")
    return (config, stage) if isinstance(stage, Mapping) else (config,)


def qwen_image_selected(config: Mapping[str, Any]) -> QwenImageProfile | None:
    for section in _sections(config):
        for key in _MODEL_KEYS:
            profile = qwen_image_profile_for_model(str(section.get(key) or ""))
            if profile is not None:
                return profile
    return None


def validate_qwen_image_config(
    profile: QwenImageProfile,
    config: Mapping[str, Any],
    *,
    negative: str = "",
    model_name: str | None = None,
) -> None:
    """Reject every represented conflict with the profile's v1 envelope; missing values take v1 defaults."""

    p = profile
    problems: list[str] = []
    pipeline = config.get("pipeline")
    sizes = {side for geometry in p.geometries for side in geometry}
    selection_key = qwen_transformer_loader_name if p.structural_transformer else _model_key
    selected_key = selection_key(model_name) if model_name else None
    for section in (*_sections(config), pipeline if isinstance(pipeline, Mapping) else {}):
        for key in _MODEL_KEYS:
            requested = section.get(key)
            if requested and (
                not qwen_model_matches(p, requested)
                or (
                    selected_key is not None
                    and selection_key(str(requested)).casefold() != selected_key.casefold()
                )
            ):
                problems.append(f"conflicting model {requested}")
        for key in ("sampler", "sampler_name"):
            if section.get(key) not in (None, "", p.sampler):
                problems.append(f"{key} {section[key]!r} conflicts with the fixed {p.sampler!r}")
        if section.get("scheduler") not in (None, "", p.scheduler):
            problems.append(
                f"scheduler {section['scheduler']!r} conflicts with the fixed {p.scheduler!r}"
            )
        if section.get("cfg_scale") is not None and section["cfg_scale"] != p.cfg_scale:
            problems.append(
                f"cfg_scale {section['cfg_scale']!r} conflicts with the fixed {p.cfg_scale:g}"
            )
        steps = section.get("steps")
        if steps is not None and (type(steps) is not int or steps != p.steps):
            problems.append(f"steps {steps!r} conflicts with the fixed {p.steps}")
        width, height = section.get("width"), section.get("height")
        if width is not None and height is not None and (width, height) not in p.geometries:
            problems.append(f"size {width}x{height} is not one of the supported sizes")
        for key in ("width", "height"):
            value = section.get(key)
            if value is not None and (type(value) is not int or value not in sizes):
                problems.append(f"{key} {value!r} is not one of the supported sizes")
        for key in ("images_per_prompt", "batch_size", "n_iter"):
            value = section.get(key)
            if value is not None and value != 1:
                problems.append(f"{key} must be 1 (one image per job)")
        if section.get("subseed_strength") not in (None, 0, 0.0):
            problems.append("variation seeds are unsupported")
        seed = section.get("seed")
        if seed is not None and (type(seed) is not int or not -1 <= seed <= _MAX_SEED):
            problems.append(f"seed must be an integer from -1 through {_MAX_SEED}")
        for key in ("vae", "sd_vae", "vae_name"):
            if str(section.get(key) or "").strip().lower() not in _NO_VAE:
                problems.append(f"{key} is unsupported (the profile pins its own VAE)")
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
            "a negative prompt is unsupported (at cfg 1 the negative branch is not sampled)"
        )
    if problems:
        raise QwenImageProfileError(
            f"{p.display_name} cannot run this work: " + "; ".join(dict.fromkeys(problems))
        )


def _clear_unsupported(profile: QwenImageProfile, config: dict[str, Any]) -> None:
    """Clear values a generic/PromptPack baseline merely carries for another model (the Ideogram 4 precedent).

    Negative text, global prompt terms, the prompt optimizer, sampling labels, steps and VAE are owned by the profile.
    Geometry, counts, seeds, stages and optional features are never touched, so ``validate_qwen_image_config`` still
    refuses a genuine conflict.
    """

    sections = [config, *(s for s in (config.get("txt2img"),) if isinstance(s, dict))]
    for section in sections:
        for key in (*_FIXED_EMPTY, "vae", "sd_vae", "vae_name"):
            if key in section:
                section[key] = ""
        for key, value in (
            ("sampler", profile.sampler),
            ("sampler_name", profile.sampler),
            ("scheduler", profile.scheduler),
            ("cfg_scale", profile.cfg_scale),
            ("steps", profile.steps),
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
            if key.startswith(("apply_global_positive_", "apply_global_negative_")):
                pipeline[key] = False


def apply_qwen_image_compile_policy(config: dict[str, Any]) -> dict[str, Any]:
    """Freeze the selected v1 profile into a merged run configuration (in place); a no-op for every other model."""

    from src.image_backends.forge_flux1_profile import selected_model_name

    model_name = selected_model_name(config)
    frozen = frozen_qwen_image_profile(config.get("backend_options"))
    profile = qwen_image_selected(config)
    if profile is None and frozen is not None and frozen.structural_transformer and model_name:
        profile = frozen
    if profile is None:
        if frozen is not None:
            raise QwenImageProfileError(
                f"The frozen {frozen.display_name} profile requires its exact model selection"
            )
        return config
    if frozen is not None and frozen is not profile:
        raise QwenImageProfileError(
            f"{profile.display_name} conflicts with the frozen {frozen.display_name} profile of this work"
        )
    _clear_unsupported(profile, config)
    model_name = model_name if profile.structural_transformer else profile.model_name
    validate_qwen_image_config(profile, config, model_name=model_name)
    from src.image_backends.exact_model_profile import resolve_model_profile
    from src.image_backends.image_backend_types import (
        normalize_image_backend_options,
        resolve_image_backend_id,
    )

    options = normalize_image_backend_options(config.get("backend_options"), model_name=model_name)
    if (
        resolve_image_backend_id(options) != profile.backend_id
        or resolve_model_profile(options) is not profile
    ):
        raise QwenImageProfileError(
            f"{profile.display_name} runs only on the '{profile.backend_id}' image backend with its exact v1 "
            "profile; StableNew never switches or falls back between backends"
        )
    if profile.structural_transformer:
        from src.image_backends.comfy_image_readiness import check_installation

        readiness = check_installation(profile, model_name=model_name)
        if not readiness.ready:
            raise QwenImageProfileError(readiness.summary)
    config["backend_options"] = options
    stage = config.setdefault("txt2img", {})
    width, height = profile.geometries[0]
    defaults: dict[str, Any] = {
        "model": model_name,
        "sampler_name": profile.sampler,
        "scheduler": profile.scheduler,
        "steps": profile.steps,
        "cfg_scale": profile.cfg_scale,
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


def validate_qwen_image_njr(njr: Any, stage_names: list[str] | None = None) -> None:
    """Pure admission check of a persisted/replayed NJR (a no-op for every other model)."""

    from src.image_backends.image_backend_types import resolve_image_backend_id

    options = getattr(njr, "backend_options", None) or {}
    model_name = getattr(njr, "base_model", None)
    frozen = frozen_qwen_image_profile(options)
    selected = (
        frozen
        if frozen is not None
        and frozen.structural_transformer
        and qwen_model_matches(frozen, model_name)
        else qwen_image_profile_for_model(model_name)
    )
    profile = selected or frozen
    if profile is None:
        return
    if (
        selected is None
        or frozen is not selected
        or resolve_image_backend_id(options) != profile.backend_id
    ):
        raise QwenImageProfileError(
            f"{profile.display_name} requires its frozen v1 profile on the '{profile.backend_id}' backend"
        )
    stages = (
        list(stage_names)
        if stage_names is not None
        else [
            s.stage_type
            for s in getattr(njr, "stage_chain", None) or ()
            if getattr(s, "enabled", False)
        ]
    )
    if stages != ["txt2img"]:
        raise QwenImageProfileError(f"{profile.display_name} supports only txt2img")
    if (
        getattr(njr, "input_image_paths", None)
        or getattr(njr, "lora_tags", None)
        or getattr(njr, "positive_embeddings", None)
        or getattr(njr, "negative_embeddings", None)
    ):
        raise QwenImageProfileError(
            f"{profile.display_name} takes no input images, LoRAs or embeddings"
        )
    validate_qwen_image_config(
        profile,
        getattr(njr, "config", None) or {},
        negative=str(getattr(njr, "negative_prompt", "") or ""),
        model_name=model_name,
    )
    validate_qwen_image_config(
        profile,
        {
            "steps": getattr(njr, "steps", None),
            "width": getattr(njr, "width", None),
            "height": getattr(njr, "height", None),
            "seed": getattr(njr, "seed", None),
            "images_per_prompt": getattr(njr, "images_per_prompt", None),
        },
    )


@dataclass(frozen=True, slots=True)
class QwenImagePlan:
    """The resolved, executable values of one job (what the frozen graph receives)."""

    width: int
    height: int
    seed: int
    requested_seed: int | None


def resolve_qwen_image_plan(
    profile: QwenImageProfile,
    *,
    width: Any,
    height: Any,
    seed: Any,
    images: Any = 1,
    rng: random.Random | None = None,
) -> QwenImagePlan:
    """Resolve geometry and the seed; a missing/-1 seed is drawn once by StableNew and recorded."""

    default_w, default_h = profile.geometries[0]
    size = (width or default_w, height or default_h)
    if size not in profile.geometries:
        raise QwenImageProfileError(
            f"{profile.display_name} size {size[0]}x{size[1]} is not one of the supported sizes"
        )
    if images not in (None, 0, 1):
        raise QwenImageProfileError(f"{profile.display_name} generates one image per job")
    requested = seed if type(seed) is int else None
    if requested is not None and not -1 <= requested <= _MAX_SEED:
        raise QwenImageProfileError(f"seed must be an integer from -1 through {_MAX_SEED}")
    resolved = (
        requested
        if requested is not None and requested >= 0
        else (rng or random.SystemRandom()).randrange(2**32)
    )
    return QwenImagePlan(int(size[0]), int(size[1]), resolved, requested)


__all__ = [
    "COMFY_IMAGE_BACKEND_ID",
    "QWEN_IMAGE_21_PROFILE_V1",
    "QWEN_IMAGE_21_TURBO_PROFILE_V1",
    "QWEN_IMAGE_FAMILY",
    "QWEN_IMAGE_PROFILES",
    "ComfyModelAsset",
    "QwenImagePlan",
    "QwenImageProfile",
    "QwenImageProfileError",
    "QwenImageResources",
    "apply_qwen_image_compile_policy",
    "frozen_qwen_image_profile",
    "is_qwen_image_model_name",
    "qwen_image_profile_for_model",
    "qwen_image_profile_for_reference",
    "qwen_image_selected",
    "resolve_qwen_image_plan",
    "validate_qwen_image_config",
    "validate_qwen_image_njr",
]
