# Subsystem: Learning
# Role: Defines feedback domain models for learning-mode evaluations.

"""Feedback models for learning runs."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List

from .learning_plan import LearningPlan


@dataclass
class UserFeedbackItem:
    """Represents a single piece of user feedback for a learning step."""

    step_index: int
    score: Any
    notes: str | None = None
    selected_best: bool = False


@dataclass
class FeedbackBundle:
    """Aggregated feedback for a learning plan."""

    plan: LearningPlan
    items: List[UserFeedbackItem]


def package_feedback_for_llm(bundle: FeedbackBundle) -> Dict[str, Any]:
    """Return a deterministic dict suitable for downstream LLM usage."""

    packaged_items = [
        {
            "step_index": item.step_index,
            "score": item.score,
            "selected_best": bool(item.selected_best),
            "notes": item.notes or "",
        }
        for item in bundle.items
    ]

    return {
        "plan": asdict(bundle.plan),
        "feedback": packaged_items,
        "metadata": {"total_items": len(packaged_items)},
    }
