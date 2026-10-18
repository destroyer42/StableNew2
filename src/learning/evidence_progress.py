"""How far an experiment is from the evidence a recommendation needs, in the engine's own thresholds."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from src.learning.recommendation_engine import MIN_CONTROLLED_RATINGS, MIN_CONTROLLED_VARIANTS


@dataclass(frozen=True)
class EvidenceProgress:
    """Controlled ratings saved so far against ``experiment_strong`` (see ``RecommendationEngine``)."""

    ratings: int
    values_rated: int

    @property
    def ratings_needed(self) -> int:
        return max(0, MIN_CONTROLLED_RATINGS - self.ratings)

    @property
    def values_needed(self) -> int:
        return max(0, MIN_CONTROLLED_VARIANTS - self.values_rated)

    @property
    def ready(self) -> bool:
        return self.ratings_needed == 0 and self.values_needed == 0

    def message(self) -> str:
        if self.ready:
            return "Enough ratings for recommendations."
        parts: list[str] = []
        if self.ratings_needed:
            noun = "rating" if self.ratings_needed == 1 else "ratings"
            parts.append(f"{self.ratings_needed} more {noun}")
        if self.values_needed:
            noun = "value" if self.values_needed == 1 else "values"
            parts.append(f"at least {self.values_needed} more tested {noun}")
        return "Need " + " across ".join(parts) + " for recommendations."


def evidence_progress(saved_ratings_per_value: Iterable[int]) -> EvidenceProgress:
    """``saved_ratings_per_value`` holds one saved-rating count for each tested value of the experiment."""

    counts = [max(0, int(count)) for count in saved_ratings_per_value]
    return EvidenceProgress(ratings=sum(counts), values_rated=sum(1 for count in counts if count))


__all__ = ["EvidenceProgress", "evidence_progress"]
