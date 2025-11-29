from __future__ import annotations

from src.gui_v2.adapters.randomizer_adapter_v2 import RiskBand, compute_variant_stats


def test_variant_count_risk_bands():
    base = {}
    options = {"fanout": 4, "variant_mode": "fanout", "model_matrix": ["a", "b", "c"], "matrix": {"model": ["a", "b", "c"]}}
    stats = compute_variant_stats(base, options, threshold=8)
    assert stats["risk_band"] == RiskBand.HIGH
    assert "combos" in stats["explanation"]

    options_small = {"fanout": 1, "variant_mode": "fanout", "model_matrix": ["a"]}
    stats_small = compute_variant_stats(base, options_small, threshold=8)
    assert stats_small["risk_band"] == RiskBand.LOW
