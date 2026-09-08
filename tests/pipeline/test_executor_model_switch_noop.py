from __future__ import annotations

from typing import Any

import pytest

from src.pipeline.executor import Pipeline
from src.pipeline.model_synchronizer import (
    A1111ModelSynchronizer,
    ModelSynchronizationError,
)


class _NoOpStructuredLogger:
    def __getattr__(self, name: str) -> Any:
        def _noop(*args: Any, **kwargs: Any) -> None:
            pass

        return _noop


class _ModelSwitchClient:
    def __init__(
        self,
        current_model: str | None,
        safe_mode: bool,
        *,
        set_model_result: bool = True,
        load_after_set: bool = True,
    ) -> None:
        self._current_model = current_model
        self.safe_mode = safe_mode
        self.set_model_result = set_model_result
        self.load_after_set = load_after_set
        self.set_model_calls: list[str] = []
        self.set_vae_calls: list[str] = []
        self.txt2img_calls = 0

    @property
    def options_write_enabled(self) -> bool:
        return not self.safe_mode

    def get_current_model(self) -> str | None:
        return self._current_model

    def set_model(self, model_name: str) -> bool:
        self.set_model_calls.append(model_name)
        if self.set_model_result and self.load_after_set:
            self._current_model = model_name
        return self.set_model_result

    def set_vae(self, vae_name: str) -> bool:
        self.set_vae_calls.append(vae_name)
        return True

    def txt2img(self) -> None:
        self.txt2img_calls += 1


def _execute_after_model_gate(pipeline: Pipeline, model_name: str) -> None:
    pipeline._ensure_model_and_vae(model_name, None)
    pipeline.client.txt2img()


def test_model_switch_is_skipped_when_the_model_matches() -> None:
    client = _ModelSwitchClient("juggernautXL_ragnarokBy.safetensors", safe_mode=False)
    pipeline = Pipeline(client=client, structured_logger=_NoOpStructuredLogger())

    pipeline._current_model = None
    pipeline._model_discovery_attempted = False

    _execute_after_model_gate(pipeline, "juggernautXL_ragnarokBy.safetensors")

    assert client.set_model_calls == []
    assert client.txt2img_calls == 1
    assert pipeline._current_model == "juggernautXL_ragnarokBy.safetensors"


def test_model_switch_fails_when_safemode_blocks_required_change() -> None:
    client = _ModelSwitchClient("stable_default.safetensors", safe_mode=True)
    pipeline = Pipeline(client=client, structured_logger=_NoOpStructuredLogger())

    pipeline._current_model = None
    pipeline._model_discovery_attempted = False

    with pytest.raises(ModelSynchronizationError, match="options writes are disabled") as exc_info:
        _execute_after_model_gate(pipeline, "juggernautXL_ragnarokBy.safetensors")

    assert client.set_model_calls == []
    assert client.txt2img_calls == 0
    assert pipeline._current_model is None
    assert "requested='juggernautXL_ragnarokBy.safetensors'" in str(exc_info.value)
    assert "actual='stable_default.safetensors'" in str(exc_info.value)


def test_model_switch_noop_with_hash_and_extension_equivalence() -> None:
    # Current model has extension and hash, desired is base name
    client = _ModelSwitchClient("model.safetensors [abc123]", safe_mode=False)
    pipeline = Pipeline(client=client, structured_logger=_NoOpStructuredLogger())

    pipeline._current_model = None
    pipeline._model_discovery_attempted = False

    _execute_after_model_gate(pipeline, "model")

    # set_model should NOT be called, as names normalize equal
    assert client.set_model_calls == []
    assert client.txt2img_calls == 1
    assert pipeline._current_model == "model.safetensors [abc123]"


def test_model_switch_resets_vae_to_automatic_when_not_explicit() -> None:
    client = _ModelSwitchClient("old_model.safetensors", safe_mode=False)
    pipeline = Pipeline(client=client, structured_logger=_NoOpStructuredLogger())
    pipeline._current_model = "old_model.safetensors"
    pipeline._current_vae = "sdxl_vae.safetensors"

    pipeline._ensure_model_and_vae("new_model.safetensors", None)

    assert client.set_model_calls == ["new_model.safetensors"]
    assert client.set_vae_calls == ["Automatic"]
    assert pipeline._current_vae == "Automatic"


def test_model_unchanged_does_not_reset_vae_when_not_explicit() -> None:
    client = _ModelSwitchClient("same_model.safetensors", safe_mode=False)
    pipeline = Pipeline(client=client, structured_logger=_NoOpStructuredLogger())
    pipeline._current_model = "same_model.safetensors"
    pipeline._current_vae = "sdxl_vae.safetensors"

    pipeline._ensure_model_and_vae("same_model.safetensors", None)

    assert client.set_model_calls == []
    assert client.set_vae_calls == []
    assert pipeline._current_vae == "sdxl_vae.safetensors"


def test_model_switch_is_verified_before_txt2img() -> None:
    client = _ModelSwitchClient("model-b.safetensors", safe_mode=False)
    pipeline = Pipeline(client=client, structured_logger=_NoOpStructuredLogger())

    _execute_after_model_gate(pipeline, "model-a.safetensors")

    assert client.set_model_calls == ["model-a.safetensors"]
    assert client.txt2img_calls == 1
    assert pipeline._current_model == "model-a.safetensors"


def test_false_model_change_stops_before_txt2img() -> None:
    client = _ModelSwitchClient(
        "model-b.safetensors",
        safe_mode=False,
        set_model_result=False,
    )
    pipeline = Pipeline(client=client, structured_logger=_NoOpStructuredLogger())

    with pytest.raises(ModelSynchronizationError, match="returned false") as exc_info:
        _execute_after_model_gate(pipeline, "model-a.safetensors")

    assert client.set_model_calls == ["model-a.safetensors"]
    assert client.txt2img_calls == 0
    assert "requested='model-a.safetensors'" in str(exc_info.value)
    assert "actual='model-b.safetensors'" in str(exc_info.value)


def test_unverified_model_change_times_out_before_txt2img() -> None:
    client = _ModelSwitchClient(
        "model-b.safetensors",
        safe_mode=False,
        load_after_set=False,
    )
    pipeline = Pipeline(client=client, structured_logger=_NoOpStructuredLogger())
    pipeline._model_synchronizer = A1111ModelSynchronizer(
        client,
        timeout_seconds=0,
        poll_interval_seconds=0,
    )

    with pytest.raises(ModelSynchronizationError, match="verification timed out") as exc_info:
        _execute_after_model_gate(pipeline, "model-a.safetensors")

    assert client.set_model_calls == ["model-a.safetensors"]
    assert client.txt2img_calls == 0
    assert "requested='model-a.safetensors'" in str(exc_info.value)
    assert "actual='model-b.safetensors'" in str(exc_info.value)


def test_same_model_jobs_reuse_verified_checkpoint_without_reload() -> None:
    client = _ModelSwitchClient("model-b.safetensors", safe_mode=False)
    pipeline = Pipeline(client=client, structured_logger=_NoOpStructuredLogger())

    for _ in range(3):
        _execute_after_model_gate(pipeline, "model-a.safetensors")

    assert client.set_model_calls == ["model-a.safetensors"]
    assert client.txt2img_calls == 3


def test_explicit_vae_noop_skips_redundant_set() -> None:
    client = _ModelSwitchClient("same_model.safetensors", safe_mode=False)
    pipeline = Pipeline(client=client, structured_logger=_NoOpStructuredLogger())
    pipeline._current_model = "same_model.safetensors"
    pipeline._current_vae = "sdxl_vae.safetensors"

    pipeline._ensure_model_and_vae("same_model.safetensors", "sdxl_vae.safetensors")

    assert client.set_model_calls == []
    assert client.set_vae_calls == []
