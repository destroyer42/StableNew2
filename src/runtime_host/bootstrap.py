from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from src.app.bootstrap import (
    ApplicationKernel,
    build_runtime_host_kernel,
)
from src.app.optional_dependency_probes import OptionalDependencySnapshot
from src.controller.job_history_service import JobHistoryService
from src.controller.job_service import JobService
from src.controller.ports.runtime_ports import ImageRuntimePorts
from src.pipeline.pipeline_runner import normalize_run_result
from src.queue.job_history_store import JSONLJobHistoryStore
from src.queue.job_model import Job
from src.queue.job_queue import JobQueue
from src.queue.single_node_runner import SingleNodeJobRunner
from src.runtime_host.local_adapter import build_local_runtime_host
from src.runtime_host.managed_runtime import ManagedRuntimeOwner
from src.runtime_host.port import RuntimeHostPort
from src.utils import StructuredLogger
from src.utils.config import ConfigManager
from src.utils.error_envelope_v2 import (
    get_attached_envelope,
    serialize_envelope,
    wrap_exception,
)


@dataclass(frozen=True, slots=True)
class RuntimeHostBootstrap:
    kernel: ApplicationKernel
    history_path: Path
    job_queue: JobQueue
    history_store: JSONLJobHistoryStore
    history_service: JobHistoryService
    job_service: JobService
    runtime_host: RuntimeHostPort
    managed_runtime_owner: ManagedRuntimeOwner


class RuntimeHostJobExecutor:
    """Execute queue jobs inside the child runtime host through PipelineRunner.run_njr()."""

    def __init__(self, kernel: ApplicationKernel) -> None:
        self._kernel = kernel

    def __call__(self, job: Job) -> dict[str, Any]:
        record = getattr(job, "_normalized_record", None)
        if record is None:
            return normalize_run_result(
                {
                    "error": (
                        "Job is missing normalized_record; child runtime host "
                        "execution is NJR-only."
                    )
                },
                default_run_id=job.job_id,
            )

        try:
            result = self._kernel.pipeline_runner.run_njr(record)
        except Exception as exc:  # noqa: BLE001
            envelope = get_attached_envelope(exc)
            if envelope is None:
                envelope = wrap_exception(exc, subsystem="runtime_host")
            return normalize_run_result(
                {
                    "error": str(exc),
                    "error_envelope": serialize_envelope(envelope),
                },
                default_run_id=job.job_id,
            )

        if isinstance(result, Mapping):
            payload = dict(result)
        elif hasattr(result, "to_dict"):
            payload = result.to_dict()
        else:
            payload = {"result": result}
        return normalize_run_result(payload, default_run_id=job.job_id)


def _single_node_runner_factory(
    job_queue: JobQueue,
    run_callable: Any,
) -> SingleNodeJobRunner:
    return SingleNodeJobRunner(
        job_queue,
        run_callable=run_callable,
        poll_interval=0.05,
    )


def _resolve_history_path(history_path: Path | str | None) -> Path:
    if history_path is None:
        return Path("runs") / "runtime_host_job_history.jsonl"
    return Path(history_path)


def build_runtime_host_bootstrap(
    *,
    history_path: Path | str | None = None,
    config_manager: ConfigManager | None = None,
    runtime_ports: ImageRuntimePorts | None = None,
    structured_logger: StructuredLogger | None = None,
    api_url: str | None = None,
    capabilities: OptionalDependencySnapshot | None = None,
    pipeline_runner: Any | None = None,
    start_managed_runtimes: bool = False,
) -> RuntimeHostBootstrap:
    kernel = build_runtime_host_kernel(
        config_manager=config_manager,
        runtime_ports=runtime_ports,
        structured_logger=structured_logger,
        api_url=api_url,
        capabilities=capabilities,
    )
    if pipeline_runner is not None:
        kernel = replace(kernel, pipeline_runner=pipeline_runner)

    resolved_history_path = _resolve_history_path(history_path)
    resolved_history_path.parent.mkdir(parents=True, exist_ok=True)

    history_store = JSONLJobHistoryStore(resolved_history_path)
    job_queue = JobQueue(history_store=history_store)
    history_service = JobHistoryService(job_queue, history_store)
    job_executor = RuntimeHostJobExecutor(kernel)
    job_service = JobService(
        job_queue,
        runner_factory=_single_node_runner_factory,
        history_store=history_store,
        history_service=history_service,
        run_callable=job_executor,
        require_normalized_records=True,
    )
    runtime_host = build_local_runtime_host(job_service)
    managed_runtime_owner = ManagedRuntimeOwner()
    if start_managed_runtimes:
        managed_runtime_owner.start_background_bootstrap()
    return RuntimeHostBootstrap(
        kernel=kernel,
        history_path=resolved_history_path,
        job_queue=job_queue,
        history_store=history_store,
        history_service=history_service,
        job_service=job_service,
        runtime_host=runtime_host,
        managed_runtime_owner=managed_runtime_owner,
    )


__all__ = [
    "RuntimeHostBootstrap",
    "RuntimeHostJobExecutor",
    "build_runtime_host_bootstrap",
]