# Subsystem: AI
# Role: Hosts the integration point to the real AI backend (stubbed for now).

"""Stubbed AI settings generator driver."""

from __future__ import annotations

from abc import ABC, abstractmethod
from copy import deepcopy

from src.ai.settings_generator_contract import (
    SettingsSuggestion,
    SettingsSuggestionRequest,
    StageSuggestion,
    SuggestionIntent,
)


class SettingsGenerator(ABC):
    """Interface for AI settings generators."""

    @abstractmethod
    def generate_suggestion(self, request: SettingsSuggestionRequest) -> SettingsSuggestion:
        raise NotImplementedError


class LocalStubSettingsGenerator(SettingsGenerator):
    """Deterministic, offline stub that tweaks baseline config."""

    def generate_suggestion(self, request: SettingsSuggestionRequest) -> SettingsSuggestion:
        baseline = deepcopy(request.baseline_config or {})
        txt2img = baseline.setdefault("txt2img", {})
        tweaks: dict[SuggestionIntent, dict[str, object]] = {
            SuggestionIntent.HIGH_DETAIL: {"steps": txt2img.get("steps", 20) + 5, "cfg_scale": 9.0},
            SuggestionIntent.FAST_DRAFT: {"steps": max(5, txt2img.get("steps", 20) - 5)},
            SuggestionIntent.PORTRAIT: {"width": 512, "height": 704},
            SuggestionIntent.LANDSCAPE: {"width": 704, "height": 512},
            SuggestionIntent.ANIMATION_FRAME: {"scheduler": "Karras"},
        }
        override = tweaks.get(request.intent, {})
        txt2img.update(override)

        stage_suggestion = StageSuggestion(
            stage_name="txt2img", config_overrides=override, notes="stubbed"
        )
        metadata = {"stub": True, "intent": request.intent.value}
        return SettingsSuggestion(
            stages=[stage_suggestion], global_notes="Stub suggestion", internal_metadata=metadata
        )
