# Subsystem: AI
# Role: Defines contracts/enums for AI-driven settings suggestions.

"""Contracts for AI-driven settings suggestions (stubbed, versioned)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Iterable, List

from src.learning.learning_record import LearningRecord


class SuggestionIntent(str, Enum):
    FAST_DRAFT = "FAST_DRAFT"
    HIGH_DETAIL = "HIGH_DETAIL"
    PORTRAIT = "PORTRAIT"
    LANDSCAPE = "LANDSCAPE"
    ANIMATION_FRAME = "ANIMATION_FRAME"


@dataclass
class StageSuggestion:
    stage_name: str
    config_overrides: dict[str, object]
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(payload: dict[str, Any]) -> "StageSuggestion":
        return StageSuggestion(
            stage_name=payload.get("stage_name", ""),
            config_overrides=payload.get("config_overrides", {}) or {},
            notes=payload.get("notes"),
        )


@dataclass
class SettingsSuggestionRequest:
    intent: SuggestionIntent
    prompt_text: str
    pack_id: str | None
    baseline_config: dict[str, object]
    recent_runs: List[LearningRecord] = field(default_factory=list)
    available_capabilities: dict[str, object] = field(default_factory=dict)
    version: str = "v1"

    def to_json(self) -> str:
        payload = asdict(self)
        payload["intent"] = self.intent.value
        payload["recent_runs"] = [json.loads(r.to_json()) for r in self.recent_runs]
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def from_json(text: str) -> "SettingsSuggestionRequest":
        payload = json.loads(text)
        runs = payload.get("recent_runs", []) or []
        return SettingsSuggestionRequest(
            intent=SuggestionIntent(payload.get("intent", SuggestionIntent.FAST_DRAFT)),
            prompt_text=payload.get("prompt_text", ""),
            pack_id=payload.get("pack_id"),
            baseline_config=payload.get("baseline_config", {}) or {},
            recent_runs=[LearningRecord.from_json(json.dumps(r)) for r in runs],
            available_capabilities=payload.get("available_capabilities", {}) or {},
            version=payload.get("version", "v1"),
        )


@dataclass
class SettingsSuggestion:
    stages: List[StageSuggestion]
    global_notes: str | None = None
    internal_metadata: dict[str, object] = field(default_factory=dict)
    version: str = "v1"

    def to_json(self) -> str:
        payload = {
            "stages": [s.to_dict() for s in self.stages],
            "global_notes": self.global_notes,
            "internal_metadata": self.internal_metadata,
            "version": self.version,
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def from_json(text: str) -> "SettingsSuggestion":
        payload = json.loads(text)
        stages_iter: Iterable[dict[str, Any]] = payload.get("stages", []) or []
        return SettingsSuggestion(
            stages=[StageSuggestion.from_dict(s) for s in stages_iter],
            global_notes=payload.get("global_notes"),
            internal_metadata=payload.get("internal_metadata", {}) or {},
            version=payload.get("version", "v1"),
        )
