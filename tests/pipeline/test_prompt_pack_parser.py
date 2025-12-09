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
    assert row.embeddings == ("alpha", "beta")
    assert row.quality_line.startswith("(masterpiece)")
    assert "[[environment]]" in row.subject_template
    assert row.lora_tags[0][0] == "detailMaster"
    assert row.lora_tags[0][1] == 0.7
    assert "negative_hands" in row.negative_embeddings
    assert "blurry" in ",".join(row.negative_phrases)
