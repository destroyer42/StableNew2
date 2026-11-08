"""Window-independent helpers for the catalog's Compatibility Probe (MEC-901 / MEC-905).

``probe_options`` turns what is known about one checkpoint (verified identity, family, header variant, a Civitai
``baseModel`` label, your past runs) into the recipes the dialog offers. ``prepare_probe`` freezes the operator's
design against fresh planning inputs through ``QualificationBatchService``; admission stays with the window's
explicit confirmation.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.learning.compatibility_probe import (
    MAX_RECIPES,
    RECIPES,
    ProbeDesign,
    ProbeRecipe,
    match_inventory,
    probe_baseline,
    probe_payload,
    recipe_from_history,
    suggest_recipes,
)
from src.learning.evidence_autopilot import ProposalPlanningContext
from src.learning.model_run_history import ModelRunSummary

_SIDECAR_LIMIT = 8 * 1024 * 1024


@dataclass(frozen=True)
class ProbeOptions:
    recipes: tuple[ProbeRecipe, ...]
    preselected: tuple[str, ...]
    unavailable: tuple[str, ...]
    notes: tuple[str, ...]


def sidecar_base_model(path: Path | None) -> str:
    """The ``baseModel`` label of a checkpoint's local ``.civitai.info`` sidecar, else ''."""
    if path is None:
        return ""
    for candidate in (
        path.with_suffix(path.suffix + ".civitai.info"),
        path.with_name(f"{path.stem}.civitai.info"),
    ):
        try:
            if not candidate.is_file() or candidate.stat().st_size > _SIDECAR_LIMIT:
                continue
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            continue
        if isinstance(data, dict):
            for key in ("baseModel", "base_model"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return ""


def history_recipe(history: ModelRunSummary | None) -> ProbeRecipe | None:
    """MEC-905: your usual settings for this checkpoint as an explicit recipe (never applied silently)."""
    if history is None:
        return None
    return recipe_from_history(dict(history.settings), history.resolution, history.completed)


def probe_options(
    *,
    family: str,
    variant: str,
    base_model_hint: str,
    history: ModelRunSummary | None,
    resources: Mapping[str, Sequence[str]],
) -> ProbeOptions:
    usual = history_recipe(history)
    suggested = suggest_recipes(
        family=family, variant=variant, base_model_hint=base_model_hint, history=usual
    )
    ordered = list(suggested) + [r for r in RECIPES.values() if r not in suggested]
    samplers = list(resources.get("samplers") or ())
    schedulers = list(resources.get("schedulers") or ())
    notes: list[str] = []
    if base_model_hint:
        notes.append(f"Civitai sidecar says base model: {base_model_hint}. Its lineage is listed first.")
    if variant:
        notes.append(f"File header variant: {variant}.")
    if usual is not None:
        notes.append(
            "‘Your usual settings’ is what most of your completed runs used. It is listed so you can compare "
            "it with the lineage defaults; it is not a recommendation."
        )
    elif history is not None and history.completed:
        notes.append(
            f"Your {history.completed} completed runs are too few or too mixed to form a usual-settings recipe."
        )
    recipes: list[ProbeRecipe] = []
    unavailable: list[str] = []
    if not samplers or not schedulers:
        notes.append(
            "The backend's sampler/scheduler list is not loaded (is the WebUI connected?). Recipes use their "
            "names as written; the backend refuses a name it does not have."
        )
        recipes = ordered
    else:
        for recipe in ordered:
            matched, problem = match_inventory(recipe, samplers, schedulers)
            if matched is None:
                unavailable.append(problem)
            else:
                recipes.append(matched)
    keys = {recipe.key for recipe in recipes}
    preselected = tuple(r.key for r in suggested if r.key in keys)[:MAX_RECIPES]
    return ProbeOptions(tuple(recipes), preselected, tuple(unavailable), tuple(notes))


@dataclass(frozen=True)
class ProbeSession:
    experiment_id: str
    name: str
    recipes: tuple[str, ...]
    statuses: tuple[tuple[str, str, int], ...]  # (recipe, status, images)


def probe_sessions(store: Any, sha256: str) -> tuple[ProbeSession, ...]:
    """Saved probe experiments for one checkpoint, read from the Experiment Library (no repository writes)."""
    from src.learning.compatibility_probe import STUDY_TYPE

    if not sha256:
        return ()
    prefix = f"probe-{sha256[:12]}-"
    found = []
    for handle in store.list_handles():
        if not handle.experiment_id.startswith(prefix):
            continue
        payload = store.load_session(handle.experiment_id) or {}
        experiment = payload.get("current_experiment") or {}
        design = (experiment.get("metadata") or {}).get(STUDY_TYPE) or {}
        if design.get("sha256") != sha256:
            continue
        plan = payload.get("plan") or []
        found.append(
            ProbeSession(
                handle.experiment_id,
                str(experiment.get("name") or handle.display_name),
                tuple(str(recipe.get("label")) for recipe in design.get("recipes") or ()),
                tuple(
                    (
                        str(variant.get("param_value")),
                        str(variant.get("status") or "pending"),
                        len(variant.get("image_refs") or ()),
                    )
                    for variant in plan
                ),
            )
        )
    return tuple(found)


def describe_sessions(sessions: Sequence[ProbeSession]) -> str:
    if not sessions:
        return (
            "No probe of this checkpoint is saved yet. You can still record a verdict from what you already know."
        )
    lines = []
    for session in sessions:
        lines.append(f"{session.name}  [{session.experiment_id}]")
        if not session.statuses:
            lines.append("  saved, not queued")
        for recipe, status, images in session.statuses:
            lines.append(f"  {status:<10} {images} images  {recipe}")
    return "\n".join(lines)


def prepare_probe(service: Any, design: ProbeDesign, context: ProposalPlanningContext, cancelled: Any) -> Any:
    """Save (or reuse) the probe draft and freeze its Preview; nothing is submitted here."""
    if context.target.identity.sha256 != design.sha256:
        raise ValueError(
            "The selected checkpoint's verified identity changed since the probe was designed. Reopen the probe."
        )
    if context.target.policy.qualified:
        raise ValueError("This checkpoint has a fixed executable profile; it does not need a probe.")
    payload = probe_payload(
        design,
        probe_baseline(context.baseline, context.target),
        context.target.identity.display_name,
    )
    return service.prepare_probe(payload, context, cancelled=cancelled)
