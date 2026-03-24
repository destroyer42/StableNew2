from __future__ import annotations

from src.prompting.prompt_deduper import dedupe_prompt_chunks


def test_deduper_drops_obvious_duplicates_deterministically() -> None:
    kept, dropped = dedupe_prompt_chunks(
        ["beautiful woman", "(beautiful woman:1.2)", "japanese garden", "beautiful woman"]
    )
    assert kept == ["beautiful woman", "(beautiful woman:1.2)", "japanese garden"]
    assert dropped == ["beautiful woman"]


def test_deduper_keeps_distinct_lora_weights() -> None:
    kept, dropped = dedupe_prompt_chunks(
        ["<lora:foo:0.8>", "<lora:foo:0.6>", "<lora:foo:0.8>"]
    )
    assert kept == ["<lora:foo:0.8>", "<lora:foo:0.6>"]
    assert dropped == ["<lora:foo:0.8>"]
