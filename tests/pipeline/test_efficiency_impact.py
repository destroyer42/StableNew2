from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from src.controller.pipeline_controller import PipelineController
from src.pipeline.executor import Pipeline


class _NoOpStructuredLogger:
    def __getattr__(self, _name: str) -> Any:
        def _noop(*_args: Any, **_kwargs: Any) -> None:
            pass

        return _noop


class _DelayedSwitchClient:
    def __init__(self, current_model: str | None, model_delay_s: float, vae_delay_s: float) -> None:
        self._current_model = current_model
        self.model_delay_s = model_delay_s
        self.vae_delay_s = vae_delay_s
        self.set_model_calls: list[str] = []
        self.set_vae_calls: list[str] = []

    @property
    def options_write_enabled(self) -> bool:
        return True

    def get_current_model(self) -> str | None:
        return self._current_model

    def set_model(self, model_name: str) -> bool:
        time.sleep(self.model_delay_s)
        self.set_model_calls.append(model_name)
        self._current_model = model_name
        return True

    def set_vae(self, vae_name: str) -> bool:
        time.sleep(self.vae_delay_s)
        self.set_vae_calls.append(vae_name)
        return True


@dataclass
class _DummyRecord:
    config: dict[str, Any]


def _legacy_set_model_vae(client: _DelayedSwitchClient, model_name: str | None, vae_name: str | None) -> None:
    if model_name:
        client.set_model(model_name)
    if vae_name:
        client.set_vae(vae_name)


def _switch_cost(records: list[_DummyRecord], model_cost: float = 1.0, vae_cost: float = 0.2) -> float:
    total = 0.0
    prev_model = ""
    prev_vae = "automatic"
    for record in records:
        cfg = record.config or {}
        model = str(cfg.get("model", "")).strip().lower()
        vae = str(cfg.get("vae", "")).strip().lower() or "automatic"
        if model != prev_model:
            total += model_cost
        if vae != prev_vae:
            total += vae_cost
        prev_model, prev_vae = model, vae
    return total


def test_executor_metrics_show_switch_overhead_reduction() -> None:
    sequence = [("modelA.safetensors", "vaeA.safetensors")] * 20
    model_delay = 0.003
    vae_delay = 0.002

    legacy_client = _DelayedSwitchClient("legacy_boot.safetensors", model_delay, vae_delay)
    t0 = time.monotonic()
    for model_name, vae_name in sequence:
        _legacy_set_model_vae(legacy_client, model_name, vae_name)
    legacy_elapsed = time.monotonic() - t0

    optimized_client = _DelayedSwitchClient("legacy_boot.safetensors", model_delay, vae_delay)
    pipeline = Pipeline(client=optimized_client, structured_logger=_NoOpStructuredLogger())
    pipeline._begin_run_metrics()
    for model_name, vae_name in sequence:
        pipeline._ensure_model_and_vae(model_name, vae_name)
    optimized_metrics = pipeline.get_run_efficiency_metrics(images_processed=len(sequence))

    assert len(optimized_client.set_model_calls) < len(legacy_client.set_model_calls)
    assert len(optimized_client.set_vae_calls) < len(legacy_client.set_vae_calls)
    assert optimized_metrics["model_switches"] == len(optimized_client.set_model_calls)
    assert optimized_metrics["vae_switches"] == len(optimized_client.set_vae_calls)
    assert optimized_metrics["elapsed_seconds"] < legacy_elapsed


def test_model_vae_grouping_reduces_estimated_switch_cost() -> None:
    records = [
        _DummyRecord({"model": "modelA", "vae": "vaeA"}),
        _DummyRecord({"model": "modelB", "vae": "vaeB"}),
        _DummyRecord({"model": "modelA", "vae": "vaeA"}),
        _DummyRecord({"model": "modelB", "vae": "vaeB"}),
        _DummyRecord({"model": "modelA", "vae": "vaeA"}),
        _DummyRecord({"model": "modelB", "vae": "vaeB"}),
    ]
    controller = object.__new__(PipelineController)
    sorted_records = controller._sort_jobs_by_model(records)

    unsorted_cost = _switch_cost(records)
    sorted_cost = _switch_cost(sorted_records)

    assert sorted_cost < unsorted_cost
