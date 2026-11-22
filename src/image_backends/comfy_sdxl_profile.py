"""PR-IMG-COMFY-381: admission and planning for SDXL txt2img on the ComfyUI still-image backend (pure; no I/O).

Qwen-Image runs under an immutable frozen profile. SDXL does not: it is an ordinary, operator-chosen checkpoint, so this
module is the SDXL counterpart of ``comfy_qwen_image_profile`` with a different contract:

* **admission**: the checkpoint must be a registry-classified SDXL checkpoint (``AssetRegistry`` family evidence, the
  single local family authority), the stage chain is exactly ``txt2img``, and every feature the Comfy leg cannot run
  (hires fix, refiner, ADetailer, img2img, upscale, ControlNet, hypernetworks, batches, variation seeds) is refused with
  guidance to switch the Image backend to Forge. Nothing falls back to Forge silently;
* **plan**: the typed values the frozen ``sdxl_t2i`` graph receives, after the Forge->Comfy vocabulary maps in
  ``comfy_sdxl_mapping`` (sampler, scheduler, ``<lora:>`` tags, embeddings).

Nothing here resolves files or touches a runtime: ``comfy_sdxl_assets`` resolves the checkpoint, LoRA and VAE files.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from src.image_backends.comfy_qwen_image_profile import QwenImageResources
from src.image_backends.comfy_sdxl_mapping import (
    ComfySdxlMappingError,
    LoraRequest,
    SamplingMap,
    map_sampling,
    translate_prompt,
)
from src.image_backends.forge_klein_profile import KleinProfileError
from src.image_backends.image_backend_types import COMFY_IMAGE_BACKEND_ID

SDXL_COMFY_GRAPH_ID = "sdxl_t2i"
SDXL_COMFY_GRAPH_VERSION = "1.0.0"
SWITCH_HINT = "switch the Image backend to Forge in Settings"
MAX_SEED = 2**32 - 1
MIN_SIDE, MAX_SIDE, SIDE_STEP = 64, 4096, 8
MAX_STEPS = 150
MAX_CLIP_SKIP = 12
MAX_LORAS = 8

#: Typed ``FamilyLookup`` (model name -> registry compatibility or ``None``); cheap and non-scanning.
FamilyLookup = Callable[[str], Any]


class SdxlComfyError(KleinProfileError):
    """SDXL work that the ComfyUI backend cannot run (the message says why and what to do)."""


@dataclass(frozen=True, slots=True)
class SdxlRunProfile:
    """The duck-typed ``profile`` the shared Comfy plumbing (floors, history wait, liveness) reads."""

    display_name: str = "SDXL (ComfyUI)"
    backend_id: str = COMFY_IMAGE_BACKEND_ID
    #: Proposals from public facts (an SDXL fp16 checkpoint is about 6.5 GB); physical qualification must confirm them.
    resources: QwenImageResources = QwenImageResources(
        min_free_vram_bytes=6 * 1024**3,
        min_free_ram_bytes=8 * 1024**3,
        history_timeout_seconds=900.0,
    )

    def reference(self) -> dict[str, str]:
        return {
            "id": "sdxl_comfy_txt2img",
            "graph": f"{SDXL_COMFY_GRAPH_ID}@{SDXL_COMFY_GRAPH_VERSION}",
        }


SDXL_RUN_PROFILE = SdxlRunProfile()

_MODEL_KEYS = ("model", "model_name", "base_model", "sd_model_checkpoint")
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
    "hypernetworks",
    "override_settings",
    "controlnet_units",
)
_UNSUPPORTED_SECTIONS = (
    "hires_fix",
    "refiner",
    "adetailer",
    "upscale",
    "img2img",
    "style_lora",
    "animatediff",
    "video_workflow",
)
_NO_VAE = {"", "none", "automatic", "no vae (model default)"}


def _sections(config: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    stage = config.get("txt2img")
    return (config, stage) if isinstance(stage, Mapping) else (config,)


def unsupported_features(config: Mapping[str, Any]) -> list[str]:
    """Every represented feature the ComfyUI SDXL leg cannot run (empty when the work is plain txt2img)."""

    problems: list[str] = []
    pipeline = config.get("pipeline")
    for section in (*_sections(config), pipeline if isinstance(pipeline, Mapping) else {}):
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
        for key in ("images_per_prompt", "batch_size", "n_iter"):
            value = section.get(key)
            if value is not None and value != 1:
                problems.append(f"{key} must be 1 (one image per job)")
        if section.get("subseed_strength") not in (None, 0, 0.0):
            problems.append("variation seeds are unsupported")
        stages = section.get("stages")
        if stages and tuple(stages) != ("txt2img",):
            problems.append("only the txt2img stage is supported")
    return list(dict.fromkeys(problems))


def validate_sdxl_comfy_config(config: Mapping[str, Any]) -> None:
    problems = unsupported_features(config)
    if problems:
        raise SdxlComfyError(
            "SDXL on the ComfyUI image backend cannot run this work: "
            + "; ".join(problems)
            + f". Hires fix, refiner, ADetailer, img2img, upscale and ControlNet need Forge: {SWITCH_HINT}."
        )


def require_sdxl_checkpoint(model_name: Any, family_lookup: FamilyLookup | None = None) -> None:
    """Admit only a registry-classified SDXL checkpoint; refuse every other model with a precise reason."""

    from src.image_backends.model_policy import (
        EVIDENCE_REGISTRY,
        FAMILY_SDXL,
        RegistryFamilyLookup,
        resolve_model_policy,
    )

    name = str(model_name or "").strip()
    if not name:
        raise SdxlComfyError("The ComfyUI image backend needs a selected SDXL checkpoint")
    policy = resolve_model_policy(name, family_lookup=family_lookup or RegistryFamilyLookup())
    if policy.family == FAMILY_SDXL and policy.evidence == EVIDENCE_REGISTRY:
        return
    if policy.family in ("unknown", "") or policy.evidence != EVIDENCE_REGISTRY:
        raise SdxlComfyError(
            f"'{name}' is not a registry-classified SDXL checkpoint, so the ComfyUI image backend will not run it "
            f"({policy.display_name}). Scan the model folders so StableNew can classify it, or {SWITCH_HINT}."
        )
    raise SdxlComfyError(
        f"'{name}' is a {policy.display_name} model. The ComfyUI image backend runs SDXL checkpoints and Qwen-Image; "
        f"{SWITCH_HINT}."
    )


def is_sdxl_comfy_selection(backend_options: Any, model_name: Any) -> bool:
    """True when this comfyui-backend work is an ordinary checkpoint (not a frozen Qwen-Image profile)."""

    from src.image_backends.comfy_qwen_image_profile import qwen_image_profile_for_model
    from src.image_backends.exact_model_profile import resolve_model_profile

    return (
        resolve_model_profile(backend_options) is None
        and qwen_image_profile_for_model(model_name) is None
    )


def validate_sdxl_comfy_njr(
    njr: Any, stage_names: list[str] | None = None, *, family_lookup: FamilyLookup | None = None
) -> None:
    """Pure admission of an NJR bound for the ComfyUI backend with an ordinary checkpoint (a no-op for every other NJR)."""

    from src.image_backends.image_backend_types import resolve_image_backend_id

    options = getattr(njr, "backend_options", None) or {}
    if resolve_image_backend_id(options) != COMFY_IMAGE_BACKEND_ID:
        return
    model = getattr(njr, "base_model", None)
    if not is_sdxl_comfy_selection(options, model):
        return  # a frozen Qwen-Image profile: its own validator owns the work
    require_sdxl_checkpoint(model, family_lookup)
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
        raise SdxlComfyError(
            "SDXL on the ComfyUI image backend supports only txt2img "
            f"(this work has: {', '.join(stages) or 'no stages'}); {SWITCH_HINT} for other stages."
        )
    if getattr(njr, "input_image_paths", None):
        raise SdxlComfyError(
            f"SDXL on the ComfyUI image backend takes no input images; {SWITCH_HINT}."
        )
    validate_sdxl_comfy_config(getattr(njr, "config", None) or {})
    if getattr(njr, "images_per_prompt", None) not in (None, 0, 1):
        raise SdxlComfyError("SDXL on the ComfyUI image backend generates one image per job")
    try:
        prompt = translate_prompt(str(getattr(njr, "positive_prompt", "") or ""))
        translate_prompt(str(getattr(njr, "negative_prompt", "") or ""), what="negative prompt")
        stage = (getattr(njr, "config", None) or {}).get("txt2img")
        stage = stage if isinstance(stage, Mapping) else {}
        map_sampling(
            stage.get("sampler_name") or getattr(njr, "sampler_name", None),
            stage.get("scheduler") or getattr(njr, "scheduler", None),
        )
    except ComfySdxlMappingError as exc:
        raise SdxlComfyError(
            f"SDXL on the ComfyUI image backend cannot run this work: {exc}"
        ) from exc
    if len(prompt.loras) > MAX_LORAS:
        raise SdxlComfyError(
            f"at most {MAX_LORAS} LoRAs are supported on the ComfyUI image backend"
        )


@dataclass(frozen=True, slots=True)
class SdxlComfyPlan:
    """The resolved, executable values of one job (what the frozen ``sdxl_t2i`` graph receives)."""

    checkpoint: str
    width: int
    height: int
    seed: int
    requested_seed: int | None
    steps: int
    cfg_scale: float
    clip_skip: int
    sampling: SamplingMap
    sampler_label: str
    scheduler_label: str
    positive: str
    negative: str
    loras: tuple[LoraRequest, ...]
    embeddings: tuple[str, ...]
    vae: str


def _first(*values: Any) -> Any:
    return next((value for value in values if value is not None and value != ""), None)


def resolve_sdxl_comfy_plan(
    *,
    model_name: Any,
    stage_config: Mapping[str, Any],
    execution_config: Mapping[str, Any],
    prompt: str,
    negative_prompt: str,
    sampler: Any,
    scheduler: Any,
    steps: Any,
    cfg_scale: Any,
    width: Any,
    height: Any,
    seed: Any,
    images: Any = 1,
    vae: Any = None,
    embedding_names: Iterable[str] = (),
    negative_embedding_names: Iterable[str] = (),
    family_lookup: FamilyLookup | None = None,
    rng: random.Random | None = None,
) -> SdxlComfyPlan:
    """Validate one stage request and resolve every value the graph needs; refuses rather than approximates."""

    require_sdxl_checkpoint(model_name, family_lookup)
    validate_sdxl_comfy_config({**dict(execution_config), "txt2img": dict(stage_config)})
    if images not in (None, 0, 1):
        raise SdxlComfyError("SDXL on the ComfyUI image backend generates one image per job")
    if not str(prompt or "").strip():
        raise SdxlComfyError("SDXL on the ComfyUI image backend needs a prompt")
    problems: list[str] = []

    def number(label: str, value: Any, kind: type, low: float, high: float) -> Any:
        if value is None or isinstance(value, bool) or not isinstance(value, int | float):
            problems.append(f"{label} is required")
            return kind(low)
        if (kind is int and not float(value).is_integer()) or not low <= value <= high:
            problems.append(f"{label} {value!r} is outside {low:g}..{high:g}")
        return kind(value)

    step_value = number("steps", _first(steps, stage_config.get("steps")), int, 1, MAX_STEPS)
    cfg_value = number(
        "cfg_scale", _first(cfg_scale, stage_config.get("cfg_scale")), float, 0.0, 100.0
    )
    skip_value = number(
        "clip_skip",
        _first(stage_config.get("clip_skip"), execution_config.get("clip_skip"), 1),
        int,
        1,
        MAX_CLIP_SKIP,
    )
    w = number("width", width, int, MIN_SIDE, MAX_SIDE)
    h = number("height", height, int, MIN_SIDE, MAX_SIDE)
    if w % SIDE_STEP or h % SIDE_STEP:
        problems.append(f"size {w}x{h} must be a multiple of {SIDE_STEP}")
    requested = seed if type(seed) is int else None
    if requested is not None and not -1 <= requested <= MAX_SEED:
        problems.append(f"seed must be an integer from -1 through {MAX_SEED}")
    if problems:
        raise SdxlComfyError(
            "SDXL on the ComfyUI image backend cannot run this work: " + "; ".join(problems)
        )
    try:
        sampling = map_sampling(
            _first(sampler, stage_config.get("sampler_name")),
            _first(scheduler, stage_config.get("scheduler")),
        )
        positive = translate_prompt(prompt, embedding_names=embedding_names)
        negative = translate_prompt(
            negative_prompt, embedding_names=negative_embedding_names, what="negative prompt"
        )
    except ComfySdxlMappingError as exc:
        raise SdxlComfyError(
            f"SDXL on the ComfyUI image backend cannot run this work: {exc}"
        ) from exc
    if negative.loras:
        raise SdxlComfyError(
            "LoRA tags belong in the positive prompt; the negative prompt carries one"
        )
    if len(positive.loras) > MAX_LORAS:
        raise SdxlComfyError(
            f"at most {MAX_LORAS} LoRAs are supported on the ComfyUI image backend"
        )
    vae_text = str(_first(vae, stage_config.get("vae"), execution_config.get("vae")) or "").strip()
    resolved_seed = (
        requested
        if requested is not None and requested >= 0
        else (rng or random.SystemRandom()).randrange(2**32)
    )
    return SdxlComfyPlan(
        checkpoint=str(model_name).strip(),
        width=w,
        height=h,
        seed=resolved_seed,
        requested_seed=requested,
        steps=step_value,
        cfg_scale=cfg_value,
        clip_skip=skip_value,
        sampling=sampling,
        sampler_label=str(_first(sampler, stage_config.get("sampler_name")) or ""),
        scheduler_label=str(_first(scheduler, stage_config.get("scheduler")) or ""),
        positive=positive.text,
        negative=negative.text,
        loras=positive.loras,
        embeddings=tuple(dict.fromkeys((*positive.embeddings, *negative.embeddings))),
        vae="" if vae_text.lower() in _NO_VAE else vae_text,
    )


__all__ = [
    "MAX_LORAS",
    "SDXL_COMFY_GRAPH_ID",
    "SDXL_COMFY_GRAPH_VERSION",
    "SDXL_RUN_PROFILE",
    "SWITCH_HINT",
    "FamilyLookup",
    "SdxlComfyError",
    "SdxlComfyPlan",
    "SdxlRunProfile",
    "is_sdxl_comfy_selection",
    "require_sdxl_checkpoint",
    "resolve_sdxl_comfy_plan",
    "unsupported_features",
    "validate_sdxl_comfy_config",
    "validate_sdxl_comfy_njr",
]
