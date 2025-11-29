from __future__ import annotations

from src.ai.settings_generator_contract import SettingsSuggestionRequest, SuggestionIntent
from src.ai.settings_generator_driver import LocalStubSettingsGenerator


def test_stub_generator_tweaks_based_on_intent() -> None:
    baseline = {"txt2img": {"steps": 20, "cfg_scale": 7.0}}
    generator = LocalStubSettingsGenerator()
    req = SettingsSuggestionRequest(
        intent=SuggestionIntent.HIGH_DETAIL,
        prompt_text="",
        pack_id=None,
        baseline_config=baseline,
        recent_runs=[],
        available_capabilities={},
    )
    suggestion = generator.generate_suggestion(req)
    override = suggestion.stages[0].config_overrides
    assert override.get("steps") == 25
    assert suggestion.internal_metadata.get("stub") is True
