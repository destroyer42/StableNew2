"""Real-world example demonstrating matrix prompt_mode usage."""

from src.utils.randomizer import PromptRandomizer


def test_append_mode_hero_portraits():
    """
    Real use case: User has detailed pack prompts describing heroes,
    and wants to add matrix variations for lighting/mood/angle without
    losing the original detailed descriptions.
    """
    config = {
        "enabled": True,
        "matrix": {
            "enabled": True,
            "mode": "fanout",
            "prompt_mode": "append",  # Keep original prompt, add variations
            "limit": 12,
            "slots": [
                {
                    "name": "lighting",
                    "values": ["soft rim light", "dramatic shadows", "golden hour glow"],
                },
                {"name": "angle", "values": ["close-up", "medium shot"]},
            ],
            "base_prompt": "[[lighting]], [[angle]]",
        },
    }

    randomizer = PromptRandomizer(config)

    # Detailed pack prompt describing a specific character
    pack_prompts = [
        "portrait of a noble medieval knight in ornate armor, scarred but determined expression, detailed metal texture, cinematic tone",
        "portrait of a wise elven mage with flowing robes, arcane symbols glowing, ethereal atmosphere",
    ]

    all_variants = []
    for pack_prompt in pack_prompts:
        variants = randomizer.generate(pack_prompt)
        all_variants.extend(variants)

        # Each pack prompt should generate 3 lighting × 2 angles = 6 variants
        assert len(variants) == 6

        # All should preserve the original pack prompt
        assert all(pack_prompt in v.text for v in variants)

        # All should have matrix variations appended
        for v in variants:
            # Should contain both pack prompt and matrix expansions
            assert pack_prompt in v.text
            assert ", " in v.text  # Separator between pack and matrix
            assert any(
                lighting in v.text
                for lighting in ["soft rim light", "dramatic shadows", "golden hour glow"]
            )
            assert any(angle in v.text for angle in ["close-up", "medium shot"])

    # Total: 2 prompts × 6 variants each = 12 variants
    assert len(all_variants) == 12

    # Example outputs to verify format
    knight_variants = [v.text for v in all_variants if "knight" in v.text]
    assert (
        "portrait of a noble medieval knight in ornate armor, scarred but determined expression, detailed metal texture, cinematic tone, soft rim light, close-up"
        in knight_variants
    )
    assert (
        "portrait of a noble medieval knight in ornate armor, scarred but determined expression, detailed metal texture, cinematic tone, dramatic shadows, medium shot"
        in knight_variants
    )

    mage_variants = [v.text for v in all_variants if "mage" in v.text]
    assert (
        "portrait of a wise elven mage with flowing robes, arcane symbols glowing, ethereal atmosphere, golden hour glow, close-up"
        in mage_variants
    )


def test_prepend_mode_style_prefix():
    """
    Use case: Add artistic style prefixes to pack prompts.
    Example: "oil painting, " + pack prompt
    """
    config = {
        "enabled": True,
        "matrix": {
            "enabled": True,
            "mode": "fanout",
            "prompt_mode": "prepend",
            "limit": 6,
            "slots": [
                {"name": "style", "values": ["oil painting", "watercolor", "digital art"]},
                {"name": "mood", "values": ["vibrant", "dark"]},
            ],
            "base_prompt": "[[style]], [[mood]]",
        },
    }

    randomizer = PromptRandomizer(config)
    pack_prompt = "portrait of a hero in armor"
    variants = randomizer.generate(pack_prompt)

    # 3 styles × 2 moods = 6 variants
    assert len(variants) == 6

    texts = [v.text for v in variants]

    # All should end with the pack prompt
    assert all(t.endswith(", portrait of a hero in armor") for t in texts)

    # All should start with style and mood
    expected = [
        "oil painting, vibrant, portrait of a hero in armor",
        "oil painting, dark, portrait of a hero in armor",
        "watercolor, vibrant, portrait of a hero in armor",
        "watercolor, dark, portrait of a hero in armor",
        "digital art, vibrant, portrait of a hero in armor",
        "digital art, dark, portrait of a hero in armor",
    ]

    for expected_text in expected:
        assert expected_text in texts


def test_replace_mode_template_workflow():
    """
    Use case: User has generic pack prompts that are just templates.
    Matrix completely replaces them with detailed expansions.
    """
    config = {
        "enabled": True,
        "matrix": {
            "enabled": True,
            "mode": "fanout",
            "prompt_mode": "replace",  # Completely replace pack prompt
            "limit": 8,
            "slots": [
                {"name": "race", "values": ["human", "elf"]},
                {"name": "job", "values": ["warrior", "mage"]},
                {"name": "gear", "values": ["armor", "robes"]},
            ],
            "base_prompt": "portrait of a [[race]] [[job]] wearing [[gear]]",
        },
    }

    randomizer = PromptRandomizer(config)

    # Pack prompt is just a placeholder/template
    pack_prompt = "hero portrait"
    variants = randomizer.generate(pack_prompt)

    # 2 races × 2 jobs × 2 gear = 8 variants
    assert len(variants) == 8

    texts = [v.text for v in variants]

    # Pack prompt should NOT appear in any variant
    assert not any("hero portrait" in t for t in texts)

    # All should be generated from matrix template
    expected = [
        "portrait of a human warrior wearing armor",
        "portrait of a human warrior wearing robes",
        "portrait of a human mage wearing armor",
        "portrait of a human mage wearing robes",
        "portrait of a elf warrior wearing armor",
        "portrait of a elf warrior wearing robes",
        "portrait of a elf mage wearing armor",
        "portrait of a elf mage wearing robes",
    ]

    for expected_text in expected:
        assert expected_text in texts


if __name__ == "__main__":
    print("Testing append mode...")
    test_append_mode_hero_portraits()
    print("✅ Append mode works!\n")

    print("Testing prepend mode...")
    test_prepend_mode_style_prefix()
    print("✅ Prepend mode works!\n")

    print("Testing replace mode...")
    test_replace_mode_template_workflow()
    print("✅ Replace mode works!\n")

    print("🎉 All real-world examples pass!")
