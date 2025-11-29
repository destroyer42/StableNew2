from pathlib import Path

from src.utils.prompt_packs import PromptPackInfo, discover_packs


def test_discover_packs_returns_sorted_descriptors(tmp_path):
    pack_two = tmp_path / "beta.txt"
    pack_two.write_text("prompt")
    pack_one = tmp_path / "alpha.tsv"
    pack_one.write_text("hello\tneg")

    packs = discover_packs(tmp_path)

    assert [p.name for p in packs] == ["alpha", "beta"]
    assert packs[0].path == pack_one
    assert isinstance(packs[0], PromptPackInfo)


def test_discover_packs_ensures_directory(tmp_path):
    target = tmp_path / "nested" / "packs"
    assert not target.exists()

    packs = discover_packs(target)

    assert packs == []
    assert target.exists()
