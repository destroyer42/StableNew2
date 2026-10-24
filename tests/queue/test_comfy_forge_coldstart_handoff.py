"""PR-RUNTIME-HANDOFF: a queued image job gets a ready, correctly identified managed WebUI after Comfy video work.

Real ``JobQueue`` / SQLite ``JobRepository`` / ``SingleNodeJobRunner`` / ``WebUIOutageCoordinator`` / ``JobService``
bindings, the real ``RuntimeTransitionCoordinator`` and the real ``ForgeWebUIImageBackend`` / ``A1111WebUIImageBackend``
``execute()`` guards. Only the machine is fake: a ``World`` models which runtimes are up, the process managers are
fakes over it, and generation transport is a counter. Nothing starts a real WebUI, Comfy, GPU or HTTP service.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from src.api.webui_identity_attestation import ManagedWebUIIdentityAttestor
from src.api.webui_process_manager import WebUIContainmentError, WebUIStartupError
from src.api.webui_runtime_identity import (
    A1111_WEBUI_IDENTITY,
    FORGE_WEBUI_IDENTITY,
    WebUIRuntimeIdentity,
)
from src.controller.webui_outage_coordinator import ProbeResult, WebUIHealth, WebUIOutageCoordinator
from src.image_backends import (
    A1111WebUIImageBackend,
    ForgeWebUIImageBackend,
    ImageExecutionRequest,
    resolve_image_backend_id,
)
from src.pipeline.stage_models import StageType
from src.queue.job_model import JobPriority, JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.queue.single_node_runner import SingleNodeJobRunner
from src.services.runtime_transition_service import (
    RuntimeTransitionCoordinator,
    RuntimeTransitionError,
)
from tests.helpers.njr_factory import make_queue_job, make_stage_config

URL = "http://127.0.0.1:7871"
DEADLINE = 8.0
FORGE_OPTIONS = {"image": {"backend_id": "forge_webui"}}


# -- job builders ----------------------------------------------------------------------------------------------------


def forge(job_id: str, priority: JobPriority = JobPriority.NORMAL):
    return make_queue_job(job_id, priority=priority, backend_options=FORGE_OPTIONS)


def legacy_a1111(job_id: str):
    """A persisted record with no explicit image identity: it resolves as A1111 exactly as at execution."""

    return make_queue_job(job_id)


def comfy(job_id: str):
    return make_queue_job(
        job_id,
        stage_chain=[make_stage_config("video_workflow")],
        config={"video_workflow": {"video_execution": {"backend_id": "comfy"}}},
    )


def svd(job_id: str):
    return make_queue_job(
        job_id,
        stage_chain=[
            make_stage_config(StageType.TXT2IMG, enabled=False),
            make_stage_config("svd_native"),
        ],
    )


# -- the fake machine ------------------------------------------------------------------------------------------------


class World:
    """Which runtimes are up, what answers on the WebUI endpoint, and what happened to them."""

    def __init__(self, *, forge_up: bool = True, identity: str = FORGE_WEBUI_IDENTITY) -> None:
        self.webui_up = forge_up  # a managed process is serving the configured endpoint
        self.webui_pending = False  # launched, not yet serving
        self.webui_identity = identity  # what a serving managed process classifies as
        self.external: str | None = (
            None  # "forge" | "a1111" | "unknown": a process StableNew did not launch
        )
        self.comfy_up = False
        self.comfy_external = False
        self.comfy_left_running = False
        self.launch_error: BaseException | None = None
        self.boot = "ok"  # "ok" | "timeout" | "exit"
        self.boot_identity = identity
        self.launches = 0
        self.posts: list[str] = []
        self.post_backend: dict[str, str] = {}
        self.log: list[str] = []
        self.gate: threading.Event | None = None  # holds a boot open
        self.release_after_comfy_job = True

    # what the endpoint classifies as right now
    def serving_identity(self) -> str | None:
        if self.external is not None:
            return {
                "forge": FORGE_WEBUI_IDENTITY,
                "a1111": A1111_WEBUI_IDENTITY,
                "unknown": "unknown",
            }[self.external]
        return self.webui_identity if self.webui_up else None

    def endpoint_present(self) -> bool:
        return self.serving_identity() is not None

    def target_probe(self, target: str) -> ProbeResult:
        identity = self.serving_identity()
        if identity is None:
            return ProbeResult(False, "endpoint_free", URL)
        if self.external == "unknown":
            return ProbeResult(False, "endpoint_occupied", URL)
        if identity == "unknown":
            return ProbeResult(
                False, "identity_unsupported", URL, "unknown", recovery_allowed=False
            )
        if identity != target and not (
            target == A1111_WEBUI_IDENTITY and identity != FORGE_WEBUI_IDENTITY
        ):
            return ProbeResult(False, "identity_mismatch", URL, identity, recovery_allowed=False)
        return ProbeResult(True, "ready", URL, identity)

    def configured_probe(self) -> ProbeResult:
        return self.target_probe(FORGE_WEBUI_IDENTITY)

    def client_identity(self) -> WebUIRuntimeIdentity:
        identity = self.serving_identity()
        if identity is None:
            raise ConnectionError("connection refused")
        return WebUIRuntimeIdentity(identity)


class FakeWebUIManager:
    """The single WebUIProcessManager slot: launches only on ``start()``, never adopts an external."""

    endpoint = URL

    def __init__(
        self, world: World, *, identity: str = FORGE_WEBUI_IDENTITY, autostart: bool = True
    ) -> None:
        self.world = world
        self.runtime_identity = identity
        self.autostart_enabled = autostart
        self.startup_timeout_seconds = 0.25
        self._owned = world.webui_up
        self.ready_epoch = 1 if world.webui_up else 0
        self.stops = 0
        self.listeners: list[Callable[[Any], None]] = []

    @property
    def owns_process(self) -> bool:
        return self._owned

    @property
    def pid(self) -> int:
        return 4242

    def is_running(self) -> bool:
        return self._owned and (self.world.webui_up or self.world.webui_pending)

    def stop_webui(self, *_a: Any, **_k: Any) -> bool:
        self.stops += 1
        if self._owned:
            self.world.log.append("webui_stop")
            self.world.webui_up = False
            self.world.webui_pending = False
            self._owned = False
        return True

    def start(self) -> None:
        self.world.launches += 1
        self.world.log.append(f"webui_launch(comfy_up={self.world.comfy_up})")
        if self.world.launch_error is not None:
            raise self.world.launch_error
        if self.world.external is not None:
            raise WebUIStartupError("Configured WebUI endpoint is already occupied.")
        self._owned = True
        self.world.webui_pending = True

    def restart_webui(self, **_k: Any) -> bool:  # pragma: no cover - the handoff must never call it
        raise AssertionError("the cold-start handoff must not use the recovery-only restart")

    def get_stdout_tail_text(self, _lines: int = 40) -> str:
        return ""

    def add_ready_listener(self, listener: Callable[[Any], None]) -> None:
        if listener not in self.listeners:
            self.listeners.append(listener)

    def mark_ready(self, *, source: str = "test") -> None:
        self.ready_epoch += 1
        event = SimpleNamespace(epoch=self.ready_epoch, source=source)
        for listener in list(self.listeners):
            listener(event)

    def wait_ready(self, _manager: Any, _base_url: str, timeout_s: float) -> None:
        """Stands in for ``wait_for_managed_startup``: ready, never ready, or the process exited."""

        if self.world.gate is not None:
            assert self.world.gate.wait(DEADLINE)
        if self.world.boot == "exit":
            raise WebUIStartupError("WebUI exited before it became ready (exit code 1)")
        if self.world.boot == "timeout":
            time.sleep(min(timeout_s, 0.01))
            raise TimeoutError("WebUI did not become ready")
        self.world.webui_pending = False
        self.world.webui_up = True
        self.world.webui_identity = self.world.boot_identity
        self.mark_ready(source="startup")

    def operator_launches(self, identity: str | None = None) -> None:
        """The operator starts it by hand (Launch/Retry): a live owned process and a readiness epoch."""

        self._owned = True
        self.world.webui_pending = False
        self.world.webui_up = True
        self.world.webui_identity = identity or self.runtime_identity
        self.mark_ready(source="operator")


class FakeComfyManager:
    def __init__(self, world: World) -> None:
        self.world = world
        self.stops = 0

    @property
    def owns_process(self) -> bool:
        return self.world.comfy_up and not self.world.comfy_external

    def is_running(self) -> bool:
        return self.world.comfy_up

    def stop(self) -> bool:
        self.stops += 1
        self.world.log.append("comfy_stop")
        self.world.comfy_up = False
        return True


class FakeSVD:
    def clear_model_cache(self) -> None:
        return None


class Stack:
    def __init__(
        self,
        tmp_path: Path,
        world: World,
        *,
        manager: FakeWebUIManager | None | str = "default",
        armed: bool = True,
        release_interval_s: float = 0.0,
        auto_run: bool = True,
    ) -> None:
        self.world = world
        self.manager: FakeWebUIManager | None = (
            FakeWebUIManager(world) if manager == "default" else manager
        )  # type: ignore[assignment]
        self.comfy_manager = FakeComfyManager(world)
        self.transition = RuntimeTransitionCoordinator(
            webui_manager_getter=lambda: self.manager,
            comfy_manager_getter=lambda: self.comfy_manager,
            svd_service_factory=FakeSVD,
            webui_endpoint_present=world.endpoint_present,
            webui_endpoint_identity=lambda: world.serving_identity() or "unknown",
            comfy_endpoint_present=lambda: world.comfy_external,
        )
        self.repository = JobRepository(tmp_path / "queue.db")
        self.queue = JobQueue(repository=self.repository)
        self.calls: list[str] = []
        self._lock = threading.Lock()
        self.coordinator = WebUIOutageCoordinator(
            self.queue,
            probe=world.configured_probe,
            manager_getter=lambda: self.manager,
            release_interval_s=release_interval_s,
        )
        self.runner = SingleNodeJobRunner(
            self.queue,
            self._run,
            poll_interval=0.005,
            held_poll_interval=0.02,
            outage_observer=self.coordinator,
        )
        self._attestor = ManagedWebUIIdentityAttestor(
            manager_getter=lambda: None
        )  # no owned-session attestation
        self._backends = {
            "forge_webui": ForgeWebUIImageBackend(
                transition=self.transition, identity_attestor=self._attestor
            ),
            "a1111_webui": A1111WebUIImageBackend(
                transition=self.transition, identity_attestor=self._attestor
            ),
        }
        self.handoff: Any = None
        if armed:
            self.arm()

    def arm(self) -> None:
        from src.controller.webui_runtime_handoff import WebUIRuntimeHandoff

        manager = self.manager
        self.handoff = WebUIRuntimeHandoff(
            transition=self.transition,
            manager_getter=lambda: self.manager,
            target_probe=self.world.target_probe,
            waiter=(manager.wait_ready if manager is not None else (lambda *_a: None)),
            sleeper=lambda _s: None,
            proof_settle_s=0.05,
        )
        self.coordinator.enable_runtime_handoff(self.handoff)

    # -- the production-shaped run callable --------------------------------------------------------------------------

    def _run(self, job: Any) -> Any:
        with self._lock:
            self.calls.append(job.job_id)
        record = job._normalized_record
        kind = str(record.workload_kind.value)
        if kind == "video" and "video_workflow" in {
            s.stage_type for s in record.stages if s.enabled
        }:
            return self._run_comfy(job)
        if kind == "video":
            return {"success": True}
        return self._run_image(job)

    def _run_comfy(self, job: Any) -> dict[str, Any]:
        result = self.transition.prepare_for(
            "comfy"
        )  # releases an owned WebUI, exactly as the Comfy backend does
        if not result.ready:
            raise RuntimeTransitionError(result)
        self.world.comfy_up = True
        self.world.log.append(f"comfy_run({job.job_id})")
        if (
            self.world.release_after_comfy_job
        ):  # the Comfy backend releases its owned runtime after each job
            self.comfy_manager.stop()
        return {"success": True}

    def _run_image(self, job: Any) -> dict[str, Any]:
        backend_id = resolve_image_backend_id(record_backend_options(job))
        pipeline = Mock()
        modules: list[str] = []
        pipeline.client = SimpleNamespace(
            probe_runtime_identity=self.world.client_identity,
            base_url=URL,
            get_additional_modules=lambda: list(modules),
            set_additional_modules=lambda selection: modules.__setitem__(
                slice(None), list(selection)
            )
            or True,
        )

        def post(*_a: Any, **_k: Any) -> dict[str, Any]:
            self.world.posts.append(job.job_id)
            self.world.post_backend[job.job_id] = backend_id
            return {"path": "out.png", "all_paths": ["out.png"]}

        pipeline.run_txt2img_stage.side_effect = post
        request = ImageExecutionRequest(
            backend_id=backend_id,
            stage_name="txt2img",
            stage_config={},
            output_dir=Path("."),
            image_name="x",
            prompt="p",
            job_id=job.job_id,
        )
        self._backends[backend_id].execute(pipeline, request)
        return {"success": True}

    # -- helpers -----------------------------------------------------------------------------------------------------

    def submit(self, *jobs: Any) -> None:
        for job in jobs:
            self.queue.submit(job)

    def status(self, job_id: str) -> JobStatus:
        job = self.queue.get_job(job_id)
        assert job is not None, job_id
        return job.status

    def queued_order(self) -> list[str]:
        return [
            job.job_id
            for job in self.queue.list_active_jobs_ordered()
            if job.status is JobStatus.QUEUED
        ]

    def start(self) -> None:
        self.runner.start()

    def close(self) -> None:
        if self.world.gate is not None:
            self.world.gate.set()
        self.runner.stop(timeout=3)


def record_backend_options(job: Any) -> dict[str, Any]:
    return dict(job._normalized_record.workload.backend_options)


@pytest.fixture
def make_stack(tmp_path: Path):
    stacks: list[Stack] = []

    def factory(world: World, **kwargs: Any) -> Stack:
        stack = Stack(_fresh(tmp_path, len(stacks)), world, **kwargs)
        stacks.append(stack)
        return stack

    yield factory
    for stack in stacks:
        stack.close()


def _fresh(tmp_path: Path, index: int) -> Path:
    path = tmp_path / f"stack{index}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def wait_for(predicate: Callable[[], bool], timeout: float = DEADLINE) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not reached before the deadline")


def settle(seconds: float = 0.3) -> None:
    threading.Event().wait(seconds)


def all_completed(stack: Stack, *job_ids: str) -> bool:
    return all(stack.status(job_id) is JobStatus.COMPLETED for job_id in job_ids)


# =====================================================================================================================
# 1-2. The reproduced gap: alternating runtimes through the production queue
# =====================================================================================================================


@pytest.mark.parametrize("comfy_left_running", [False, True])
def test_alternating_forge_comfy_forge_comfy_completes_through_the_canonical_queue(
    make_stack, comfy_left_running
):
    world = World(forge_up=True)
    world.release_after_comfy_job = not comfy_left_running
    stack = make_stack(world)
    stack.submit(forge("F1"), comfy("C1"), forge("F2"), comfy("C2"), forge("F3"))
    stack.start()

    wait_for(lambda: all_completed(stack, "F1", "C1", "F2", "C2", "F3"))

    assert stack.calls == [
        "F1",
        "C1",
        "F2",
        "C2",
        "F3",
    ]  # FIFO preserved across the hold and the launches
    assert world.posts == ["F1", "F2", "F3"]  # exactly one generation dispatch per image job
    assert world.launches == 2  # F1 found Forge up; F2 and F3 each needed a managed launch
    assert all("comfy_up=False" in entry for entry in world.log if entry.startswith("webui_launch"))
    assert stack.queue.is_webui_held() is False
    assert stack.coordinator.snapshot()["status"] == WebUIHealth.HEALTHY.value


def test_a_stopped_forge_is_not_started_speculatively_after_video_work(make_stack):
    world = World(forge_up=True)
    stack = make_stack(world)
    stack.submit(forge("F1"), comfy("C1"))
    stack.start()
    wait_for(lambda: all_completed(stack, "F1", "C1"))
    settle()

    assert world.launches == 0  # no eligible image work needs Forge, so nothing launches it
    assert world.webui_up is False and stack.queue.is_webui_held() is False


def test_forge_starts_only_when_the_image_job_is_the_next_workload(make_stack):
    world = World(forge_up=False)
    stack = make_stack(world)
    stack.submit(comfy("C1"), forge("F1"))
    stack.start()
    wait_for(lambda: all_completed(stack, "C1", "F1"))

    launch_at = next(i for i, entry in enumerate(world.log) if entry.startswith("webui_launch"))
    assert launch_at > world.log.index(
        "comfy_run(C1)"
    )  # video first (queue order); Forge only afterwards
    assert world.launches == 1 and world.posts == ["F1"]


# =====================================================================================================================
# 3. External runtimes are immutable
# =====================================================================================================================


def test_external_comfy_blocks_the_launch_and_is_never_touched(make_stack):
    world = World(forge_up=False)
    world.comfy_external = True
    world.comfy_up = True
    stack = make_stack(world)
    stack.submit(forge("F1"))
    stack.start()
    settle(0.5)

    assert stack.status("F1") is JobStatus.QUEUED and world.launches == 0 and world.posts == []
    assert stack.comfy_manager.stops == 0 and world.comfy_up is True
    snapshot = stack.coordinator.snapshot()
    assert snapshot["status"] == WebUIHealth.ACTION_REQUIRED.value
    assert "comfy" in snapshot["message"].lower() and "will not" in snapshot["message"].lower()


def test_an_external_matching_forge_is_used_without_adoption_or_launch(make_stack):
    world = World(forge_up=False)
    world.external = "forge"
    stack = make_stack(world, manager=FakeWebUIManager(world))
    stack.submit(forge("F1"))
    stack.start()

    wait_for(lambda: all_completed(stack, "F1"))
    assert world.launches == 0 and stack.manager.stops == 0 and stack.manager.owns_process is False
    assert world.posts == ["F1"]


@pytest.mark.parametrize(
    ("external", "needle"),
    [("a1111", "identity"), ("unknown", "endpoint")],
)
def test_a_mismatched_or_ambiguous_external_webui_holds_the_job_and_is_never_replaced(
    make_stack, external, needle
):
    world = World(forge_up=False)
    world.external = external
    stack = make_stack(world)
    stack.submit(forge("F1"), svd("S1"))
    stack.start()

    wait_for(lambda: all_completed(stack, "S1"))
    settle(0.4)
    assert stack.status("F1") is JobStatus.QUEUED and world.posts == []
    assert world.launches == 0 and stack.manager.stops == 0
    snapshot = stack.coordinator.snapshot()
    assert snapshot["status"] == WebUIHealth.ACTION_REQUIRED.value
    assert needle in snapshot["message"].lower()

    world.external = "forge"  # the operator fixes it: a fresh proof releases the hold, the job runs
    wait_for(lambda: all_completed(stack, "F1"))
    assert world.launches == 0


# =====================================================================================================================
# 4. Startup failure keeps the job queued; later legitimate recovery
# =====================================================================================================================


def _force_failure(world: World, kind: str) -> str:
    if kind == "refusal":
        world.launch_error = WebUIStartupError("Failed to start WebUI: refused")
        return "launch_refused"
    if kind == "containment":
        world.launch_error = WebUIContainmentError("WebUI containment failed: job object refused")
        return "containment_failed"
    if kind == "timeout":
        world.boot = "timeout"
        return "startup_timeout"
    if kind == "exit":
        world.boot = "exit"
        return "startup_exited"
    world.boot_identity = "unknown"  # it serves, but never proves Forge
    return "identity_unproven"


@pytest.mark.parametrize("kind", ["refusal", "containment", "timeout", "exit", "identity"])
def test_a_failed_startup_leaves_the_job_queued_is_not_retried_every_cycle_and_recovers_later(
    make_stack, kind
):
    world = World(forge_up=False)
    reason = _force_failure(world, kind)
    stack = make_stack(world)
    stack.submit(forge("F1"))
    before = dict(stack.queue.get_job("F1").snapshot)
    stack.start()
    wait_for(lambda: stack.coordinator.snapshot()["status"] == WebUIHealth.ACTION_REQUIRED.value)
    settle(0.6)  # many worker cycles

    assert world.launches == 1  # one bounded attempt, not one per polling cycle
    assert stack.status("F1") is JobStatus.QUEUED and world.posts == []
    job = stack.queue.get_job("F1")
    assert job.snapshot == before and job.priority == JobPriority.NORMAL
    snapshot = stack.coordinator.snapshot()
    assert snapshot["last_recovery_result"] == reason
    assert stack.queue.is_paused() is False  # a backend-scoped hold, never the user's pause

    # A manager readiness epoch alone proves nothing; the operator's real Launch does.
    stack.manager.mark_ready(source="noise")
    settle(0.2)
    assert stack.status("F1") is JobStatus.QUEUED and world.posts == []
    world.launch_error, world.boot, world.boot_identity = None, "ok", FORGE_WEBUI_IDENTITY
    stack.manager.operator_launches()
    wait_for(lambda: all_completed(stack, "F1"))
    assert world.posts == ["F1"] and stack.queue.is_webui_held() is False


def test_a_new_readiness_epoch_allows_exactly_one_new_attempt(make_stack):
    world = World(forge_up=False)
    world.boot = "timeout"
    stack = make_stack(world)
    stack.submit(forge("F1"))
    stack.start()
    wait_for(lambda: world.launches == 1)
    settle(0.4)
    assert world.launches == 1

    stack.manager.mark_ready(source="operator_retry_that_crashed")  # new epoch, endpoint still dead
    wait_for(lambda: world.launches == 2)
    settle(0.4)
    assert world.launches == 2 and stack.status("F1") is JobStatus.QUEUED


def test_holds_retain_jobs_identity_and_order_while_independent_video_continues(make_stack):
    world = World(forge_up=False)
    world.launch_error = WebUIStartupError("refused")
    stack = make_stack(world)
    stack.submit(
        forge("F-low", JobPriority.LOW),
        forge("F-n1"),
        svd("S1"),
        forge("F-high", JobPriority.HIGH),
        comfy("C1"),
        forge("F-n2"),
    )
    originals = {
        j: dict(stack.queue.get_job(j).snapshot) for j in ("F-low", "F-n1", "F-high", "F-n2")
    }
    stack.start()

    wait_for(lambda: all_completed(stack, "S1", "C1"))
    settle(0.4)
    assert stack.queued_order() == [
        "F-high",
        "F-n1",
        "F-n2",
        "F-low",
    ]  # priority, then FIFO, unchanged
    assert {j: dict(stack.queue.get_job(j).snapshot) for j in originals} == originals
    assert world.launches == 1 and world.posts == []
    assert stack.calls.count("F-high") == 0


# =====================================================================================================================
# 5. Quarantine, pause, fence, configuration
# =====================================================================================================================


def test_gpu_quarantine_prevents_launch_and_dispatch_and_is_never_released_implicitly(make_stack):
    world = World(forge_up=False)
    stack = make_stack(world)
    stack.queue.quarantine_gpu_dispatch({"incident_id": "gpu-1"})
    stack.submit(forge("F1"))
    stack.start()
    settle(0.5)

    assert world.launches == 0 and world.posts == [] and stack.status("F1") is JobStatus.QUEUED
    assert stack.queue.is_gpu_quarantined() is True
    assert stack.coordinator.prepare_next_dispatch(force=True) == "not_applicable"
    assert world.launches == 0


def test_pause_prevents_launch_and_resume_continues(make_stack):
    world = World(forge_up=False)
    stack = make_stack(world)
    stack.queue.pause()
    stack.submit(forge("F1"))
    stack.start()
    settle(0.4)
    assert world.launches == 0 and stack.status("F1") is JobStatus.QUEUED

    stack.queue.resume()
    wait_for(lambda: all_completed(stack, "F1"))
    assert world.launches == 1


def test_the_shutdown_fence_prevents_launch_and_claim(make_stack):
    world = World(forge_up=False)
    stack = make_stack(world)
    stack.submit(forge("F1"))
    stack.queue.fence_dispatch()

    assert stack.coordinator.prepare_next_dispatch(force=True) == "not_applicable"
    assert world.launches == 0 and stack.queue.claim_next_job() is None


def test_a_fence_during_the_startup_wait_abandons_the_wait_without_failing_or_dispatching(
    make_stack,
):
    world = World(forge_up=False)
    world.gate = threading.Event()
    stack = make_stack(world)
    stack.submit(forge("F1"))
    stack.start()
    wait_for(lambda: world.launches == 1)
    stack.queue.fence_dispatch()
    world.gate.set()

    settle(0.4)
    assert stack.status("F1") is JobStatus.QUEUED and world.posts == []


def test_disabled_autostart_and_missing_launch_configuration_are_actionable_and_launch_nothing(
    make_stack,
):
    world = World(forge_up=False)
    stack = make_stack(world, manager=FakeWebUIManager(world, autostart=False))
    stack.submit(forge("F1"))
    stack.start()
    wait_for(lambda: stack.coordinator.snapshot()["status"] == WebUIHealth.ACTION_REQUIRED.value)
    settle(0.3)
    assert world.launches == 0 and stack.status("F1") is JobStatus.QUEUED
    assert "autostart" in stack.coordinator.snapshot()["message"].lower()

    stack.manager.autostart_enabled = (
        True  # the operator re-enables it: the next evaluation starts it
    )
    wait_for(lambda: all_completed(stack, "F1"))
    assert world.launches == 1

    none_world = World(forge_up=False)
    none_stack = make_stack(none_world, manager=None)
    none_stack.submit(forge("F2"))
    none_stack.start()
    wait_for(
        lambda: none_stack.coordinator.snapshot()["status"] == WebUIHealth.ACTION_REQUIRED.value
    )
    assert none_world.launches == 0 and none_stack.status("F2") is JobStatus.QUEUED
    assert "managed" in none_stack.coordinator.snapshot()["message"].lower()


# =====================================================================================================================
# 6. Manual Run Next, single flight, no replay
# =====================================================================================================================


def test_manual_run_next_cold_starts_on_its_worker_and_does_not_block_the_caller(make_stack):
    world = World(forge_up=False)
    world.gate = threading.Event()
    stack = make_stack(world)
    stack.submit(forge("F1"))

    started = time.monotonic()
    assert stack.runner.run_next_once() is True  # the launch happens on the one-shot worker
    assert time.monotonic() - started < 1.0
    wait_for(lambda: world.launches == 1)
    assert stack.runner.run_next_once() is False  # a worker is already preparing: single flight

    world.gate.set()
    wait_for(lambda: all_completed(stack, "F1"))
    assert world.launches == 1 and world.posts == ["F1"]


def test_manual_run_next_after_a_failure_is_one_new_bounded_attempt(make_stack):
    world = World(forge_up=False)
    world.launch_error = WebUIStartupError("refused")
    stack = make_stack(world)
    stack.submit(forge("F1"))

    assert stack.runner.run_next_once() is True
    wait_for(lambda: world.launches == 1 and not stack.runner.is_running())
    assert stack.status("F1") is JobStatus.QUEUED

    assert (
        stack.runner.run_next_once() is True
    )  # the operator asked again: one more attempt, not a loop
    wait_for(lambda: world.launches == 2 and not stack.runner.is_running())
    settle(0.2)
    assert world.launches == 2 and stack.status("F1") is JobStatus.QUEUED and world.posts == []


def test_concurrent_callers_start_one_managed_launch_and_dispatch_once(make_stack):
    world = World(forge_up=False)
    world.gate = threading.Event()
    stack = make_stack(world)
    stack.submit(forge("F1"))
    results: list[str] = []
    threads = [
        threading.Thread(
            target=lambda: results.append(stack.coordinator.prepare_next_dispatch(force=True))
        )
        for _ in range(4)
    ]
    for thread in threads:
        thread.start()
    wait_for(lambda: world.launches == 1)
    wait_for(
        lambda: len(results) >= 3
    )  # the losers return at once as held; they never wait or launch
    assert results.count("held") == 3
    world.gate.set()
    for thread in threads:
        thread.join(timeout=DEADLINE)

    assert world.launches == 1 and sorted(results).count("started") == 1
    stack.start()
    wait_for(lambda: all_completed(stack, "F1"))
    assert world.posts == ["F1"]


def test_an_ambiguous_generation_dispatch_is_never_replayed_by_the_handoff(make_stack):
    world = World(forge_up=True)
    stack = make_stack(world)
    real = stack._run_image

    def dispatch_then_lose_the_runtime(job: Any) -> dict[str, Any]:
        real(job)
        world.webui_up = False  # the runtime dies after the POST went out
        raise RuntimeError("Connection reset while waiting for the txt2img response")

    stack._run_image = dispatch_then_lose_the_runtime  # type: ignore[method-assign]
    stack.submit(forge("F1"))
    stack.start()
    wait_for(lambda: stack.status("F1") in (JobStatus.FAILED, JobStatus.CANCELLED))
    settle(0.4)

    assert world.posts == ["F1"]  # dispatched exactly once; no cold start re-sent it
    assert stack.status("F1") is JobStatus.FAILED


# =====================================================================================================================
# 7. Historical A1111 identity
# =====================================================================================================================


def test_a_historical_a1111_job_is_not_run_by_launching_the_forge_runtime(make_stack):
    world = World(forge_up=False)
    stack = make_stack(world)  # the configured managed runtime is Forge
    stack.submit(legacy_a1111("H1"))
    stack.start()
    wait_for(lambda: stack.coordinator.snapshot()["status"] == WebUIHealth.ACTION_REQUIRED.value)
    settle(0.3)

    assert world.launches == 0 and stack.status("H1") is JobStatus.QUEUED and world.posts == []
    message = stack.coordinator.snapshot()["message"].lower()
    assert "a1111" in message and "forge" in message  # actionable: names both identities
    assert (
        resolve_image_backend_id(record_backend_options(stack.queue.get_job("H1"))) == "a1111_webui"
    )


def test_a_historical_a1111_job_starts_the_managed_a1111_slot_and_keeps_its_frozen_identity(
    make_stack,
):
    world = World(forge_up=False, identity=A1111_WEBUI_IDENTITY)
    stack = make_stack(world, manager=FakeWebUIManager(world, identity=A1111_WEBUI_IDENTITY))
    stack.submit(legacy_a1111("H1"))
    stack.start()

    wait_for(lambda: all_completed(stack, "H1"))
    assert (
        world.launches == 1 and world.posts == ["H1"] and world.post_backend["H1"] == "a1111_webui"
    )


# =====================================================================================================================
# 8. Readiness epochs, existing outage behaviour and stale handles
# =====================================================================================================================


def test_an_outage_hold_is_left_to_the_existing_recovery_and_the_handoff_takes_no_action(
    make_stack,
):
    world = World(forge_up=False)
    stack = make_stack(world)
    stack.submit(forge("F1"))
    stack.queue.hold_webui_dispatch(reason="webui_connection", incident_id="webui-1")

    assert stack.coordinator.prepare_next_dispatch(force=True) == "not_applicable"
    assert world.launches == 0 and stack.queue.webui_hold_info()["incident_id"] == "webui-1"


def test_a_stale_owned_handle_whose_process_died_is_relaunched_through_the_normal_start(make_stack):
    world = World(forge_up=True)
    stack = make_stack(world)
    world.webui_up = False  # crashed between jobs: the manager still reports its stale handle
    stack.submit(forge("F1"))
    stack.start()

    wait_for(lambda: all_completed(stack, "F1"))
    assert world.launches == 1 and world.posts == ["F1"]


def test_a_healthy_owned_forge_with_a_transient_unknown_identity_is_left_to_the_backend_guard(
    make_stack,
):
    world = World(forge_up=True)
    world.webui_identity = (
        "unknown"  # up and owned, but the identity probe is not positive right now
    )
    stack = make_stack(world)
    stack.submit(forge("F1"))

    assert stack.coordinator.prepare_next_dispatch(force=True) == "ready"
    assert world.launches == 0 and stack.manager.stops == 0 and stack.queue.is_webui_held() is False


def test_the_unarmed_coordinator_does_nothing(make_stack):
    world = World(forge_up=False)
    stack = make_stack(world, armed=False)
    stack.submit(forge("F1"))

    assert stack.coordinator.prepare_next_dispatch(force=True) == "not_applicable"
    assert world.launches == 0 and stack.queue.is_webui_held() is False
