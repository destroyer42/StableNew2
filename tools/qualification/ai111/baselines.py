"""The arms a model must beat: identity, the deterministic engine, and a trivial heuristic. Pure and deterministic."""

from __future__ import annotations

import re
from types import SimpleNamespace

from src.image_backends.forge_klein_profile import latest_klein_profile
from src.image_backends.model_policy import ModelPolicy, policy_for_profile, resolve_model_policy
from src.prompting.prompt_adaptation import (
    EFFECT_DROPPED,
    EFFECT_REWRITTEN,
    PromptAdaptationInput,
    adapt_prompt_for_target,
)
from src.prompting.prompt_compatibility import BREAK_SEPARATOR_PATTERN, WEIGHTED_ATTENTION_PATTERN
from tools.qualification.ai111.corpus import Case

_MOTION = re.compile(
    r"\b(walk|walks|turn|turns|wave|waves|run|runs|spin|spins|move|moves)\b", re.IGNORECASE
)


def policy_for(target_id: str) -> ModelPolicy:
    """The deterministic policy for a target id used by the corpus (``sdxl`` or ``flux2_klein``)."""

    if target_id == "flux2_klein":
        return policy_for_profile(latest_klein_profile())
    if target_id == "sdxl":
        resolved = SimpleNamespace(
            status=SimpleNamespace(value="resolved"),
            family=SimpleNamespace(value="sdxl"),
            structural_error=None,
            checkpoint_architecture=None,
        )
        return resolve_model_policy(
            "qualification-sdxl-checkpoint", family_lookup=lambda _name: resolved
        )
    raise ValueError(f"unknown target id: {target_id}")


def residual_operations(target_id: str, positive: str, negative: str) -> int:
    """How many changes the deterministic engine would *still* make to this text for the target (lower is better)."""

    plan = adapt_prompt_for_target(
        policy_for(target_id), PromptAdaptationInput(positive_text=positive, negative_text=negative)
    )
    return sum(1 for op in plan.operations if op.effect in (EFFECT_REWRITTEN, EFFECT_DROPPED))


def b0_identity(case: Case) -> dict[str, str]:
    if case.kind == "prompt_rewrite":
        return {"positive": case.positive, "negative": case.negative}
    options = case.allowed_targets or case.allowed_workflows
    return {"choice": options[0]}


def b1_engine(case: Case) -> dict[str, str]:
    """The existing deterministic behaviour: the engine's adaptation for rewrites; its dialect detectors for choices."""

    if case.kind == "prompt_rewrite":
        plan = adapt_prompt_for_target(
            policy_for(case.target_policy_id),
            PromptAdaptationInput(positive_text=case.positive, negative_text=case.negative),
        )
        return {"positive": plan.positive_text, "negative": plan.negative_text}
    if case.kind == "target_fit_advice":
        weighted = bool(
            WEIGHTED_ATTENTION_PATTERN.search(case.positive)
            or BREAK_SEPARATOR_PATTERN.search(case.positive)
        )
        return {"choice": "sdxl" if weighted else "flux2_klein"}
    return {"choice": "video_workflow" if _MOTION.search(case.positive) else "txt2img"}


def _dedupe_terms(text: str) -> str:
    seen: set[str] = set()
    kept: list[str] = []
    for term in (part.strip() for part in text.split(",")):
        key = term.lower()
        if term and key not in seen:
            seen.add(key)
            kept.append(term)
    return ", ".join(kept)


def b2_heuristic(case: Case) -> dict[str, str]:
    """Collapse whitespace and drop duplicate comma terms: the cheapest thing that is not the identity."""

    if case.kind == "prompt_rewrite":
        return {
            "positive": _dedupe_terms(re.sub(r"[ \t]+", " ", case.positive)),
            "negative": _dedupe_terms(re.sub(r"[ \t]+", " ", case.negative)),
        }
    return b0_identity(case)


ARMS = {"B0_identity": b0_identity, "B1_engine": b1_engine, "B2_heuristic": b2_heuristic}

__all__ = ["ARMS", "b0_identity", "b1_engine", "b2_heuristic", "policy_for", "residual_operations"]
