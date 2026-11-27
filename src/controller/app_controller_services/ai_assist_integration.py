"""Application-scoped AI Assist composition; read generation truth, never own it."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any, TypeVar

from src.ai_assist.activation import ActivationRefused
from src.ai_assist.contracts import AssistOutcome, AssistRequest, OutcomeCode
from src.ai_assist.host import GenerationActivity, read_host_memory
from src.ai_assist.manifests import (
    ModelRegistry,
    RuntimeManifest,
    load_model_registry,
    load_runtime_manifest,
    verify_installation,
)
from src.ai_assist.paths import resolve_ai_root
from src.ai_assist.preview import (
    PREVIEW_LABEL,
    PREVIEW_MEANING,
    TRUST_CANDIDATE,
    TRUST_PREVIEW,
    PreviewRefused,
    PreviewState,
    enable_preview,
    revoke_preview,
)
from src.ai_assist.remote import RemoteAssist, RemoteState
from src.ai_assist.remote_preview import (
    REMOTE_DISCLOSURE,
    REMOTE_PREVIEW_LABEL,
    UNCENSORED_MODEL,
    RemoteApproval,
    RemoteSettings,
)
from src.ai_assist.selector import (
    REFUSED_IN_FLIGHT,
    REFUSED_NOT_ATTESTED,
    REFUSED_NOT_COVERED,
    ModelChoice,
    SelectionRefused,
    list_model_choices,
    select_model,
)
from src.ai_assist.service import AiAssistService, ServicePolicy, Submission
from src.ai_assist.status import (
    EGRESS_ATTESTED,
    EGRESS_NOT_COVERED,
    MISSING_IMPORTED_MODEL,
    MISSING_PINNED_BUILD,
    MODEL_REGISTRY_PATH,
    RUNTIME_MANIFEST_PATH,
    STATE_INTEGRITY_FAILED,
    STATE_PREVIEW,
    STATE_PREVIEW_AVAILABLE,
    STATE_READY,
    AiAssistStatus,
    preview_state,
    read_status,
)
from src.queue.job_model import JobStatus

_REMOTE_STATUS = {
    RemoteState.RECOVERING: "AI Assist is checking the remote GPU.",
    RemoteState.READY: "AI Assist: Remote GPU ready.",
    RemoteState.RESTORED: "AI Assist: Remote GPU restored.",
    RemoteState.RUNNING: "AI Assist: Running on remote GPU.",
    RemoteState.UNAVAILABLE: "AI Assist: Remote GPU unavailable.",
    RemoteState.UNTRUSTED: "Remote AI requires verification of the Ollama version and manifest digest.",
    RemoteState.ERROR: "Remote AI readiness check failed.",
    RemoteState.LOCAL_FALLBACK: "AI Assist: Remote unavailable. Running local fallback.",
}

logger = logging.getLogger(__name__)

_J = TypeVar("_J")


def egress_refusal_text(egress: str, build_id: str) -> str:
    """The operator-facing words for a missing or non-covering egress attestation (one copy, shared by the request gate and
    the model selector)."""

    if egress == EGRESS_NOT_COVERED:
        return (
            f"The recorded outbound restriction does not cover runtime {build_id}. "
            "Record an attestation for this build and its executable."
        )
    return "Operator-managed outbound restriction must be attested."


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

    Local requests retain strict-offline and resource gates. An approved remote configuration starts only a
    tracked, prompt-free health monitor. The remote adapter has no generation or process-control dependencies.
    """

    def __init__(
        self,
        job_service: Callable[[], Any],
        dispatch: Callable[[Callable[[], None]], None],
        *,
        root: Path | None = None,
        runtime_manifest: RuntimeManifest | None = None,
        registry: ModelRegistry | None = None,
        remote: RemoteAssist | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._dispatch = dispatch
        self._closed = False
        self._active_id: str | None = None
        self.quiescent: bool | None = None
        self.service: AiAssistService | None = None
        self._root = resolve_ai_root(root)
        self._activity = QueueGenerationActivity(job_service)
        self._remote = remote if remote is not None else RemoteAssist(self._root)
        self._manifests: tuple[RuntimeManifest, ModelRegistry] | None = None
        try:
            self._manifests = (
                runtime_manifest
                if runtime_manifest is not None
                else load_runtime_manifest(RUNTIME_MANIFEST_PATH),
                registry if registry is not None else load_model_registry(MODEL_REGISTRY_PATH),
            )
            self.service = AiAssistService(
                root=self._root,
                runtime_manifest=self._manifests[0],
                registry=self._manifests[1],
                activity_provider=self._activity,
                remote=self._remote,
                memory_probe=read_host_memory,
                policy=ServicePolicy(
                    allow_candidate=False, allow_preview=True, strict_offline=True
                ),
            )
        except Exception:  # noqa: BLE001 - construction failure must leave a usable, disabled GUI
            logger.error("AI Assist construction failed (service_unavailable)")
        if self.service is not None:
            self._start_remote_monitor()

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
            if self._manifests is None:
                return read_status(self._root)
            return read_status(self._root, *self._manifests)
        except Exception:  # noqa: BLE001 - fixed content-free status, no paths or exception text
            return AiAssistStatus(
                STATE_INTEGRITY_FAILED, "AI readiness is unreadable. Open Operator Readiness."
            )

    def _start_remote_monitor(self) -> None:
        try:
            self._remote.start_monitor()
        except RuntimeError:
            logger.warning("Remote AI readiness monitor could not be started")

    def operator_status(self) -> AiAssistStatus:
        local = self.status()
        remote = self._remote.state()
        if remote is RemoteState.DISABLED:
            return local
        code, fallback = self._fallback_availability()
        return replace(
            local,
            summary=f"{_REMOTE_STATUS[remote]} {fallback}",
            remote_state=remote.value,
            local_fallback_ready=code is None,
        )

    def _fallback_availability(self) -> tuple[OutcomeCode | None, str]:
        code, reason = self._local_availability()
        if code is None:
            try:
                active = self._activity()
            except ActivityUnreadable:
                return (
                    OutcomeCode.GENERATION_ACTIVE,
                    "Local fallback blocked: queue activity is unreadable.",
                )
            if active.running_jobs or active.gpu_quarantined:
                return (
                    OutcomeCode.GENERATION_ACTIVE,
                    "Local fallback blocked by generation or GPU quarantine.",
                )
            return None, "Local fallback ready for request-time admission."
        return code, f"Local fallback blocked. {reason}"

    # -- AI Assist Preview (owner decision D13) ---------------------------------------------------------------------

    def preview_state(self) -> PreviewState:
        return preview_state(self.status())

    def remote_preview(self) -> tuple[RemoteSettings, str]:
        settings = self._remote.settings()
        state = self._remote.state()
        if settings.damaged:
            return (
                settings,
                "Remote Preview settings are damaged. Restore or reset them with the admin tool.",
            )
        if state is RemoteState.DISABLED:
            return settings, "Remote Preview is disabled."
        if settings.approval is None:
            return settings, "Select an approved remote model or approve one with the admin tool."
        return settings, _REMOTE_STATUS[state]

    def select_remote_model(self, approval: RemoteApproval) -> tuple[bool, str]:
        with self._lock:
            if self._closed or self.service is None or self._active_id is not None:
                return (
                    False,
                    "Remote model selection is unavailable while AI Assist is busy or closing.",
                )
            try:
                self.service.select_remote_model(approval)
            except (OSError, ValueError):
                return (
                    False,
                    "Remote model selection could not be saved. Check approval and request status.",
                )
        return True, "Remote model selected."

    def trust_label(self) -> str:
        """The label every Preview surface shows; empty when the installed model is qualified or nothing is usable."""

        remote = self._remote.state()
        if remote in (
            RemoteState.READY,
            RemoteState.RESTORED,
            RemoteState.RUNNING,
            RemoteState.RECOVERING,
        ):
            return REMOTE_PREVIEW_LABEL
        return PREVIEW_LABEL if self.status().state == STATE_PREVIEW else ""

    @staticmethod
    def preview_meaning() -> str:
        return PREVIEW_MEANING

    def enable_preview(self) -> tuple[bool, str]:
        """The operator's explicit confirmation. Records the verified active identities; never anything else."""

        if self.closed or self._manifests is None:
            return False, "AI Assist is unavailable."
        try:
            enable_preview(self._root, *self._manifests)
        except PreviewRefused as exc:
            return False, f"AI Assist Preview could not be enabled ({exc.code})."
        except Exception:  # noqa: BLE001 - fixed copy only
            return False, "AI Assist Preview could not be enabled."
        return True, "AI Assist Preview is enabled for the installed model and runtime."

    def revoke_preview(self) -> tuple[bool, str]:
        """Revoke Preview for the active model and runtime build only; other enabled models stay enabled (D20)."""

        entry = build = None
        if self._manifests is not None:
            verification = verify_installation(self._root, *self._manifests, allow_candidate=True)
            if verification.ok:
                entry, build = verification.entry, verification.build
        if revoke_preview(self._root, entry, build):
            return True, "AI Assist Preview is revoked."
        return False, "AI Assist Preview could not be revoked."

    # -- Model selector (owner decision D20) ------------------------------------------------------------------------

    def model_choices(self) -> tuple[ModelChoice, ...]:
        """Models imported and verified here, with the runtime build each would use. Read-only."""

        if self._manifests is None:
            return ()
        try:
            return list_model_choices(self._root, *self._manifests)
        except Exception:  # noqa: BLE001 - an unreadable installation lists nothing
            return ()

    def select_model(self, model_id: str) -> tuple[bool, str]:
        """Switch the active model on the operator's explicit choice. Synchronous; no thread, no process, no download.

        Refused while a request is running, and unless the egress attestation already covers the build it would use. It
        never records an attestation and never enables Preview: a model that is not enabled yet is activated and then
        needs the same explicit Enable confirmation as before."""

        if self._manifests is None:
            return False, "AI Assist is unavailable."
        with self._lock:
            if self._closed:
                return False, "Application shutdown has begun."
            in_flight = self._active_id is not None or bool(
                self.service is not None and self.service.busy
            )
            try:
                selection = select_model(
                    self._root, *self._manifests, model_id, request_in_flight=in_flight
                )
            except SelectionRefused as exc:
                return False, self._selection_refusal_text(exc)
            except ActivationRefused as exc:
                return False, f"The model could not be activated ({exc.code})."
            except Exception:  # noqa: BLE001 - fixed copy only
                return False, "The model could not be activated."
        choice = selection.choice
        if not selection.changed:
            return True, f"{choice.display_name} is already active."
        text = f"Switched to {choice.display_name} on runtime {choice.build_id}."
        if choice.trust == TRUST_CANDIDATE:
            text += " AI Assist Preview is not enabled for it yet: use Enable AI Assist Preview to confirm."
        return True, text

    @staticmethod
    def _selection_refusal_text(exc: SelectionRefused) -> str:
        if exc.code == REFUSED_IN_FLIGHT:
            return "Another AI request is running. Wait for it to finish before switching models."
        if exc.code in (REFUSED_NOT_COVERED, REFUSED_NOT_ATTESTED):
            egress = EGRESS_NOT_COVERED if exc.code == REFUSED_NOT_COVERED else ""
            return egress_refusal_text(egress, exc.build_id)
        return "That model is not imported and verified here with a compatible runtime build."

    def availability(self) -> tuple[OutcomeCode | None, str]:
        if self.closed:
            return OutcomeCode.UNAVAILABLE, "Application shutdown has begun."
        if self.service is None:
            return OutcomeCode.UNAVAILABLE, "AI Assist service is unavailable."
        remote = self._remote.state()
        if self.busy:
            message = "Another AI request is running."
            if remote in (RemoteState.RUNNING, RemoteState.LOCAL_FALLBACK):
                message = _REMOTE_STATUS[remote]
            return OutcomeCode.BUSY, message
        if remote is RemoteState.DISABLED:
            return self._local_availability()
        self._start_remote_monitor()
        if remote is RemoteState.UNTRUSTED:
            return OutcomeCode.INTEGRITY_FAILED, _REMOTE_STATUS[remote]
        if remote is RemoteState.UNAVAILABLE:
            # A request rechecks availability even when the local fallback is blocked.
            _, fallback = self._fallback_availability()
            return None, f"{_REMOTE_STATUS[remote]} {fallback} {REMOTE_DISCLOSURE}"
        return None, f"{_REMOTE_STATUS[remote]} {REMOTE_DISCLOSURE}"

    def _local_availability(self) -> tuple[OutcomeCode | None, str]:
        status = self.status()
        if status.state == STATE_INTEGRITY_FAILED:
            return (
                OutcomeCode.INTEGRITY_FAILED,
                "AI integrity check failed. Open Operator Readiness.",
            )
        if status.state == STATE_PREVIEW_AVAILABLE:
            return (
                OutcomeCode.NOT_INSTALLED,
                "AI Assist Preview is not enabled for the installed (unqualified) model. Use AI Preview to enable it.",
            )
        if status.state not in (STATE_READY, STATE_PREVIEW):
            if status.missing == MISSING_PINNED_BUILD:
                return (
                    OutcomeCode.NOT_INSTALLED,
                    "AI Assist needs a pinned runtime build: none is pinned in config/managed_ai_runtime.json.",
                )
            if status.missing == MISSING_IMPORTED_MODEL:
                return (
                    OutcomeCode.NOT_INSTALLED,
                    "AI Assist needs an imported runtime and model: nothing is imported and activated.",
                )
            return (
                OutcomeCode.NOT_INSTALLED,
                "AI Assist needs an installed runtime and model (qualified, or an enabled Preview model).",
            )
        if status.egress != EGRESS_ATTESTED:
            return (
                OutcomeCode.EGRESS_NOT_ATTESTED,
                egress_refusal_text(status.egress, status.build_id),
            )
        if status.trust == TRUST_PREVIEW:
            return None, f"{PREVIEW_LABEL}. Suggestions are advisory. Review before accepting."
        return None, "AI suggestions are advisory. Review before accepting."

    def set_dispatcher(self, dispatch: Callable[[Callable[[], None]], None]) -> None:
        """Bind the window's queued invoker; it never falls back to running Tk work on a worker."""
        with self._lock:
            self._dispatch = dispatch

    def refusal_retry_model(self, outcome: AssistOutcome) -> RemoteApproval | None:
        """The approved uncensored model to offer after another remote model refused; ``None`` otherwise."""

        if (
            outcome.code is not OutcomeCode.REFUSED_BY_MODEL
            or outcome.details.get("provider") != "remote"
            or outcome.details.get("model_name") == UNCENSORED_MODEL
        ):
            return None
        settings = self._remote.settings()
        if not settings.preferred:
            return None
        return next((a for a in settings.approvals if a.model == UNCENSORED_MODEL), None)

    def submit(
        self,
        request: AssistRequest,
        on_done: Callable[[AssistOutcome], None],
        *,
        one_off: RemoteApproval | None = None,
    ) -> Submission:
        return self._submit(request, lambda outcome: on_done(outcome), None, one_off)

    def submit_plan(
        self,
        request: AssistRequest,
        judge: Callable[[AssistOutcome], _J],
        on_done: Callable[[AssistOutcome, _J | None], None],
        *,
        one_off: RemoteApproval | None = None,
    ) -> Submission:
        """Advisory planning (AI-210): the same single-flight request, plus a deterministic ``judge``.

        ``judge`` runs once, on the AI worker thread, only for a validated suggestion (never on the GUI thread, because the
        workflow preflight may read local state). A judge failure yields ``None`` and the GUI shows no steps. The result
        is advice: this method adds no path to Intent, the compiler, the queue or any job.
        """

        return self._submit(request, on_done, judge, one_off)

    def _submit(
        self,
        request: AssistRequest,
        on_done: Callable[..., None],
        judge: Callable[[AssistOutcome], Any] | None,
        one_off: RemoteApproval | None = None,
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
                judged: Any = None
                if judge is not None and outcome.ok:
                    try:
                        judged = judge(outcome)
                    except Exception:  # noqa: BLE001 - a failed judge shows nothing; content never reaches a log
                        logger.warning("AI plan judge failed", exc_info=False)
                        judged = None

                def deliver() -> None:
                    with self._lock:
                        if self._closed or self._active_id != request.request_id:
                            return
                        self._active_id = None
                    delivered = self._remote.validate_delivery(outcome)
                    if judge is None:
                        on_done(delivered)
                    else:
                        on_done(delivered, judged if delivered.ok else None)

                with self._lock:
                    if self._closed:
                        return
                self._dispatch(deliver)

            try:
                result = (
                    self.service.submit(request, completed)
                    if one_off is None
                    else self.service.submit(request, completed, one_off=one_off)
                )
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
