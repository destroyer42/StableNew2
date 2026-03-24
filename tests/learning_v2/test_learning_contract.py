from __future__ import annotations

from src.learning import learning_contract as contract


def test_learning_contract_imports_and_returns_placeholders() -> None:
    modifiers = contract.get_available_modifiers()
    ranges = contract.get_modifier_ranges()
    defaults = contract.get_current_best_defaults()
    presets = contract.get_prompt_optimizer_learning_presets()
    proposed = contract.propose_new_defaults(
        {
            "runs": [
                {"id": 1, "prompt_optimizer_learning": {"preset_id": "score_classifier_v1"}},
                {"id": 2, "metadata": {"prompt_optimizer_learning": {"preset_id": "score_classifier_v1"}}},
            ]
        }
    )

    assert isinstance(modifiers, list)
    assert "prompt_optimizer_preset" in modifiers
    assert "steps" in ranges
    assert "prompt_optimizer_preset" in ranges
    assert "txt2img" in defaults
    assert defaults["prompt_optimizer"]["preset_id"] == "baseline_safe_v1"
    assert "baseline_safe_v1" in presets
    assert proposed.get("proposed") is True
    assert proposed["prompt_optimizer"]["preset_id"] == "score_classifier_v1"
