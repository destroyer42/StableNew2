"""learning_completion_router — routes job-completion events to the learning
controller without hard-wiring AppController to GUI internals.

Extracted from AppController._create_learning_completion_handler (PR-047).
AppController delegates to build_learning_completion_handler(); the routing
logic is now testable in isolation.

Uses runtime_ports.JobCompletionCallbackPort to replace bare getattr probing
for the callback (PR-049).
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from src.controller.ports.runtime_ports import JobCompletionCallbackPort

logger = logging.getLogger(__name__)


def route_job_completion_to_learning(
    main_window: Any,
    job: Any,
    result: Any,
) -> None:
    """Deliver a job-completion event to the learning controller.

    Walks ``main_window.learning_tab`` to find the learning controller and
    calls ``on_job_completed_callback`` if present.  All attribute lookups are
    guarded so a missing or partially-constructed window never raises.

    Args:
        main_window: The active GUI window (or ``None``).
        job: The completed Job object.
        result: The job result dict.
    """
    if main_window is None:
        return

    learning_tab = getattr(main_window, "learning_tab", None)
    if learning_tab is None:
        return

    controller_obj = getattr(learning_tab, "learning_controller", None)
    if controller_obj is None:
        controller_obj = getattr(learning_tab, "controller", None)
    if controller_obj is None:
        return

    # Use the explicit port contract (PR-049) instead of bare getattr + callable probe.
    if isinstance(controller_obj, JobCompletionCallbackPort):
        try:
            controller_obj.on_job_completed_callback(job, result)
        except Exception:
            logger.exception("Error in learning on_job_completed_callback")


def build_learning_completion_handler(
    get_main_window: Callable[[], Any],
) -> Callable[[Any, Any], None]:
    """Return a job-completion handler that routes to the learning subsystem.

    ``get_main_window`` is a zero-argument callable that returns the current
    main window (or ``None``).  Using a callable instead of the window object
    directly avoids capturing a stale reference during controller construction.

    Returns:
        A ``(job, result) -> None`` handler suitable for passing to the runner.
    """

    def handler(job: Any, result: Any) -> None:
        route_job_completion_to_learning(get_main_window(), job, result)

    return handler
