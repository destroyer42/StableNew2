"""WebUI outage and GPU device-loss containment owned at the JobService boundary (PR-QUEUE-WEBUI-171, PR-QUEUE-GPU-180).

``JobService`` already owns continuous-dispatch policy and the shutdown fence; this is the counterpart for backend
outages. It binds the transient :class:`WebUIOutageCoordinator` and the :class:`GpuLossCoordinator` to the service's one
runner. It adds no queue, runner or lifecycle authority: the queue's eligibility flags decide claims, the single worker
executes, and the process managers remain the only process owners.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.controller.gpu_loss_coordinator import GpuLossCoordinator
from src.controller.webui_outage_coordinator import WebUIOutageCoordinator

if TYPE_CHECKING:
    from src.controller.job_service import JobService


def bind_webui_outage_containment(
    service: JobService,
    *,
    coordinator: WebUIOutageCoordinator | None = None,
    gpu_loss: GpuLossCoordinator | None = None,
) -> WebUIOutageCoordinator:
    """Create (or adopt) the coordinators and hand each to the runner as its observer."""

    bound = coordinator or WebUIOutageCoordinator(service.job_queue)
    service.webui_outage = bound
    configure = getattr(service.runner, "set_outage_observer", None)
    if callable(configure):
        configure(bound)
    gpu = gpu_loss or getattr(service, "gpu_loss", None) or GpuLossCoordinator(service.job_queue)
    service.gpu_loss = gpu
    configure_gpu = getattr(service.runner, "set_gpu_loss_observer", None)
    if callable(configure_gpu):
        configure_gpu(gpu)
    return bound


def arm_runtime_handoff(service: JobService) -> bool:
    """Arm the queue-driven runtime handoff on the service's one coordinator (production wiring only).

    Injected and test services never call this, so they stay inert. Returns whether a coordinator was armed.
    """

    coordinator = getattr(service, "webui_outage", None)
    arm = getattr(coordinator, "enable_runtime_handoff", None)
    if not callable(arm):
        return False
    arm()
    return True


def snapshot(service: JobService) -> dict[str, Any]:
    coordinator = getattr(service, "webui_outage", None)
    return coordinator.snapshot() if coordinator is not None else {}


def gpu_snapshot(service: JobService) -> dict[str, Any]:
    coordinator = getattr(service, "gpu_loss", None)
    return coordinator.snapshot() if coordinator is not None else {}


def diagnostics(service: JobService) -> dict[str, Any]:
    """Both containment projections under their stable diagnostics keys."""

    return {"webui_outage": snapshot(service), "gpu_device_loss": gpu_snapshot(service)}
