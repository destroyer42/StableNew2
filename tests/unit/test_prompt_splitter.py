from __future__ import annotations

from src.prompting.prompt_splitter import (
    detect_lora_syntax,
    detect_weight_syntax,
    split_prompt_chunks,
)


def test_splitter_preserves_wrapped_chunks() -> None:
    prompt = "(foo:1.2), [bar], <lora:baz:0.8>, plain text"
    assert split_prompt_chunks(prompt) == ["(foo:1.2)", "[bar]", "<lora:baz:0.8>", "plain text"]


def test_splitter_ignores_commas_inside_wrappers() -> None:
    prompt = "(portrait, dramatic:1.2), [soft, warm light], <lora:foo,bar:0.8>, landscape"
    assert split_prompt_chunks(prompt) == [
        "(portrait, dramatic:1.2)",
        "[soft, warm light]",
        "<lora:foo,bar:0.8>",
        "landscape",
    ]


def test_splitter_degrades_gracefully_for_malformed_syntax() -> None:
    prompt = "(portrait, dramatic lighting, landscape"
    assert split_prompt_chunks(prompt) == ["(portrait, dramatic lighting, landscape"]


def test_splitter_detects_weight_and_lora_syntax() -> None:
    assert detect_weight_syntax("(foo:1.2)") is True
    assert detect_weight_syntax("[foo]") is False
    assert detect_lora_syntax("<lora:foo:0.8>") is True
    assert detect_lora_syntax("portrait") is False
