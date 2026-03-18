from src.gui.utils.lora_embedding_parser import parse_embeddings, parse_loras


def test_parse_loras_multiple():
    text = "A {lora:foo:0.8} prompt with {lora:bar}"
    refs = parse_loras(text)
    assert len(refs) == 2
    assert refs[0].name == "foo"
    assert refs[0].weight == 0.8
    assert refs[1].name == "bar"
    assert refs[1].weight is None


def test_parse_embeddings_multiple():
    text = "Using <embedding:styleA> and <embedding:styleB>"
    refs = parse_embeddings(text)
    assert len(refs) == 2
    assert refs[0].name == "styleA"
    assert refs[1].name == "styleB"


def test_parse_embeddings_weighted():
    """Weighted embedding syntax (<embedding:name>:weight) should parse name and weight."""
    text = "(<embedding:styleX>:0.75) <embedding:styleY>"
    refs = parse_embeddings(text)
    assert len(refs) == 2
    weighted = next(r for r in refs if r.name == "styleX")
    assert weighted.weight == 0.75
    plain = next(r for r in refs if r.name == "styleY")
    assert plain.weight is None
