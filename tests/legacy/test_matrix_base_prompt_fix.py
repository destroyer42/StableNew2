"""Integration test demonstrating matrix base_prompt fix for issue reported in run_20251111_102316."""

from src.utils.randomizer import PromptRandomizer


def test_heroes_portrait_matrix_config():
    """
    Reproduce the exact config from output/run_20251111_102316/Test_Hero_Portrait_pack/config.json
    to verify that base_prompt now works correctly.

    BEFORE FIX: Matrix was enabled but base_prompt was ignored.
    Pack prompt ("close-up portrait of a noble medieval knight...") was used as-is.
    No matrix expansion occurred.

    AFTER FIX: Matrix base_prompt replaces pack prompt.
    Pack prompt is ignored when matrix is enabled with base_prompt.
    Matrix slots expand correctly.
    """
    # Exact config from the user's failed run
    config = {
        "enabled": True,
        "matrix": {
            "enabled": True,
            "mode": "fanout",
            "limit": 8,
            "slots": [{"name": "job", "values": ["druid", "enchantress"]}],
            "base_prompt": "a female [[job]] wearing [[clothes]] and looking [[style]]",
        },
    }

    randomizer = PromptRandomizer(config)

    # This was the pack prompt that was incorrectly used
    pack_prompt = 'close-up portrait of a noble medieval knight in ornate armor, scarred but determined expression, soft rim light, detailed metal texture, cinematic tone"'

    variants = randomizer.generate(pack_prompt)

    # AFTER FIX: Should get 2 variants from base_prompt (only job slot defined)
    # NOT the knight prompt
    assert len(variants) == 2, f"Expected 2 variants, got {len(variants)}"

    texts = [v.text for v in variants]

    # Verify base_prompt was used (with undefined slots as literals)
    assert "a female druid wearing [[clothes]] and looking [[style]]" in texts
    assert "a female enchantress wearing [[clothes]] and looking [[style]]" in texts

    # Verify pack prompt was NOT used
    assert not any(
        "knight" in v.text for v in variants
    ), "Pack prompt should be replaced by base_prompt"
    assert not any(
        "armor" in v.text for v in variants
    ), "Pack prompt should be replaced by base_prompt"

    # Verify labels track matrix substitutions
    labels = [v.label for v in variants]
    assert any(
        "job" in (label or "") for label in labels
    ), "Labels should track matrix slot replacements"

    print("✅ Matrix base_prompt now correctly replaces pack prompt!")
    print("✅ Generated variants:")
    for i, variant in enumerate(variants, 1):
        print(f"   {i}. {variant.text}")
        print(f"      Label: {variant.label}")


def test_corrected_heroes_config_all_slots():
    """
    Test the CORRECTED config with all 3 slots defined.
    This is what the user should use to get proper matrix expansion.
    """
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
    pack_prompt = "ignored knight prompt"
    variants = randomizer.generate(pack_prompt)

    # 2 jobs × 2 clothes × 2 styles = 8 total
    assert len(variants) == 8

    texts = [v.text for v in variants]

    # Verify all combos generated
    expected_combos = [
        "a female druid wearing armor and looking fierce",
        "a female druid wearing armor and looking serene",
        "a female druid wearing robes and looking fierce",
        "a female druid wearing robes and looking serene",
        "a female enchantress wearing armor and looking fierce",
        "a female enchantress wearing armor and looking serene",
        "a female enchantress wearing robes and looking fierce",
        "a female enchantress wearing robes and looking serene",
    ]

    for expected in expected_combos:
        assert expected in texts, f"Missing expected combo: {expected}"

    # No undefined slots should remain
    assert not any("[[" in text for text in texts), "All slots should be replaced"

    print("✅ Corrected config with all slots generates all 8 combos!")
    print("✅ Generated variants:")
    for i, variant in enumerate(variants, 1):
        print(f"   {i}. {variant.text}")


if __name__ == "__main__":
    test_heroes_portrait_matrix_config()
    print()
    test_corrected_heroes_config_all_slots()
