from __future__ import annotations

from typing import Any

from src.pipeline.executor import Pipeline


class _NoOpStructuredLogger:
    def __getattr__(self, name: str) -> Any:
        def _noop(*args: Any, **kwargs: Any) -> None:
            pass

        return _noop


class _ModelSwitchClient:
    def __init__(self, current_model: str | None, safe_mode: bool) -> None:
        self._current_model = current_model
        self.safe_mode = safe_mode
        self.set_model_calls: list[str] = []
        self.set_vae_calls: list[str] = []

    @property
    def options_write_enabled(self) -> bool:
        return not self.safe_mode

    def get_current_model(self) -> str | None:
        return self._current_model

    def set_model(self, model_name: str) -> bool:
        self.set_model_calls.append(model_name)
        self._current_model = model_name
        return True

    def set_vae(self, vae_name: str) -> bool:
        self.set_vae_calls.append(vae_name)
        return True


def test_model_switch_is_skipped_when_the_model_matches() -> None:
    client = _ModelSwitchClient("juggernautXL_ragnarokBy.safetensors", safe_mode=False)
    pipeline = Pipeline(client=client, structured_logger=_NoOpStructuredLogger())

    pipeline._current_model = None
    pipeline._model_discovery_attempted = False

    pipeline._ensure_model_and_vae("juggernautXL_ragnarokBy.safetensors", None)

    assert client.set_model_calls == []
    assert pipeline._current_model == "juggernautXL_ragnarokBy.safetensors"


def test_model_switch_is_avoided_when_safemode_blocks_changes() -> None:
    client = _ModelSwitchClient("stable_default.safetensors", safe_mode=True)
    pipeline = Pipeline(client=client, structured_logger=_NoOpStructuredLogger())

    pipeline._current_model = None
    pipeline._model_discovery_attempted = False

    pipeline._ensure_model_and_vae("juggernautXL_ragnarokBy.safetensors", None)

    assert client.set_model_calls == []
    assert pipeline._current_model == "stable_default.safetensors"

