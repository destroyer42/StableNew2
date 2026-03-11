from __future__ import annotations

from src.learning.variable_selection_contract import normalize_resource_entries


def test_normalize_resource_entries_prefers_display_and_internal_names() -> None:
    values, mapping = normalize_resource_entries(
        [
            {"title": "Juggernaut XL", "name": "juggernautXL_ragnarokBy.safetensors"},
            {"title": "Juggernaut XL", "name": "duplicate_should_be_ignored"},
            "Euler a",
        ]
    )

    assert values == ["Juggernaut XL", "Euler a"]
    assert mapping["Juggernaut XL"] == "juggernautXL_ragnarokBy.safetensors"
    assert mapping["Euler a"] == "Euler a"
