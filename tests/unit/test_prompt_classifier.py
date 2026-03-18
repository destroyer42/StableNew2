from __future__ import annotations

import json
from pathlib import Path

from src.prompting.prompt_bucket_rules import build_default_prompt_bucket_rules
from src.prompting.prompt_classifier import classify_chunk_rule_based, classify_chunk_score_based


def _load_fixture(name: str) -> list[dict[str, object]]:
    path = Path("tests") / "fixtures" / name
    return json.loads(path.read_text(encoding="utf-8"))


def test_rule_based_classifier_positive_fixture() -> None:
    rules = build_default_prompt_bucket_rules()
    fixture = _load_fixture("prompts_positive_basic.json")[0]
    expected = fixture["expected_buckets"]
    for bucket, chunks in expected.items():
        for chunk in chunks:
            assert classify_chunk_rule_based(chunk, "positive", rules) == bucket


def test_rule_based_classifier_negative_fixture() -> None:
    rules = build_default_prompt_bucket_rules()
    fixture = _load_fixture("prompts_negative_basic.json")[0]
    expected = fixture["expected_buckets"]
    for bucket, chunks in expected.items():
        for chunk in chunks:
            assert classify_chunk_rule_based(chunk, "negative", rules) == bucket


def test_classifier_marks_loras_as_positive_lora_tokens() -> None:
    rules = build_default_prompt_bucket_rules()
    assert classify_chunk_rule_based("<lora:foo:0.8>", "positive", rules) == "lora_tokens"


def test_score_based_classifier_handles_ambiguous_chunk() -> None:
    rules = build_default_prompt_bucket_rules()
    assert classify_chunk_score_based("cinematic photorealistic portrait", "positive", rules) in {
        "subject",
        "style_medium",
        "lighting_atmosphere",
    }
