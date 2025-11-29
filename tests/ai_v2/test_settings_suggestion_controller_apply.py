from __future__ import annotations

from src.ai.settings_generator_contract import SettingsSuggestion, StageSuggestion, SuggestionIntent
from src.controller.settings_suggestion_controller import SettingsSuggestionController


def test_apply_suggestion_does_not_mutate_baseline():
    controller = SettingsSuggestionController()
    baseline = {"txt2img": {"steps": 20}}
    suggestion = SettingsSuggestion(
        stages=[StageSuggestion(stage_name="txt2img", config_overrides={"steps": 25})],
        global_notes=None,
        internal_metadata={},
    )
    merged = controller.apply_suggestion_to_config(baseline, suggestion)
    assert merged["txt2img"]["steps"] == 25
    assert baseline["txt2img"]["steps"] == 20


def test_controller_requests_stub_suggestion():
    controller = SettingsSuggestionController()
    suggestion = controller.request_suggestion(
        SuggestionIntent.FAST_DRAFT, "pack", {"txt2img": {"steps": 20}}, dataset_snapshot={"runs": [], "feedback": []}
    )
    assert suggestion.stages
    assert suggestion.internal_metadata.get("stub") is True
