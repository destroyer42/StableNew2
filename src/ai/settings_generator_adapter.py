# Subsystem: AI
# Role: Transforms learning data into AI-friendly requests for settings generation.

"""Adapters from learning data to AI settings generator requests."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from src.ai.settings_generator_contract import SettingsSuggestionRequest, SuggestionIntent
from src.learning.dataset_builder import build_learning_dataset
from src.learning.learning_record import LearningRecord


def summarize_capabilities_for_request() -> dict[str, object]:
    """Return a placeholder capabilities snapshot (stub)."""

    return {"models": [], "vaes": [], "loras": []}


def build_request_from_learning_data(
    intent: SuggestionIntent,
    pack_id: str | None,
    baseline_config: Dict[str, Any],
    dataset_snapshot: Dict[str, Any] | None = None,
) -> SettingsSuggestionRequest:
    dataset = dataset_snapshot or build_learning_dataset()
    runs = dataset.get("runs", []) if isinstance(dataset, dict) else []
    records = []
    for item in runs:
        try:
            records.append(LearningRecord.from_json(json_dump(item)))
        except Exception:
            continue
    prompt_text = ""
    return SettingsSuggestionRequest(
        intent=intent,
        prompt_text=prompt_text,
        pack_id=pack_id,
        baseline_config=deepcopy(baseline_config or {}),
        recent_runs=records,
        available_capabilities=summarize_capabilities_for_request(),
    )


def json_dump(obj: Any) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)
