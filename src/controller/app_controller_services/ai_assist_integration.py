"""Application-scoped Offline AI Assist composition; read generation truth, never own it."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.ai_assist.contracts import AssistOutcome, AssistRequest, OutcomeCode
from src.ai_assist.host import GenerationActivity, read_host_memory
from src.ai_assist.manifests import load_model_registry, load_runtime_manifest
from src.ai_assist.paths import resolve_ai_root
from src.ai_assist.service import AiAssistService, ServicePolicy, Submission
from src.ai_assist.status import (
    MODEL_REGISTRY_PATH,
    RUNTIME_MANIFEST_PATH,
    STATE_INTEGRITY_FAILED,
    STATE_READY,
    AiAssistStatus,
    read_status,
)
from src.queue.job_model import JobStatus

logger = logging.getLogger(__name__)


class ActivityUnreadable(RuntimeError):
    """Authoritative generation activity is unavailable; never an idle reading."""


class QueueGenerationActivity:
    """Use the injected production JobService's supported, locked queue readers."""

    def __init__(self, job_service: Callable[[], Any]) -> None:
        self._job_service = job_service

    def __call__(self) -> GenerationActivity:
        try:
            queue = self._job_service().job_queue
            running = queue.list_jobs(status_filter=JobStatus.RUNNING)
            quarantined = queue.is_gpu_quarantined()
            if not isinstance(running, list) or type(quarantined) is not bool:
                raise ActivityUnreadable("activity_unreadable")
            if any(job.status is not JobStatus.RUNNING for job in running):
                raise ActivityUnreadable("activity_unreadable")
            # list_jobs takes its snapshot under the queue lock; queued work is never counted.
            return GenerationActivity(len(running), quarantined)
        except Exception:  # noqa: BLE001 - exception text can contain private job metadata
            raise ActivityUnreadable("activity_unreadable") from None


class AiAssistIntegration:
    """One service per application, with lifetime-checked delivery on the existing UI scheduler.

    Construction reads pinned manifests only. No import/install/download, deep hashing, worker or process launch.
    Production always requires qualification and the operator-managed outbound restriction attestation.
    """

    def __init__(
        self,
        job_service: Callable[[], Any],
        dispatch: Callable[[Callable[[], None]], None],
        *,
        root: Path | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._dispatch = dispatch
        self._closed = False
        self._active_id: str | None = None
        self.quiescent: bool | None = None
        self.service: AiAssistService | None = None
        self._root = resolve_ai_root(root)
        try:
            self.service = AiAssistService(
                root=self._root,
                runtime_manifest=load_runtime_manifest(RUNTIME_MANIFEST_PATH),
                registry=load_model_registry(MODEL_REGISTRY_PATH),
                activity_provider=QueueGenerationActivity(job_service),
                memory_probe=read_host_memory,
                policy=ServicePolicy(allow_candidate=False, strict_offline=True),
            )
        except Exception:  # noqa: BLE001 - construction failure must leave a usable, disabled GUI
            logger.error("Offline AI Assist construction failed (service_unavailable)")

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._active_id is not None

    def status(self) -> AiAssistStatus:
        try:
            return read_status(self._root)
        except Exception:  # noqa: BLE001 - fixed content-free status, no paths or exception text
            return AiAssistStatus(
                STATE_INTEGRITY_FAILED, "AI readiness is unreadable. Open Operator Readiness."
            )

    def set_dispatcher(self, dispatch: Callable[[Callable[[], None]], None]) -> None:
        """Bind the window's queued invoker; it never falls back to running Tk work on a worker."""
        with self._lock:
            self._dispatch = dispatch

    def availability(self) -> tuple[OutcomeCode | None, str]:
        if self.closed:
            return OutcomeCode.UNAVAILABLE, "Application shutdown has begun."
        if self.service is None:
            return OutcomeCode.UNAVAILABLE, "AI Assist service is unavailable."
        if self.busy:
            return OutcomeCode.BUSY, "Another AI request is running."
        status = self.status()
        if status.state == STATE_INTEGRITY_FAILED:
            return (
                OutcomeCode.INTEGRITY_FAILED,
                "AI integrity check failed. Open Operator Readiness.",
            )
        if status.state != STATE_READY:
            return (
                OutcomeCode.NOT_INSTALLED,
                "AI Assist needs an installed, qualified runtime and model.",
            )
        if status.egress != "attested":
            return (
                OutcomeCode.EGRESS_NOT_ATTESTED,
                "Operator-managed outbound restriction must be attested.",
            )
        return None, "AI suggestions are advisory. Review before accepting."

    def submit(
        self, request: AssistRequest, on_done: Callable[[AssistOutcome], None]
    ) -> Submission:
        with self._lock:
            if self._closed or self.service is None:
                return Submission(
                    False,
                    AssistOutcome(OutcomeCode.UNAVAILABLE, request.request_id, "service_closed"),
                )
            if self._active_id is not None:
                return Submission(
                    False,
                    AssistOutcome(OutcomeCode.BUSY, request.request_id, "another_request_active"),
                )
            self._active_id = request.request_id

            def completed(outcome: AssistOutcome) -> None:
                # This callback runs on the service worker. It only enqueues; never reads a widget or invokes Tk.
                def deliver() -> None:
                    with self._lock:
                        if self._closed or self._active_id != request.request_id:
                            return
                        self._active_id = None
                    on_done(outcome)

                with self._lock:
                    if self._closed:
                        return
                self._dispatch(deliver)

            try:
                result = self.service.submit(request, completed)
            except Exception:  # noqa: BLE001 - only fixed messages may cross into the GUI
                result = Submission(
                    False,
                    AssistOutcome(OutcomeCode.UNAVAILABLE, request.request_id, "submission_failed"),
                )
            if not result.accepted:
                self._active_id = None
            return result

    def cancel(self, request_id: str) -> bool:
        return bool(self.service is not None and self.service.cancel(request_id))

    def begin_shutdown(self) -> None:
        with self._lock:
            self._closed = True
            if self.service is not None:
                self.service.begin_shutdown()

    def shutdown(self, timeout: float = 10.0) -> bool:
        self.begin_shutdown()
        try:
            self.quiescent = self.service is None or self.service.shutdown(timeout) is True
        except Exception:  # noqa: BLE001 - observable failure, never assume a child exited
            self.quiescent = False
        if not self.quiescent:
            logger.error("Offline AI Assist did not quiesce within its shutdown bound")
        return self.quiescent
