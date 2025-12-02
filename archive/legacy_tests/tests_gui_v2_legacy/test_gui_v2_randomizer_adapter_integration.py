from __future__ import annotations

from src.gui_v2.adapters.randomizer_adapter_v2 import (
    build_randomizer_plan,
    compute_variant_count,
)


def test_randomizer_adapter_generates_variants_and_counts() -> None:
    base_config = {"pipeline": {"variant_mode": "fanout"}}
    options = {
        "variant_mode": "fanout",
        "fanout": 2,
        "model_matrix": ["model_a", "model_b"],
    }

    result = build_randomizer_plan(base_config, options)

    assert result.fanout == 2
    assert result.variant_count == len(result.configs)
    assert result.variant_count >= 2
    assert compute_variant_count(base_config, options) == result.variant_count
    # Ensure base config is not mutated and pipeline options are present
    assert "model_matrix" in result.options
    assert "model_matrix" not in base_config.get("pipeline", {})
