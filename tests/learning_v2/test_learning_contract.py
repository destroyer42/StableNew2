from __future__ import annotations

from src.learning import learning_contract as contract


def test_learning_contract_imports_and_returns_placeholders() -> None:
    modifiers = contract.get_available_modifiers()
    ranges = contract.get_modifier_ranges()
    defaults = contract.get_current_best_defaults()
    proposed = contract.propose_new_defaults({"runs": [{"id": 1}]})

    assert isinstance(modifiers, list)
    assert "steps" in ranges
    assert "txt2img" in defaults
    assert proposed.get("proposed") is True
