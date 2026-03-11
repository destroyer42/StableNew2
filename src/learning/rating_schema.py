from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RatingCategory:
    key: str
    label: str


BASE_CATEGORIES = (
    RatingCategory("composition", "Composition"),
    RatingCategory("prompt_adherence", "Prompt Adherence"),
    RatingCategory("technical_quality", "Technical Quality"),
)

PEOPLE_CATEGORIES = (
    RatingCategory("anatomy", "Anatomy"),
    RatingCategory("expression", "Expression"),
)

ANIMAL_CATEGORIES = (
    RatingCategory("anatomy", "Anatomy"),
)

SCENE_CATEGORIES = (
    RatingCategory("structure", "Scene Structure"),
)


def get_active_categories(flags: dict[str, bool] | None = None) -> list[RatingCategory]:
    flags = dict(flags or {})
    categories: list[RatingCategory] = list(BASE_CATEGORIES)
    if flags.get("people"):
        categories.extend(PEOPLE_CATEGORIES)
    elif flags.get("animals"):
        categories.extend(ANIMAL_CATEGORIES)
    if flags.get("landscape") or flags.get("architecture"):
        categories.extend(SCENE_CATEGORIES)
    deduped: dict[str, RatingCategory] = {}
    for category in categories:
        deduped[category.key] = category
    return list(deduped.values())


def blend_rating(overall_rating: int, subscores: dict[str, int] | None = None) -> int:
    details = {key: int(value) for key, value in dict(subscores or {}).items() if value}
    if not details:
        return int(overall_rating)
    avg_details = sum(details.values()) / len(details)
    weighted = (float(overall_rating) * 0.45) + (avg_details * 0.55)
    return int(min(5, max(1, round(weighted))))
