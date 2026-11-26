"""N5 owner decision 3: in a packs x models batch, a model with a saved recipe uses its own settings.

A *recipe* is the generation profile the model picker applies when that model is chosen
(``GenerationProfileService.plan_for_model``: the model's favorite, else its first Research profile). For each model in
the batch, the recipe's changes (sampler, scheduler, steps, CFG, size, VAE) are applied to the Pipeline tab's working
settings exactly as choosing the model in the picker would apply them, and the cell then compiles as Add to Job does.
So a PromptPack's own saved settings still win where they would for a single model.

A model without a recipe uses the Pipeline tab's settings unchanged. The owner can turn recipes off for the whole batch
(``BatchRequest.use_recipes``) to use the Pipeline tab's settings for every model.
"""

from __future__ import annotations

import logging
from collections.abc import Collection, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field, replace
from typing import Any

log = logging.getLogger(__name__)

#: Profile setting name -> ``Txt2ImgOverrides`` field (the pack-settings override bundle).
_OVERRIDE_FIELD = {
    "sampler_name": "sampler",
    "scheduler": "scheduler",
    "steps": "steps",
    "cfg_scale": "cfg_scale",
    "width": "width",
    "height": "height",
    "vae": "vae",
}
#: Profile setting name -> the NJR field that shows whether it reached the job.
_RECORD_FIELD = {
    "sampler_name": "sampler_name",
    "scheduler": "scheduler",
    "steps": "steps",
    "cfg_scale": "cfg_scale",
}
_LABELS = {
    "sampler_name": "sampler",
    "scheduler": "scheduler",
    "steps": "steps",
    "cfg_scale": "CFG",
    "width": "width",
    "height": "height",
    "vae": "VAE",
}
_KIND_LABELS = {"research": "Research", "learning": "Learning", "custom": "Custom"}


@dataclass(frozen=True)
class ModelRecipe:
    """The recipe one batch model uses, or why it uses the Pipeline tab's settings."""

    model: str
    #: ``{"kind", "profile_id", "revision"}`` of the profile used; ``None`` when no recipe applies.
    ref: Mapping[str, Any] | None = None
    label: str = ""
    #: Profile setting name -> value written over the Pipeline tab's working settings for this model.
    changes: Mapping[str, Any] = field(default_factory=dict)
    note: str = ""

    @property
    def applies(self) -> bool:
        return self.ref is not None

    def describe(self) -> str:
        if not self.applies:
            return f"{self.model}: Pipeline tab settings" + (f" ({self.note})" if self.note else "")
        if not self.changes:
            return f"{self.model}: recipe {self.label} (same as the Pipeline tab settings)"
        changed = ", ".join(
            f"{_LABELS.get(key, key)} {value}" for key, value in self.changes.items()
        )
        return f"{self.model}: recipe {self.label} ({changed})"

    def provenance(self) -> dict[str, Any]:
        return {
            "ref": dict(self.ref) if self.ref is not None else None,
            "label": self.label,
            "changes": dict(self.changes),
        }


@dataclass(frozen=True)
class RecipeContext:
    """Captured on the GUI thread: the profile service and the Pipeline tab's working values and catalogs."""

    service: Any
    working: Mapping[str, Any]
    catalogs: Mapping[str, Collection[str]]
    resources: Mapping[str, Any]


def capture_recipe_context(app: Any) -> RecipeContext | None:
    controller = getattr(app, "generation_profiles", None)
    if controller is None:
        return None
    resources = getattr(controller, "_resources", None)
    return RecipeContext(
        service=controller.service,
        working=dict(controller.working_values()),
        catalogs=dict(controller.catalogs()),
        resources=dict(resources() if callable(resources) else {}),
    )


def resolve_recipe(context: RecipeContext, model: str, previous_family: str | None) -> ModelRecipe:
    """What choosing ``model`` in the picker would apply to the Pipeline tab's working settings."""

    from src.generation_profiles.application import STATUS_IDENTITY_CONFLICT

    service = context.service
    working = {key: value for key, value in context.working.items() if key != "model"}
    working["model"] = model
    plan, profile = service.plan_for_model(
        model,
        working,
        catalogs=context.catalogs,
        vae_options=service.vae_options(model, context.resources),
        previous_family=previous_family,
    )
    if profile is None:
        return ModelRecipe(model, note="no saved recipe")
    if plan.status == STATUS_IDENTITY_CONFLICT:
        return ModelRecipe(model, note=plan.message)
    label = f"{_KIND_LABELS.get(profile.kind, profile.kind)}: {profile.name}"
    changes = {key: value for key, value in plan.changes.items() if key in _OVERRIDE_FIELD}
    return ModelRecipe(model, profile.ref.to_dict(), label, changes)


def resolve_recipes(context: RecipeContext | None, models: Sequence[str]) -> dict[str, ModelRecipe]:
    """Worker thread: each model's recipe. A model whose recipe cannot be read uses the Pipeline tab's settings."""

    if context is None:
        return {model: ModelRecipe(model, note="saved recipes are unavailable") for model in models}
    current = str(context.working.get("model") or "")
    previous_family = None
    if current:
        try:
            previous_family = context.service.resolve(current).identity.family
        except Exception:  # noqa: BLE001 - an unknown current model only skips the family carry-over
            previous_family = None
    recipes: dict[str, ModelRecipe] = {}
    for model in models:
        try:
            recipes[model] = resolve_recipe(context, model, previous_family)
        except Exception as exc:  # noqa: BLE001 - an unreadable recipe falls back to the Pipeline settings
            log.info("[batch] recipe for %s could not be read: %s", model, exc)
            recipes[model] = ModelRecipe(model, note=f"its recipe could not be read: {exc}")
    return recipes


def with_recipe(draft_config: Any, recipe: ModelRecipe | None) -> Any:
    """``draft_config`` (a ``PackDraftConfig``) with the recipe written where the picker would write it."""

    if recipe is None or not recipe.applies or not recipe.changes:
        return draft_config
    base = deepcopy(dict(draft_config.base_config))
    txt2img = dict(base.get("txt2img") or {})
    txt2img.update(recipe.changes)
    base["txt2img"] = txt2img
    overrides = draft_config.stage_overrides
    if overrides is not None and getattr(overrides, "txt2img", None) is not None:
        stage = replace(
            overrides.txt2img,
            **{_OVERRIDE_FIELD[key]: value for key, value in recipe.changes.items()},
        )
        overrides = replace(overrides, txt2img=stage)
    return replace(draft_config, base_config=base, stage_overrides=overrides)


def replaced_by_pack(recipe: ModelRecipe | None, records: Sequence[Any]) -> tuple[str, ...]:
    """Recipe settings the cell's jobs do not carry (the PromptPack's own saved settings won)."""

    if recipe is None or not recipe.applies:
        return ()
    replaced = []
    for key, value in recipe.changes.items():
        attr = _RECORD_FIELD.get(key)
        if attr is None:
            continue
        if any(not _same(getattr(record, attr, value), value) for record in records):
            replaced.append(_LABELS[key])
    return tuple(replaced)


def _same(left: Any, right: Any) -> bool:
    try:
        return float(left) == float(right)
    except (TypeError, ValueError):
        return str(left) == str(right)


__all__ = [
    "ModelRecipe",
    "RecipeContext",
    "capture_recipe_context",
    "replaced_by_pack",
    "resolve_recipes",
    "with_recipe",
]
