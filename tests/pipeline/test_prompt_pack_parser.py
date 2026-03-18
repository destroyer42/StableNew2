from src.pipeline.prompt_pack_parser import PackRow, parse_prompt_pack_text


def _sample_block() -> str:
    return """<embedding:alpha> <embedding:beta>
(masterpiece) silky skin, sharp focus
hero with glowing sword over [[environment]]
<lora:detailMaster:0.7> <lora:antiAlias:0.4>
neg: <embedding:negative_hands> blurry, artifacts
neg: low quality, deformed"""


def test_parse_single_block() -> None:
    rows = parse_prompt_pack_text(_sample_block())
    assert len(rows) == 1
    row = rows[0]
    assert isinstance(row, PackRow)
    assert row.embeddings == (("alpha", 1.0), ("beta", 1.0))
    assert row.quality_line.startswith("(masterpiece)")
    assert "[[environment]]" in row.subject_template
    assert row.lora_tags[0][0] == "detailMaster"
    assert row.lora_tags[0][1] == 0.7
    assert any(name == "negative_hands" for name, _ in row.negative_embeddings)
    assert "blurry" in ",".join(row.negative_phrases)


def test_parse_three_line_block_keeps_loras_and_negative_embeddings_separate() -> None:
    content = """gorgeous portrait, cinematic lighting
<lora:detailMaster:0.7> <lora:antiAlias:0.4>
neg: <embedding:negative_hands> blurry, artifacts"""

    rows = parse_prompt_pack_text(content)

    assert len(rows) == 1
    row = rows[0]
    assert row.quality_line == "gorgeous portrait, cinematic lighting"
    assert row.subject_template == ""
    assert row.lora_tags == (("detailMaster", 0.7), ("antiAlias", 0.4))
    assert row.negative_embeddings == (("negative_hands", 1.0),)
    assert row.negative_phrases == ("blurry", "artifacts")


def test_parse_weighted_embeddings() -> None:
    """Weighted embedding tokens round-trip through the parser preserving weights."""
    content = """(<embedding:styleA>:0.8) <embedding:styleB>
cinematic portrait
neg: (<embedding:bad_hands>:1.2) blurry"""

    rows = parse_prompt_pack_text(content)

    assert len(rows) == 1
    row = rows[0]
    assert ("styleA", 0.8) in row.embeddings
    assert ("styleB", 1.0) in row.embeddings
    assert ("bad_hands", 1.2) in row.negative_embeddings
    assert "blurry" in row.negative_phrases
