from src.pipeline.prompt_pack_parser import PackRow
from src.pipeline.resolution_layer import PromptResolution, UnifiedPromptResolver


def test_resolve_from_pack_row_substitutes_matrix_tokens() -> None:
    row = PackRow(
        embeddings=("alpha", "beta"),
        quality_line="high quality light",
        subject_template="knight guarding [[environment]]",
        lora_tags=(("detail", 0.6),),
        negative_embeddings=("neg_hands",),
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
    assert result.positive_embeddings == ("alpha", "beta")
    assert result.negative_embeddings == ("neg_hands",)
    assert ("detail", 0.6) in result.lora_tags
