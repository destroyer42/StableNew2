"""Compatibility probe design (MEC-901): "does this checkpoint run here, and what kind of model is it?".

A probe renders one fixed prompt with a common seed cohort under 2–4 candidate *recipes* (a sampler, scheduler,
steps, CFG and size bundle typical of one model lineage). The operator compares the images to see which recipe works
and what the model looks like. It is exploratory, txt2img only, with no LoRA, ADetailer, hires or upscale, and the
model's own VAE. Its ratings and verdicts stay experiment-local: no recommendation, Apply or profile publication.

This module is pure: recipe table, recipe selection and the frozen design document. The Learning study
coordination (Preview/NJR) lives in ``learning_controller_services/compatibility_probe.py``; admission reuses
``QualificationBatchService``.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

STUDY_TYPE = "compatibility_probe"
CONTRACT = "learning_compatibility_probe/1"
VARIABLE = "Compatibility Recipe"
RECIPE_FIELDS = ("sampler_name", "scheduler", "steps", "cfg_scale", "width", "height")
MAX_RECIPES = 4
MIN_RECIPES = 2
DEFAULT_IMAGES_PER_RECIPE = 2
MAX_IMAGES_PER_RECIPE = 4
DEFAULT_PROMPT = (
    "photo of a woman standing in a sunlit garden, detailed face, natural light, sharp focus"
)
DEFAULT_NEGATIVE = "lowres, blurry, deformed, watermark, text"
#: Minimum completed runs before "your usual settings" (MEC-905) is offered as a recipe.
HISTORY_MIN_RUNS = 3

ORIGIN_FAMILY = "family_default"
ORIGIN_HISTORY = "your_runs"
ORIGIN_CATALOG = "catalog"


@dataclass(frozen=True)
class ProbeRecipe:
    key: str
    label: str
    lineage: str
    settings: Mapping[str, Any]
    source: str
    note: str = ""
    origin: str = ORIGIN_FAMILY

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "lineage": self.lineage,
            "settings": dict(self.settings),
            "source": self.source,
            "note": self.note,
            "origin": self.origin,
        }


def _recipe(
    key: str, label: str, lineage: str, source: str, note: str, **settings: Any
) -> ProbeRecipe:
    return ProbeRecipe(key, label, lineage, settings, source, note)


#: Typical publisher recipes per lineage. Each is a starting point to *ask a question*, not a recommendation.
RECIPES: Mapping[str, ProbeRecipe] = {
    recipe.key: recipe
    for recipe in (
        _recipe(
            "sd15",
            "SD 1.5 standard (512², Euler a, 25 steps, CFG 7)",
            "sd1",
            "https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-v1-5",
            "SD 1.x models are trained at 512 px; larger sizes duplicate subjects.",
            sampler_name="Euler a",
            scheduler="Automatic",
            steps=25,
            cfg_scale=7.0,
            width=512,
            height=512,
        ),
        _recipe(
            "sd15_portrait",
            "SD 1.5 portrait (512×768, DPM++ 2M Karras, 25 steps, CFG 7)",
            "sd1",
            "https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-v1-5",
            "Common SD 1.5 fine-tune setting; tells a 512 base from a 768-trained fine-tune.",
            sampler_name="DPM++ 2M",
            scheduler="Karras",
            steps=25,
            cfg_scale=7.0,
            width=512,
            height=768,
        ),
        _recipe(
            "sd2",
            "SD 2.x (768², DPM++ 2M Karras, 25 steps, CFG 7)",
            "sd2",
            "https://huggingface.co/stabilityai/stable-diffusion-2-1",
            "SD 2.x 768 models need v-prediction support in the backend.",
            sampler_name="DPM++ 2M",
            scheduler="Karras",
            steps=25,
            cfg_scale=7.0,
            width=768,
            height=768,
        ),
        _recipe(
            "sdxl",
            "SDXL standard (1024², DPM++ 2M Karras, 30 steps, CFG 6)",
            "sdxl",
            "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0",
            "Also the starting point for Pony and Illustrious fine-tunes (SDXL architecture).",
            sampler_name="DPM++ 2M",
            scheduler="Karras",
            steps=30,
            cfg_scale=6.0,
            width=1024,
            height=1024,
        ),
        _recipe(
            "sdxl_lightning",
            "SDXL low-step (1024², Euler SGM Uniform, 8 steps, CFG 1)",
            "sdxl",
            "https://huggingface.co/ByteDance/SDXL-Lightning",
            "Lightning/Hyper/DMD-style distilled models; ordinary SDXL looks unfinished here.",
            sampler_name="Euler",
            scheduler="SGM Uniform",
            steps=8,
            cfg_scale=1.0,
            width=1024,
            height=1024,
        ),
        _recipe(
            "sdxl_turbo",
            "SDXL Turbo (512², Euler a SGM Uniform, 4 steps, CFG 1)",
            "sdxl",
            "https://huggingface.co/stabilityai/sdxl-turbo",
            "Publisher recipe is 1–4 steps without guidance (CFG 1 here); many steps or high CFG burn the image.",
            sampler_name="Euler a",
            scheduler="SGM Uniform",
            steps=4,
            cfg_scale=1.0,
            width=512,
            height=512,
        ),
        _recipe(
            "flux",
            "FLUX-style (1024², Euler Simple, 20 steps, CFG 1)",
            "flux",
            "https://huggingface.co/black-forest-labs/FLUX.1-dev",
            "Guidance-distilled; a single-file checkpoint may still need separate text encoders/VAE.",
            sampler_name="Euler",
            scheduler="Simple",
            steps=20,
            cfg_scale=1.0,
            width=1024,
            height=1024,
        ),
    )
}

_FAMILY_ORDER: Mapping[str, tuple[str, ...]] = {
    "sd1": ("sd15", "sd15_portrait", "sdxl"),
    "sd2": ("sd2", "sd15", "sdxl"),
    "sdxl": ("sdxl", "sdxl_lightning"),
    "flux": ("flux", "sdxl"),
    "unknown": ("sdxl", "sd15", "flux"),
}
_VARIANT_ORDER: Mapping[str, tuple[str, ...]] = {
    "turbo": ("sdxl_turbo", "sdxl_lightning", "sdxl"),
    "lightning": ("sdxl_lightning", "sdxl_turbo", "sdxl"),
}
#: Civitai ``baseModel`` labels (MEC-903) mapped to the recipe lineage to try first.
_BASE_MODEL_HINTS: tuple[tuple[str, str], ...] = (
    ("turbo", "sdxl_turbo"),
    ("lightning", "sdxl_lightning"),
    ("hyper", "sdxl_lightning"),
    ("pony", "sdxl"),
    ("illustrious", "sdxl"),
    ("noobai", "sdxl"),
    ("sdxl", "sdxl"),
    ("flux", "flux"),
    ("sd 2", "sd2"),
    ("sd 1", "sd15"),
)


def recipe_from_history(
    settings: Mapping[str, Sequence[tuple[str, int]]],
    resolution: Sequence[tuple[str, int]],
    completed: int,
) -> ProbeRecipe | None:
    """MEC-905: the settings most of the operator's completed runs used, as one explicit recipe."""
    if completed < HISTORY_MIN_RUNS:
        return None
    values: dict[str, Any] = {}
    for name in ("sampler_name", "scheduler", "steps", "cfg_scale"):
        top = settings.get(name) or ()
        if not top:
            return None
        values[name] = top[0][0]
    size = resolution[0][0] if resolution else ""
    match = re.fullmatch(r"(\d+)x(\d+)", size)
    if not match:
        return None
    try:
        values["steps"] = int(float(values["steps"]))
        values["cfg_scale"] = float(values["cfg_scale"])
    except (TypeError, ValueError):
        return None
    values["width"], values["height"] = int(match.group(1)), int(match.group(2))
    label = (
        f"Your usual settings ({values['width']}×{values['height']}, {values['sampler_name']} "
        f"{values['scheduler']}, {values['steps']} steps, CFG {values['cfg_scale']:g})"
    )
    return ProbeRecipe(
        "history",
        label,
        "observed",
        values,
        f"Most used by your {completed} completed queue runs of this checkpoint",
        "Shown so the probe can compare your habitual settings with the lineage defaults.",
        ORIGIN_HISTORY,
    )


def suggest_recipes(
    *,
    family: str,
    variant: str = "",
    base_model_hint: str = "",
    history: ProbeRecipe | None = None,
    limit: int = MAX_RECIPES,
) -> tuple[ProbeRecipe, ...]:
    """Ordered candidates: your usual settings, then the lineage the evidence points at, then alternatives."""
    keys: list[str] = []
    hint = base_model_hint.casefold()
    for token, key in _BASE_MODEL_HINTS:
        if token in hint:
            keys.append(key)
            break
    for token, order in _VARIANT_ORDER.items():
        if token in variant.casefold():
            keys.extend(order)
            break
    keys.extend(_FAMILY_ORDER.get(family, _FAMILY_ORDER["unknown"]))
    keys.extend(_FAMILY_ORDER["unknown"])
    chosen: list[ProbeRecipe] = [history] if history is not None else []
    for key in dict.fromkeys(keys):
        if len(chosen) >= limit:
            break
        chosen.append(RECIPES[key])
    return tuple(chosen[:limit])


def match_inventory(
    recipe: ProbeRecipe, samplers: Iterable[str], schedulers: Iterable[str]
) -> tuple[ProbeRecipe | None, str]:
    """Use the backend's own spelling of the sampler/scheduler; never substitute a different one."""
    settings = dict(recipe.settings)
    for name, available in (("sampler_name", list(samplers)), ("scheduler", list(schedulers))):
        wanted = str(settings[name])
        exact = next((item for item in available if item == wanted), None)
        folded = next((item for item in available if item.casefold() == wanted.casefold()), None)
        found = exact or folded
        if found is None:
            return (
                None,
                f"{recipe.label}: {name.replace('_', ' ')} '{wanted}' is not available in this backend.",
            )
        settings[name] = found
    return (
        ProbeRecipe(
            recipe.key,
            recipe.label,
            recipe.lineage,
            settings,
            recipe.source,
            recipe.note,
            recipe.origin,
        ),
        "",
    )


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


@dataclass(frozen=True)
class ProbeDesign:
    """Everything the operator chose; the experiment identity derives from it."""

    model: str
    sha256: str
    family: str
    recipes: tuple[ProbeRecipe, ...]
    prompt: str = DEFAULT_PROMPT
    negative: str = DEFAULT_NEGATIVE
    images_per_recipe: int = DEFAULT_IMAGES_PER_RECIPE
    notes: tuple[str, ...] = field(default_factory=tuple)

    def validate(self) -> None:
        if not re.fullmatch(r"[0-9a-f]{64}", self.sha256 or ""):
            raise ValueError("Verify the checkpoint (Verify Selected) before probing it.")
        if not MIN_RECIPES <= len(self.recipes) <= MAX_RECIPES:
            raise ValueError(f"Choose {MIN_RECIPES}–{MAX_RECIPES} recipes.")
        labels = [recipe.label for recipe in self.recipes]
        if len(set(labels)) != len(labels):
            raise ValueError("Recipes must be distinct.")
        settings = [tuple(sorted(recipe.settings.items())) for recipe in self.recipes]
        if len(set(settings)) != len(settings):
            raise ValueError("Two recipes have identical settings; keep one.")
        for recipe in self.recipes:
            missing = [name for name in RECIPE_FIELDS if name not in recipe.settings]
            if missing:
                raise ValueError(f"{recipe.label}: missing {', '.join(missing)}")
        if not self.prompt.strip() or len(self.prompt) > 4000 or len(self.negative) > 4000:
            raise ValueError("The probe needs a nonempty prompt (at most 4000 characters).")
        if not 1 <= int(self.images_per_recipe) <= MAX_IMAGES_PER_RECIPE:
            raise ValueError(f"Images per recipe must be 1–{MAX_IMAGES_PER_RECIPE}.")

    @property
    def total_images(self) -> int:
        return len(self.recipes) * int(self.images_per_recipe)

    def document(self) -> dict[str, Any]:
        recipes = [recipe.to_dict() for recipe in self.recipes]
        core = {
            "contract": CONTRACT,
            "model": self.model,
            "sha256": self.sha256,
            "family": self.family,
            "recipes": recipes,
            "prompt": self.prompt,
            "negative": self.negative,
            "images_per_recipe": int(self.images_per_recipe),
        }
        return {**core, "digest": digest(core)}

    @property
    def experiment_id(self) -> str:
        return f"probe-{self.sha256[:12]}-{self.document()['digest'][:16]}"


def frozen_recipe(spec: Mapping[str, Any], label: str) -> dict[str, Any]:
    for recipe in spec.get("recipes") or ():
        if recipe.get("label") == label:
            return copy.deepcopy(dict(recipe))
    raise ValueError("Variant is outside the frozen probe recipes.")


def verify_spec(spec: Mapping[str, Any]) -> None:
    core = {key: spec.get(key) for key in spec if key != "digest"}
    if spec.get("contract") != CONTRACT or digest(core) != spec.get("digest"):
        raise ValueError("Frozen compatibility probe design is corrupt.")


def probe_baseline(baseline: Mapping[str, Any], target: Any) -> dict[str, Any]:
    """The generation-only baseline a probe runs: target checkpoint, its own VAE, txt2img alone.

    Built from ``model_baseline`` (no prompts, paths, adapters or drafts), with global prompt additions and the prompt
    optimizer off so the images show exactly the probe prompt.
    """
    from src.learning import baseline_authoring as authoring
    from src.learning.evidence_autopilot import model_baseline
    from src.pipeline.global_prompt_policy import (
        GLOBAL_NEGATIVE_STAGE_FLAGS,
        GLOBAL_POSITIVE_STAGE_FLAG,
    )

    result = model_baseline(baseline, target)
    result["txt2img"]["vae"] = ""
    pipeline = result["pipeline"]
    for flag in (GLOBAL_POSITIVE_STAGE_FLAG, *GLOBAL_NEGATIVE_STAGE_FLAGS):
        pipeline[flag] = False
    result["global_positive_prompt"] = ""
    result["global_negative_prompt"] = ""
    result["prompt_optimizer"] = {"enabled": False}
    authoring.align_aliases(result, "txt2img")
    return authoring.finalize_for_stage(result, "txt2img")


def probe_payload(
    design: ProbeDesign, baseline: Mapping[str, Any], display_name: str
) -> dict[str, Any]:
    """The Learning session draft a probe is saved as before its Preview is built (same shape as a proposal)."""
    from src.gui.learning_state import LearningExperiment, LearningState
    from src.learning import baseline_authoring as authoring

    design.validate()
    document = design.document()
    labels = [recipe["label"] for recipe in document["recipes"]]
    state = LearningState()
    authored = authoring.new_authoring(authoring.ORIGIN_LEARNING, source="compatibility_probe")
    state.baseline_draft = {"config": copy.deepcopy(dict(baseline)), "authoring": authored}
    state.current_experiment = LearningExperiment(
        name=f"Compatibility probe: {display_name}",
        experiment_id=design.experiment_id,
        description=(
            "Does this checkpoint run here, and which lineage's settings suit it? "
            "Exploratory; classification is a separate decision after review."
        ),
        baseline_config=copy.deepcopy(dict(baseline)),
        baseline_authoring=authored,
        prompt_text=design.prompt,
        variable_under_test=VARIABLE,
        values=labels,
        images_per_value=int(design.images_per_recipe),
        metadata={
            "study_type": STUDY_TYPE,
            STUDY_TYPE: document,
            "prompt_source": "custom",
            "selected_prompt_negative_text": design.negative,
            "selected_items": labels,
        },
    )
    payload = state.to_dict()
    payload.update(workflow_state="designing", learning_enabled=True, resume_schema_version=1)
    return payload
