"""Incident-shaped offline acceptance: real SQLite/queue/runner, fake WebUI and processes."""
from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
import requests
from PIL import Image

from src.api.client import SDWebUIClient, WebUIGenerationOutcomeUnknownError
from src.api.types import GenerateError, GenerateErrorCode, GenerateOutcome
from src.api.webui_failure_evidence import (
    DispatchCertainty,
    assess_exception,
    assess_result,
    build_failure_evidence,
)
from src.api.webui_process_manager import WebUIProcessConfig, WebUIProcessManager
from src.api.webui_runtime_identity import (
    UNKNOWN_RUNTIME_IDENTITY,
    WebUIRuntimeIdentity,
    WebUIRuntimeIdentityMismatch,
)
from src.controller.job_service import JobService
from src.controller.job_service_outage import bind_webui_outage_containment
from src.controller.webui_connection_controller import (
    WebUIConnectionController,
    WebUIConnectionState,
)
from src.controller.webui_outage_coordinator import ProbeResult
from src.pipeline.executor import Pipeline, PipelineStageError
from src.pipeline.pipeline_runner import PipelineRunner
from src.queue.job_model import JobStatus, StageCheckpoint
from src.queue.single_node_runner import _extract_stage_checkpoints
from src.utils import StructuredLogger
from tests.helpers.njr_factory import make_pipeline_njr
from tests.helpers.webui_mocks import DummyProcess
from tests.queue.test_webui_outage_containment_171 import (
    Backend,
    FakeManager,
    Stack,
    comfy,
    image,
    svd,
    wait_for,
)

URL = "http://127.0.0.1:7871"


def unknown_error(stage="txt2img"):
    return PipelineStageError(GenerateError(
        code=GenerateErrorCode.OUTCOME_UNKNOWN, message="10054 response reset after dispatch",
        stage=stage, details={"request_may_have_executed": True},
    ))


def identity_error(observed=UNKNOWN_RUNTIME_IDENTITY):
    return WebUIRuntimeIdentityMismatch("forge_webui", observed)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr("src.pipeline.executor.get_global_webui_process_manager", lambda: None)
    monkeypatch.setattr("src.pipeline.executor._capture_webui_tail", lambda: None)
    monkeypatch.setattr("requests.Session.request", Mock(side_effect=AssertionError("unexpected network")))


@pytest.fixture
def pipeline(tmp_path):
    client = Mock()
    client.get_current_model.return_value = "sdxl"
    client.get_current_vae.return_value = "Automatic"
    instance = Pipeline(client, StructuredLogger(output_dir=tmp_path / "logs"))
    with (
        patch.object(instance, "_ensure_runtime_admissible", return_value={"status": "healthy"}),
        patch.object(instance, "_apply_webui_defaults_once"),
        patch.object(instance, "_ensure_webui_true_ready"),
        patch.object(instance, "_check_webui_health_before_stage"),
    ):
        yield instance


@pytest.mark.parametrize("stage", ["txt2img", "img2img", "upscale", "adetailer"])
def test_typed_error_survives_stage_boundary(pipeline, tmp_path, stage):
    source = tmp_path / "source.png"
    Image.new("RGB", (32, 32)).save(source)
    error = unknown_error(stage)
    method = "run_adetailer" if stage == "adetailer" else (
        "_generate_images" if stage == "upscale" else "_generate_images_with_progress"
    )
    with patch.object(pipeline, method, side_effect=error) as dispatch:
        with pytest.raises(PipelineStageError) as raised:
            if stage == "txt2img":
                pipeline.run_txt2img_stage("synthetic", "", {}, tmp_path / "out", "test")
            elif stage == "img2img":
                pipeline.run_img2img_stage(source, "synthetic", {}, tmp_path / "out", "test")
            elif stage == "upscale":
                pipeline.run_upscale_stage(source, {"upscale_mode": "img2img"}, tmp_path / "out", "test")
            else:
                pipeline.run_adetailer_stage(source, {}, tmp_path / "out", "test")
    assert raised.value is error and dispatch.call_count == 1
    assert assess_exception(raised.value).certainty is DispatchCertainty.UNKNOWN


def test_actual_10054_transport_one_post_no_executor_restart(pipeline, monkeypatch):
    client = SDWebUIClient(base_url=URL)
    pipeline.client = client
    methods = []

    def reset(method, url, **kwargs):
        methods.append(method.upper())
        raise requests.ConnectionError("Connection reset by peer [WinError 10054]")

    monkeypatch.setattr(client._session, "request", reset)
    manager = Mock(owns_process=True, pid=4242)
    manager.is_running.return_value = False
    monkeypatch.setattr("src.pipeline.executor.get_global_webui_process_manager", lambda: manager)
    with pytest.raises(PipelineStageError) as error:
        pipeline._generate_images("txt2img", {"prompt": "synthetic"})
    assert methods == ["POST"]
    assert error.value.error.code is GenerateErrorCode.OUTCOME_UNKNOWN
    assert "10054" in error.value.error.details["diagnostics"]["error_message"]
    manager.restart_webui.assert_not_called()
    evidence = build_failure_evidence(error.value)
    assert evidence["request_may_have_executed"] is True and evidence["recovery_attempts"] == 0
    assert evidence["dispatch_certainty"] == "unknown"
    assert evidence["transport_exception_type"] == "ConnectionError"


@pytest.mark.parametrize("alternate_code", [False, True])
def test_10054_normalized_through_run_njr_jobservice_sqlite(tmp_path, monkeypatch, alternate_code):
    from src.image_backends import ForgeWebUIImageBackend, ImageBackendRegistry

    client = SDWebUIClient(base_url=URL)
    dispatches = []
    def reset(method, url, **kwargs):
        dispatches.append((method, url))
        raise requests.ConnectionError("[WinError 10054] response reset")
    monkeypatch.setattr(client._session, "request", reset)
    registry = ImageBackendRegistry()
    adapter = ForgeWebUIImageBackend(transition=SimpleNamespace(
        prepare_for=lambda _: SimpleNamespace(ready=True),
    ))
    # This test targets the transport/stage boundary; readiness/asset attestation is tested separately.
    monkeypatch.setattr(adapter, "_before_dispatch", Mock())
    registry.register(adapter)
    monkeypatch.setattr("src.image_backends.webui_family_backend.verify_backend_runtime_identity", Mock())
    runner = PipelineRunner(
        client, StructuredLogger(output_dir=tmp_path / "logs"),
        image_backend_registry=registry, runs_base_dir=str(tmp_path / "output"),
        survivor_telemetry_factory=Mock(return_value=Mock()),
    )
    pipeline = runner._pipeline
    for name in ("_ensure_webui_true_ready", "_check_webui_health_before_stage", "_apply_webui_defaults_once"):
        monkeypatch.setattr(pipeline, name, Mock())
    monkeypatch.setattr(pipeline, "_ensure_runtime_admissible", Mock(return_value={"status": "healthy"}))
    monkeypatch.setattr(pipeline, "_generate_images_with_progress", lambda stage, payload, **_: pipeline._generate_images(stage, payload))
    monkeypatch.setattr(client, "get_current_model", lambda: "sdxl")
    monkeypatch.setattr(client, "get_current_vae", lambda: "Automatic")
    monkeypatch.setattr(client, "get_models", lambda: [{"title": "sdxl", "model_name": "sdxl"}])
    monkeypatch.setattr(client, "set_vae", Mock())
    monkeypatch.setattr(client, "free_vram", Mock())
    if alternate_code:
        def ambiguous(stage, payload):
            dispatches.append(("POST", URL + "/sdapi/v1/txt2img"))
            return GenerateOutcome(error=GenerateError(
                code=GenerateErrorCode.CONNECTION, message="response reset after dispatch", stage=stage,
                details={"request_may_have_executed": True, "original_exception": "ConnectionError"},
            ))
        monkeypatch.setattr(client, "generate_images", ambiguous)
    backend = Backend(False)
    manager = FakeManager(backend, recovers=False)
    results = []
    def execute(job):
        result = runner.run_njr(job._normalized_record).to_dict()
        results.append(result)
        return result
    stack = Stack(tmp_path, behavior=execute, manager=manager)
    service = JobService(stack.queue, runner=stack.runner)
    bind_webui_outage_containment(service, coordinator=stack.coordinator)
    njr = make_pipeline_njr(
        job_id="reset", path_output_dir=str(tmp_path / "output"),
        backend_options={"image": {"backend_id": "forge_webui"}},
    )
    assert service.submit_njrs([njr]) == ["reset"]
    stack.runner.run_once(stack.queue.get_job("reset"))
    assert len(dispatches) == 1 and dispatches[0][0].upper() == "POST"
    result = results[0]
    assert result["success"] is False and result["metadata"]["action_required"] is True
    typed = result["metadata"]["failure_evidence"]
    assert typed["error_code"] == ("connection_error" if alternate_code else "outcome_unknown")
    assert typed["dispatch_certainty"] == "unknown"
    assert typed["transport_exception_type"] == "ConnectionError"
    assert stack.repository.get_job("reset").result["metadata"]["failure_evidence"] == typed
    assert stack.status("reset") is JobStatus.FAILED and stack.queue.is_webui_held()
    assert manager.restarts == 1


@pytest.mark.parametrize("http_error", [False, True])
def test_single_image_upscale_preserves_dispatched_transport_failure(pipeline, tmp_path, monkeypatch, http_error):
    source = tmp_path / "source.png"
    Image.new("RGB", (32, 32)).save(source)
    client = SDWebUIClient(base_url=URL)
    monkeypatch.setattr(client, "get_current_model", lambda: "sdxl")
    monkeypatch.setattr(client, "get_current_vae", lambda: "Automatic")
    pipeline.client = client
    dispatches = []

    def fail(method, url, **kwargs):
        dispatches.append((method, url, kwargs["json"]))
        if not http_error:
            raise requests.ConnectionError("[WinError 10054] response reset")
        response = requests.Response()
        response.status_code = 500
        response.url = url
        response._content = b"server error"
        return response

    monkeypatch.setattr(client._session, "request", fail)
    expected = requests.HTTPError if http_error else WebUIGenerationOutcomeUnknownError
    with pytest.raises(expected) as raised:
        pipeline.run_upscale_stage(source, {"upscale_mode": "single"}, tmp_path / "out", "test")
    evidence = build_failure_evidence(raised.value)
    assert evidence["dispatch_certainty"] == ("dispatched" if http_error else "unknown")
    if not http_error:
        assert evidence["error_code"] == "outcome_unknown"
        assert evidence["transport_exception_type"] == "ConnectionError"
        assert evidence["generation_endpoint"] == "/sdapi/v1/extra-single-image"
    assert assess_exception(raised.value).safe_to_requeue is False
    assert len(dispatches) == 1
    assert dispatches[0][1].endswith("/sdapi/v1/extra-single-image")
    assert dispatches[0][2]["image"].startswith("data:image/png;base64,")


@pytest.mark.parametrize("observed,suspected", [
    (UNKNOWN_RUNTIME_IDENTITY, True),
    (WebUIRuntimeIdentity("unknown", {"endpoint_state": {"options": "malformed"}}), True),
    (WebUIRuntimeIdentity("a1111_webui", {"options_readable": True}), False),
    (WebUIRuntimeIdentity("unknown", {"options_readable": True}), False),
])
def test_identity_fields_and_gap_drive_assessment(observed, suspected):
    error = identity_error(observed)
    evidence = build_failure_evidence(error)
    assert evidence["expected_identity"] == "forge_webui"
    assert evidence["observed_identity"] == observed.identity
    assessment = assess_exception(error)
    assert assessment.suspects_outage is suspected
    assert assessment.certainty is DispatchCertainty.NOT_DISPATCHED
    assert assessment.safe_to_requeue is suspected


@pytest.mark.parametrize("shape", [
    {"stage_events": [{"stage": "txt2img", "phase": "exit"}]},
    {"stage_events": [{"stage": "txt2img", "event": "exit"}]},
    {"output_paths": ["earlier.png"]},
    {"metadata": {"completed_output_paths": ["earlier.png"]}},
    {"variants": [{"path": "earlier.png"}]},
])
def test_current_partial_work_never_requeues(tmp_path, shape):
    metadata = {**shape.get("metadata", {}), "failure_evidence": build_failure_evidence(identity_error())}
    result = {**shape, "success": False, "metadata": metadata}
    assert assess_result(result).safe_to_requeue is False
    stack = Stack(tmp_path, behavior=lambda job: result)
    job = image("partial")
    stack.submit(job, image("remaining"))
    stack.runner.run_once(job)
    assert stack.status("partial") is JobStatus.FAILED
    assert stack.status("remaining") is JobStatus.QUEUED
    assert stack.queue.is_webui_held()


@pytest.mark.parametrize("key", ["phase", "event"])
def test_production_and_historical_exit_checkpoint_extraction(key):
    checkpoints = _extract_stage_checkpoints({"stage_events": [{"stage": "txt2img", key: "exit"}]})
    assert [checkpoint.stage_name for checkpoint in checkpoints] == ["txt2img"]


def test_persisted_checkpoint_blocks_raised_identity_refusal(tmp_path):
    stack = Stack(tmp_path, behavior=lambda job: identity_error())
    job = image("partial")
    stack.submit(job)
    job.execution_metadata.stage_checkpoints = [StageCheckpoint("txt2img", output_paths=["earlier.png"])]
    stack.queue.persist_runtime_state(job)
    with pytest.raises(WebUIRuntimeIdentityMismatch):
        stack.runner.run_once(job)
    assert stack.status("partial") is JobStatus.FAILED
    assert stack.repository.get_job_model("partial").execution_metadata.stage_checkpoints
    assert stack.repository.get_job_model("partial").execution_metadata.return_to_queue_count == 0


@pytest.mark.parametrize("owned", [True, False])
def test_real_manager_retained_dead_launch_ownership(monkeypatch, owned):
    manager = WebUIProcessManager(WebUIProcessConfig(command=["fake-forge"], base_url=URL))
    child = DummyProcess(4242)
    child._returncode = 1
    manager._process, manager._pid, manager._owns_process = child, child.pid, owned
    manager._launch_session_command = ["fake-forge"]
    monkeypatch.setattr("src.utils.single_instance.SingleInstanceLock.is_gui_running", lambda: True)
    with patch.object(manager, "stop_webui") as stop, patch.object(manager, "start") as start:
        assert manager.is_running() is False
        assert manager.owns_process is owned
        assert manager.restart_webui(wait_ready=False, max_attempts=1) is owned
    assert start.call_count == stop.call_count == int(owned)


@pytest.mark.parametrize("recovers", [False, True])
def test_25_job_incident_via_jobservice_keeps_remaining_work(tmp_path, recovers):
    backend = Backend(False)
    manager = FakeManager(backend, recovers=recovers)
    manager.is_running = lambda: backend.up
    def behavior(job):
        if job.job_id == "image-00":
            return unknown_error()
        return {"success": True}
    stack = Stack(tmp_path, behavior=behavior, manager=manager)
    service = JobService(stack.queue, runner=stack.runner)
    bind_webui_outage_containment(service, coordinator=stack.coordinator)
    jobs = [image(f"image-{i:02d}") for i in range(25)] + [svd("svd"), comfy("comfy")]
    assert len(service.submit_njrs([job._normalized_record for job in jobs])) == 27
    service.auto_run_enabled = True
    stack.start()
    try:
        wait_for(lambda: stack.status("comfy") is JobStatus.COMPLETED)
        assert manager.restarts == 1
        assert stack.status("image-00") is JobStatus.FAILED
        assert stack.calls.count("image-00") == 1
        assert stack.status("svd") is JobStatus.COMPLETED
        if recovers:
            assert all(stack.status(job.job_id) is JobStatus.COMPLETED for job in jobs[1:])
            assert not stack.queue.is_webui_held()
        else:
            assert stack.calls == ["image-00", "svd", "comfy"]
            assert stack.queued_order() == [job.job_id for job in jobs[1:25]]
            assert stack.coordinator.snapshot()["held_webui_jobs"] == 24
            assert stack.runner.run_once(stack.queue.get_job("image-01")) is None
            assert stack.calls == ["image-00", "svd", "comfy"]
        # No recovery mutates the interrupted FAILED record.
        assert stack.repository.get_job("image-00").status is JobStatus.FAILED
    finally:
        stack.close()


def test_identity_refusal_holds_before_second_claim_and_requeues_once(tmp_path):
    backend = Backend(False)
    manager = FakeManager(backend, recovers=False)
    stack = Stack(tmp_path, behavior=lambda job: identity_error(), manager=manager)
    stack.submit(*(image(f"job-{i}") for i in range(25)))
    job = stack.queue.get_job("job-0")
    assert stack.runner.run_once(job) is None
    assert len(stack.calls) == 1 and manager.restarts == 1
    assert all(status == "queued" for status in stack.statuses().values())
    assert stack.queue.claim_next_job() is None
    assert stack.repository.get_job_model("job-0").execution_metadata.return_to_queue_count == 1
    decision = stack.coordinator.assess(job, exc=identity_error())
    stack.coordinator.recover(decision)
    assert manager.restarts == 1


def test_positive_wrong_identity_probe_never_restarts(tmp_path):
    manager = FakeManager(Backend(False))
    stack = Stack(tmp_path, manager=manager)
    stack.coordinator._probe = lambda: ProbeResult(False, "identity_mismatch", URL, "a1111_webui", False)
    decision = stack.coordinator.assess(image("a"), exc=identity_error())
    stack.coordinator.recover(decision)
    assert manager.restarts == 0 and stack.queue.is_webui_held()
    assert stack.coordinator.snapshot()["last_recovery_result"] == "identity_mismatch"


def test_cached_ready_and_fresh_status_cannot_mask_process_death():
    controller = WebUIConnectionController(base_url_provider=lambda: URL)
    manager = SimpleNamespace(owns_process=True, is_running=lambda: False, add_ready_listener=Mock())
    controller.attach_process_manager(manager)
    controller._set_state(WebUIConnectionState.READY)
    controller._last_strict_status = True
    controller._last_strict_check_ts = float("inf")
    assert controller.get_state() is WebUIConnectionState.ERROR
    assert controller.is_webui_ready_strict() is False
    assert controller.last_readiness_error == "owned process exited"


def test_fresh_probe_and_outage_projection_override_cached_ready():
    controller = WebUIConnectionController(base_url_provider=lambda: URL)
    controller._set_state(WebUIConnectionState.READY)
    with patch.object(controller, "_evaluate_strict_readiness", return_value=(False, "endpoint unreachable")):
        assert controller.refresh_health() is WebUIConnectionState.ERROR
    controller._set_state(WebUIConnectionState.READY)
    controller.set_outage_provider(lambda: {"status": "operator_action_required"})
    assert controller.get_state() is WebUIConnectionState.ERROR


def test_stale_periodic_failure_cannot_overwrite_new_ready_epoch():
    controller = WebUIConnectionController(base_url_provider=lambda: URL)
    def stale_probe():
        controller._ready_epoch += 1
        controller._set_state(WebUIConnectionState.READY)
        return False, "old endpoint failure"
    with patch.object(controller, "_evaluate_strict_readiness", side_effect=stale_probe):
        assert controller.refresh_health() is WebUIConnectionState.READY


def test_real_manager_ready_publication_wins_over_inflight_old_health_probe():
    from src.api.webui_process_manager import WebUIReadyEvent

    controller = WebUIConnectionController(base_url_provider=lambda: URL)
    entered, finish = threading.Event(), threading.Event()
    def old_probe():
        entered.set()
        assert finish.wait(3)
        return False, "old failure"
    results = []
    with patch.object(controller, "_evaluate_strict_readiness", side_effect=old_probe):
        worker = threading.Thread(target=lambda: results.append(controller.refresh_health()))
        worker.start()
        assert entered.wait(3)
        controller._on_manager_ready(WebUIReadyEvent(1, "restart", 4242, "forge_webui", URL))
        finish.set()
        worker.join(3)
    assert not worker.is_alive()
    assert controller.ready_epoch == 1 and results == [WebUIConnectionState.READY]
