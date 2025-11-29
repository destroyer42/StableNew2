from __future__ import annotations

import json

from src.ai.settings_generator_contract import (
    SettingsSuggestion,
    SettingsSuggestionRequest,
    StageSuggestion,
    SuggestionIntent,
)
from src.learning.learning_record import LearningRecord


def test_contract_roundtrip_json() -> None:
    record = LearningRecord(
        run_id="r1",
        timestamp="2025-01-01T00:00:00",
        base_config={},
        variant_configs=[],
        randomizer_mode="off",
        randomizer_plan_size=1,
        primary_model="m",
        primary_sampler="Euler",
        primary_scheduler="Normal",
        primary_steps=20,
        primary_cfg_scale=7.0,
    )
    req = SettingsSuggestionRequest(
        intent=SuggestionIntent.HIGH_DETAIL,
        prompt_text="Hello",
        pack_id="pack",
        baseline_config={"txt2img": {"steps": 20}},
        recent_runs=[record],
        available_capabilities={"models": []},
    )
    text = req.to_json()
    loaded = SettingsSuggestionRequest.from_json(text)
    assert loaded.intent == req.intent
    assert loaded.pack_id == "pack"
    assert loaded.recent_runs[0].run_id == "r1"

    suggestion = SettingsSuggestion(
        stages=[StageSuggestion(stage_name="txt2img", config_overrides={"steps": 25}, notes="hi")],
        global_notes="ok",
        internal_metadata={"a": 1},
    )
    s_text = suggestion.to_json()
    loaded_s = SettingsSuggestion.from_json(s_text)
    assert loaded_s.global_notes == "ok"
    assert loaded_s.stages[0].config_overrides["steps"] == 25
