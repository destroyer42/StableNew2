from __future__ import annotations

from src.learning.rating_schema import blend_rating, get_active_categories


def test_get_active_categories_adds_people_specific_fields() -> None:
    categories = get_active_categories({"people": True, "animals": False, "landscape": False, "architecture": False})
    keys = {item.key for item in categories}
    assert "composition" in keys
    assert "anatomy" in keys
    assert "expression" in keys


def test_blend_rating_uses_subscores_when_present() -> None:
    blended = blend_rating(3, {"composition": 5, "prompt_adherence": 5, "technical_quality": 4})
    assert blended >= 4
