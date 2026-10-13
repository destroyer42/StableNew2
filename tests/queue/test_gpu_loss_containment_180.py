"""PR-QUEUE-GPU-180: GPU device-loss dispatch containment, end to end and offline.

Real ``SDWebUIClient`` -> ``Pipeline`` executor -> ``ForgeWebUIImageBackend`` -> ``PipelineRunner.run_njr`` ->
``SingleNodeJobRunner`` -> ``WebUIOutageCoordinator`` + ``GpuLossCoordinator`` -> ``JobService`` / ``JobQueue`` / SQLite.
Only the HTTP transport (a Forge that stays HTTP-responsive while its CUDA device is gone), the host GPU evidence
probe and the owned process manager are fakes. Nothing starts a runtime, runs a workload or touches a GPU.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
import requests

from src.api.client import SDWebUIClient
from src.controller import gpu_loss_coordinator as gpu_coord
from src.controller.gpu_loss_coordinator import GpuLossCoordinator
from src.controller.job_service import JobService
from src.controller.job_service_outage import bind_webui_outage_containment
from src.controller.webui_outage_coordinator import ProbeResult, WebUIOutageCoordinator
from src.pipeline.pipeline_runner import PipelineRunner
from src.queue import backend_dependency
from src.queue.job_model import JobStatus
from src.queue.job_repository import JobRepository
from src.utils import StructuredLogger
from src.utils.gpu_device_health import HostGpuEvidence, HostGpuState
from tests.helpers.njr_factory import make_pipeline_njr
from tests.queue.test_webui_outage_containment_171 import Backend, FakeManager, Stack

URL = "http://127.0.0.1:7871"
JOBS = 15  # the in-flight job that observes the loss plus the 14 that were consumed afterwards
CUDA_500 = {
    "error": "AcceleratorError",
    "detail": "",
    "body": "",
    "errors": "CUDA error: unknown error\nCUDA kernel errors might be asynchronously reported at some other API call",
}
OOM_500 = {
    "error": "OutOfMemoryError",
    "detail": "",
    "body": "",
    "errors": "CUDA out of memory. Tried to allocate 2.00 GiB. GPU 0 has a total capacity of 11.99 GiB",
}
PLAIN_500 = {"error": "RuntimeError", "detail": "", "body": "", "errors": "unspecified internal failure"}
BAD_REQUEST_422 = {"detail": "Sampler not found"}

LOST = (HostGpuState.DEVICE_LOST, "gpu_is_lost")
HEALTHY = (HostGpuState.HEALTHY, "gpu_enumerated")


class HostGpu:
    """The host's view of the GPU as the read-only enumeration probe reports it."""

    def __init__(self, state=HEALTHY) -> None:
        self.state, self.reason = state
        self.probes = 0

    def set(self, state: tuple[HostGpuState, str]) -> None:
        self.state, self.reason = state

    def probe(self) -> HostGpuEvidence:
        self.probes += 1
        count = 1 if self.state is HostGpuState.HEALTHY else 0
        return HostGpuEvidence(self.state, self.reason, device_count=count)


def forge_response(status: int, payload: Any) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps(payload).encode("utf-8")
    response.headers["content-type"] = "application/json"
    response.url = URL
    return response


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr("src.pipeline.executor.get_global_webui_process_manager", lambda: None)
    monkeypatch.setattr("src.pipeline.executor._capture_webui_tail", lambda: None)


class Incident:
    """One real-stack scenario: ``jobs`` Forge txt2img jobs behind a Forge that answers HTTP but fails CUDA."""

    def __init__(
        self,
        tmp_path: Path,
        monkeypatch,
        *,
        raised: bool = False,
        failure: tuple[int, Any] = (500, CUDA_500),
        host_state=HEALTHY,
        lose_on_first_post: bool = True,
        webui_up: bool = True,
        repository: JobRepository | None = None,
        manager_recovers: bool = True,
    ) -> None:
        from src.image_backends import ForgeWebUIImageBackend, ImageBackendRegistry

        self.tmp_path = tmp_path
        self.host = HostGpu(host_state)
        self.posts: list[str] = []
        self.failure_status, self.failure_body = failure
        self.client = SDWebUIClient(base_url=URL)

        def transport(method, url, **kwargs):
            if method.upper() == "POST" and url.endswith("/sdapi/v1/txt2img"):
                self.posts.append(url)
                if lose_on_first_post and len(self.posts) == 1:
                    self.host.set(LOST)
                return forge_response(self.failure_status, self.failure_body)
            return forge_response(200, {})

        monkeypatch.setattr(self.client._session, "request", transport)
        registry = ImageBackendRegistry()
        adapter = ForgeWebUIImageBackend(
            transition=SimpleNamespace(prepare_for=lambda _: SimpleNamespace(ready=True))
        )
        monkeypatch.setattr(adapter, "_before_dispatch", Mock())
        registry.register(adapter)
        monkeypatch.setattr(
            "src.image_backends.webui_family_backend.verify_backend_runtime_identity", Mock()
        )
        runner = PipelineRunner(
            self.client,
            StructuredLogger(output_dir=tmp_path / "logs"),
            image_backend_registry=registry,
            runs_base_dir=str(tmp_path / "output"),
            survivor_telemetry_factory=Mock(return_value=Mock()),
        )
        pipeline = runner._pipeline
        for name in ("_ensure_webui_true_ready", "_check_webui_health_before_stage", "_apply_webui_defaults_once"):
            monkeypatch.setattr(pipeline, name, Mock())
        monkeypatch.setattr(pipeline, "_ensure_runtime_admissible", Mock(return_value={"status": "healthy"}))
        monkeypatch.setattr(
            pipeline,
            "_generate_images_with_progress",
            lambda stage, payload, **_: pipeline._generate_images(stage, payload),
        )
        monkeypatch.setattr(self.client, "get_current_model", lambda: "sdxl")
        monkeypatch.setattr(self.client, "get_current_vae", lambda: "Automatic")
        monkeypatch.setattr(self.client, "get_models", lambda: [{"title": "sdxl", "model_name": "sdxl"}])
        monkeypatch.setattr(self.client, "set_vae", Mock())
        monkeypatch.setattr(self.client, "free_vram", Mock())

        self.backend = Backend(webui_up)  # the WebUI endpoint's own health proof
        self.manager = FakeManager(self.backend, recovers=manager_recovers)
        self.manager.is_running = lambda: self.backend.up
        self.runs: list[str] = []

        def execute(job):
            self.runs.append(job.job_id)
            result = runner.run_njr(job._normalized_record)
            if raised:
                raise RuntimeError(result.error or "generation failed")
            return result.to_dict()

        self.stack = Stack(tmp_path, behavior=execute, manager=self.manager, repository=repository)
        self.queue = self.stack.queue
        self.repository = self.stack.repository
        self.gpu = GpuLossCoordinator(self.queue, probe=self.host.probe)
        self.service = JobService(self.queue, runner=self.stack.runner)
        bind_webui_outage_containment(self.service, coordinator=self.stack.coordinator, gpu_loss=self.gpu)
        self.service.auto_run_enabled = True

    def submit(self, count: int = JOBS, prefix: str = "forge") -> list[str]:
        njrs = [
            make_pipeline_njr(
                job_id=f"{prefix}-{i:02d}",
                path_output_dir=str(self.tmp_path / "output"),
                backend_options={"image": {"backend_id": "forge_webui"}},
            )
            for i in range(count)
        ]
        return self.service.submit_njrs(njrs)

    def status(self, job_id: str) -> JobStatus:
        return self.stack.status(job_id)

    def statuses(self, ids: list[str]) -> list[str]:
        return [self.status(job_id).value for job_id in ids]

    def drain_until_quiet(self, settle: float = 0.25) -> None:
        """Run the auto-run worker and wait until it has nothing left it is allowed to claim."""

        self.stack.start()
        end = time.monotonic() + 8
        last = (-1, -1)
        stable_since = time.monotonic()
        while time.monotonic() < end:
            state = (len(self.posts), sum(s == "queued" for s in self.stack.statuses().values()))
            if state != last:
                last, stable_since = state, time.monotonic()
            elif time.monotonic() - stable_since >= settle:
                return
            time.sleep(0.01)

    def close(self) -> None:
        self.stack.close()


@pytest.fixture
def incident_factory(tmp_path, monkeypatch):
    made: list[Incident] = []

    def factory(**kwargs):
        incident = Incident(tmp_path, monkeypatch, **kwargs)
        made.append(incident)
        return incident

    yield factory
    for incident in made:
        incident.close()


# -- the incident ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("raised", [False, True], ids=["normalized_failure", "raised_exception"])
def test_first_confirmed_loss_quarantines_before_the_next_claim(incident_factory, raised):
    incident = incident_factory(raised=raised)
    ids = incident.submit()
    incident.drain_until_quiet()

    # Exactly one generation request left the process; the endpoint stayed HTTP-responsive throughout.
    assert len(incident.posts) == 1 and incident.runs == [ids[0]]
    assert incident.status(ids[0]) is JobStatus.FAILED
    assert incident.statuses(ids[1:]) == ["queued"] * 14
    assert incident.stack.queued_order() == ids[1:]
    assert incident.queue.is_gpu_quarantined() and not incident.queue.is_webui_held()
    assert incident.manager.restarts == 0 and incident.manager.stops == 0 and incident.manager.starts == 0

    snapshot = incident.service.get_diagnostics_snapshot()["gpu_device_loss"]
    assert snapshot["status"] == "quarantined" and snapshot["held_gpu_jobs"] == 14
    assert snapshot["evidence_class"] == "confirmed_device_loss"
    assert snapshot["trigger"]["job_id"] == ids[0] and snapshot["trigger"]["accelerator_fault"] == "device_fault"
    assert snapshot["host_evidence"]["state"] == "device_lost"
    assert snapshot["operator_confirmation_required"] is True and snapshot["jobs_remain_queued"] is True

    # The original failure evidence is preserved untouched on the failed record.
    stored = incident.repository.get_job(ids[0])
    assert "CUDA error: unknown error" in (stored.error_message or "")
    if not raised:
        evidence = stored.result["metadata"]["failure_evidence"]
        assert evidence["accelerator_fault"] == "device_fault" and evidence["dispatch_certainty"] == "dispatched"
    assert incident.host.probes == 1  # one bounded read-only query for the whole incident


def test_manual_run_next_and_auto_run_both_respect_the_quarantine(incident_factory):
    incident = incident_factory()
    ids = incident.submit()
    incident.drain_until_quiet()
    posts = len(incident.posts)
    # Auto-run is off for the manual path: Run Next must be refused by the same atomic claim, not by a worker.
    incident.service.auto_run_enabled = False
    assert incident.stack.runner.stop(timeout=3)
    assert incident.service.run_next_now() is False
    assert incident.stack.runner.run_next_once() is False
    assert incident.stack.runner.run_once(incident.queue.get_job(ids[1])) is None
    assert incident.queue.claim_next_job() is None
    incident.service.auto_run_enabled = True
    incident.drain_until_quiet()
    assert len(incident.posts) == posts == 1
    assert incident.statuses(ids[1:]) == ["queued"] * 14


def test_comfy_svd_and_unresolved_work_do_not_bypass_the_quarantine(incident_factory):
    from tests.queue.test_webui_outage_containment_171 import comfy, image, svd, unresolved

    incident = incident_factory()
    incident.queue.quarantine_gpu_dispatch({"incident_id": "gpu-prior", "evidence_class": "confirmed_device_loss"})
    jobs = [image("img"), svd("svd"), comfy("comfy"), unresolved("unresolved")]
    for job in jobs:
        incident.queue.submit(job)
    incident.drain_until_quiet()
    assert incident.runs == []
    assert all(incident.status(job.job_id) is JobStatus.QUEUED for job in jobs)
    summary = incident.queue.dispatch_summary()
    assert summary["held_gpu_loss"] == 4 and summary["independent"] == 0 and summary["eligible"] == 0


def test_proven_gpu_free_work_alone_may_continue(incident_factory, monkeypatch):
    from tests.queue.test_webui_outage_containment_171 import image, svd

    monkeypatch.setattr(backend_dependency, "_GPU_FREE_STAGES", frozenset({"txt2img"}))
    incident = incident_factory()
    incident.queue.quarantine_gpu_dispatch({"incident_id": "gpu-prior", "evidence_class": "confirmed_device_loss"})
    incident.queue.submit(svd("held-svd"))
    incident.queue.submit(image("proven-free"))
    incident.stack.behavior = lambda job: {"success": True}
    incident.drain_until_quiet()
    assert incident.status("proven-free") is JobStatus.COMPLETED
    assert incident.status("held-svd") is JobStatus.QUEUED


# -- restart, release and the operator gate -------------------------------------------------------------------------


def test_quarantine_survives_restart_without_touching_prior_failures(incident_factory, tmp_path, monkeypatch):
    first = incident_factory()
    ids = first.submit()
    first.drain_until_quiet()
    before = {job_id: first.repository.get_job(job_id) for job_id in ids}
    incident_id = first.queue.gpu_quarantine_info()["incident_id"]
    first.close()
    first.repository.close()

    reopened = JobRepository(tmp_path / "queue.db")
    second = incident_factory(repository=reopened, lose_on_first_post=False, host_state=HEALTHY)
    assert second.queue.is_gpu_quarantined() and second.queue.is_paused() is False
    assert second.queue.gpu_quarantine_info()["incident_id"] == incident_id
    assert second.stack.queued_order() == ids[1:]
    # The GPU enumerates again and a startup gate / WebUI readiness proof is satisfied: still no execution.
    second.stack.coordinator.enable_startup_gate()
    second.backend.up = True
    second.stack.coordinator.maybe_release(force=True)
    second.drain_until_quiet()
    assert second.runs == [] and second.posts == []
    after = {job_id: reopened.get_job(job_id) for job_id in ids}
    for job_id in ids:  # identities, statuses, results and errors are exactly as the first process left them
        assert after[job_id].status is before[job_id].status
        assert after[job_id].error_message == before[job_id].error_message
        assert after[job_id].result == before[job_id].result


def test_healthy_webui_and_recovered_gpu_cannot_release_without_the_operator(incident_factory):
    incident = incident_factory()
    ids = incident.submit()
    incident.drain_until_quiet()
    # A healthy WebUI endpoint, a manager READY epoch, and a recovered GPU: none of them is an operator action.
    incident.backend.up = True
    incident.stack.coordinator.maybe_release(force=True)
    incident.stack.coordinator._on_manager_ready(object())
    incident.host.set(HEALTHY)
    incident.drain_until_quiet()
    assert incident.queue.is_gpu_quarantined()
    assert len(incident.posts) == 1 and incident.statuses(ids[1:]) == ["queued"] * 14

    refused = incident.gpu.release(operator_confirmed=False)
    assert (refused.released, refused.reason) == (False, gpu_coord.CONFIRMATION_REQUIRED)
    assert incident.queue.is_gpu_quarantined()


def test_release_needs_positive_host_evidence_and_the_matching_incident(incident_factory):
    incident = incident_factory()
    ids = incident.submit()
    incident.drain_until_quiet()
    active = incident.queue.gpu_quarantine_info()["incident_id"]

    still_lost = incident.gpu.release(operator_confirmed=True)  # host still reports the device lost
    assert (still_lost.released, still_lost.reason) == (False, gpu_coord.NO_POSITIVE_EVIDENCE)
    incident.host.set((HostGpuState.UNAVAILABLE, "probe_timeout"))
    unknown = incident.gpu.release(operator_confirmed=True)
    assert (unknown.released, unknown.reason) == (False, gpu_coord.NO_POSITIVE_EVIDENCE)
    incident.host.set(HEALTHY)
    stale = incident.gpu.release(operator_confirmed=True, incident_id="gpu-someone-else")
    assert (stale.released, stale.reason) == (False, gpu_coord.INCIDENT_MISMATCH)
    assert incident.queue.is_gpu_quarantined()
    refusal = incident.gpu.snapshot()["last_release_refusal"]
    assert refusal["reason"] == gpu_coord.INCIDENT_MISMATCH and refusal["incident_id"] == active

    # Fresh positive evidence plus explicit confirmation releases; held work then runs in its original order.
    incident.stack.behavior = lambda job: incident.runs.append(job.job_id) or {"success": True}
    released = incident.gpu.release(operator_confirmed=True, incident_id=active)
    assert released.released and released.reason == gpu_coord.RELEASED and released.incident_id == active
    assert not incident.queue.is_gpu_quarantined()
    incident.drain_until_quiet()
    assert incident.runs[1:] == ids[1:] and incident.status(ids[0]) is JobStatus.FAILED
    assert incident.gpu.snapshot()["status"] == "clear"
    assert incident.gpu.release(operator_confirmed=True).reason == gpu_coord.NOT_QUARANTINED


def test_owned_webui_recovery_is_not_attempted_under_a_gpu_quarantine(incident_factory):
    # The WebUI process is also gone (the GPU loss took it down): the owned restart cycle must not run.
    incident = incident_factory(webui_up=False, lose_on_first_post=True)
    ids = incident.submit()
    incident.drain_until_quiet()
    assert incident.queue.is_gpu_quarantined()
    assert incident.manager.restarts == 0
    webui = incident.stack.coordinator.snapshot()
    assert webui["status"] == "operator_action_required"
    assert webui["last_recovery_result"] == "gpu_device_loss_quarantine"
    assert incident.statuses(ids[1:]) == ["queued"] * 14


# -- false positives ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("failure", "host_state", "probes"),
    [
        pytest.param((500, PLAIN_500), HEALTHY, 1, id="http_500_with_healthy_gpu"),
        pytest.param((500, OOM_500), HEALTHY, 0, id="recoverable_oom"),
        pytest.param((500, OOM_500), LOST, 0, id="oom_never_asks_the_host"),
        pytest.param((422, BAD_REQUEST_422), LOST, 0, id="unrelated_request_failure"),
        pytest.param((500, CUDA_500), HEALTHY, 1, id="device_fault_signature_but_gpu_enumerates"),
        pytest.param((500, CUDA_500), (HostGpuState.UNAVAILABLE, "nvidia_smi_missing"), 1, id="probe_unavailable"),
    ],
)
def test_ordinary_failures_never_establish_a_confirmed_loss(incident_factory, failure, host_state, probes):
    incident = incident_factory(failure=failure, host_state=host_state, lose_on_first_post=False)
    ids = incident.submit(6)
    incident.drain_until_quiet()
    assert not incident.queue.is_gpu_quarantined()
    assert len(incident.posts) == 6 and incident.statuses(ids) == ["failed"] * 6  # pre-existing behavior
    assert incident.host.probes == probes * 6
    assert incident.gpu.snapshot()["status"] == "clear"


def test_unrelated_application_exception_is_not_a_gpu_loss(incident_factory):
    incident = incident_factory(host_state=LOST, lose_on_first_post=False)
    incident.stack.behavior = Mock(side_effect=ValueError("PromptPack row 3 is malformed"))
    ids = incident.submit(3)
    incident.drain_until_quiet()
    assert not incident.queue.is_gpu_quarantined() and incident.host.probes == 0
    assert incident.statuses(ids) == ["failed"] * 3


# -- coordinator-level guarantees -----------------------------------------------------------------------------------


def test_probe_failures_are_contained_and_never_confirm(tmp_path):
    from tests.queue.test_webui_outage_containment_171 import failed, image

    stack = Stack(tmp_path)
    def boom() -> HostGpuEvidence:
        raise RuntimeError("probe exploded")

    coordinator = GpuLossCoordinator(stack.queue, probe=boom)
    job = image("probe-boom")
    stack.queue.submit(job)
    result = failed(accelerator_fault="device_fault", http_status=500)
    assessment = coordinator.assess_failure(job, result=result)
    assert assessment is not None and assessment.evidence_class.value == "evidence_unavailable"
    assert not stack.queue.is_gpu_quarantined()
    assert assessment.host.reason == "probe_error"
    stack.close()


def test_failure_after_quarantine_does_not_probe_again(tmp_path):
    from tests.queue.test_webui_outage_containment_171 import failed, image

    stack = Stack(tmp_path)
    host = HostGpu(LOST)
    coordinator = GpuLossCoordinator(stack.queue, probe=host.probe)
    job = image("one")
    stack.queue.submit(job)
    assert coordinator.assess_failure(job, result=failed(accelerator_fault="device_fault")).confirmed
    first = stack.queue.gpu_quarantine_info()
    assert coordinator.assess_failure(job, result=failed(accelerator_fault="device_fault")) is None
    assert host.probes == 1 and stack.queue.gpu_quarantine_info() == first
    stack.close()


def test_quarantine_record_is_content_free(incident_factory):
    incident = incident_factory()
    incident.submit(2)
    incident.drain_until_quiet()
    record = json.dumps(incident.queue.gpu_quarantine_info(), sort_keys=True)
    for forbidden in ("prompt", "AcceleratorError", "CUDA error", "0000:01:00.0", str(incident.tmp_path)):
        assert forbidden not in record
    assert set(incident.queue.gpu_quarantine_info()) >= {
        "schema", "incident_id", "evidence_class", "established_at", "trigger", "host_evidence",
        "release_requirements",
    }


def test_webui_outage_coordinator_interlock_uses_only_the_queue_flag(tmp_path):
    stack = Stack(tmp_path, manager=FakeManager(Backend(False)))
    stack.queue.quarantine_gpu_dispatch({"incident_id": "gpu-x", "evidence_class": "confirmed_device_loss"})
    coordinator: WebUIOutageCoordinator = stack.coordinator
    coordinator._probe = lambda: ProbeResult(False, "endpoint_free", URL, "forge_webui")
    from tests.queue.test_webui_outage_containment_171 import CONNECTION, failed, image

    job = image("a")
    stack.queue.submit(job)
    decision = coordinator.assess(job, result=failed(**CONNECTION))
    coordinator.recover(decision)
    assert stack.manager.restarts == 0
    assert coordinator.snapshot()["last_recovery_result"] == "gpu_device_loss_quarantine"
    stack.close()


def test_default_job_service_wires_the_gpu_observer_and_survives_runner_replacement(tmp_path):
    from src.queue.job_queue import JobQueue
    from src.queue.single_node_runner import SingleNodeJobRunner

    repository = JobRepository(tmp_path / "wired.db")
    try:
        queue = JobQueue(repository=repository)
        first = SingleNodeJobRunner(queue, lambda job: {"success": True}, poll_interval=0.005)
        service = JobService(queue, runner=first)
        assert isinstance(service.gpu_loss, GpuLossCoordinator)
        assert first._gpu_loss_observer is service.gpu_loss
        assert service.get_diagnostics_snapshot()["gpu_device_loss"]["status"] == "clear"
        # The same coordinator (and its persisted incident view) follows a replacement runner.
        second = SingleNodeJobRunner(queue, lambda job: {"success": True}, poll_interval=0.005)
        coordinator = service.gpu_loss
        service.replace_runner(second)
        assert second._gpu_loss_observer is coordinator and service.gpu_loss is coordinator
    finally:
        repository.close()
