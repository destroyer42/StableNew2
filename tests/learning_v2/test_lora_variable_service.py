from __future__ import annotations

from types import SimpleNamespace

from src.learning.lora_variable_service import collect_available_loras
from src.utils.config import LoraRuntimeConfig


def test_collect_available_loras_merges_runtime_prompt_and_baseline_sources() -> None:
    prompt_metadata = SimpleNamespace(
        loras=[
            SimpleNamespace(name="PromptLoRA", weight=0.8),
            SimpleNamespace(name="RuntimeLoRA", weight=0.6),
        ]
    )
    prompt_workspace_state = SimpleNamespace(get_current_prompt_metadata=lambda: prompt_metadata)
    app_state = SimpleNamespace(
        lora_strengths=[
            LoraRuntimeConfig(name="RuntimeLoRA", strength=0.7, enabled=True),
            LoraRuntimeConfig(name="DisabledLoRA", strength=1.0, enabled=False),
        ]
    )
    baseline_config = {
        "txt2img": {
            "lora_strengths": [{"name": "BaselineLoRA", "strength": 1.1, "enabled": True}],
        }
    }

    loras = collect_available_loras(
        prompt_workspace_state=prompt_workspace_state,
        app_state=app_state,
        baseline_config=baseline_config,
    )

    names = {entry["name"] for entry in loras}
    assert names == {"PromptLoRA", "RuntimeLoRA", "DisabledLoRA", "BaselineLoRA"}

    runtime = next(entry for entry in loras if entry["name"] == "RuntimeLoRA")
    assert runtime["strength"] == 0.6 or runtime["strength"] == 0.7
