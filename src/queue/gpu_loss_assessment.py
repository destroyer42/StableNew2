# Subsystem: Queue
# Role: Pure, content-free assessment of whether a failed job shows GPU device loss (PR-QUEUE-GPU-180).

"""Classify one failed job against host GPU evidence.

Inputs are typed facts only: the frozen NJR dependency, the existing WebUI failure category, a fixed-vocabulary
accelerator-fault code and (when it was needed) one read-only host GPU evidence record. The result is a stable,
content-free evidence class.

Safety properties, each covered by tests:

* A failure signature is a *suspicion* that gates the host probe. It never confirms a loss on its own; only
  ``DEVICE_LOST`` host evidence does. A healthy WebUI response is irrelevant to this decision.
* An unobtainable probe is ``EVIDENCE_UNAVAILABLE``, never confirmation.
* An allocation failure (out of memory) proves the driver answered, so it never gates the host probe.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from src.api.webui_failure_evidence import (
    METADATA_KEY,
    DispatchCertainty,
    FailureCategory,
    assess_exception,
    assess_result,
    build_failure_evidence,
    completed_work,
)
from src.queue.backend_dependency import BackendDependency, classify_job
from src.utils.gpu_device_health import (
    AcceleratorFault,
    HostGpuEvidence,
    HostGpuState,
    classify_accelerator_fault,
)

CONTRACT = "gpu_loss_assessment/1"


class GpuLossEvidenceClass(str, Enum):
    #: Host evidence reports the device lost, on a failure that gave reason to ask.
    CONFIRMED_DEVICE_LOSS = "confirmed_device_loss"
    #: The accelerator runtime reported a device-level fault but the host still enumerates the device.
    SUSPECTED_DEVICE_LOSS = "suspected_device_loss"
    #: Allocation failure: recoverable, and the device demonstrably answered.
    CUDA_OUT_OF_MEMORY = "cuda_out_of_memory"
    #: Numerical model/precision failure.
    MODEL_FAILURE = "model_failure"
    #: The backend was unreachable/ambiguous but the host GPU is present.
    TRANSPORT_FAILURE = "transport_failure"
    #: Host evidence was needed and could not be obtained.
    EVIDENCE_UNAVAILABLE = "evidence_unavailable"
    #: No accelerator evidence: an ordinary application, validation or HTTP failure.
    NOT_GPU_FAILURE = "not_gpu_failure"


_TRANSPORT_CATEGORIES = frozenset(
    {
        FailureCategory.PRE_DISPATCH_UNAVAILABLE,
        FailureCategory.READINESS_FAILURE,
        FailureCategory.OUTCOME_UNKNOWN,
        FailureCategory.TIMEOUT,
    }
)


@dataclass(frozen=True, slots=True)
class GpuFailureFacts:
    #: The failed job is not proven GPU-free (see ``DependencyAssessment.held_by_gpu_loss``).
    gpu_dependent: bool
    fault: AcceleratorFault | None = None
    category: FailureCategory | None = None
    certainty: DispatchCertainty | None = None
    #: The existing typed signal that the backend itself looked unavailable (transport, 5xx, readiness).
    suspects_outage: bool = False
    stage: str | None = None
    #: The job already produced output; used only to keep the projection honest, never to replay anything.
    completed_work: bool = False


@dataclass(frozen=True, slots=True)
class GpuLossAssessment:
    evidence_class: GpuLossEvidenceClass
    facts: GpuFailureFacts
    #: Host evidence consulted for this decision (``None`` when the failure never warranted a probe).
    host: HostGpuEvidence | None = None

    @property
    def confirmed(self) -> bool:
        return self.evidence_class is GpuLossEvidenceClass.CONFIRMED_DEVICE_LOSS

    def to_dict(self) -> dict[str, Any]:
        facts = self.facts
        return {
            "contract": CONTRACT,
            "evidence_class": self.evidence_class.value,
            "accelerator_fault": facts.fault.value if facts.fault is not None else None,
            "failure_category": facts.category.value if facts.category is not None else None,
            "dispatch_certainty": facts.certainty.value if facts.certainty is not None else None,
            "stage": facts.stage,
            "host_probed": self.host is not None,
            "host_evidence": self.host.to_dict() if self.host is not None else None,
        }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def facts_from_failure(
    job: Any,
    *,
    result: Mapping[str, Any] | None = None,
    exc: BaseException | None = None,
) -> GpuFailureFacts:
    """Typed facts of one failed job, from a raised exception or a normalized unsuccessful result."""

    dependency = classify_job(job)
    gpu_dependent = dependency.held_by_gpu_loss
    runs_webui = dependency.dependency is not BackendDependency.INDEPENDENT_VIDEO
    if exc is not None:
        evidence: Mapping[str, Any] = build_failure_evidence(exc)
        assessment = assess_exception(exc, job_runs_webui_stage=runs_webui)
        texts: list[Any] = [str(exc)]
        done = False
    else:
        data = _mapping(result)
        metadata = _mapping(data.get("metadata"))
        evidence = _mapping(metadata.get(METADATA_KEY)) or _mapping(data.get(METADATA_KEY))
        assessment = assess_result(data, job_runs_webui_stage=runs_webui)
        texts = [data.get("error")]
        done = completed_work(data)
    recorded = evidence.get("accelerator_fault")
    try:
        fault = AcceleratorFault(recorded) if recorded else None
    except ValueError:
        fault = None
    if fault is None:
        fault = classify_accelerator_fault(*texts)
    category = assessment.category if assessment.category is not FailureCategory.NOT_WEBUI else None
    return GpuFailureFacts(
        gpu_dependent=gpu_dependent,
        fault=fault,
        category=category,
        certainty=assessment.certainty if category is not None else None,
        suspects_outage=assessment.suspects_outage,
        stage=assessment.stage,
        completed_work=done,
    )


def needs_host_evidence(facts: GpuFailureFacts) -> bool:
    """Whether the failure warrants one read-only host GPU query."""

    if not facts.gpu_dependent:
        return False
    if facts.fault is AcceleratorFault.DEVICE_FAULT:
        return True
    if facts.fault is not None:
        return False  # allocation/numeric failures prove the device answered
    return facts.suspects_outage


def assess_gpu_loss(facts: GpuFailureFacts, host: HostGpuEvidence | None = None) -> GpuLossAssessment:
    """Pure decision table; ``host`` is only consulted when :func:`needs_host_evidence` holds."""

    def done(evidence_class: GpuLossEvidenceClass, consulted: HostGpuEvidence | None = None) -> GpuLossAssessment:
        return GpuLossAssessment(evidence_class, facts, consulted)

    if not facts.gpu_dependent:
        return done(GpuLossEvidenceClass.NOT_GPU_FAILURE)
    if facts.fault is AcceleratorFault.OUT_OF_MEMORY:
        return done(GpuLossEvidenceClass.CUDA_OUT_OF_MEMORY)
    if facts.fault is AcceleratorFault.NUMERIC_FAULT:
        return done(GpuLossEvidenceClass.MODEL_FAILURE)
    if not needs_host_evidence(facts):
        return done(GpuLossEvidenceClass.NOT_GPU_FAILURE)
    if host is None or host.state is HostGpuState.UNAVAILABLE:
        return done(GpuLossEvidenceClass.EVIDENCE_UNAVAILABLE, host)
    if host.state is HostGpuState.DEVICE_LOST:
        return done(GpuLossEvidenceClass.CONFIRMED_DEVICE_LOSS, host)
    if facts.fault is AcceleratorFault.DEVICE_FAULT:
        return done(GpuLossEvidenceClass.SUSPECTED_DEVICE_LOSS, host)
    if facts.category in _TRANSPORT_CATEGORIES:
        return done(GpuLossEvidenceClass.TRANSPORT_FAILURE, host)
    return done(GpuLossEvidenceClass.NOT_GPU_FAILURE, host)


__all__ = [
    "CONTRACT",
    "GpuFailureFacts",
    "GpuLossAssessment",
    "GpuLossEvidenceClass",
    "assess_gpu_loss",
    "facts_from_failure",
    "needs_host_evidence",
]
