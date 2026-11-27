"""Bounded, per-run observations at the image executor's controlled boundaries."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Concatenate, ParamSpec, Protocol, TypeVar

from src.api.client import SDWebUIClient
from src.controller.runtime_state import CancellationError
from src.pipeline.model_synchronizer import operator_model_title

SCHEMA = "stablenew.image-performance.v1"
METADATA_KEY = "image_performance"
_MAX_RECORDS = 256


def _ms(seconds: float) -> float:
    return round(max(0.0, seconds) * 1000, 3)


@dataclass(slots=True)
class StagePerformance:
    stage: str
    image_index: int | None
    started: float
    first_request_at: float | None = None
    finalization_at: float | None = None
    request_seconds: float | None = None
    mode: str | None = None
    checkpoint: dict[str, Any] = field(default_factory=dict)
    passes: list[dict[str, Any]] = field(default_factory=list)
    passthrough: bool | None = None
    mask_count: int | None = None
    returned_images: int | None = None

    def record(
        self, *, now: float, outcome: str, operations: list[dict[str, Any]]
    ) -> dict[str, Any]:
        preparation_end = self.first_request_at
        if preparation_end is None and self.finalization_at is None:
            preparation_end = now
        return {
            "stage": self.stage,
            "image_index": self.image_index,
            "mode": self.mode,
            "outcome": outcome,
            "checkpoint": self.checkpoint,
            "timing_ms": {
                "preparation": _ms(preparation_end - self.started)
                if preparation_end is not None
                else None,
                "backend_request": _ms(self.request_seconds)
                if self.request_seconds is not None
                else None,
                "finalization": _ms(now - self.finalization_at)
                if self.finalization_at is not None
                else None,
                "stage_total": _ms(now - self.started),
                "model_sync": _sum_duration(operations, "model_sync"),
                "memory_cleanup": _sum_duration(operations, "memory_cleanup"),
            },
            "passes": self.passes,
            "mask_count": self.mask_count,
            "source_passthrough": self.passthrough,
            "returned_images": self.returned_images,
            "backend_internal_timing": {"status": "not_instrumented"},
        }


def _sum_duration(operations: list[dict[str, Any]], name: str) -> float | None:
    durations = [entry["duration_ms"] for entry in operations if entry["operation"] == name]
    return round(sum(durations), 3) if durations else None


class ImagePerformanceTrace:
    """One executor job's bounded evidence. The runner replaces it at the next job."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.active: StagePerformance | None = None
        self.stages: list[dict[str, Any]] = []
        self.operations: list[dict[str, Any]] = []
        #: Job-level time outside the backend operations above (preparation, admission, result writing).
        self.steps: list[dict[str, Any]] = []
        self.stages_omitted = 0
        self.operations_omitted = 0
        self._adetailer_index = 0
        self.base_images_returned: int | None = None

    @contextmanager
    def operation(self, name: str, reason: str, **details: Any) -> Iterator[dict[str, Any]]:
        stage = self.active
        started = self.clock()
        entry = {
            "operation": name,
            "reason": reason,
            "stage": stage.stage if stage else None,
            "image_index": stage.image_index if stage else None,
            "outcome": "unverified",
            **details,
        }
        try:
            yield entry
        except CancellationError:
            entry["outcome"] = "cancelled"
            raise
        except Exception:
            if entry["outcome"] == "unverified":
                entry["outcome"] = "failed"
            raise
        finally:
            entry["duration_ms"] = _ms(self.clock() - started)
            if len(self.operations) < _MAX_RECORDS:
                self.operations.append(entry)
            else:
                self.operations_omitted += 1

    @contextmanager
    def step(self, name: str) -> Iterator[None]:
        started = self.clock()
        try:
            yield
        finally:
            if len(self.steps) < _MAX_RECORDS:
                self.steps.append({"step": name, "duration_ms": _ms(self.clock() - started)})

    @contextmanager
    def backend_request(self) -> Iterator[None]:
        stage = self.active
        if stage is None:
            yield
            return
        started = self.clock()
        if stage.first_request_at is None:
            stage.first_request_at = started
        try:
            yield
        finally:
            stage.request_seconds = (stage.request_seconds or 0.0) + max(
                0.0, self.clock() - started
            )

    def begin_finalization(self) -> None:
        if self.active is not None:
            self.active.finalization_at = self.clock()

    def begin_stage(self, stage: str) -> StagePerformance:
        index = None
        if stage == "adetailer":
            index = self._adetailer_index
            self._adetailer_index += 1
        self.active = StagePerformance(stage, index, self.clock())
        return self.active

    def finish_stage(self, stage: StagePerformance, *, operation_offset: int, outcome: str) -> None:
        self.active = None
        if len(self.stages) < _MAX_RECORDS:
            self.stages.append(
                stage.record(
                    now=self.clock(), outcome=outcome, operations=self.operations[operation_offset:]
                )
            )
        else:
            self.stages_omitted += 1

    def snapshot(self, outcome: str) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "outcome": outcome,
            "stages": list(self.stages),
            "operations": list(self.operations),
            "steps": list(self.steps),
            "stages_omitted": self.stages_omitted,
            "operations_omitted": self.operations_omitted,
        }


def timed_step(trace: Any, name: str) -> AbstractContextManager[None]:
    """Time ``name`` into the job's record; a caller without a trace (a stand-in pipeline) is not measured."""

    return trace.step(name) if isinstance(trace, ImagePerformanceTrace) else nullcontext()


def observe_cleanup(
    client: Any,
    trace: ImagePerformanceTrace | None,
    *,
    reason: str,
    unload_model: bool,
    stage: str | None = None,
    image_index: int | None = None,
    **kwargs: Any,
) -> None:
    if trace is None:
        client.free_vram(unload_model=unload_model, **kwargs)
        return
    with trace.operation(
        "memory_cleanup", reason, unload_checkpoint_requested=unload_model
    ) as entry:
        if stage is not None:
            entry.update(stage=stage, image_index=image_index)
        details: dict[str, dict[str, Any]] = {}
        entry["operations"] = details
        if isinstance(client, SDWebUIClient):
            kwargs["operation_evidence"] = details
        result = client.free_vram(unload_model=unload_model, **kwargs)
        if result is True:
            entry["outcome"] = (
                "partial"
                if any(item["outcome"] == "failed" for item in details.values())
                else "completed"
            )
        elif result is False:
            entry["outcome"] = "failed"


def adetailer_passes(
    *, face: dict[str, Any], hands: dict[str, Any], verified: dict[str, Any] | None
) -> list[dict[str, Any]]:
    by_label = {entry["label"]: entry for entry in verified["passes"]} if verified else {}
    records = []
    for label, args in (("face", face), ("hands", hands)):
        requested = bool(args.get("ad_tab_enable"))
        evidence = by_label.get(label)
        masks = evidence["effective_mask_count"] if evidence else None
        sampled = evidence.get("sampled_masks") if evidence else None
        skipped = True if not requested else None
        if evidence is not None and verified is not None:
            skipped = masks == 0 or sampled == 0 or not verified["refinement_sampled"]
        records.append(
            {
                "label": label,
                "requested": requested,
                "detector_id": operator_model_title(args["ad_model"])
                if args.get("ad_model")
                else None,
                "effective_masks": masks,
                "sampled_masks": sampled,
                "skipped": skipped,
            }
        )
    return records


class _ExecutorWithTrace(Protocol):
    _image_performance: ImagePerformanceTrace


_P = ParamSpec("_P")
_Executor = TypeVar("_Executor", bound=_ExecutorWithTrace)


def trace_image_stage(
    stage: str,
) -> Callable[
    [Callable[Concatenate[_Executor, _P], dict[str, Any] | None]],
    Callable[Concatenate[_Executor, _P], dict[str, Any] | None],
]:
    def decorate(
        method: Callable[Concatenate[_Executor, _P], dict[str, Any] | None],
    ) -> Callable[Concatenate[_Executor, _P], dict[str, Any] | None]:
        @wraps(method)
        def measured(
            self: _Executor, /, *args: _P.args, **kwargs: _P.kwargs
        ) -> dict[str, Any] | None:
            trace = self._image_performance
            operation_offset = len(trace.operations)
            measurement = trace.begin_stage(stage)
            outcome = "failed"
            try:
                result = method(self, *args, **kwargs)
                if result and (result.get("path") or result.get("all_paths")):
                    outcome = "completed"
                return result
            except CancellationError:
                outcome = "cancelled"
                raise
            finally:
                trace.finish_stage(measurement, operation_offset=operation_offset, outcome=outcome)

        return measured

    return decorate
