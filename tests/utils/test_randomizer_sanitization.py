"""Sanitization-specific tests for the randomizer layer."""

import pytest

from src.utils.randomizer import sanitize_prompt, RandomizerError


def test_matrix_tokens_removed_after_expansion():
    config = {
        "enabled": True,
        "matrix": {
            "enabled": True,
            "mode": "fanout",
            "slots": [
                {"name": "Character", "values": ["knight", "mage"]},
            ],
        },
    }
    prompt = "[[Character]] guarding the gate"
    results = sanitize_prompt(prompt, config, seed=99)
    assert all("[[" not in text for text in results)


def test_wildcards_removed_after_expansion():
    config = {
        "enabled": True,
        "wildcards": {
            "enabled": True,
            "mode": "sequential",
            "tokens": [
                {"token": "__weather__", "values": ["storm", "sun"]},
            ],
        },
    }
    prompt = "__weather__ over the city"
    results = sanitize_prompt(prompt, config, seed=5)
    assert all("__" not in text for text in results)


def test_malformed_matrix_raises_clear_error():
    config = {
        "enabled": True,
        "matrix": {"enabled": True, "mode": "fanout", "slots": []},
    }
    prompt = "Broken [[matrix"
    with pytest.raises(RandomizerError):
        sanitize_prompt(prompt, config, seed=0)
