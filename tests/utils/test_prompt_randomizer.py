import random

from src.utils.randomizer import PromptRandomizer


def test_prompt_sr_round_robin_reuses_indices():
    config = {
        "enabled": True,
        "prompt_sr": {
            "enabled": True,
            "mode": "round_robin",
            "rules": [
                {"search": "knight", "replacements": ["paladin", "warrior"]},
            ],
        },
    }
    randomizer = PromptRandomizer(config, rng=random.Random(42))
    first_run = randomizer.generate("a knight in armor")
    assert [variant.text for variant in first_run] == ["a paladin in armor"]

    second_run = randomizer.generate("a knight in armor")
    assert [variant.text for variant in second_run] == ["a warrior in armor"]


def test_wildcard_random_selection(monkeypatch):
    config = {
        "enabled": True,
        "wildcards": {
            "enabled": True,
            "mode": "random",
            "tokens": [{"token": "__creature__", "values": ["dragon", "phoenix"]}],
        },
    }
    rand = random.Random(0)
    randomizer = PromptRandomizer(config, rng=rand)

    outputs = []
    for _ in range(2):
        variants = randomizer.generate("a __creature__")
        assert len(variants) == 1
        outputs.append(variants[0].text)

    assert all(text in {"a dragon", "a phoenix"} for text in outputs)


def test_matrix_fanout_limit():
    config = {
        "enabled": True,
        "matrix": {
            "enabled": True,
            "mode": "fanout",
            "limit": 2,
            "slots": [
                {"name": "Style", "values": ["A", "B"]},
                {"name": "Lighting", "values": ["Day", "Night"]},
            ],
        },
    }
    randomizer = PromptRandomizer(config)
    variants = randomizer.generate("[[Style]] scene at [[Lighting]]")
    assert len(variants) == 2
    assert all("Style" in (variant.label or "") for variant in variants)


def test_matrix_rotate_advances_between_calls():
    config = {
        "enabled": True,
        "matrix": {
            "enabled": True,
            "mode": "rotate",
            "slots": [
                {"name": "Style", "values": ["A", "B"]},
            ],
        },
    }
    randomizer = PromptRandomizer(config)
    first = randomizer.generate("look [[Style]]")[0].text
    second = randomizer.generate("look [[Style]]")[0].text
    assert first == "look A"
    assert second == "look B"


def test_matrix_rotate_advances_within_single_generate_call():
    config = {
        "enabled": True,
        "prompt_sr": {
            "enabled": True,
            "mode": "fanout",
            "rules": [
                {"search": "CREATURE", "replacements": ["wolf", "lion"]},
            ],
        },
        "matrix": {
            "enabled": True,
            "mode": "rotate",
            "slots": [
                {"name": "Style", "values": ["A", "B"]},
            ],
        },
    }
    randomizer = PromptRandomizer(config)
    variants = randomizer.generate("CREATURE [[Style]]")
    assert [variant.text for variant in variants] == ["wolf A", "lion B"]


def test_randomizer_combines_all_features():
    config = {
        "enabled": True,
        "prompt_sr": {
            "enabled": True,
            "mode": "round_robin",
            "rules": [
                {"search": "hero", "replacements": ["hero", "champion"]},
            ],
        },
        "wildcards": {
            "enabled": True,
            "mode": "sequential",
            "tokens": [
                {"token": "__creature__", "values": ["dragon", "phoenix"]},
            ],
        },
        "matrix": {
            "enabled": True,
            "mode": "fanout",
            "limit": 0,
            "slots": [
                {"name": "Weather", "values": ["day", "night"]},
            ],
        },
    }
    randomizer = PromptRandomizer(config)
    variants = randomizer.generate("[[Weather]] hero vs __creature__")

    assert len(variants) == 2
    texts = {variant.text for variant in variants}
    assert texts == {"day hero vs dragon", "night hero vs dragon"}


def test_randomizer_caps_variants_when_exceeding_limit():
    config = {
        "enabled": True,
        "max_variants": 5,
        "prompt_sr": {
            "enabled": True,
            "mode": "round_robin",
            "rules": [
                {"search": "hero", "replacements": ["hero", "champion", "guardian"]},
            ],
        },
        "wildcards": {
            "enabled": True,
            "mode": "random",
            "tokens": [{"token": "__mood__", "values": ["bold", "calm", "fierce"]}],
        },
        "matrix": {
            "enabled": True,
            "mode": "fanout",
            "limit": 0,
            "slots": [
                {"name": "Style", "values": ["cinematic", "gritty", "painterly"]},
                {"name": "Lighting", "values": ["Day", "Night", "Dusk"]},
            ],
        },
    }
    randomizer = PromptRandomizer(config)
    variants = randomizer.generate("__mood__ [[Style]] hero in [[Lighting]]")
    assert len(variants) == 5


def test_matrix_fanout_repeats_consistently():
    config = {
        "enabled": True,
        "matrix": {
            "enabled": True,
            "mode": "fanout",
            "limit": 0,
            "slots": [
                {"name": "A", "values": ["A1", "A2"]},
                {"name": "B", "values": ["B1", "B2"]},
            ],
        },
    }
    randomizer = PromptRandomizer(config, rng=random.Random(0))
    prompt = "base [[A]] [[B]]"

    expected = {
        "base A1 B1",
        "base A1 B2",
        "base A2 B1",
        "base A2 B2",
    }

    first = randomizer.generate(prompt)
    assert {variant.text for variant in first} == expected

    second = randomizer.generate(prompt)
    assert {variant.text for variant in second} == expected


def test_matrix_sequential_with_single_sr_choice():
    config = {
        "enabled": True,
        "prompt_sr": {
            "enabled": True,
            "mode": "random",
            "rules": [
                {"search": "X", "replacements": ["x1", "x2", "x3"]},
            ],
        },
        "matrix": {
            "enabled": True,
            "mode": "sequential",
            "limit": 0,
            "slots": [
                {"name": "Style", "values": ["Casual", "Formal"]},
                {"name": "Lighting", "values": ["Day", "Night"]},
            ],
        },
    }
    randomizer = PromptRandomizer(config, rng=random.Random(0))

    texts = []
    for _ in range(4):
        variants = randomizer.generate("X [[Style]] shot under [[Lighting]]")
        assert len(variants) == 1
        texts.append(variants[0].text)

    def _extract_combo(text: str) -> tuple[str, str]:
        before, after = text.split(" shot under ")
        style = before.split()[-1]
        lighting = after.split()[0]
        return (style, lighting)

    combos_seen = {_extract_combo(text) for text in texts}
    expected_combos = {
        ("Casual", "Day"),
        ("Casual", "Night"),
        ("Formal", "Day"),
        ("Formal", "Night"),
    }
    assert combos_seen == expected_combos
    assert all(text.count("x1") + text.count("x2") + text.count("x3") == 1 for text in texts)


def test_wildcard_random_per_prompt_single_value():
    config = {
        "enabled": True,
        "wildcards": {
            "enabled": True,
            "mode": "random",
            "tokens": [
                {"token": "__hair__", "values": ["red hair", "black hair", "blonde hair"]},
            ],
        },
    }
    randomizer = PromptRandomizer(config, rng=random.Random(0))

    for _ in range(5):
        variants = randomizer.generate("portrait of __hair__ heroine")
        assert len(variants) == 1
        text = variants[0].text
        assert "__hair__" not in text
        assert sum(token in text for token in ["red hair", "black hair", "blonde hair"]) == 1


def test_fanout_modes_still_expand():
    config = {
        "enabled": True,
        "prompt_sr": {
            "enabled": True,
            "mode": "fanout",
            "rules": [
                {"search": "hero", "replacements": ["hero", "champion"]},
            ],
        },
    }
    randomizer = PromptRandomizer(config)
    variants = randomizer.generate("brave hero")
    assert len(variants) == 2
    assert {variant.text for variant in variants} == {"brave hero", "brave champion"}
