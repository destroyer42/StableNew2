"""Test that matrix base_prompt replaces pack prompt when enabled."""

from src.utils.randomizer import PromptRandomizer


def test_matrix_base_prompt_replaces_pack_prompt():
    """When matrix is enabled with base_prompt, it should replace the input prompt."""
    config = {
        "enabled": True,
        "matrix": {
            "enabled": True,
            "mode": "fanout",
            "limit": 8,
            "slots": [
                {"name": "job", "values": ["druid", "enchantress"]},
            ],
            "base_prompt": "a female [[job]] portrait",
        },
    }

    randomizer = PromptRandomizer(config)

    # Input is knight prompt (from pack), but should be replaced by base_prompt
    pack_prompt = "close-up portrait of a noble medieval knight in ornate armor"
    variants = randomizer.generate(pack_prompt)

    # Should generate 2 variants from base_prompt, NOT use the knight prompt
    assert len(variants) == 2

    texts = [v.text for v in variants]
    assert "a female druid portrait" in texts
    assert "a female enchantress portrait" in texts

    # Should NOT contain any knight-related text
    assert not any("knight" in v.text for v in variants)
    assert not any("armor" in v.text for v in variants)


def test_matrix_without_base_prompt_uses_pack_prompt():
    """When matrix is enabled but no base_prompt, use pack prompt's [[slot]] tokens."""
    config = {
        "enabled": True,
        "matrix": {
            "enabled": True,
            "mode": "fanout",
            "limit": 8,
            "slots": [
                {"name": "mood", "values": ["happy", "sad"]},
            ],
            "base_prompt": "",  # Empty base_prompt
        },
    }

    randomizer = PromptRandomizer(config)

    # Pack prompt has [[mood]] token
    pack_prompt = "a [[mood]] person"
    variants = randomizer.generate(pack_prompt)

    # Should generate 2 variants from pack prompt
    assert len(variants) == 2

    texts = [v.text for v in variants]
    assert "a happy person" in texts
    assert "a sad person" in texts


def test_matrix_base_prompt_with_undefined_slots():
    """Matrix base_prompt with undefined slot references leaves them as literals."""
    config = {
        "enabled": True,
        "matrix": {
            "enabled": True,
            "mode": "fanout",
            "limit": 8,
            "slots": [
                {"name": "job", "values": ["druid", "enchantress"]},
                # Missing: clothes, style
            ],
            "base_prompt": "a female [[job]] wearing [[clothes]] and looking [[style]]",
        },
    }

    randomizer = PromptRandomizer(config)
    pack_prompt = "ignored knight prompt"
    variants = randomizer.generate(pack_prompt)

    # Should generate 2 variants (only job slot defined)
    assert len(variants) == 2

    texts = [v.text for v in variants]
    # Undefined slots remain as literal text
    assert "a female druid wearing [[clothes]] and looking [[style]]" in texts
    assert "a female enchantress wearing [[clothes]] and looking [[style]]" in texts


def test_matrix_base_prompt_complete_slots():
    """Matrix with all slots defined generates all combos."""
    config = {
        "enabled": True,
        "matrix": {
            "enabled": True,
            "mode": "fanout",
            "limit": 8,
            "slots": [
                {"name": "job", "values": ["druid", "enchantress"]},
                {"name": "clothes", "values": ["armor", "robes"]},
                {"name": "style", "values": ["fierce", "serene"]},
            ],
            "base_prompt": "a female [[job]] wearing [[clothes]] and looking [[style]]",
        },
    }

    randomizer = PromptRandomizer(config)
    pack_prompt = "ignored"
    variants = randomizer.generate(pack_prompt)

    # 2 jobs × 2 clothes × 2 styles = 8 total
    assert len(variants) == 8

    texts = [v.text for v in variants]
    assert "a female druid wearing armor and looking fierce" in texts
    assert "a female druid wearing armor and looking serene" in texts
    assert "a female druid wearing robes and looking fierce" in texts
    assert "a female druid wearing robes and looking serene" in texts
    assert "a female enchantress wearing armor and looking fierce" in texts
    assert "a female enchantress wearing armor and looking serene" in texts
    assert "a female enchantress wearing robes and looking fierce" in texts
    assert "a female enchantress wearing robes and looking serene" in texts

    # No undefined slots should remain
    assert not any("[[" in v.text for v in variants)


def test_matrix_disabled_uses_pack_prompt():
    """When matrix is disabled, pack prompt is used as-is."""
    config = {
        "enabled": True,
        "matrix": {
            "enabled": False,  # Disabled
            "base_prompt": "should be ignored",
            "slots": [],
        },
    }

    randomizer = PromptRandomizer(config)
    pack_prompt = "knight in armor"
    variants = randomizer.generate(pack_prompt)

    assert len(variants) == 1
    assert variants[0].text == "knight in armor"
