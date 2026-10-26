"""Textual-inversion invocation: StableNew's authoring notation is not the backend's invocation (EMBED-700).

The pinned Forge Neo (``d70373eb``) removes every ``<name:args>`` tag from the positive prompt before tokenization
(``modules/extra_networks.py``: ``re_extra_net``) and only ``lora`` is a registered extra network, so an
``<embedding:Name>`` tag never reaches the text encoder. A textual inversion is invoked by its filename token and
weighted with ordinary prompt attention, ``(Name:w)``. These tests keep that contract explicit and deterministic
without a backend.
"""

from __future__ import annotations

import re

import pytest

from src.pipeline.prompt_pack_parser import PackRow
from src.pipeline.resolution_layer import render_pack_intent, resolve_pack_intent
from src.prompting.prompt_optimizer_config import PromptOptimizerConfig
from src.prompting.prompt_optimizer_service import PromptOptimizerService
from src.utils.embedding_prompt_utils import (
    extract_embedding_entries,
    is_invocable_embedding_name,
    render_embedding_invocation,
    render_embedding_reference,
)

#: The pinned backend's extra-network tag grammar (``modules/extra_networks.py`` at d70373eb).
FORGE_EXTRA_NETWORK_TAG = re.compile(r"<(\w+):([^>]+)>")
FORGE_REGISTERED_EXTRA_NETWORKS = {"lora"}


def forge_prompt_after_extra_network_parsing(prompt: str) -> str:
    """What the encoder receives: every tag is removed, registered or not (unknown ones are only logged)."""
    return FORGE_EXTRA_NETWORK_TAG.sub("", prompt)


def test_authoring_notation_is_removed_before_the_encoder_but_invocation_survives():
    reference = render_embedding_reference("PortraitStyle", 1.0)
    invocation = render_embedding_invocation("PortraitStyle", 1.0)
    assert reference == "<embedding:PortraitStyle>"
    assert "embedding" not in FORGE_REGISTERED_EXTRA_NETWORKS
    assert "PortraitStyle" not in forge_prompt_after_extra_network_parsing(f"knight, {reference}")
    assert "PortraitStyle" in forge_prompt_after_extra_network_parsing(f"knight, {invocation}")


@pytest.mark.parametrize(
    ("weight", "expected"),
    [
        (1.0, "PortraitStyle"),
        (0.6, "(PortraitStyle:0.6)"),
        (1.3, "(PortraitStyle:1.3)"),
        (1.25, "(PortraitStyle:1.25)"),
    ],
)
def test_invocation_is_the_bare_name_with_attention_weighting(weight, expected):
    assert render_embedding_invocation("PortraitStyle", weight) == expected
    assert render_embedding_invocation("  ", 1.0) == ""


@pytest.mark.parametrize("name", ["Style", "style_v2", "My Style", "style-1.5", "Ünicode"])
def test_names_that_can_be_invoked_by_token(name):
    assert is_invocable_embedding_name(name)


@pytest.mark.parametrize(
    "name", ["", " ", " pad", "a:b", "a,b", "a(b)", "a[b]", "<a>", "a|b", "a\\b", "a\nb"]
)
def test_names_that_prompt_syntax_would_split_cannot_be_invoked(name):
    assert not is_invocable_embedding_name(name)


def test_compiled_prompts_use_invocation_for_both_channels_and_keep_other_tokens():
    row = PackRow(
        embeddings=(("styleA", 0.8), ("styleB", 1.0)),
        quality_line="cinematic quality",
        subject_template="a knight",
        lora_tags=(("detail", 0.6),),
        negative_embeddings=(("bad_hands", 1.2),),
        negative_phrases=("blurry",),
    )
    rendered = render_pack_intent(
        resolve_pack_intent(pack_row=row, pack_negative="", apply_global_negative=False)
    )
    assert rendered.positive.startswith("(styleA:0.8) styleB")
    assert rendered.positive.endswith("<lora:detail:0.6>")
    assert rendered.negative == "(bad_hands:1.2), blurry"
    assert "<embedding:" not in rendered.positive + rendered.negative
    # The structured fields remain the identity; only the rendered text changed.
    assert rendered.positive_embeddings == (("styleA", 0.8), ("styleB", 1.0))


def test_pack_storage_notation_round_trips_unchanged():
    """PromptPack TXT/JSON authoring stays ``<embedding:...>``: it is a parseable notation, not the invocation."""
    text = (
        render_embedding_reference("styleA", 0.8) + " " + render_embedding_reference("styleB", 1.0)
    )
    assert text == "(<embedding:styleA>:0.8) <embedding:styleB>"
    assert extract_embedding_entries(text) == [("styleA", 0.8), ("styleB", 1.0)]


@pytest.mark.parametrize("token", ["PortraitStyle", "(PortraitStyle:1.3)"])
def test_optimizer_keeps_a_rendered_invocation_exactly_once(token):
    """Characterization: the optimizer treats the invocation as prose but must not drop or duplicate it."""
    prompt = f"{token}, knight, detailed armor"
    result = (
        PromptOptimizerService(PromptOptimizerConfig())
        .optimize_prompts(prompt, "", pipeline_name="txt2img")
        .positive
    )
    assert result.optimized_prompt.count(token) == 1
