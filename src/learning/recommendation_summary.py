"""Operator-facing reading of a ``RecommendationSet``: what, where, on what evidence, and what Apply may do.

Presentation only. It restates the facts the recommendation engine already computed (tier, confidence, sample
counts, model policy context) and the existing automation-mode gates; it never invents confidence intervals,
causal claims or a recommendation, and it never decides evidence eligibility itself.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from src.learning.automation_modes import AUTO_MICRO_EXPERIMENT, SUGGEST_ONLY
from src.learning.recommendation_engine import (
    EVIDENCE_TIER_EXPERIMENT_STRONG,
    EVIDENCE_TIER_NO_EVIDENCE,
    EVIDENCE_TIER_REVIEW_ONLY,
    EVIDENCE_TIER_SPARSE_PLUS_REVIEW,
    MIN_CONTROLLED_RATINGS,
    MIN_CONTROLLED_VARIANTS,
)

TIER_LABELS = {
    EVIDENCE_TIER_EXPERIMENT_STRONG: "Controlled experiment evidence",
    EVIDENCE_TIER_SPARSE_PLUS_REVIEW: "Too few controlled ratings, plus review feedback (manual only)",
    EVIDENCE_TIER_REVIEW_ONLY: "Review feedback only (manual only)",
    EVIDENCE_TIER_NO_EVIDENCE: "No usable evidence",
}


@dataclass(frozen=True)
class RecommendationItem:
    setting: str
    value: str
    summary: str
    details: tuple[str, ...]


@dataclass(frozen=True)
class RecommendationSummary:
    tier: str
    tier_label: str
    headline: str
    applies_to: str
    items: tuple[RecommendationItem, ...]
    progress: str
    apply_enabled: bool
    apply_note: str
    changes: tuple[str, ...]

    @property
    def has_recommendations(self) -> bool:
        return bool(self.items)


def _field(rec: Any, attr: str, key: str, default: Any) -> Any:
    if hasattr(rec, attr):
        return getattr(rec, attr)
    if isinstance(rec, Mapping):
        return rec.get(key, default)
    return default


def _applies_to(recommendations: Any) -> str:
    context = getattr(recommendations, "model_policy_context", None)
    stage = str(getattr(recommendations, "stage", "") or "txt2img")
    if isinstance(context, Mapping) and context:
        model = str(context.get("selected_model") or "").strip()
        family = str(context.get("family") or "").strip()
        profile = context.get("profile_ref")
        target = (
            f"{profile['id']} v{profile.get('version', '?')}"
            if isinstance(profile, Mapping) and profile.get("id")
            else family
        )
        label = " ".join(part for part in (model, f"({target})" if target else "") if part)
        if label:
            return f"{label}, {stage} stage"
    return f"{stage} stage (no model-specific evidence recorded)"


def apply_availability(
    mode: str, *, has_recommendations: bool, automation_eligible: bool
) -> tuple[bool, str]:
    """Whether Apply may be offered and why not. Mirrors the controller's own mode gates; it adds none."""
    if not has_recommendations:
        return False, "There is nothing to apply yet."
    if mode == SUGGEST_ONLY:
        return (
            False,
            "Suggest only is on, so recommendations are shown but never applied. Change the mode to apply them.",
        )
    if mode == AUTO_MICRO_EXPERIMENT and not automation_eligible:
        return (
            False,
            "Auto micro-experiment needs controlled experiment evidence "
            f"({MIN_CONTROLLED_VARIANTS} distinct tested values and {MIN_CONTROLLED_RATINGS} controlled ratings "
            "in one experiment). Switch to Apply with confirm to apply this manually.",
        )
    if mode == AUTO_MICRO_EXPERIMENT:
        return (
            True,
            "Apply asks first, then changes the Pipeline settings and queues one preview job.",
        )
    return (
        True,
        "Apply asks first, then changes only the current Pipeline settings. Past jobs and prompts are untouched.",
    )


def build_recommendation_summary(
    recommendations: Any,
    *,
    mode: str,
    evidence_message: str = "",
    changes: Sequence[tuple[str, Any, Any]] = (),
    changes_note: str = "",
) -> RecommendationSummary:
    """``changes`` are ``(setting, current value, recommended value)`` rows from a read-only dry run."""
    rec_list: list[Any] = []
    if hasattr(recommendations, "recommendations"):
        rec_list = list(recommendations.recommendations or [])
    elif isinstance(recommendations, list):
        rec_list = list(recommendations)
    tier = str(getattr(recommendations, "evidence_tier", "") or EVIDENCE_TIER_NO_EVIDENCE)
    eligible = bool(getattr(recommendations, "automation_eligible", False))
    items: list[RecommendationItem] = []
    for rec in rec_list[:5]:
        setting = str(_field(rec, "parameter_name", "parameter", "Unknown"))
        value = _field(rec, "recommended_value", "value", "?")
        confidence = float(_field(rec, "confidence_score", "confidence", 0) or 0)
        samples = int(_field(rec, "sample_count", "samples", 0) or 0)
        mean = float(_field(rec, "mean_rating", "mean_rating", 0) or 0)
        rationale = str(_field(rec, "confidence_rationale", "rationale", "") or "")
        context = str(_field(rec, "context_key", "context", "") or "")
        details = [
            f"Average rating {mean:.1f} of 5 from {samples} rating{'s' if samples != 1 else ''}",
            f"Engine confidence score {confidence * 100:.0f}% (the engine's existing score, not a statistical guarantee)",
        ]
        if rationale:
            details.append(f"Why: {rationale}")
        if context:
            details.append(f"Context: {context}")
        items.append(
            RecommendationItem(
                setting=setting,
                value=str(value),
                summary=f"{setting}: {value}",
                details=tuple(details),
            )
        )
    if not items:
        headline = "No recommendation yet."
        if evidence_message:
            headline += " " + evidence_message
        else:
            headline += f" Rate at least {MIN_CONTROLLED_RATINGS} results across {MIN_CONTROLLED_VARIANTS} tested values."
    elif len(items) == 1:
        headline = f"Suggested: {items[0].summary}"
    else:
        headline = f"{len(items)} suggested settings; the strongest is {items[0].summary}"
    enabled, note = apply_availability(
        mode, has_recommendations=bool(items), automation_eligible=eligible
    )
    change_lines = tuple(
        f"{setting} is already {new}"
        if str(old) == str(new)
        else f"Would change {setting}: {old} -> {new}"
        for setting, old, new in changes
    )
    if enabled and not change_lines and changes_note:
        note = f"{note} {changes_note}".strip()
    return RecommendationSummary(
        tier=tier,
        tier_label=TIER_LABELS.get(tier, f"Evidence tier: {tier}"),
        headline=headline,
        applies_to=_applies_to(recommendations) if items else "",
        items=tuple(items),
        progress=evidence_message,
        apply_enabled=enabled,
        apply_note=note,
        changes=change_lines,
    )


__all__ = [
    "RecommendationItem",
    "RecommendationSummary",
    "TIER_LABELS",
    "apply_availability",
    "build_recommendation_summary",
]
