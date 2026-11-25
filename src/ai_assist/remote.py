"""Remote Ollama readiness and one request per explicit AI Assist action."""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

from src.ai_assist.argv import RunLimits, Sampling
from src.ai_assist.contracts import (
    AiCancelToken,
    AssistOutcome,
    AssistRequest,
    OutcomeCode,
    SuggestionKind,
)
from src.ai_assist.framing import FramingError, build_json_schema, render_prompt
from src.ai_assist.remote_preview import (
    DuplicateRemoteKeyError,
    RemoteApproval,
    RemoteSettings,
    read_remote_settings,
    reject_duplicate_json_keys,
    select_remote_model,
)
from src.ai_assist.remote_transport import (
    MAX_REQUEST_BYTES,
    Transport,
    TransportFailure,
    loopback_request,
)
from src.ai_assist.runtime import RuntimeResult
from src.utils.thread_registry import get_thread_registry

logger = logging.getLogger(__name__)

HEALTH_SECONDS = 1.5
HEALTH_LIMIT = 128 * 1024
READY_TTL = 8.0
RECOVERY_INTERVAL = 3.0
MAX_OUTPUT_BYTES = 256 * 1024


_SUCCESS_PAYLOAD = {
    SuggestionKind.PROMPT_REWRITE: (
        "Write the revised prompts in positive and negative. If NEGATIVE_PROMPT is empty, return an empty negative. "
        "Only reproduce protected tokens that occur in the authored prompts."
    ),
    SuggestionKind.TARGET_FIT_ADVICE: "Set target to one exact identifier from Allowed targets.",
    SuggestionKind.WORKFLOW_CHOICE: "Set workflow to one exact identifier from Allowed workflows.",
    SuggestionKind.PLAN_PROPOSAL: (
        "Put the ordered advice in steps. Copy identifiers exactly, including capitalization and punctuation. "
        "For an image step, set target and use null for workflow. For a video step, set workflow and use null for target."
    ),
    SuggestionKind.SLOT_PROPOSAL: (
        "Put the proposals in proposals. Each needs a new slot_name, its values, the insertion_point number copied from "
        "the numbered positions listed in the data, and a rationale."
    ),
    SuggestionKind.PHRASE_SLOT: (
        "Put the proposals in phrase_slots. Each needs a new slot_name, its alternative values for the selected phrase, "
        "and a rationale."
    ),
    SuggestionKind.SLOT_VARIETY: (
        "Put the proposals in slots. Copy each slot name exactly into slot and put the new phrases in values. "
        "Follow the requested category for each value."
    ),
}


def _ollama_prompt(request: AssistRequest) -> str:
    # A refusal was the only concrete response shape in the shared frame. Describe both paths without
    # placing a copyable refusal object in front of the model. The wire schema still constrains both.
    return render_prompt(
        request,
        response_instructions=(
            'For a suggestion, set status to "ok" and use the schema id and kind given above. '
            + _SUCCESS_PAYLOAD[request.kind]
            + ' If you cannot or will not help, set status to "refused" and provide a short refusal_reason.'
        ),
    )


class RemoteState(StrEnum):
    DISABLED = "remote_disabled"
    RECOVERING = "remote_recovering"
    READY = "remote_ready"
    RESTORED = "remote_restored"
    UNAVAILABLE = "remote_unavailable"
    UNTRUSTED = "remote_untrusted"
    ERROR = "remote_error"
    RUNNING = "remote_running"
    LOCAL_FALLBACK = "local_fallback"


@dataclass(frozen=True, slots=True)
class _Health:
    identity: RemoteApproval
    state: RemoteState
    checked_at: float


def _read_object(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicate_json_keys)
    except (RecursionError, ValueError):
        raise TransportFailure("invalid_json") from None
    if not isinstance(value, dict):
        raise TransportFailure("invalid_json")
    return value


def _wire_problem(output: str, schema: dict[str, Any]) -> str:
    """Enforce the envelope sent to Ollama before the shared semantic validator."""
    try:
        document = json.loads(output, object_pairs_hook=reject_duplicate_json_keys)
    except DuplicateRemoteKeyError:
        return "remote_duplicate_response_key"
    except (RecursionError, ValueError):
        # The canonical validator classifies malformed JSON and plain-text refusals.
        return ""
    if not isinstance(document, dict):
        return ""
    for branch in schema["oneOf"]:
        fields = branch["properties"]
        if document.get("status") != fields["status"]["const"]:
            continue
        if not set(branch["required"]) <= document.keys() <= fields.keys():
            return "remote_response_fields"
        if any(
            fields[key].get("type") == "string" and not isinstance(value, str)
            for key, value in document.items()
        ):
            return "remote_response_field_type"
        break
    return ""


class RemoteAssist:
    def __init__(self, root: Path, *, transport: Transport = loopback_request) -> None:
        self._root = root
        self._transport = transport
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._monitor_token = AiCancelToken()
        self._monitor: threading.Thread | None = None
        self._health: _Health | None = None
        self._probe_number = 0
        self._active: RemoteState | None = None

    def settings(self) -> RemoteSettings:
        return read_remote_settings(self._root)

    def select_model(self, approval: RemoteApproval) -> None:
        select_remote_model(self._root, approval)

    def state(self) -> RemoteState:
        settings = self.settings()
        if not settings.preferred:
            return RemoteState.DISABLED
        if settings.approval is None:
            return RemoteState.UNTRUSTED
        with self._lock:
            if self._active is not None:
                return self._active
            health = self._health
            if health is None or health.identity != settings.approval:
                return RemoteState.RECOVERING
            if health.state in (RemoteState.READY, RemoteState.RESTORED):
                if time.monotonic() - health.checked_at > READY_TTL:
                    return RemoteState.RECOVERING
            return health.state

    def start_monitor(self) -> None:
        if self.settings().approval is None:
            return
        with self._lock:
            if self._stop.is_set() or (self._monitor is not None and self._monitor.is_alive()):
                return
            self._monitor = get_thread_registry().spawn(
                target=self._monitor_work,
                name="AiAssist-RemoteHealth",
                purpose="Remote AI readiness",
            )

    def validate_delivery(self, outcome: AssistOutcome) -> AssistOutcome:
        """The GUI may deliver a worker result after an administrative approval change."""
        if not outcome.ok or outcome.details.get("provider") != "remote":
            return outcome
        identity = self.settings().approval
        if (
            identity is not None
            and outcome.details.get("model_sha256") == identity.digest
            and outcome.details.get("model_name") == identity.model
            and outcome.details.get("runtime_build_id") == f"ollama-{identity.version}"
        ):
            return outcome
        return replace(
            outcome,
            code=OutcomeCode.INTEGRITY_FAILED,
            reason="remote_identity_mismatch",
            suggestion=None,
        )

    def begin_shutdown(self) -> None:
        with self._lock:
            self._stop.set()
            self._monitor_token.cancel()

    def join(self, timeout: float) -> bool:
        with self._lock:
            monitor = self._monitor
        if monitor is not None and monitor.is_alive():
            if monitor is threading.current_thread():
                return False
            monitor.join(timeout)
            return not monitor.is_alive()
        return True

    def set_active(self, provider: RemoteState | None) -> None:
        with self._lock:
            self._active = provider

    def _monitor_work(self) -> None:
        while not self._stop.is_set():
            identity = self.settings().approval
            with self._lock:
                previous = self._health
            if identity is not None and (
                previous is None
                or previous.identity != identity
                or time.monotonic() - previous.checked_at
                >= (
                    READY_TTL / 2
                    if previous.state in (RemoteState.READY, RemoteState.RESTORED)
                    else RECOVERY_INTERVAL
                )
            ):
                try:
                    self._probe(identity, self._monitor_token)
                except TransportFailure:
                    pass
            self._stop.wait(RECOVERY_INTERVAL)

    def _probe(self, identity: RemoteApproval, token: AiCancelToken) -> None:
        with self._lock:
            self._probe_number += 1
            number = self._probe_number
        try:
            version = self._metadata("/api/version", token)
            if version.get("version") != identity.version:
                raise TransportFailure("identity_mismatch")
            catalog = self._metadata("/api/tags", token).get("models")
            if not isinstance(catalog, list):
                raise TransportFailure("identity_mismatch")
            matches = [
                model.get("digest")
                for model in catalog
                if isinstance(model, dict)
                and isinstance(name := model.get("name"), str)
                and name.casefold() == identity.model.casefold()
            ]
            if matches != [identity.digest] and matches != [f"sha256:{identity.digest}"]:
                raise TransportFailure("identity_mismatch")
            self._require_approval(identity, token)
        except TransportFailure as exc:
            reason = str(exc)
            if reason == "cancelled":
                raise
            if reason in {"identity_mismatch", "invalid_json", "invalid_http"}:
                state = RemoteState.UNTRUSTED
            elif reason == "disconnected":
                state = RemoteState.UNAVAILABLE
            else:
                state = RemoteState.ERROR
            if not token.cancelled:
                self._publish_health(number, identity, state)
            raise
        except Exception:  # noqa: BLE001 - unexpected probe failures must stay content-free
            logger.warning("Remote AI readiness probe failed unexpectedly")
            self._publish_health(number, identity, RemoteState.ERROR)
            raise TransportFailure("health_probe_failed") from None
        else:
            self._publish_health(number, identity, RemoteState.READY)

    def _publish_health(self, number: int, identity: RemoteApproval, state: RemoteState) -> None:
        with self._lock:
            if self._stop.is_set() or self._probe_number != number:
                return
            previous = self._health
            if (
                state is RemoteState.READY
                and previous is not None
                and previous.identity == identity
                and previous.state is RemoteState.UNAVAILABLE
            ):
                state = RemoteState.RESTORED
            self._health = _Health(identity, state, time.monotonic())

    def _metadata(self, path: str, token: AiCancelToken) -> dict[str, Any]:
        status, raw = self._transport(path, None, token, HEALTH_SECONDS, HEALTH_LIMIT)
        if status in (401, 403, 404):
            raise TransportFailure("identity_mismatch")
        if status != 200:
            raise TransportFailure("health_http_error")
        return _read_object(raw)

    def _require_approval(self, identity: RemoteApproval, token: AiCancelToken) -> None:
        if token.cancelled or self._stop.is_set():
            raise TransportFailure("cancelled")
        if self.settings().approval != identity:
            raise TransportFailure("identity_mismatch")

    def run(
        self,
        identity: RemoteApproval,
        request: AssistRequest,
        token: AiCancelToken,
        limits: RunLimits,
        sampling: Sampling,
    ) -> RuntimeResult:
        started = time.monotonic()
        try:
            schema = build_json_schema(request)
            body = json.dumps(
                {
                    "model": identity.model_reference,
                    "prompt": _ollama_prompt(request),
                    "format": schema,
                    "stream": False,
                    "think": False,
                    "options": {
                        "num_ctx": limits.context_tokens,
                        "num_predict": limits.max_new_tokens,
                        "temperature": sampling.temperature,
                        "top_p": sampling.top_p,
                        "top_k": sampling.top_k,
                        "presence_penalty": sampling.presence_penalty,
                        "seed": sampling.seed,
                    },
                },
                ensure_ascii=True,
                allow_nan=False,
            ).encode("ascii")
        except (FramingError, ValueError):
            return RuntimeResult(OutcomeCode.INVALID_REQUEST, "invalid_frame")
        if len(body) > MAX_REQUEST_BYTES:
            return RuntimeResult(OutcomeCode.INVALID_REQUEST, "remote_request_too_large")

        try:
            self._require_approval(identity, token)
            # The short-lived readiness cache is for display and monitoring. Revalidate identity before sending data.
            self._probe(identity, token)
            self._require_approval(identity, token)
            self.set_active(RemoteState.RUNNING)
            status, raw = self._transport(
                "/api/generate",
                body,
                token,
                limits.timeout_seconds,
                min(limits.max_stdout_bytes, MAX_OUTPUT_BYTES),
            )
            self._require_approval(identity, token)
            if status in (401, 403, 404) or 300 <= status < 400:
                raise TransportFailure("identity_mismatch")
            if status != 200:
                raise TransportFailure("generation_http_error")
            response = _read_object(raw)
            if response.get("model") != identity.model_reference:
                raise TransportFailure("identity_mismatch")
            output = response.get("response")
            if response.get("done") is not True or not isinstance(output, str):
                raise TransportFailure("invalid_response")
            raw_output = output.encode("utf-8")
            if problem := _wire_problem(output, schema):
                return RuntimeResult(
                    OutcomeCode.MALFORMED,
                    problem,
                    elapsed_ms=int((time.monotonic() - started) * 1000),
                )
        except UnicodeError:
            return RuntimeResult(OutcomeCode.MALFORMED, "remote_invalid_response")
        except TransportFailure as exc:
            reason = str(exc)
            if reason in {"disconnected", "response_lost", "identity_mismatch"}:
                with self._lock:
                    self._probe_number += 1
                    self._health = _Health(
                        identity,
                        RemoteState.UNAVAILABLE
                        if reason in {"disconnected", "response_lost"}
                        else RemoteState.UNTRUSTED,
                        time.monotonic(),
                    )
            code = {
                "cancelled": OutcomeCode.CANCELLED,
                "timeout": OutcomeCode.TIMEOUT,
                "identity_mismatch": OutcomeCode.INTEGRITY_FAILED,
                "invalid_json": OutcomeCode.MALFORMED,
                "invalid_response": OutcomeCode.MALFORMED,
                "response_too_large": OutcomeCode.MALFORMED,
            }.get(reason, OutcomeCode.UNAVAILABLE)
            return RuntimeResult(
                code, f"remote_{reason}", elapsed_ms=int((time.monotonic() - started) * 1000)
            )
        return RuntimeResult(
            None, stdout=raw_output, elapsed_ms=int((time.monotonic() - started) * 1000)
        )
