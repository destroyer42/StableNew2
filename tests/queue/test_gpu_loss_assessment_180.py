"""PR-QUEUE-GPU-180: pure GPU device-loss decision table over typed facts (no queue, no process, no host)."""
from __future__ import annotations

import pytest

from src.api.types import GenerateError, GenerateErrorCode
from src.pipeline.executor import PipelineStageError
from src.queue import backend_dependency
from src.queue.backend_dependency import BackendDependency, classify_job
from src.queue.gpu_loss_assessment import (
    GpuLossEvidenceClass,
    assess_gpu_loss,
    facts_from_failure,
    needs_host_evidence,
)
from src.utils.gpu_device_health import HostGpuEvidence, HostGpuState
from tests.queue.test_webui_outage_containment_171 import comfy, failed, image, svd, unresolved

LOST = HostGpuEvidence(HostGpuState.DEVICE_LOST, "gpu_is_lost")
HEALTHY = HostGpuEvidence(HostGpuState.HEALTHY, "gpu_enumerated", device_count=1)
UNAVAILABLE = HostGpuEvidence(HostGpuState.UNAVAILABLE, "probe_timeout")

CLASS = GpuLossEvidenceClass
DEVICE_FAULT = {"accelerator_fault": "device_fault", "error_code": "unknown_error", "http_status": 500}
HTTP_500 = {"error_code": "unknown_error", "http_status": 500}
TRANSPORT = {"error_code": GenerateErrorCode.CONNECTION.value, "webui_unavailable": True}


def classify(job, result, host=None):
    facts = facts_from_failure(job, result=result)
    return assess_gpu_loss(facts, host if needs_host_evidence(facts) else None)


@pytest.mark.parametrize(
    ("fields", "host", "expected"),
    [
        # The incident: a device-level CUDA fault answered by a dead device.
        (DEVICE_FAULT, LOST, CLASS.CONFIRMED_DEVICE_LOSS),
        (DEVICE_FAULT, HEALTHY, CLASS.SUSPECTED_DEVICE_LOSS),
        (DEVICE_FAULT, UNAVAILABLE, CLASS.EVIDENCE_UNAVAILABLE),
        (DEVICE_FAULT, None, CLASS.EVIDENCE_UNAVAILABLE),
        # An ordinary HTTP 500 is only ever a GPU loss when the host says so.
        (HTTP_500, LOST, CLASS.CONFIRMED_DEVICE_LOSS),
        (HTTP_500, HEALTHY, CLASS.NOT_GPU_FAILURE),
        (HTTP_500, UNAVAILABLE, CLASS.EVIDENCE_UNAVAILABLE),
        # Transport failures (backend unreachable) on a present GPU stay transport failures.
        (TRANSPORT, HEALTHY, CLASS.TRANSPORT_FAILURE),
        (TRANSPORT, LOST, CLASS.CONFIRMED_DEVICE_LOSS),
        (TRANSPORT, UNAVAILABLE, CLASS.EVIDENCE_UNAVAILABLE),
        # Allocation and numeric failures never consult, and are never overridden by, host evidence.
        ({"accelerator_fault": "out_of_memory", "http_status": 500}, LOST, CLASS.CUDA_OUT_OF_MEMORY),
        ({"accelerator_fault": "out_of_memory", "http_status": 500}, HEALTHY, CLASS.CUDA_OUT_OF_MEMORY),
        ({"accelerator_fault": "numeric_fault", "http_status": 500}, LOST, CLASS.MODEL_FAILURE),
        # Client-side rejections and plain failures carry no accelerator evidence at all.
        ({"error_code": "validation_error", "http_status": 422}, LOST, CLASS.NOT_GPU_FAILURE),
        ({"error_code": "unknown_error"}, LOST, CLASS.NOT_GPU_FAILURE),
    ],
)
def test_decision_table_for_a_forge_image_job(fields, host, expected):
    job = image("forge")
    result = failed(**fields)
    facts = facts_from_failure(job, result=result)
    # The probe is requested only for failures that warrant it, and the table agrees with that gate.
    outcome = assess_gpu_loss(facts, host if needs_host_evidence(facts) else None)
    assert outcome.evidence_class is expected
    assert outcome.confirmed is (expected is CLASS.CONFIRMED_DEVICE_LOSS)
    if expected in {CLASS.CUDA_OUT_OF_MEMORY, CLASS.MODEL_FAILURE}:
        assert not needs_host_evidence(facts) and outcome.host is None


def test_unavailable_probe_and_healthy_host_never_confirm():
    facts = facts_from_failure(image("forge"), result=failed(**DEVICE_FAULT))
    assert not assess_gpu_loss(facts, UNAVAILABLE).confirmed
    assert not assess_gpu_loss(facts, HEALTHY).confirmed
    assert not assess_gpu_loss(facts, None).confirmed
    assert assess_gpu_loss(facts, LOST).confirmed


@pytest.mark.parametrize("make", [svd, comfy, unresolved], ids=["svd", "comfy", "unresolved"])
def test_non_webui_gpu_work_is_assessed_from_the_failure_text(make):
    job = make("video")
    text = {"success": False, "error": "txt2vid failed: CUDA error: unknown error", "metadata": {}}
    facts = facts_from_failure(job, result=text)
    assert facts.gpu_dependent and facts.category is None
    assert needs_host_evidence(facts)
    assert assess_gpu_loss(facts, LOST).evidence_class is CLASS.CONFIRMED_DEVICE_LOSS
    assert assess_gpu_loss(facts, HEALTHY).evidence_class is CLASS.SUSPECTED_DEVICE_LOSS
    # Plain failures of the same job never ask the host anything.
    plain = facts_from_failure(job, result={"success": False, "error": "decode failed", "metadata": {}})
    assert not needs_host_evidence(plain)
    assert assess_gpu_loss(plain, LOST).evidence_class is CLASS.NOT_GPU_FAILURE


def test_ready_gate_refusal_is_a_transport_class_suspicion():
    result = {"success": False, "error": "WebUI not ready", "metadata": {"execution_path": "ready_gate"}}
    facts = facts_from_failure(image("forge"), result=result)
    assert facts.suspects_outage and needs_host_evidence(facts)
    assert assess_gpu_loss(facts, HEALTHY).evidence_class is CLASS.TRANSPORT_FAILURE
    assert assess_gpu_loss(facts, LOST).confirmed


def test_raised_exception_path_derives_the_same_signature():
    error = GenerateError(
        code=GenerateErrorCode.UNKNOWN,
        message="txt2img error: AcceleratorError: CUDA error: unknown error",
        stage="txt2img",
        details={
            "diagnostics": {
                "request_summary": {"status": 500, "stage": "txt2img", "method": "POST"},
                "error_message": "500 Server Error",
            }
        },
    )
    facts = facts_from_failure(image("forge"), exc=PipelineStageError(error))
    assert facts.fault is not None and facts.fault.value == "device_fault"
    assert assess_gpu_loss(facts, LOST).confirmed


def test_job_is_gpu_dependent_unless_every_stage_is_proven_gpu_free(monkeypatch):
    for make in (image, svd, comfy, unresolved):
        assert classify_job(make("any")).held_by_gpu_loss
    # Independence from the WebUI (SVD/Comfy) is not independence from the GPU.
    assert classify_job(svd("svd")).dependency is BackendDependency.INDEPENDENT_VIDEO
    assert classify_job(svd("svd")).held_by_gpu_loss
    # Only an explicit, frozen-identity proof lifts the hold; nothing is inferred.
    monkeypatch.setattr(backend_dependency, "_GPU_FREE_STAGES", frozenset({"txt2img"}))
    free = classify_job(image("free"))
    assert free.gpu_free and not free.held_by_gpu_loss and free.held_by_webui_outage
    assert classify_job(svd("svd")).held_by_gpu_loss
    facts = facts_from_failure(image("free"), result=failed(**DEVICE_FAULT))
    assert not needs_host_evidence(facts)
    assert assess_gpu_loss(facts, LOST).evidence_class is CLASS.NOT_GPU_FAILURE


def test_assessment_projection_is_content_free():
    outcome = classify(image("forge"), failed(**DEVICE_FAULT), LOST)
    projected = outcome.to_dict()
    assert projected["evidence_class"] == "confirmed_device_loss"
    assert projected["accelerator_fault"] == "device_fault"
    assert projected["host_evidence"] == LOST.to_dict() and projected["host_probed"] is True
    assert set(projected) == {
        "contract", "evidence_class", "accelerator_fault", "failure_category", "dispatch_certainty",
        "stage", "host_probed", "host_evidence",
    }
