from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from src.utils.thread_registry import ThreadRegistry, get_thread_registry

T = TypeVar("T")


@dataclass
class _TaskSpec(Generic[T]):
    key: str
    generation: int
    work: Callable[[], T]
    on_result: Callable[[T], None] | None
    on_error: Callable[[Exception], None] | None
    on_complete: Callable[[bool, Exception | None], None] | None
    name: str
    purpose: str | None


class BackgroundTaskCoordinator:
    """Latest-wins keyed background work with tracked-thread execution."""

    def __init__(
        self,
        *,
        dispatcher: Callable[[Callable[[], None]], None] | None = None,
        thread_registry: ThreadRegistry | None = None,
        run_inline: bool = False,
        logger: logging.Logger | None = None,
    ) -> None:
        self._dispatcher = dispatcher
        self._thread_registry = thread_registry or get_thread_registry()
        self._run_inline = bool(run_inline)
        self._logger = logger or logging.getLogger(__name__)
        self._lock = threading.RLock()
        self._latest_generation: dict[str, int] = {}
        self._inflight_generation: dict[str, int] = {}
        self._pending: dict[str, _TaskSpec[Any]] = {}
        self._submitted = 0
        self._completed = 0
        self._stale_dropped = 0

    def submit(
        self,
        key: str,
        work: Callable[[], T],
        *,
        on_result: Callable[[T], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
        on_complete: Callable[[bool, Exception | None], None] | None = None,
        name: str | None = None,
        purpose: str | None = None,
    ) -> int:
        with self._lock:
            generation = self._latest_generation.get(key, 0) + 1
            self._latest_generation[key] = generation
            self._submitted += 1
            spec: _TaskSpec[T] = _TaskSpec(
                key=key,
                generation=generation,
                work=work,
                on_result=on_result,
                on_error=on_error,
                on_complete=on_complete,
                name=name or f"bg-{key.replace(':', '-')}",
                purpose=purpose,
            )
            if key in self._inflight_generation:
                self._pending[key] = spec  # latest request supersedes older pending work
                return generation
            self._inflight_generation[key] = generation
        self._start(spec)
        return generation

    def get_metrics_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "submitted": self._submitted,
                "completed": self._completed,
                "stale_dropped": self._stale_dropped,
                "inflight": dict(self._inflight_generation),
                "pending": {key: spec.generation for key, spec in self._pending.items()},
                "latest_generation": dict(self._latest_generation),
            }

    def _start(self, spec: _TaskSpec[T]) -> None:
        if self._run_inline:
            self._run(spec)
            return
        self._thread_registry.spawn(
            target=self._run,
            args=(spec,),
            name=spec.name,
            purpose=spec.purpose,
        )

    def _run(self, spec: _TaskSpec[T]) -> None:
        result: T | None = None
        error: Exception | None = None
        try:
            result = spec.work()
        except Exception as exc:  # noqa: BLE001
            error = exc

        with self._lock:
            self._completed += 1
            latest_generation = self._latest_generation.get(spec.key, 0)
            is_latest = spec.generation == latest_generation
            if not is_latest:
                self._stale_dropped += 1
            self._inflight_generation.pop(spec.key, None)
            next_spec = self._pending.pop(spec.key, None)
            if next_spec is not None:
                self._inflight_generation[spec.key] = next_spec.generation

        if next_spec is not None:
            self._start(next_spec)

        def _deliver() -> None:
            if error is not None:
                if is_latest and callable(spec.on_error):
                    spec.on_error(error)
                elif not is_latest:
                    self._logger.debug(
                        "Dropping stale background task error for key=%s generation=%s",
                        spec.key,
                        spec.generation,
                    )
                if callable(spec.on_complete):
                    spec.on_complete(False, error)
                return
            if is_latest and callable(spec.on_result):
                spec.on_result(result)  # type: ignore[arg-type]
            if callable(spec.on_complete):
                spec.on_complete(is_latest, None)

        dispatcher = self._dispatcher
        if callable(dispatcher):
            dispatcher(_deliver)
            return
        _deliver()

