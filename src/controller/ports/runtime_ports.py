"""runtime_ports — Protocol definitions for runtime wiring contracts.

These Protocol classes replace ad-hoc ``hasattr``/``getattr`` probing at
consumer sites.  Any object that implements the methods named in a Protocol
satisfies it structurally (Python ≥ 3.8 typing.Protocol duck-typing).

Usage::

    from src.controller.ports.runtime_ports import NJRSummaryPort

    # Instead of:            hasattr(job, "to_unified_summary")
    # Use:                   isinstance(job, NJRSummaryPort)
    #
    # Or, with TYPE_CHECKING: annotate parameters as NJRSummaryPort
    # so IDEs surface the contract.

Extracted from ad-hoc probing in:
- src/gui/preview_panel_v2.py (PR-049)
- src/controller/job_service.py (PR-049)
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class NJRSummaryPort(Protocol):
    """Structural contract for objects that can produce a unified job summary.

    Satisfied by ``NormalizedJobRecord`` in ``src/pipeline/job_models_v2.py``.
    Using this Protocol instead of bare ``hasattr`` probing makes the intent
    explicit and surfaces type errors in IDEs.
    """

    def to_unified_summary(self) -> Any:
        """Return a ``UnifiedJobSummary`` (or equivalent summary object)."""
        ...


@runtime_checkable
class NJRUISummaryPort(Protocol):
    """Structural contract for objects that can produce a UI-summary.

    Satisfied by ``NormalizedJobRecord`` in ``src/pipeline/job_models_v2.py``.
    """

    def to_ui_summary(self) -> Any:
        """Return a ``JobUiSummary`` (or equivalent UI-summary object)."""
        ...


@runtime_checkable
class JobCompletionCallbackPort(Protocol):
    """Structural contract for objects that accept job-completion notifications.

    Satisfied by ``LearningController`` and any other controller that exposes
    an ``on_job_completed_callback`` handler.
    """

    def on_job_completed_callback(self, job: Any, result: Any) -> None:
        """Handle a job-completion event."""
        ...
