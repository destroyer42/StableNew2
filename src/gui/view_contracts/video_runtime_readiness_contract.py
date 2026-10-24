"""Toolkit-neutral state for the Video Workflow "Runtime readiness" strip (PR-VID-UX-311).

The session owns no generation authority and no runtime: it holds the latest preflight for the selected workflow and
nothing else. The probe is an injected callable that the panel runs on a worker; the session never builds a payload,
touches the queue or starts a process, and what it shows cannot change what is submitted.

Staleness. Each refresh bumps a selection token; at most one worker is in flight, and a selection that changes
meanwhile is picked up when the running worker returns, so a finished probe can never overwrite a newer selection.

Blocking. Only a *finished* preflight with a blocked gate disables Queue. While a probe is running, after a probe
error, and for any gate that is ``unknown`` (it needs a runtime that is not running), Queue stays as the rest of the form
decides: the backend still refuses a job that fails a gate the strip could not see.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass

from src.gui.view_contracts.video_experiment_contract import WorkOutcome
from src.video.workflow_preflight import WorkflowPreflight

STATE_IDLE = "idle"
STATE_LOADING = "loading"
STATE_READY = "ready"
STATE_ERROR = "error"


@dataclass(frozen=True)
class RuntimeReadinessWork:
    token: int
    workflow_id: str
    workflow_version: str


@dataclass(frozen=True)
class GateRow:
    label: str
    state: str
    detail: str
    fix: str


@dataclass(frozen=True)
class RuntimeReadinessView:
    """Everything the strip renders, as plain data (no Tk)."""

    state: str
    summary: str
    rows: tuple[GateRow, ...]
    block_reason: str
    busy: bool
    #: Setup facts that are not gates (an environment override, a saved change waiting for a restart).
    notices: tuple[str, ...] = ()
    #: True only while a blocked gate is one Engine Settings > Video runtime (ComfyUI) can repair (never for RAM, VRAM,
    #: nodes or model files). The strip offers the action; it changes nothing by itself.
    repair_available: bool = False
    repair_reason: str = ""


class RuntimeReadinessSession:
    def __init__(self, *, evaluate: Callable[[str, str], WorkflowPreflight]) -> None:
        self._evaluate = evaluate
        self._lock = threading.Lock()
        self._token = 0
        self._selection: tuple[str, str] | None = None
        self._shown: tuple[str, str] | None = None
        self._state = STATE_IDLE
        self._preflight: WorkflowPreflight | None = None
        self._error = ""
        self._inflight: RuntimeReadinessWork | None = None
        self._closed = False

    # ------------------------------------------------------------------ Tk thread

    def refresh(
        self, workflow_id: str, workflow_version: str, *, force: bool = False
    ) -> RuntimeReadinessWork | None:
        """Select a workflow; returns work to start, or ``None`` (nothing to do, or a worker will follow up)."""

        with self._lock:
            if self._closed:
                return None
            selection = (str(workflow_id or ""), str(workflow_version or ""))
            if not selection[0]:
                self._selection = None
                self._shown = None
                self._preflight = None
                self._error = ""
                self._state = STATE_IDLE
                self._token += 1
                return None
            changed = selection != self._selection
            self._selection = selection
            if not changed and not force and self._state in (STATE_READY, STATE_LOADING):
                return None
            self._token += 1
            if changed:
                self._preflight = None  # a previous workflow's gates never describe this one
                self._error = ""
            self._state = STATE_LOADING
            if self._inflight is not None:
                return None  # the running worker's finish() starts the newest selection
            return self._begin_locked()

    def _begin_locked(self) -> RuntimeReadinessWork:
        assert self._selection is not None
        work = RuntimeReadinessWork(self._token, self._selection[0], self._selection[1])
        self._inflight = work
        return work

    def finish(
        self, work: RuntimeReadinessWork, outcome: WorkOutcome
    ) -> RuntimeReadinessWork | None:
        with self._lock:
            if self._inflight is work:
                self._inflight = None
            if self._closed:
                return None
            if work.token != self._token:
                # The selection moved on while this probe ran: discard it and probe the newest one.
                return self._begin_locked() if self._selection is not None else None
            if outcome.error or not isinstance(outcome.value, WorkflowPreflight):
                self._preflight = None
                self._error = outcome.error or "the readiness probe returned nothing"
                self._state = STATE_ERROR
            else:
                self._preflight = outcome.value
                self._shown = (work.workflow_id, work.workflow_version)
                self._error = ""
                self._state = STATE_READY
            return None

    def close(self) -> None:
        with self._lock:
            self._closed = True

    # ------------------------------------------------------------------ worker thread

    def run(self, work: RuntimeReadinessWork) -> WorkOutcome:
        try:
            return WorkOutcome(value=self._evaluate(work.workflow_id, work.workflow_version))
        except Exception as exc:  # noqa: BLE001 - a failed probe is shown, never raised into the worker
            return WorkOutcome(error=str(exc) or type(exc).__name__)

    # ------------------------------------------------------------------ projections

    def block_reason(self) -> str:
        with self._lock:
            # A re-probe of the same workflow keeps the last answer (a blocked gate stays blocked until the new
            # probe says otherwise); an error or a different workflow's answer never blocks.
            if self._state not in (STATE_READY, STATE_LOADING) or self._preflight is None:
                return ""
            if self._shown != self._selection:
                return ""
            return self._preflight.block_reason

    def view(self) -> RuntimeReadinessView:
        with self._lock:
            if self._state == STATE_IDLE:
                return RuntimeReadinessView(STATE_IDLE, "", (), "", False)
            if self._state == STATE_ERROR:
                return RuntimeReadinessView(
                    STATE_ERROR,
                    f"Readiness could not be checked: {self._error}",
                    (),
                    "",
                    False,
                )
            if self._preflight is None:
                return RuntimeReadinessView(STATE_LOADING, "Checking the runtime...", (), "", True)
            preflight = self._preflight
            rows = tuple(
                GateRow(gate.label, gate.state, gate.detail, gate.fix) for gate in preflight.gates
            )
            blocked = len(preflight.blocking)
            if blocked:
                summary = (
                    f"{blocked} gate{'s' if blocked != 1 else ''} blocking: Queue is off until "
                    f"{'it is' if blocked == 1 else 'they are'} fixed."
                )
            else:
                unknown = sum(1 for gate in preflight.gates if gate.state == "unknown")
                summary = "Ready to queue." + (
                    f" {unknown} item{'s' if unknown != 1 else ''} can only be checked once ComfyUI is running."
                    if unknown
                    else ""
                )
            return RuntimeReadinessView(
                STATE_READY,
                summary,
                rows,
                preflight.block_reason,
                self._state == STATE_LOADING,
                notices=preflight.notices,
                repair_available=preflight.setup_repair_available,
                repair_reason=preflight.setup_repair_reason,
            )


__all__ = [
    "STATE_ERROR",
    "STATE_IDLE",
    "STATE_LOADING",
    "STATE_READY",
    "GateRow",
    "RuntimeReadinessSession",
    "RuntimeReadinessView",
    "RuntimeReadinessWork",
]
