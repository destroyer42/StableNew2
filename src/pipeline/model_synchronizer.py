"""Deterministic A1111 checkpoint synchronization for pipeline execution."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, NoReturn

DEFAULT_MODEL_SWITCH_TIMEOUT_SECONDS = 30.0
DEFAULT_MODEL_SWITCH_POLL_INTERVAL_SECONDS = 0.5


#: Failure kinds that are a verified checkpoint problem (the endpoint answered; the selected checkpoint
#: is not the active one and could not be made so).  Every other kind (``query_failed``, ``change_error``,
#: ``invalid_request``) is not evidence about the checkpoint and keeps its generic reporting.
CHECKPOINT_PROBLEM_KINDS = frozenset({"writes_disabled", "change_rejected", "not_applied"})

_MAX_NAME_CHARS = 80
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]+")


def operator_model_title(raw: str | None) -> str:
    """A checkpoint title for operator text: file name only (no directories), bounded, single line."""

    text = _CONTROL_CHARS.sub(" ", str(raw or "")).strip().replace("\\", "/").rstrip("/")
    text = text.rsplit("/", 1)[-1].strip()
    if not text:
        return "unknown"
    return text if len(text) <= _MAX_NAME_CHARS else text[: _MAX_NAME_CHARS - 1].rstrip() + "…"


class ModelSynchronizationError(RuntimeError):
    """Raised when A1111 cannot verify the checkpoint requested by an NJR.

    ``kind`` is a fixed vocabulary (never parsed from the message); ``requested`` / ``actual`` are the raw
    names the failure was raised with.  ``operator_message()`` is the bounded, path-free text for operators.
    """

    def __init__(
        self,
        message: str,
        *,
        kind: str = "unspecified",
        requested: str | None = None,
        actual: str | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.requested = requested
        self.actual = actual

    @property
    def is_checkpoint_problem(self) -> bool:
        return self.kind in CHECKPOINT_PROBLEM_KINDS

    def operator_message(self) -> str | None:
        """Operator-readable reason for a verified checkpoint problem, else ``None`` (not a checkpoint issue)."""

        if not self.is_checkpoint_problem:
            return None
        wanted = operator_model_title(self.requested)
        active = operator_model_title(self.actual) if self.actual else None
        state = f" (it reports '{active}')" if active else ""
        if self.kind == "writes_disabled":
            reason = (
                f"The WebUI checkpoint is not the selected '{wanted}'{state} and StableNew is not "
                "allowed to change it."
            )
        elif self.kind == "change_rejected":
            reason = (
                f"The WebUI refused to switch to the selected checkpoint '{wanted}'{state}; it may "
                "no longer be available."
            )
        else:
            reason = (
                f"The WebUI did not switch to the selected checkpoint '{wanted}'{state}; it may "
                "have been changed or removed outside StableNew."
            )
        return (
            f"Checkpoint mismatch: {reason} No images were generated. Restore the selected model in "
            "the WebUI, or prepare a new job with an available model."
        )


@dataclass(frozen=True)
class ModelSynchronizationResult:
    actual_model: str
    switched: bool


def normalize_model_name(raw: str | None) -> str | None:
    """Normalize harmless A1111 checkpoint identity variations."""
    if not raw:
        return None
    cleaned = str(raw).strip()
    if not cleaned:
        return None
    cleaned = cleaned.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = re.sub(r"\s*\[[a-f0-9]+\]$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"\.(safetensors|ckpt|pt|pth)$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned.lower()


class A1111ModelSynchronizer:
    """Synchronize and verify A1111's actual checkpoint before generation."""

    def __init__(
        self,
        client: Any,
        *,
        timeout_seconds: float = DEFAULT_MODEL_SWITCH_TIMEOUT_SECONDS,
        poll_interval_seconds: float = DEFAULT_MODEL_SWITCH_POLL_INTERVAL_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client
        self._timeout_seconds = max(0.0, float(timeout_seconds))
        self._poll_interval_seconds = max(0.0, float(poll_interval_seconds))
        self._monotonic = monotonic
        self._sleep = sleep

    def synchronize(self, requested_model: str) -> ModelSynchronizationResult:
        requested = str(requested_model).strip()
        requested_key = normalize_model_name(requested)
        if not requested_key:
            raise ModelSynchronizationError(
                "A1111 checkpoint synchronization failed: requested checkpoint is empty",
                kind="invalid_request",
            )

        actual = self._read_actual(requested, phase="before switch")
        if normalize_model_name(actual) == requested_key:
            return ModelSynchronizationResult(actual_model=actual, switched=False)

        if not bool(getattr(self._client, "options_write_enabled", False)):
            self._raise_failure(
                requested,
                actual,
                "WebUI options writes are disabled",
                kind="writes_disabled",
            )

        try:
            changed = self._client.set_model(requested)
        except Exception as exc:
            self._raise_failure(
                requested, actual, f"model change request failed: {exc}", kind="change_error"
            )
        if changed is not True:
            failure_reason = getattr(self._client, "last_options_write_failure", None)
            detail = (
                f"model change request returned false ({failure_reason})"
                if failure_reason
                else "model change request returned false"
            )
            self._raise_failure(requested, actual, detail, kind="change_rejected")

        deadline = self._monotonic() + self._timeout_seconds
        last_actual = actual
        while True:
            last_actual = self._read_actual(requested, phase="after switch")
            if normalize_model_name(last_actual) == requested_key:
                return ModelSynchronizationResult(actual_model=last_actual, switched=True)

            remaining = deadline - self._monotonic()
            if remaining <= 0:
                self._raise_failure(
                    requested,
                    last_actual,
                    f"verification timed out after {self._timeout_seconds:g}s",
                    kind="not_applied",
                )
            self._sleep(min(self._poll_interval_seconds, remaining))

    def _read_actual(self, requested: str, *, phase: str) -> str:
        try:
            actual = self._client.get_current_model()
        except Exception as exc:
            self._raise_failure(
                requested,
                None,
                f"could not query WebUI {phase}: {exc}",
                kind="query_failed",
            )
        if not isinstance(actual, str) or not actual.strip():
            self._raise_failure(
                requested,
                None,
                f"WebUI returned no current checkpoint {phase}",
                kind="query_failed",
            )
        return actual.strip()

    @staticmethod
    def _raise_failure(
        requested: str,
        actual: str | None,
        reason: str,
        *,
        kind: str,
    ) -> NoReturn:
        raise ModelSynchronizationError(
            "A1111 checkpoint synchronization failed: "
            f"requested='{requested}', actual='{actual or 'unknown'}'; {reason}",
            kind=kind,
            requested=requested,
            actual=actual,
        )


__all__ = [
    "CHECKPOINT_PROBLEM_KINDS",
    "A1111ModelSynchronizer",
    "ModelSynchronizationError",
    "ModelSynchronizationResult",
    "normalize_model_name",
    "operator_model_title",
]
