from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from src.controller.job_service import JobService
from src.runtime_host.messages import (
    RuntimeHostProtocolMessage,
    build_protocol_message,
    describe_runtime_host_protocol,
)
from src.runtime_host.port import RuntimeHostPort


class LocalRuntimeHostAdapter:
    """Local-only adapter that presents JobService through the runtime-host seam."""

    def __init__(self, job_service: JobService) -> None:
        self._job_service = job_service

    @property
    def job_service(self) -> JobService:
        return self._job_service

    @property
    def queue(self) -> Any:
        return self._job_service.queue

    @property
    def job_queue(self) -> Any:
        return self._job_service.job_queue

    @property
    def runner(self) -> Any:
        return self._job_service.runner

    @property
    def history_store(self) -> Any:
        return self._job_service.history_store

    @property
    def auto_run_enabled(self) -> bool:
        return bool(self._job_service.auto_run_enabled)

    @auto_run_enabled.setter
    def auto_run_enabled(self, value: bool) -> None:
        self._job_service.auto_run_enabled = bool(value)

    def describe_protocol(self) -> dict[str, Any]:
        return describe_runtime_host_protocol()

    def build_command_message(
        self,
        name: str,
        payload: dict[str, Any] | None = None,
    ) -> RuntimeHostProtocolMessage:
        return build_protocol_message("command", name, payload)

    def build_event_message(
        self,
        name: str,
        payload: dict[str, Any] | None = None,
    ) -> RuntimeHostProtocolMessage:
        return build_protocol_message("event", name, payload)

    def build_snapshot_message(
        self,
        name: str,
        payload: dict[str, Any] | None = None,
    ) -> RuntimeHostProtocolMessage:
        return build_protocol_message("snapshot", name, payload)

    def register_callback(self, event: str, callback: Callable[..., None]) -> None:
        self._job_service.register_callback(event, callback)

    def set_status_callback(self, name: str, callback: Callable[..., None]) -> None:
        self._job_service.set_status_callback(name, callback)

    def set_event_dispatcher(self, dispatch_fn: Callable[[Callable[[], None]], None]) -> None:
        self._job_service.set_event_dispatcher(dispatch_fn)

    def set_job_lifecycle_logger(self, logger: Any | None) -> None:
        self._job_service.set_job_lifecycle_logger(logger)

    def set_activity_hooks(self, *, on_queue_activity=None, on_runner_activity=None) -> None:
        self._job_service.set_activity_hooks(
            on_queue_activity=on_queue_activity,
            on_runner_activity=on_runner_activity,
        )

    def register_completion_handler(self, handler: Callable[[Any, Any], None]) -> None:
        self._job_service.register_completion_handler(handler)

    def submit_job_with_run_mode(self, job: Any, *, emit_queue_updated: bool = True) -> None:
        self._job_service.submit_job_with_run_mode(job, emit_queue_updated=emit_queue_updated)

    def submit_queued(self, job: Any, *, emit_queue_updated: bool = True) -> None:
        self._job_service.submit_queued(job, emit_queue_updated=emit_queue_updated)

    def enqueue(self, job: Any, *, emit_queue_updated: bool = True) -> None:
        self._job_service.enqueue(job, emit_queue_updated=emit_queue_updated)

    def run_now(self, job: Any) -> None:
        self._job_service.run_now(job)

    def enqueue_njrs(self, njrs: list[Any], run_request: Any) -> list[str]:
        return self._job_service.enqueue_njrs(njrs, run_request)

    def run_next_now(self) -> None:
        self._job_service.run_next_now()

    def cancel_current(self, *, return_to_queue: bool = False) -> Any:
        return self._job_service.cancel_current(return_to_queue=return_to_queue)

    def pause(self) -> None:
        self._job_service.pause()

    def resume(self) -> None:
        self._job_service.resume()

    def replace_runner(self, value: Any) -> None:
        self._job_service.replace_runner(value)

    def get_diagnostics_snapshot(self) -> dict[str, Any]:
        return self._job_service.get_diagnostics_snapshot()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._job_service, name)


def coerce_runtime_host(
    value: JobService | RuntimeHostPort | None,
) -> RuntimeHostPort | None:
    if value is None:
        return None
    if isinstance(value, LocalRuntimeHostAdapter):
        return value
    if isinstance(value, JobService):
        return LocalRuntimeHostAdapter(value)
    return cast(RuntimeHostPort, value)


def build_local_runtime_host(job_service: JobService) -> LocalRuntimeHostAdapter:
    return LocalRuntimeHostAdapter(job_service)


__all__ = [
    "LocalRuntimeHostAdapter",
    "build_local_runtime_host",
    "coerce_runtime_host",
]