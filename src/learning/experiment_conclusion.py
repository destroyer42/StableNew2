"""Derived, read-only conclusion projection for one designed experiment."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def build_experiment_conclusion(
    plan: list[Any], rating_details: dict[str, dict[str, Any]], review_drafts: dict[str, Any]
) -> dict[str, Any]:
    """Summarize persisted sample evidence without creating a second rating."""
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
    return {
        "controlled_valid": controlled,
        "saved": saved_total,
        "draft": draft_total,
        "unrated": max(0, sample_total - saved_total - draft_total),
        "values": rows,
        "best_value": winner,
        "sufficient_evidence": eligible,
        "message": (
            f"Highest-rated tested value: {winner}"
            if eligible
            else "Insufficient controlled saved evidence for a causal winner."
        ),
    }
