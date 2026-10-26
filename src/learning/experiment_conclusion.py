"""Derived, read-only conclusion projection for one designed experiment."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def build_experiment_conclusion(
    plan: list[Any], rating_details: dict[str, dict[str, Any]], review_drafts: dict[str, Any],
    *, study_type: str = "controlled_variable"
) -> dict[str, Any]:
    """Summarize persisted sample evidence without creating a second rating."""
    if study_type == "prompt_slot":
        from src.learning.prompt_slot_experiment import conclusion

        return conclusion(plan, rating_details, review_drafts)
    if study_type == "prompt_model_matrix":
        from src.learning.prompt_model_matrix import conclusion as matrix_conclusion

        return matrix_conclusion(plan, rating_details, review_drafts)
    if study_type == "embedding_experiment":
        from src.learning.embedding_experiment import conclusion as embedding_conclusion

        return embedding_conclusion(plan, rating_details, review_drafts)
    if study_type == "lora_composition":
        from src.learning.lora_composition import conclusion as lora_conclusion

        return lora_conclusion(plan, rating_details, review_drafts)
    rows: list[dict[str, Any]] = []
    controlled = True
    saved_total = 0
    draft_total = 0
    sample_total = 0
    for variant in plan:
        refs = [str(path) for path in list(getattr(variant, "image_refs", []) or [])]
        sample_total += len(refs)
        values: list[float] = []
        subscores: dict[str, list[float]] = defaultdict(list)
        for path in refs:
            detail = rating_details.get(path)
            if detail:
                rating = float(detail.get("overall_rating", 0) or 0)
                if rating > 0:
                    values.append(rating)
                    saved_total += 1
                for name, raw in dict(detail.get("subscores") or {}).items():
                    try:
                        subscores[str(name)].append(float(raw))
                    except (TypeError, ValueError):
                        continue
            elif any(str(key).endswith(f":{path}") for key in review_drafts):
                draft_total += 1
        validity = dict(getattr(variant, "execution_metadata", {}) or {}).get(
            "controlled_evidence_valid"
        )
        if validity is False or str(getattr(variant, "status", "")) == "uncontrolled":
            controlled = False
        rows.append(
            {
                "value": getattr(variant, "param_value", None),
                "sample_count": len(refs),
                "saved_count": len(values),
                "average_overall": round(sum(values) / len(values), 3) if values else None,
                "average_subscores": {
                    name: round(sum(scores) / len(scores), 3)
                    for name, scores in sorted(subscores.items())
                    if scores
                },
            }
        )
    eligible = controlled and len(rows) >= 2 and all(row["saved_count"] > 0 for row in rows)
    winner = max(rows, key=lambda row: row["average_overall"] or 0)["value"] if eligible else None
    comparison = study_type == "model_comparison"
    grid = study_type == "two_axis_grid"
    if grid:
        # Two varying settings: ratings are described per cell, never ranked or called a causal winner.
        eligible, winner = False, None
    return {
        "controlled_valid": controlled and not comparison and not grid,
        "study_type": study_type,
        "comparison_claim": (
            "target_envelope_preference" if comparison
            else "exploratory_two_variable_observation" if grid else "controlled_variable"
        ),
        "causal_one_variable": not (comparison or grid),
        "saved": saved_total,
        "draft": draft_total,
        "unrated": max(0, sample_total - saved_total - draft_total),
        "values": rows,
        "best_value": winner,
        "sufficient_evidence": eligible,
        "message": (
            "Exploratory two-variable grid: observed ratings are descriptive per cell; no winner is chosen."
            if grid else
            (f"{winner} was preferred under its frozen target envelope; model-specific settings and prompt adaptation may differ."
             if eligible else "Insufficient saved evidence for a target-envelope preference.")
            if comparison else
            f"Highest-rated tested value: {winner}"
            if eligible
            else "Insufficient controlled saved evidence for a causal winner."
        ),
    }
