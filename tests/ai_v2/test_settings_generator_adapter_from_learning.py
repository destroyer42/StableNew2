from __future__ import annotations

from src.ai.settings_generator_adapter import build_request_from_learning_data
from src.ai.settings_generator_contract import SuggestionIntent


def test_adapter_builds_request_from_dataset(snapshot=None):
    baseline = {"txt2img": {"steps": 10}}
    dataset = {
        "runs": [
            {
                "run_id": "r1",
                "timestamp": "2025-01-01T00:00:00",
                "base_config": {"txt2img": {"model": "m"}},
                "variant_configs": [],
                "randomizer_mode": "off",
                "randomizer_plan_size": 1,
                "primary_model": "m",
                "primary_sampler": "Euler",
                "primary_scheduler": "Normal",
                "primary_steps": 20,
                "primary_cfg_scale": 7.0,
                "metadata": {},
            }
        ],
        "feedback": [],
    }
    req = build_request_from_learning_data(
        SuggestionIntent.FAST_DRAFT, "pack1", baseline, dataset_snapshot=dataset
    )
    assert req.pack_id == "pack1"
    assert req.baseline_config["txt2img"]["steps"] == 10
    assert req.recent_runs and req.recent_runs[0].run_id == "r1"
