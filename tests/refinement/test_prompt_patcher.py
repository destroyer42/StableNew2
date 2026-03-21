from __future__ import annotations

from src.refinement.prompt_patcher import apply_prompt_patch


def test_apply_prompt_patch_removes_exact_chunks_and_appends_deterministically() -> None:
    result = apply_prompt_patch(
        "portrait woman, soft face, cinematic lighting",
        "blurry, low detail",
        {
            "add_positive": ["clear irises", "natural skin texture"],
            "remove_positive": ["soft face"],
            "add_negative": ["blurred eyes"],
            "remove_negative": ["blurry"],
        },
    )

    assert result.positive.patched == "portrait woman, cinematic lighting, clear irises, natural skin texture"
    assert result.negative.patched == "low detail, blurred eyes"
    assert result.applied_patch["remove_positive"] == ["soft face"]
    assert result.applied_patch["add_negative"] == ["blurred eyes"]


def test_apply_prompt_patch_ignores_lora_embedding_and_weight_tokens() -> None:
    result = apply_prompt_patch(
        "portrait woman",
        "bad anatomy",
        {
            "add_positive": ["<lora:detail:1>", "embedding:foo", "(sharp eyes:1.2)", "clear irises"],
            "remove_negative": ["(bad anatomy:1.2)", "<lora:neg:1>", "embedding:badneg", "bad anatomy"],
        },
    )

    assert result.positive.patched == "portrait woman, clear irises"
    assert result.negative.patched == ""
    assert "<lora:detail:1>" in result.ignored_patch["positive"]
    assert "embedding:foo" in result.ignored_patch["positive"]
    assert "(sharp eyes:1.2)" in result.ignored_patch["positive"]
    assert "(bad anatomy:1.2)" in result.ignored_patch["negative"]
    assert "<lora:neg:1>" in result.ignored_patch["negative"]
    assert "embedding:badneg" in result.ignored_patch["negative"]
