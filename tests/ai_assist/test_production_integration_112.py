"""Production authority, composition and shutdown; synthetic installations/children only."""

from __future__ import annotations

import threading
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.ai_assist.contracts import AssistOutcome, OutcomeCode
from src.ai_assist.host import GenerationActivity, read_host_memory
from src.ai_assist.service import AiAssistService, Submission
from src.controller.app_controller_services import ai_assist_integration as integration
from src.controller.app_controller_services import shutdown_coordinator
from src.queue.job_model import JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from tests.helpers.njr_factory import make_queue_job

from .conftest import request_for
from .test_service_runtime import make_service


@pytest.fixture
def authority(tmp_path):
    repository = JobRepository(tmp_path / "jobs.db")
    queue = JobQueue(repository=repository)
    service = SimpleNamespace(job_queue=queue)
    yield service, queue, integration.QueueGenerationActivity(lambda: service)
    repository.close()


def test_real_queue_idle_queued_running_and_quarantine(authority):
    _service, queue, provider = authority
    assert provider() == GenerationActivity()
    queue.submit(make_queue_job("first"))
    assert provider().running_jobs == 0
    queue.mark_running("first")
    assert provider().running_jobs == 1
    queue.quarantine_gpu_dispatch({"incident_id": "gpu-test"})
    assert provider() == GenerationActivity(1, True)
    assert queue.list_jobs()[0].status is JobStatus.RUNNING


@pytest.mark.parametrize(
    "authority",
    [
        None,
        SimpleNamespace(),
        SimpleNamespace(job_queue=None),
        SimpleNamespace(
            job_queue=SimpleNamespace(
                list_jobs=lambda **_kw: None, is_gpu_quarantined=lambda: False
            )
        ),
        SimpleNamespace(
            job_queue=SimpleNamespace(list_jobs=lambda **_kw: [], is_gpu_quarantined=lambda: None)
        ),
        SimpleNamespace(
            job_queue=SimpleNamespace(list_jobs=Mock(side_effect=OSError("PRIVATE_CANARY")))
        ),
    ],
)
def test_unreadable_authority_fails_closed_without_exception_content(
    authority, installation, caplog
):
    provider = integration.QueueGenerationActivity(lambda: authority)
    result = make_service(installation, activity=provider).submit(request_for(), Mock())
    assert not result.accepted
    assert result.outcome.code is OutcomeCode.GENERATION_ACTIVE
    assert "PRIVATE_CANARY" not in caplog.text


def test_queued_work_reaches_later_memory_gate_without_spawn(authority, installation):
    _service, queue, provider = authority
    queue.submit(make_queue_job("pending"))
    service = make_service(installation, activity=provider, memory=lambda: None)
    result = service.submit(request_for(), Mock())
    assert result.outcome.code is OutcomeCode.RESOURCE_INSUFFICIENT
    assert service._worker is None
    assert queue.list_jobs()[0].status is JobStatus.QUEUED


@pytest.mark.parametrize("transition", ["running", "quarantine", "unreadable"])
def test_live_queue_transition_yields_only_ai_child(authority, installation, transition):
    _service, queue, provider = authority
    queue.submit(make_queue_job("generation"))
    calls = 0

    def activity():
        nonlocal calls
        calls += 1
        if calls == 3:
            if transition == "running":
                queue.mark_running("generation")
            elif transition == "quarantine":
                queue.quarantine_gpu_dispatch({"incident_id": "new-loss"})
        if calls >= 3 and transition == "unreadable":
            raise integration.ActivityUnreadable("activity_unreadable")
        return provider()

    ai = make_service(installation, activity=activity)
    outcome = ai.run(
        request_for("sleep")
    )  # existing contained Python-child fixture, never llama.cpp
    assert outcome.code is OutcomeCode.YIELDED_TO_GENERATION
    assert ai.shutdown(2)
    expected = JobStatus.RUNNING if transition == "running" else JobStatus.QUEUED
    assert queue.list_jobs()[0].status is expected


def test_production_composition_reads_pins_once_launches_nothing_and_requires_qualification(
    tmp_path, monkeypatch
):
    created = []
    real = AiAssistService

    def factory(**kwargs):
        created.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(integration, "AiAssistService", factory)
    owner = integration.AiAssistIntegration(lambda: None, lambda cb: None, root=tmp_path / "absent")
    assert len(created) == 1
    assert created[0]["memory_probe"] is read_host_memory
    assert created[0]["policy"].allow_candidate is False
    assert created[0]["policy"].strict_offline is True
    assert owner.service._worker is None
    assert not (tmp_path / "absent").exists()
    for _ in range(2):
        assert owner.availability()[0] is OutcomeCode.NOT_INSTALLED
        result = owner.submit(request_for(), Mock())
        assert not result.accepted and result.outcome.code is OutcomeCode.NOT_INSTALLED
    assert len(created) == 1 and owner.service._worker is None
    assert owner.shutdown()


def test_unqualified_candidate_cannot_run_in_production(installation):
    owner = integration.AiAssistIntegration(lambda: None, lambda cb: None, root=installation.root)
    owner.service._manifest = replace(
        installation.manifest, builds=(replace(installation.build, qualified=False),)
    )
    owner.service._registry = replace(
        installation.registry, entries=(replace(installation.entry, qualified=False),)
    )
    result = owner.submit(request_for(), Mock())
    assert result.outcome.code is OutcomeCode.NOT_INSTALLED
    assert owner.service._worker is None


def test_shutdown_fences_requests_and_drops_already_queued_completion(tmp_path):
    callbacks, delivered = [], []
    owner = integration.AiAssistIntegration(lambda: None, callbacks.append, root=tmp_path)

    def submit(request, done):
        done(AssistOutcome(OutcomeCode.CANCELLED, request.request_id))
        return Submission(True)

    fake = SimpleNamespace(submit=submit, begin_shutdown=Mock(), shutdown=Mock(return_value=True))
    owner.service = fake
    assert owner.submit(request_for(), delivered.append).accepted
    assert callbacks and not delivered  # worker completion enqueues; it cannot mutate UI
    assert owner.shutdown(0.2) is True
    callbacks[0]()
    assert not delivered
    assert owner.submit(request_for(), delivered.append).outcome.code is OutcomeCode.UNAVAILABLE
    assert owner.shutdown() is True


def test_constructor_failure_and_failed_quiescence_are_observable(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(
        integration, "AiAssistService", Mock(side_effect=RuntimeError("PRIVATE_CANARY"))
    )
    owner = integration.AiAssistIntegration(lambda: None, lambda cb: None, root=tmp_path)
    assert owner.availability()[0] is OutcomeCode.UNAVAILABLE
    assert owner.shutdown()
    owner.service = SimpleNamespace(begin_shutdown=Mock(), shutdown=Mock(return_value=False))
    assert owner.shutdown() is False
    assert not shutdown_coordinator.ai_is_quiescent(SimpleNamespace(ai_assist=owner))
    assert "did not quiesce" in caplog.text and "PRIVATE_CANARY" not in caplog.text


def test_shutdown_entry_fences_ai_and_queue_before_repository_close():
    events = []
    ai = SimpleNamespace(
        begin_shutdown=lambda: events.append("ai-fence"), shutdown=lambda: events.append("ai-join")
    )
    jobs = SimpleNamespace(
        begin_shutdown=lambda: events.append("queue-fence"),
        is_quiescent=lambda: True,
        history_store=SimpleNamespace(close=lambda: events.append("repository-close")),
    )
    controller = SimpleNamespace(ai_assist=ai, job_service=jobs)
    shutdown_coordinator.fence_application_admission(controller)
    assert events == ["ai-fence", "queue-fence"]
    shutdown_coordinator.shutdown_owned_services(controller)
    assert events == ["ai-fence", "queue-fence", "ai-join", "repository-close"]


def test_service_shutdown_after_admission_before_worker_publish_cannot_launch(
    installation, monkeypatch
):
    service = make_service(installation)
    admit = service._admit

    def fenced(request, token):
        value = admit(request, token)
        service.begin_shutdown()
        return value

    monkeypatch.setattr(service, "_admit", fenced)
    submission = service.submit(request_for(), Mock())
    assert not submission.accepted and submission.outcome.code is OutcomeCode.UNAVAILABLE
    assert service._worker is None and service.shutdown(0)


def test_service_shutdown_reports_live_worker_then_can_join(installation):
    service = make_service(installation)
    entered, release = threading.Event(), threading.Event()
    original = service._execute

    def execute(*args):
        entered.set()
        assert release.wait(5)
        return original(*args)

    service._execute = execute
    assert service.submit(request_for(), Mock()).accepted
    try:
        assert entered.wait(5)
        assert service.shutdown(0) is False
        assert service.submit(request_for(), Mock()).outcome.code is OutcomeCode.UNAVAILABLE
    finally:
        release.set()
        assert service.shutdown(5)
