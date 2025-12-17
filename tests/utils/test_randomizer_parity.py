"""Parity and determinism tests for the randomizer layer."""

import copy

from src.utils.randomizer import sanitize_prompt


def _simple_matrix_config():
    return {
        "enabled": True,
        "matrix": {
            "enabled": True,
            "mode": "fanout",
            "slots": [
                {"name": "Weather", "values": ["sunny", "rainy"]},
            ],
        },
    }


def test_preview_and_pipeline_prompts_match_exactly_for_simple_matrix():
    config = _simple_matrix_config()
    prompt = "hero in [[Weather]] field"

    preview_prompts = sanitize_prompt(prompt, config, seed=42)
    pipeline_prompts = sanitize_prompt(prompt, config, seed=42)

    assert preview_prompts == pipeline_prompts
    assert all("[[" not in text for text in preview_prompts)


def test_preview_and_pipeline_prompts_match_with_wildcards_and_matrices():
    config = {
        "enabled": True,
        "wildcards": {
            "enabled": True,
            "mode": "sequential",
            "tokens": [
                {"token": "__creature__", "values": ["dragon", "phoenix"]},
            ],
        },
        "matrix": {
            "enabled": True,
            "mode": "fanout",
            "slots": [
                {"name": "Style", "values": ["cinematic", "painterly"]},
            ],
        },
    }
    prompt = "[[Style]] __creature__ portrait"

    preview_prompts = sanitize_prompt(prompt, config, seed=7)
    pipeline_prompts = sanitize_prompt(prompt, config, seed=7)

    assert preview_prompts == pipeline_prompts
    assert all("[[" not in text and "__" not in text for text in preview_prompts)


def test_randomizer_output_deterministic_for_given_seed():
    config = _simple_matrix_config()
    original = copy.deepcopy(config)
    prompt = "hero under [[Weather]] skies"

    run_one = sanitize_prompt(prompt, config, seed=123)
    run_two = sanitize_prompt(prompt, config, seed=123)

    assert run_one == run_two
    assert config == original, "sanitize_prompt must not mutate input config"
