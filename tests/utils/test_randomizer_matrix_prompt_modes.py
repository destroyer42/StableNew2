"""Test matrix prompt_mode: replace, append, prepend."""

from src.utils.randomizer import PromptRandomizer


def test_matrix_prompt_mode_replace():
    """Default 'replace' mode: base_prompt replaces pack prompt."""
    config = {
        "enabled": True,
        "matrix": {
            "enabled": True,
            "mode": "fanout",
            "prompt_mode": "replace",
            "slots": [
                {"name": "job", "values": ["warrior", "mage"]},
            ],
            "base_prompt": "a [[job]] hero",
        },
    }

    randomizer = PromptRandomizer(config)
    pack_prompt = "detailed portrait in armor"
    variants = randomizer.generate(pack_prompt)

    assert len(variants) == 2
    texts = [v.text for v in variants]

    # Pack prompt should be completely replaced
    assert "a warrior hero" in texts
    assert "a mage hero" in texts
    assert not any("detailed" in t for t in texts)
    assert not any("portrait" in t for t in texts)


def test_matrix_prompt_mode_append():
    """'append' mode: base_prompt is appended to pack prompt."""
    config = {
        "enabled": True,
        "matrix": {
            "enabled": True,
            "mode": "fanout",
            "prompt_mode": "append",
            "slots": [
                {"name": "job", "values": ["warrior", "mage"]},
            ],
            "base_prompt": "a [[job]] hero",
        },
    }

    randomizer = PromptRandomizer(config)
    pack_prompt = "detailed portrait in armor"
    variants = randomizer.generate(pack_prompt)

    assert len(variants) == 2
    texts = [v.text for v in variants]

    # Pack prompt should come first, then matrix expansion
    assert "detailed portrait in armor, a warrior hero" in texts
    assert "detailed portrait in armor, a mage hero" in texts


def test_matrix_prompt_mode_prepend():
    """'prepend' mode: base_prompt is prepended before pack prompt."""
    config = {
        "enabled": True,
        "matrix": {
            "enabled": True,
            "mode": "fanout",
            "prompt_mode": "prepend",
            "slots": [
                {"name": "job", "values": ["warrior", "mage"]},
            ],
            "base_prompt": "a [[job]] hero",
        },
    }

    randomizer = PromptRandomizer(config)
    pack_prompt = "detailed portrait in armor"
    variants = randomizer.generate(pack_prompt)

    assert len(variants) == 2
    texts = [v.text for v in variants]

    # Matrix expansion should come first, then pack prompt
    assert "a warrior hero, detailed portrait in armor" in texts
    assert "a mage hero, detailed portrait in armor" in texts


def test_matrix_prompt_mode_default_is_replace():
    """If prompt_mode is omitted, default to 'replace' for backward compatibility."""
    config = {
        "enabled": True,
        "matrix": {
            "enabled": True,
            "mode": "fanout",
            # prompt_mode omitted - should default to "replace"
            "slots": [
                {"name": "mood", "values": ["happy"]},
            ],
            "base_prompt": "a [[mood]] person",
        },
    }

    randomizer = PromptRandomizer(config)
    pack_prompt = "knight in armor"
    variants = randomizer.generate(pack_prompt)

    assert len(variants) == 1
    # Should replace, not append
    assert variants[0].text == "a happy person"
    assert "knight" not in variants[0].text


def test_matrix_append_with_multiple_slots():
    """Append mode with multiple matrix slots."""
    config = {
        "enabled": True,
        "matrix": {
            "enabled": True,
            "mode": "fanout",
            "prompt_mode": "append",
            "limit": 4,
            "slots": [
                {"name": "job", "values": ["druid", "enchantress"]},
                {"name": "style", "values": ["fierce", "serene"]},
            ],
            "base_prompt": "[[job]] looking [[style]]",
        },
    }

    randomizer = PromptRandomizer(config)
    pack_prompt = "portrait of a hero"
    variants = randomizer.generate(pack_prompt)

    # 2 jobs × 2 styles = 4 total
    assert len(variants) == 4

    texts = [v.text for v in variants]

    # All should start with pack prompt
    assert all(t.startswith("portrait of a hero, ") for t in texts)

    # All combos present
    assert "portrait of a hero, druid looking fierce" in texts
    assert "portrait of a hero, druid looking serene" in texts
    assert "portrait of a hero, enchantress looking fierce" in texts
    assert "portrait of a hero, enchantress looking serene" in texts


def test_matrix_prepend_with_multiple_slots():
    """Prepend mode with multiple matrix slots."""
    config = {
        "enabled": True,
        "matrix": {
            "enabled": True,
            "mode": "fanout",
            "prompt_mode": "prepend",
            "limit": 4,
            "slots": [
                {"name": "job", "values": ["druid", "enchantress"]},
                {"name": "style", "values": ["fierce", "serene"]},
            ],
            "base_prompt": "[[job]] looking [[style]]",
        },
    }

    randomizer = PromptRandomizer(config)
    pack_prompt = "portrait of a hero"
    variants = randomizer.generate(pack_prompt)

    # 2 jobs × 2 styles = 4 total
    assert len(variants) == 4

    texts = [v.text for v in variants]

    # All should end with pack prompt
    assert all(t.endswith(", portrait of a hero") for t in texts)

    # All combos present
    assert "druid looking fierce, portrait of a hero" in texts
    assert "druid looking serene, portrait of a hero" in texts
    assert "enchantress looking fierce, portrait of a hero" in texts
    assert "enchantress looking serene, portrait of a hero" in texts


def test_matrix_no_base_prompt_ignores_prompt_mode():
    """If base_prompt is empty, prompt_mode has no effect."""
    config = {
        "enabled": True,
        "matrix": {
            "enabled": True,
            "prompt_mode": "append",
            "base_prompt": "",  # Empty
            "slots": [],
        },
    }

    randomizer = PromptRandomizer(config)
    pack_prompt = "knight in armor"
    variants = randomizer.generate(pack_prompt)

    # Should just use pack prompt as-is
    assert len(variants) == 1
    assert variants[0].text == "knight in armor"


def test_matrix_append_real_world_example():
    """Real-world example: base pack prompt + matrix variations."""
    config = {
        "enabled": True,
        "matrix": {
            "enabled": True,
            "mode": "fanout",
            "prompt_mode": "append",
            "limit": 8,
            "slots": [
                {"name": "lighting", "values": ["soft rim light", "dramatic shadows"]},
                {"name": "mood", "values": ["determined", "weary"]},
            ],
            "base_prompt": "[[lighting]], [[mood]] expression",
        },
    }

    randomizer = PromptRandomizer(config)
    pack_prompt = "close-up portrait of a medieval knight in ornate armor"
    variants = randomizer.generate(pack_prompt)

    # 2 lighting × 2 mood = 4 total
    assert len(variants) == 4

    texts = [v.text for v in variants]

    # All should preserve the original knight description
    assert all("close-up portrait of a medieval knight in ornate armor" in t for t in texts)

    # All should have matrix variations appended
    expected_suffixes = [
        "soft rim light, determined expression",
        "soft rim light, weary expression",
        "dramatic shadows, determined expression",
        "dramatic shadows, weary expression",
    ]

    for suffix in expected_suffixes:
        full_text = f"close-up portrait of a medieval knight in ornate armor, {suffix}"
        assert full_text in texts, f"Missing: {full_text}"
