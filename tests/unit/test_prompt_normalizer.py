from __future__ import annotations

import pytest

from src.prompting.prompt_normalizer import build_dedupe_key, normalize_for_match
from src.prompting.prompt_optimizer_config import PromptOptimizerConfig
from src.prompting.prompt_optimizer_errors import PromptConfigError


def test_normalize_for_match_collapses_case_and_spacing() -> None:
    assert normalize_for_match("  Beautiful   Woman  ") == "beautiful woman"


def test_build_dedupe_key_strips_weight_noise_but_keeps_lora_identity() -> None:
    assert build_dedupe_key("(Beautiful Woman:1.2)") == "beautiful woman"
    assert build_dedupe_key("<lora:foo:0.8>") == "lora:foo"


def test_prompt_optimizer_config_round_trip() -> None:
    config = PromptOptimizerConfig.from_dict({"enabled": False, "opt_out_pipeline_names": ["adetailer"]})
    payload = config.to_dict()
    assert payload["enabled"] is False
    assert payload["opt_out_pipeline_names"] == ["adetailer"]


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"large_chunk_warning_threshold": 0}, "large_chunk_warning_threshold"),
        ({"subject_anchor_boost_min_chunk_count": 0}, "subject_anchor_boost_min_chunk_count"),
        ({"opt_out_pipeline_names": "adetailer"}, "opt_out_pipeline_names"),
    ],
)
def test_prompt_optimizer_config_validation_failures(payload: dict[str, object], message: str) -> None:
    with pytest.raises(PromptConfigError, match=message):
        PromptOptimizerConfig.from_dict(payload)
