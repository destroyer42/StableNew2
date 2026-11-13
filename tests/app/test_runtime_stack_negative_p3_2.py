"""P3-2A negative tests: no second authority, no process action, no replay, fail closed.

N1 distinguishes *production construction sites* from *permitted non-production constructors*; a call site in neither
list fails. N2 and N4 exercise the new factory module (``src.app.runtime_stack``) and so cannot run on a tree without
it; N1 also encodes the post-change allowlist. Everything else is behavior that must hold before and after.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest

from src.controller.app_controller import AppController
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.queue.single_node_runner import SingleNodeJobRunner
from src.utils.logger import StructuredLogger, close_all_structured_loggers

REPO_ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------------------------------------- N1
# Production construction sites: where the running application is allowed to construct each authority.
PRODUCTION_SITES: dict[str, frozenset[str]] = {
    "JobRepository": frozenset({"src/app/runtime_stack.py"}),
    "JobQueue": frozenset({"src/app/runtime_stack.py"}),
    "SingleNodeJobRunner": frozenset({"src/app/runtime_stack.py"}),
    "JobService": frozenset({"src/app/runtime_stack.py"}),
    "WebUIOutageCoordinator": frozenset({"src/controller/job_service_outage.py"}),
    "GpuLossCoordinator": frozenset({"src/controller/job_service_outage.py"}),
    "PipelineRunner": frozenset({"src/controller/ports/default_runtime_ports.py"}),
    "RuntimeHandoffGate": frozenset({"src/controller/webui_outage_coordinator.py"}),
    "ComfyProcessManager": frozenset({"src/video/comfy_workflow_backend.py"}),
    "WebUIProcessManager": frozenset(
        {"src/main.py", "src/controller/webui_connection_controller.py"}
    ),
}

# Permitted non-production constructors, each with its reason. A site in neither table fails.
PERMITTED_NON_PRODUCTION: dict[tuple[str, str], str] = {
    (
        "JobRepository",
        "src/queue/job_queue.py",
    ): "JobQueue() default: test convenience, never the production path",
    (
        "SingleNodeJobRunner",
        "src/controller/job_service.py",
    ): "JobService default runner: test convenience",
    (
        "JobRepository",
        "src/migrations/sqlite_job_importer.py",
    ): "offline importer, not the application stack",
    (
        "WebUIProcessManager",
        "src/gui/main_window_v2.py",
    ): "dormant launcher run_app (OD-7, separate package)",
}

_TRACKED_NAMES = frozenset(PRODUCTION_SITES)


def _construction_sites() -> dict[tuple[str, str], int]:
    sites: dict[tuple[str, str], int] = {}
    for path in sorted((REPO_ROOT / "src").rglob("*.py")):
        relative = path.relative_to(REPO_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr
                if isinstance(func, ast.Attribute)
                else None
            )
            if name in _TRACKED_NAMES:
                sites[(name, relative)] = sites.get((name, relative), 0) + 1
    return sites


def test_n1_every_authority_construction_site_is_allowlisted() -> None:
    unexpected = []
    for (name, relative), count in _construction_sites().items():
        if relative in PRODUCTION_SITES[name] or (name, relative) in PERMITTED_NON_PRODUCTION:
            continue
        unexpected.append(f"{relative}: {name}( x{count}")
    assert not unexpected, "unallowlisted authority construction sites:\n" + "\n".join(unexpected)


def test_n1_the_runtime_stack_authorities_are_each_constructed_once_in_the_factory() -> None:
    sites = _construction_sites()
    for name in ("JobRepository", "JobQueue", "SingleNodeJobRunner", "JobService"):
        assert sites.get((name, "src/app/runtime_stack.py")) == 1, name


def test_n1_the_permitted_non_production_entries_are_still_live() -> None:
    """A stale exemption would hide a future second site: each listed pair must still exist."""

    sites = _construction_sites()
    stale = [pair for pair in PERMITTED_NON_PRODUCTION if pair not in sites]
    assert not stale, f"remove stale allowlist entries: {stale}"


# ---------------------------------------------------------------------------------------------------------- N2
def test_n2_existing_constructor_guards_reject_a_second_repository() -> None:
    from src.controller.job_execution_controller import JobExecutionController
    from src.controller.job_service import JobService

    first, second = JobRepository(), JobRepository()
    queue = JobQueue(repository=first)
    with pytest.raises(ValueError):
        JobExecutionController(repository=second, queue=queue)
    with pytest.raises(ValueError):
        JobService(queue, history_store=second)
    with pytest.raises(ValueError):
        JobQueue(repository=first, history_store=second)  # type: ignore[call-arg]


def test_n2_verify_rejects_a_service_that_disagrees_with_the_execution_controller(
    tmp_path: Path,
) -> None:
    from src.app.runtime_stack import RuntimeCompositionError

    controller = AppController(
        None,
        threaded=False,
        structured_logger=StructuredLogger(output_dir=str(tmp_path / "structured_logs")),
    )
    try:
        stack = controller.pipeline_controller.get_runtime_stack()
        stack.verify()  # the production stack is consistent

        service = stack.job_service
        jec = stack.job_execution_controller
        # The record is read-only: it stores identities only and cannot be reassigned.
        with pytest.raises(dataclasses.FrozenInstanceError):
            stack.job_service = object()  # type: ignore[misc]
        assert not hasattr(stack, "production")  # OD-6: no stored production flag in stage A

        other_queue = JobQueue(repository=JobRepository())
        other_runner = SingleNodeJobRunner(other_queue, lambda job: {})
        for attribute, value in (
            ("job_queue", other_queue),
            ("history_store", JobRepository()),
            ("_runner", other_runner),
        ):
            original = getattr(service, attribute)
            setattr(service, attribute, value)
            try:
                with pytest.raises(RuntimeCompositionError):
                    stack.verify()
            finally:
                setattr(service, attribute, original)
        stack.verify()
        assert jec.get_queue() is service.job_queue
    finally:
        controller.job_service.stop()
        close_all_structured_loggers()


# ---------------------------------------------------------------------------------------------------------- N3
def test_n3_replace_runner_keeps_one_observer_and_one_coordinator_pair(tmp_path: Path) -> None:
    controller = AppController(
        None,
        threaded=False,
        structured_logger=StructuredLogger(output_dir=str(tmp_path / "structured_logs")),
    )
    try:
        pipeline = controller.pipeline_controller
        service = controller.job_service
        queue = service.job_queue
        outage, gpu = service.webui_outage, service.gpu_loss
        old = service.runner
        repository = service.history_store
        before = len(repository._callbacks)

        replacement = SingleNodeJobRunner(queue, lambda job: {}, poll_interval=0.05)
        pipeline.replace_queue_runner(replacement)

        assert service.runner is replacement
        assert replacement._outage_observer is outage and replacement._gpu_loss_observer is gpu
        assert not old.is_running()
        assert len(repository._callbacks) == before == 1
    finally:
        controller.job_service.stop()
        close_all_structured_loggers()


# ---------------------------------------------------------------------------------------------------------- N4
class _PipelineControllerWithoutService:
    """A harness stub pipeline controller that yields no service."""

    def get_job_service(self) -> None:
        return None

    def get_job_execution_controller(self) -> None:
        return None


def test_n4_no_service_and_none_injected_fails_closed_without_building_a_repository(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from src.app.runtime_stack import RuntimeCompositionError

    built: list[object] = []
    original_init = JobRepository.__init__

    def recording_init(self, *args, **kwargs):
        built.append(self)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(JobRepository, "__init__", recording_init)
    with pytest.raises(RuntimeCompositionError):
        AppController(
            None,
            threaded=False,
            pipeline_controller=_PipelineControllerWithoutService(),
            structured_logger=StructuredLogger(output_dir=str(tmp_path / "structured_logs")),
        )
    close_all_structured_loggers()
    assert built == []


# ---------------------------------------------------------------------------------------------------------- N5/N6
def test_n5_n6_production_construction_and_shutdown_take_no_process_or_cancel_shortcut(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import src.api.webui_process_manager as webui_pm
    import src.video.comfy_process_manager as comfy_pm
    from src.controller.job_service import JobService

    webui_pm.clear_global_webui_process_manager()  # no leftover global manager from another test
    constructed: list[str] = []
    for cls in (webui_pm.WebUIProcessManager, comfy_pm.ComfyProcessManager):
        original = cls.__init__

        def recording(self, *a, __original=original, __name=cls.__name__, **k):
            constructed.append(__name)
            __original(self, *a, **k)

        monkeypatch.setattr(cls, "__init__", recording)
    process_actions: list[str] = []
    for method in ("start", "stop_webui", "restart_webui"):
        monkeypatch.setattr(
            webui_pm.WebUIProcessManager,
            method,
            lambda self, *a, __m=method, **k: process_actions.append(__m),
        )
    cancels: list[str] = []
    original_cancel_current = JobService.cancel_current
    monkeypatch.setattr(
        JobService,
        "cancel_current",
        lambda self, *a, **k: cancels.append("cancel_current")
        or original_cancel_current(self, *a, **k),
    )
    direct: list[str] = []
    for owner, name in (
        (JobQueue, "cancel_if_queued"),
        (JobQueue, "cancel_job"),
        (JobRepository, "cancel_job"),
    ):
        if hasattr(owner, name):
            monkeypatch.setattr(
                owner,
                name,
                lambda self, *a, __n=f"{owner.__name__}.{name}", **k: direct.append(__n),
            )
    generation: list[str] = []
    import src.api.client as api_client

    for name in ("txt2img", "img2img", "generate_images"):
        monkeypatch.setattr(
            api_client.SDWebUIClient,
            name,
            lambda self, *a, __n=name, **k: generation.append(__n),
            raising=False,
        )

    controller = AppController(
        None,
        threaded=False,
        structured_logger=StructuredLogger(output_dir=str(tmp_path / "structured_logs")),
    )
    assert constructed == []
    controller.shutdown_app("n5")

    assert constructed == []
    assert process_actions == []
    assert generation == []
    assert direct == []  # no direct queue or repository cancel from AppController
    assert len(cancels) == 1  # the only cancel route is JobService.cancel_current


def test_n6_one_cancel_token_per_claim_created_by_the_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.queue.single_node_runner as runner_module
    from tests.helpers.njr_factory import make_queue_job

    tokens: list[object] = []
    original = runner_module.CancelToken

    def counting_token(*args, **kwargs):
        token = original(*args, **kwargs)
        tokens.append(token)
        return token

    monkeypatch.setattr(runner_module, "CancelToken", counting_token)
    queue = JobQueue(repository=JobRepository())
    queue.submit(make_queue_job(job_id="n6-a"))
    queue.submit(make_queue_job(job_id="n6-b"))
    runner = SingleNodeJobRunner(queue, lambda job: {"success": True})
    for expected in (1, 2):
        job = queue.claim_next_job()
        assert job is not None
        runner.run_once(job)
        assert len(tokens) == expected
