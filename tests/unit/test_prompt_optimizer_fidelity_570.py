"""Token semantics, rather than cosmetic output, are the optimizer contract."""

import pytest

from src.prompting.prompt_normalizer import build_dedupe_key
from src.prompting.prompt_optimizer_config import PromptOptimizerConfig
from src.prompting.prompt_optimizer_service import PromptOptimizerService
from src.prompting.prompt_splitter import lora_token_positions


@pytest.mark.parametrize(
    "weighted",
    ["(beautiful woman)", "[beautiful woman]", "(beautiful woman:.8)", "((beautiful woman))"],
)
def test_implicit_and_explicit_weights_are_not_duplicates_of_plain_text(weighted):
    result = (
        PromptOptimizerService(PromptOptimizerConfig())
        .optimize_prompts(f"beautiful woman, {weighted}", "", pipeline_name="txt2img")
        .positive
    )
    assert weighted in result.optimized_prompt
    assert result.dropped_duplicates == []


@pytest.mark.parametrize("token", ["<lora:Detail:0.70>", "<embedding:face>", "<legacy_face>"])
def test_network_reference_inside_attention_group_keeps_the_group_intact(token):
    authored = f"(beautiful woman {token}:1.2)"
    result = (
        PromptOptimizerService(PromptOptimizerConfig())
        .optimize_prompts(authored, "", pipeline_name="txt2img")
        .positive
    )
    assert result.optimized_prompt == authored
    assert result.optimized_prompt.count(token) == 1


@pytest.mark.parametrize("polarity", ["positive", "negative"])
@pytest.mark.parametrize(
    "group",
    [
        "((beautiful woman {token}:1.20))",
        "[beautiful woman {token}]",
        "({token})",
        "(({token}:1.2))",
        "[{token}]",
        "(beautiful woman, ({token}:0.8):1.2)",
        "beautiful woman ({token}) under rain",
    ],
)
@pytest.mark.parametrize("token", ["<lora:Detail:0.70>", "<embedding:face>", "<legacy_face>"])
def test_nested_and_token_only_groups_are_preserved_without_empty_remnants(polarity, group, token):
    authored = group.format(token=token)
    result = PromptOptimizerService(PromptOptimizerConfig()).optimize_prompts(
        authored if polarity == "positive" else "",
        authored if polarity == "negative" else "",
        pipeline_name="txt2img",
    )
    channel = getattr(result, polarity)
    assert channel.optimized_prompt == authored
    assert channel.optimized_prompt.count(token) == 1
    assert (
        getattr(result, "negative" if polarity == "positive" else "positive").optimized_prompt == ""
    )


def test_weighted_expressions_keep_distinct_identity_and_significant_order():
    expressions = [
        "beautiful woman",
        "(beautiful woman)",
        "[beautiful woman]",
        "((beautiful woman))",
        "(beautiful woman:1.1)",
        "(beautiful woman:1.10)",
        "(beautiful woman:1.2)",
        "[red:blue:0.5]",
        "[blue:red:0.5]",
        "(red AND blue:1.2)",
        "(blue AND red:1.2)",
    ]
    assert len({build_dedupe_key(value) for value in expressions}) == len(expressions)
    text = ", ".join(expressions)
    result = PromptOptimizerService(PromptOptimizerConfig()).optimize_prompts(text, "")
    assert result.positive.optimized_prompt == text
    assert result.positive.dropped_duplicates == []


@pytest.mark.parametrize("preserve_lora", [True, False])
@pytest.mark.parametrize("preserve_unknown", [True, False])
def test_mixed_tokens_keep_verbatim_weights_and_accepted_deduplication(
    preserve_lora, preserve_unknown
):
    service = PromptOptimizerService(
        PromptOptimizerConfig(
            preserve_lora_relative_order=preserve_lora,
            preserve_unknown_order=preserve_unknown,
        )
    )
    tags = ["<lora:Detail:0.70>", "<lora:Detail:0.8>", "<lora:Other:-0.2>"]
    positive = (
        f"masterpiece, beautiful woman {tags[0]}{tags[1]}, crystal sigil, {tags[2]}, {tags[0]}"
    )
    negative = "(<embedding:avoid>:0.70), (<embedding:avoid>:0.8), bad anatomy, bad anatomy, blurry"
    result = service.optimize_prompts(positive, negative)
    assert [token for token, _ in lora_token_positions(result.positive.optimized_prompt)] == tags
    assert result.positive.dropped_duplicates == [tags[0]]
    assert result.negative.dropped_duplicates == ["bad anatomy"]
    assert result.negative.optimized_prompt.startswith(
        "(<embedding:avoid>:0.70), (<embedding:avoid>:0.8)"
    )
    assert "<lora:" not in result.negative.optimized_prompt
    assert "<embedding:avoid>" not in result.positive.optimized_prompt
    if not preserve_lora and not preserve_unknown:
        assert result.positive.optimized_prompt.endswith(", ".join(tags))


def test_historical_anchor_boost_fields_have_no_effect():
    text = "masterpiece, beautiful woman, garden, standing, 85mm lens, cinematic lighting, photorealistic, crystal sigil"
    off = PromptOptimizerService(PromptOptimizerConfig()).optimize_prompts(text, "")
    on = PromptOptimizerService(
        PromptOptimizerConfig(
            allow_subject_anchor_boost=True,
            subject_anchor_boost_min_chunk_count=1,
        )
    ).optimize_prompts(text, "")
    assert off == on
