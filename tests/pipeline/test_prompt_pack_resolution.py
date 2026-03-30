from src.pipeline.prompt_pack_parser import PackRow
from src.pipeline.resolution_layer import PromptResolution, UnifiedPromptResolver


def test_resolve_from_pack_row_substitutes_matrix_tokens() -> None:
    row = PackRow(
        embeddings=(("alpha", 1.0), ("beta", 1.0)),
        quality_line="high quality light",
        subject_template="knight guarding [[environment]]",
        lora_tags=(("detail", 0.6),),
        negative_embeddings=(("neg_hands", 1.0),),
        negative_phrases=("blurry",),
    )
    resolver = UnifiedPromptResolver(max_preview_length=200)
    result = resolver.resolve_from_pack(
        pack_row=row,
        matrix_slot_values={"environment": "castle"},
        pack_negative="pack noise",
        global_negative="global hush",
    )
    assert isinstance(result, PromptResolution)
    assert "castle" in result.positive
    assert "global hush" in result.negative
    assert result.positive_embeddings == (("alpha", 1.0), ("beta", 1.0))
    assert result.negative_embeddings == (("neg_hands", 1.0),)
    assert ("detail", 0.6) in result.lora_tags
    assert result.positive.endswith("<lora:detail:0.6>")
    assert result.negative.startswith("global hush, pack noise, <embedding:neg_hands>")


def test_resolve_from_pack_row_weighted_embeddings_render_in_prompt() -> None:
    """Weighted embeddings should appear as (<embedding:name>:weight) in the final prompt."""
    row = PackRow(
        embeddings=(("styleA", 0.8), ("styleB", 1.0)),
        quality_line="cinematic quality",
        subject_template="",
        lora_tags=(),
        negative_embeddings=(("bad_hands", 1.2),),
        negative_phrases=(),
    )
    resolver = UnifiedPromptResolver(max_preview_length=200)
    result = resolver.resolve_from_pack(
        pack_row=row,
        pack_negative="",
        global_negative="",
    )
    assert "(<embedding:styleA>:0.8)" in result.positive
    assert "<embedding:styleB>" in result.positive
    assert "(<embedding:bad_hands>:1.2)" in result.negative


def test_resolve_from_pack_row_accepts_hyphenated_slot_aliases() -> None:
    row = PackRow(
        embeddings=(),
        quality_line="",
        subject_template="athletic [[hair-color]] haired [[eye_color]] eyed subject",
        lora_tags=(),
        negative_embeddings=(),
        negative_phrases=(),
    )
    resolver = UnifiedPromptResolver(max_preview_length=200)
    result = resolver.resolve_from_pack(
        pack_row=row,
        matrix_slot_values={"haircolor": "auburn", "eyecolor": "green"},
        pack_negative="",
        global_negative="",
    )

    assert "[[" not in result.positive
    assert "auburn haired" in result.positive
    assert "green eyed" in result.positive


def test_resolve_from_pack_row_prepends_actor_tokens_and_actor_loras() -> None:
    row = PackRow(
        embeddings=(),
        quality_line="cinematic quality",
        subject_template="portrait on a rooftop",
        lora_tags=(("shared_style", 0.4), ("pack_style", 0.7)),
        negative_embeddings=(),
        negative_phrases=(),
    )
    resolver = UnifiedPromptResolver(max_preview_length=200)
    result = resolver.resolve_from_pack(
        pack_row=row,
        actor_resolutions=[
            {
                "name": "Ada",
                "trigger_phrase": "ada person",
                "lora_name": "shared_style",
                "weight": 0.9,
            },
            {
                "name": "Bran",
                "trigger_phrase": "bran ranger",
                "lora_name": "bran_lora",
                "weight": 0.8,
            },
        ],
        pack_negative="",
        global_negative="",
    )

    assert "ada person, bran ranger" in result.positive
    assert result.lora_tags == (
        ("shared_style", 0.9),
        ("bran_lora", 0.8),
        ("pack_style", 0.7),
    )
    assert result.positive.endswith(
        "<lora:shared_style:0.9> <lora:bran_lora:0.8> <lora:pack_style:0.7>"
    )


def test_resolve_from_pack_row_appends_style_trigger_and_style_lora_after_pack_loras() -> None:
    row = PackRow(
        embeddings=(),
        quality_line="cinematic quality",
        subject_template="portrait on a rooftop",
        lora_tags=(("pack_style", 0.7),),
        negative_embeddings=(),
        negative_phrases=(),
    )
    resolver = UnifiedPromptResolver(max_preview_length=200)
    result = resolver.resolve_from_pack(
        pack_row=row,
        actor_resolutions=[
            {
                "name": "Ada",
                "trigger_phrase": "ada person",
                "lora_name": "ada_lora",
                "weight": 0.9,
            }
        ],
        style_lora={
            "style_id": "cinematic_grit",
            "trigger_phrase": "cinematic grit lighting",
            "lora_name": "style_cinematic_grit",
            "weight": 0.65,
            "applied": True,
        },
        pack_negative="",
        global_negative="",
    )

    assert "ada person, cinematic grit lighting" in result.positive
    assert result.lora_tags == (
        ("ada_lora", 0.9),
        ("pack_style", 0.7),
        ("style_cinematic_grit", 0.65),
    )
    assert result.positive.endswith(
        "<lora:ada_lora:0.9> <lora:pack_style:0.7> <lora:style_cinematic_grit:0.65>"
    )
