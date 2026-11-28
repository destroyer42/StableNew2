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
    # N1b: completed runs in this repository are observed-execution evidence (read-only, off the Tk thread).
    from src.history.observed_execution import install_for_repository

    install_for_repository(repository)
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


def _gateway_actions(app: Any, ledger: Any, root: Path, records: Path) -> Any:
    """RG-140 phone actions over the running application, or ``None`` when it has no job repository."""

    from src.app.review_gateway_actions import AppActionCompiler, GatewayActions, admission_claim
    from src.app.site_phone_admission import admit_phone_records
    from src.app.site_phone_preview_host import PhonePreviewHost
    from src.app.site_phone_queue import PhoneQueueView, gateway_owner
    from src.controller.submission_policy_v26 import SubmissionPolicy
    from src.queue.job_model import JobPriority
    from src.review.review_lineage import repository_of

    repository = repository_of(app)
    if repository is None:
        return None

    def admit(owner: str, receipt: str, compiled: Any, warnings: Any, runs_next: bool) -> list[str]:
        jobs = app.job_service  # read through: it may be replaced
        return admit_phone_records(
            jobs,
            PhoneQueueView(repository, jobs),
            owner,
            receipt,
            compiled.kind,
            compiled.records,
            warnings,
            reprocess=compiled.reprocess,
            # D8 first step: touch-ups run after the current job, ahead of NORMAL work (the existing priority).
            policy=SubmissionPolicy(priority=JobPriority.HIGH if runs_next else JobPriority.NORMAL),
            claim=admission_claim(compiled),
        )

    def admitted(owner: str, receipt: str) -> list[str]:
        found = PhoneQueueView(repository, app.job_service).receipt(owner, receipt)
        return list(found["job_ids"]) if found["state"] == "admitted" else []

    compiler = AppActionCompiler(PhonePreviewHost(app, repository, records), repository, root)
    return GatewayActions(ledger, compiler, admit, owner_of=gateway_owner, admitted=admitted)


def _gateway_catalog(app: Any, ledger: Any, records: Path) -> Any:
    """RG-160: what the phone may choose, read from the running application (``None`` without a repository)."""

    from src.app.review_gateway_catalog import ChoiceCatalog
    from src.app.site_phone_preview_host import PhonePreviewHost
    from src.app.site_phone_video import gateway_video_label
    from src.image_backends.model_policy_warnings import shown_warning_for
    from src.review.review_lineage import repository_of

    repository = repository_of(app)
    if repository is None:
        return None
    return ChoiceCatalog(
        ledger,
        models=PhonePreviewHost(app, repository, records).gateway_models,
        warning_of=shown_warning_for,
        video=gateway_video_label,
    )


def _gateway_batch_of_job(app: Any, identity: Any) -> Any:
    """LEARN-JOIN: the batch stamped on a phone decision, read when it is applied (``None`` without a repository)."""

    from src.review.review_lineage import batch_of_job_reader, repository_of

    def read(job_id: str) -> Any:
        repository = repository_of(app)
        return batch_of_job_reader(repository, identity)(job_id) if repository is not None else None

    return read


def build_review_gateway_sync(
    app: Any,
    *,
    state_dir: Path | None = None,
    records_path: Path | None = None,
    settings_store: Any = None,
    transport_factory: Any = None,
) -> ReviewGatewaySync:
    """Compose the phone review gateway sync worker (RG-120) around the running application; nothing starts here.

    The worker reads the Output Library index (never the job database) and writes review evidence and archive moves
    through the native services. Phone actions (RG-140) from a device with the ``queue`` grant are compiled by the
    existing Preview and follow-up compilers and admitted only through ``admit_phone_records`` into
    ``JobService.submit_njrs``; without a job repository they are refused. ``app`` is the application controller;
    Discard refuses (fails closed) when its job queue is unreadable.
    """

    from src.app.review_gateway_apply import RecordApplier
    from src.app.review_gateway_origin import job_input_reader
    from src.app.review_gateway_publish import (
        GatewayPublisher,
        job_batch_reader,
        job_info_reader,
    )
    from src.app.review_gateway_ratings import RatingTaskSync
    from src.app.review_gateway_store import GatewaySettingsStore, SyncLedger
    from src.app.review_gateway_sync import ReviewGatewaySync as Sync
    from src.app.site_media_files import SiteOutputError
    from src.app.site_output_library import OutputLibrary
    from src.controller.app_controller_services.pack_model_batch_service import batch_identity
    from src.learning.learning_paths import get_learning_records_path
    from src.review.archive import active_input_paths, configured_output_root, job_queue_of
    from src.review.review_lineage import repository_of

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
    applier = RecordApplier(
        ledger,
        root,
        records,
        active_inputs=active,
        actions=_gateway_actions(app, ledger, root, records),
        batch_of_job=_gateway_batch_of_job(app, batch_identity),
    )

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
        repository = repository_of(app)
        # N5: the inbox groups an image by the named batch its job was queued in (read-only snapshot lookup).
        batch_of = job_batch_reader(repository, batch_identity) if repository is not None else None
        # PHONE-FAST: and shows an output beside the input image its job started from.
        input_of = job_input_reader(repository) if repository is not None else None
        # NAME-INFO: and says how each output was made ("More info").
        info_of = job_info_reader(repository, batch_identity)
        return GatewayPublisher(
            library, ledger, batch_of=batch_of, input_of=input_of, info_of=info_of
        )

    extra = {"transport_factory": transport_factory} if transport_factory is not None else {}
    sync = Sync(
        settings_store=store,
        ledger=ledger,
        publisher_factory=publisher,
        applier=applier,
        busy=busy,
        catalog=_gateway_catalog(app, ledger, records),
        **extra,
    )
    owner.append(sync)
    # RG-170: sittings registered beside the ledger are published to the phone; submitted ratings come back.
    sync.attach_rating_tasks(RatingTaskSync(ledger.path.parent / "rating_tasks", ledger))
    # PHONE-FAST: a finished job's outputs reach the phone without waiting for the busy-queue rate.
    jobs = getattr(app, "job_service", None)
    register = getattr(jobs, "register_completion_handler", None)
    if callable(register):
        register(lambda _job, _result: sync.notify_job_completed())
    return sync


def build_live_update_service(
    app: Any,
    *,
    state_dir: Path | None = None,
    repo_root: Path | None = None,
    launch_updater: Callable[[Any], None] | None = None,
) -> Any:
    """Compose the live update service (LAUNCH-UPDATE-1) around the running application; nothing starts here.

    The checkout is the one this process runs from. The preflight compares ``origin`` with the expected repository,
    asks GitHub whether it signed the target commit (SAFE-UPDATE; desktop and phone requests alike) and runs the
    launcher's read-only environment check with this interpreter. The only queue effect is the in-memory
    update hold; the busy probe counts the runner's current job and any RUNNING job in the queue. Without a queue that
    supports the hold the service refuses every update (``queue_unavailable``).
    """

    import sys

    from src.app import live_update as lu
    from src.app.live_update_service import LiveUpdateService
    from src.review.archive import job_queue_of

    root = repo_root or lu.REPO_ROOT
    git = lu.subprocess_git(root)
    env_check = lu.environment_check(
        root,
        python=Path(sys.executable),
        read_file=lambda sha, path: lu.read_target_file(git, sha, path),
    )

    signature_check = lu.github_signature_check()

    def preflight(expected_sha: str | None) -> lu.Preflight:
        return lu.preflight(
            git,
            expected_sha=expected_sha,
            expected_origin=lu.EXPECTED_ORIGIN,
            env_check=env_check,
            signature_check=signature_check,
        )

    queue = job_queue_of(app)

    def busy() -> bool:
        runner = getattr(
            getattr(app, "job_service", None), "runner", None
        )  # read through: may be replaced
        if getattr(runner, "current_job_id", None):
            return True
        lister = getattr(queue, "list_jobs", None)
        return bool(callable(lister) and lister(status_filter=JobStatus.RUNNING))

    hold = queue if callable(getattr(queue, "hold_dispatch_for_update", None)) else None
    return LiveUpdateService(
        store=lu.LiveUpdateStore(state_dir or lu.default_state_dir()),
        preflight=preflight,
        queue=hold,
        busy=busy,
        launch_updater=launch_updater or lu.launch_updater_process,
        repo_root=root,
        pid=os.getpid(),
    )


def build_remote_update(app: Any, service: Any, *, spawn: Callable[..., None] | None = None) -> Any:
    """Compose the phone side of a live update (LAUNCH-UPDATE-2) around a ``LiveUpdateService``; nothing starts here.

    The status probe reads the same checkout as the service, under the service's Git lock. The queue view is counts
    only: idle, running or paused, and how many jobs wait.
    """

    from src.app import live_update as lu
    from src.app.live_update_remote import CheckoutProbe, RemoteUpdate
    from src.review.archive import job_queue_of

    queue = job_queue_of(app)

    def queue_state() -> tuple[str, int]:
        if queue is None:
            return "unknown", 0
        queued = len(queue.list_jobs(status_filter=JobStatus.QUEUED))
        runner = getattr(getattr(app, "job_service", None), "runner", None)
        running = bool(getattr(runner, "current_job_id", None)) or bool(
            queue.list_jobs(status_filter=JobStatus.RUNNING)
        )
        if running:
            return "running", queued
        paused = getattr(queue, "is_paused", None)
        return ("paused" if callable(paused) and paused() else "idle"), queued

    if spawn is None:
        probe = CheckoutProbe(lu.subprocess_git(service.repo_root), git_lock=service.git_lock)
        return RemoteUpdate(service, checkout=probe, queue_state=queue_state)
    probe = CheckoutProbe(
        lu.subprocess_git(service.repo_root), git_lock=service.git_lock, spawn=spawn
    )
    return RemoteUpdate(service, checkout=probe, queue_state=queue_state, spawn=spawn)
