"""Controller wrapper for AI settings suggestions."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from src.ai.settings_generator_adapter import build_request_from_learning_data
from src.ai.settings_generator_contract import SettingsSuggestion, SuggestionIntent
from src.ai.settings_generator_driver import LocalStubSettingsGenerator, SettingsGenerator


class SettingsSuggestionController:
    """Thin controller layer for requesting and applying AI settings suggestions."""

    def __init__(self, generator: SettingsGenerator | None = None) -> None:
        self.generator = generator or LocalStubSettingsGenerator()

    def request_suggestion(
        self,
        intent: SuggestionIntent,
        pack_id: str | None,
        baseline_config: dict[str, Any],
        dataset_snapshot: dict[str, Any] | None = None,
    ) -> SettingsSuggestion:
        request = build_request_from_learning_data(intent, pack_id, baseline_config, dataset_snapshot)
        return self.generator.generate_suggestion(request)

    def apply_suggestion_to_config(
        self,
        baseline_config: Dict[str, Any],
        suggestion: SettingsSuggestion,
    ) -> Dict[str, Any]:
        merged = deepcopy(baseline_config or {})
        for stage in suggestion.stages:
            stage_name = stage.stage_name
            if not stage_name:
                continue
            merged.setdefault(stage_name, {})
            if isinstance(merged[stage_name], dict):
                merged[stage_name].update(stage.config_overrides or {})
        return merged
