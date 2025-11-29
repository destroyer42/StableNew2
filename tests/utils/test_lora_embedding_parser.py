from src.gui.utils.lora_embedding_parser import parse_loras, parse_embeddings


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
