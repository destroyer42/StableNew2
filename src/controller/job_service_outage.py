"""WebUI outage containment owned at the JobService boundary (PR-QUEUE-WEBUI-171).

``JobService`` already owns continuous-dispatch policy and the shutdown fence; this is the counterpart for a WebUI
outage. It binds the transient :class:`WebUIOutageCoordinator` to the service's one runner. It adds no queue, runner or
lifecycle authority and persists nothing: the queue's in-memory hold decides eligibility, the single worker executes,
and ``WebUIProcessManager`` remains the only process owner.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.controller.webui_outage_coordinator import WebUIOutageCoordinator

if TYPE_CHECKING:
    from src.controller.job_service import JobService


def bind_webui_outage_containment(
    service: JobService, *, coordinator: WebUIOutageCoordinator | None = None
) -> WebUIOutageCoordinator:
    """Create (or adopt) the coordinator and hand it to the runner as its outage observer."""

    bound = coordinator or WebUIOutageCoordinator(service.job_queue)
    service.webui_outage = bound
    configure = getattr(service.runner, "set_outage_observer", None)
    if callable(configure):
        configure(bound)
    return bound


def snapshot(service: JobService) -> dict[str, Any]:
    coordinator = getattr(service, "webui_outage", None)
    return coordinator.snapshot() if coordinator is not None else {}
