"""Unit tests for the randomization parsing helpers."""

from src.gui.main_window import StableNewGUI


def test_parse_prompt_sr_rules_round_trip():
    text = """
    knight => paladin | warrior | samurai
    # comment line
    city => metropolis | capital
    """
    rules = StableNewGUI._parse_prompt_sr_rules(text)
    assert len(rules) == 2
    assert rules[0]["search"] == "knight"
    assert rules[0]["replacements"] == ["paladin", "warrior", "samurai"]

    formatted = StableNewGUI._format_prompt_sr_rules(rules)
    assert "knight => paladin | warrior | samurai" in formatted
    assert "city => metropolis | capital" in formatted


def test_parse_wildcard_tokens_round_trip():
    text = """
    subject: dragon | phoenix | griffin
    __mood__: happy | serious
    """
    tokens = StableNewGUI._parse_token_lines(text)
    assert {token["token"] for token in tokens} == {"__subject__", "__mood__"}
    assert tokens[0]["values"][0] == "dragon"

    formatted = StableNewGUI._format_token_lines(tokens)
    assert "subject:" in formatted
    assert "mood:" in formatted


def test_parse_matrix_slots_round_trip():
    text = """
    Style: watercolor | oil painting
    Lighting: sunrise | sunset
    """
    slots = StableNewGUI._parse_matrix_lines(text)
    assert len(slots) == 2
    assert slots[0]["name"] == "Style"
    assert slots[1]["values"] == ["sunrise", "sunset"]

    formatted = StableNewGUI._format_matrix_lines(slots)
    assert "Style:" in formatted
    assert "Lighting:" in formatted
