"""The one construction site for the application's queue stack, and a read-only record of it (P3-2A).

``JobRepository``, ``JobQueue``, ``SingleNodeJobRunner`` and ``JobService`` are constructed here and nowhere else in the
running application. The owners that hold their dependencies (``JobExecutionController``, ``PipelineController``) call
these functions at the same point and in the same order they constructed the objects before, so recovery of interrupted
jobs, callback registration and the startup gate do not move.

``RuntimeStack`` is a frozen record of identities. It owns no lifecycle, process, cancellation or pause/auto-run state
and holds no production flag; it exists so one object can state, and verify, which repository, queue, runner and
service make up the stack. Two things stay out of this module on purpose: the full composition-root move into
``build_v2_app`` (a later decision) and any process manager.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.queue.job_model import Job, JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.queue.single_node_runner import SingleNodeJobRunner
from src.state.workspace_paths import workspace_paths

if TYPE_CHECKING:
    from src.app.review_gateway_sync import ReviewGatewaySync
    from src.controller.job_execution_controller import JobExecutionController
    from src.controller.job_history_service import JobHistoryService
    from src.controller.job_service import JobService


class RuntimeCompositionError(RuntimeError):
    """The runtime stack is inconsistent or could not be assembled; the application fails closed."""


def resolve_job_repository_location() -> str | Path:
    """The one rule for the application repository location.

    ``:memory:`` under pytest (hermetic tests never open the operator's database), otherwise the workspace repository.
    The environment test is temporary compatibility debt (OD-4), kept here so it exists once.
    """

    return ":memory:" if os.environ.get("PYTEST_CURRENT_TEST") else workspace_paths.job_repository()


def build_queue_stack(
    *,
    repository: JobRepository | None = None,
    queue: JobQueue | None = None,
    runner: SingleNodeJobRunner | None = None,
    run_callable: Callable[[Job], dict[str, Any]],
    on_status_change: Callable[[Job, JobStatus], None],
    poll_interval: float,
) -> tuple[JobRepository, JobQueue, SingleNodeJobRunner]:
    """Complete the repository, queue and runner triple, building only what was not supplied.

    Order is repository, then queue (which recovers interrupted jobs on construction), then runner.
    """

    if queue is not None and repository is None:
        repository = queue.repository
    if repository is None:
        repository = JobRepository(resolve_job_repository_location())
    if queue is None:
        queue = JobQueue(repository=repository)
    if runner is None:
        runner = SingleNodeJobRunner(
            queue, run_callable, poll_interval=poll_interval, on_status_change=on_status_change
        )
    return repository, queue, runner


@dataclass(frozen=True, slots=True, eq=False)
class RuntimeStack:
    """Identities of the one queue stack. Read-only; no behavior beyond ``verify``."""

    repository: JobRepository
    queue: JobQueue
    job_service: JobService
    history_service: JobHistoryService | None
    job_execution_controller: JobExecutionController

    @property
    def runner(self) -> Any:
        """The service's live runner (read through, so a coordinated runner replacement is never stale)."""

        return self.job_service.runner

    @property
    def webui_outage(self) -> Any:
        return getattr(self.job_service, "webui_outage", None)

    @property
    def gpu_loss(self) -> Any:
        return getattr(self.job_service, "gpu_loss", None)

    def verify(self) -> None:
        """Raise ``RuntimeCompositionError`` unless the controller, service, queue and repository agree."""

        service, controller = self.job_service, self.job_execution_controller
        problems = []
        if self.queue.repository is not self.repository:
            problems.append("queue does not project from the stack repository")
        if controller.get_queue() is not self.queue or service.job_queue is not self.queue:
            problems.append("controller and service do not share the stack queue")
        if (
            controller.get_history_store() is not self.repository
            or service.history_store is not self.repository
        ):
            problems.append("controller and service do not share the stack repository")
        runner: Any = controller.get_runner()  # protocol-typed on the service side
        if runner is not service.runner:
            problems.append("controller and service use different runners")
        history = self.history_service
        if history is not None and (
            history._queue is not self.queue or history._history is not self.repository
        ):
            problems.append("history service is not bound to the stack queue and repository")
        if problems:
            raise RuntimeCompositionError("; ".join(problems))


def assemble_runtime_stack(
    job_controller: JobExecutionController,
    job_service: JobService | None,
    history_service: JobHistoryService | None,
) -> RuntimeStack:
    """Record the stack around ``job_controller``, constructing the one ``JobService`` unless one was injected.

    A service built here is verified. An injected service (tests, harnesses) is recorded as given and left untouched:
    stand-ins need not expose every attribute, so ``verify`` is not forced on them.
    """

    repository = job_controller.get_history_store()
    queue = job_controller.get_queue()
    injected = job_service is not None
    if job_service is None:
        from src.controller.job_service import JobService

        runner: Any = job_controller.get_runner()
        job_service = JobService(
            queue,
            runner,
            repository,
            history_service=history_service,
            require_normalized_records=True,
        )
    stack = RuntimeStack(
        repository=repository,  # type: ignore[arg-type]
        queue=queue,
        job_service=job_service,
        history_service=history_service,
        job_execution_controller=job_controller,
    )
    if not injected:
        stack.verify()
    return stack


def build_review_gateway_sync(
    app: Any,
    *,
    state_dir: Path | None = None,
    records_path: Path | None = None,
    settings_store: Any = None,
    transport_factory: Any = None,
) -> ReviewGatewaySync:
    """Compose the phone review gateway sync worker (RG-120) around the running application; nothing starts here.

    The worker reads the Output Library index (never the job database), writes review evidence and archive moves
    through the native services, and has no path to the queue or the runner: action requests are refused until
    RG-140. ``app`` is the application controller; Discard refuses (fails closed) when its job queue is unreadable.
    """

    from src.app.review_gateway_apply import RecordApplier
    from src.app.review_gateway_publish import GatewayPublisher
    from src.app.review_gateway_store import GatewaySettingsStore, SyncLedger
    from src.app.review_gateway_sync import ReviewGatewaySync as Sync
    from src.app.site_media_files import SiteOutputError
    from src.app.site_output_library import OutputLibrary
    from src.learning.learning_paths import get_learning_records_path
    from src.review.archive import active_input_paths, configured_output_root, job_queue_of

    root = configured_output_root(getattr(app, "_config_manager", None))
    try:
        root = root.resolve(strict=True)
    except OSError:
        pass  # publishing waits until the Output folder exists; decisions then resolve nothing
    ledger = SyncLedger(state_dir / "ledger.sqlite3" if state_dir is not None else None)
    store = settings_store or GatewaySettingsStore(
        state_dir / "settings.dpapi" if state_dir is not None else None
    )
    queue = job_queue_of(app)

    def unreadable() -> set[str]:
        raise RuntimeError("the job queue is not reachable")

    active = (lambda: active_input_paths(queue)) if queue is not None else unreadable
    records = records_path or get_learning_records_path(create_parent=False)
    applier = RecordApplier(ledger, root, records, active_inputs=active)

    def busy() -> bool:
        runner = getattr(
            getattr(app, "job_service", None), "runner", None
        )  # read through: may be replaced
        return bool(getattr(runner, "current_job_id", None))

    owner: list[Sync] = []

    def require_active() -> None:
        if owner and owner[0].stopping:
            raise SiteOutputError("output_folder_not_shared")

    def publisher() -> GatewayPublisher | None:
        if not root.is_dir():
            return None
        library = OutputLibrary(
            root, "review-gateway", require_active, preview_idle=lambda: not busy()
        )
        return GatewayPublisher(library, ledger)

    extra = {"transport_factory": transport_factory} if transport_factory is not None else {}
    sync = Sync(
        settings_store=store,
        ledger=ledger,
        publisher_factory=publisher,
        applier=applier,
        busy=busy,
        **extra,
    )
    owner.append(sync)
    return sync
