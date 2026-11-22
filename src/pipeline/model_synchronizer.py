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
#: is not the active one and could not be made so). Separate local pre-dispatch failures do not
#: attribute the failed switch to the checkpoint.
CHECKPOINT_PROBLEM_KINDS = frozenset({"writes_disabled", "change_rejected", "not_applied"})

_LOCAL_WRITE_FAILURE_KINDS = {
    "safe_mode": "writes_disabled",
    "readiness": "write_not_ready",
    "throttle_timeout": "write_throttle_timeout",
}

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
        switch_requested: bool = False,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.requested = requested
        self.actual = actual
        self.switch_requested = switch_requested

    @property
    def is_checkpoint_problem(self) -> bool:
        return self.kind in CHECKPOINT_PROBLEM_KINDS

    def operator_message(self) -> str | None:
        """Return a bounded operator message for recognized preparation failures."""

        if self.kind == "write_throttle_timeout":
            return (
                "Checkpoint switch timed out waiting for StableNew's local options-write throttle. "
                "No checkpoint write was sent and no images were generated."
            )
        if self.kind == "write_not_ready":
            return (
                "WebUI was not ready for the checkpoint switch. "
                "No checkpoint write was sent and no images were generated."
            )
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


def checkpoint_names_match(left: str | None, right: str | None) -> bool:
    """Allow display-name variations, while retaining a conflict between two stated hashes."""
    if normalize_model_name(left) != normalize_model_name(right):
        return False
    first = re.search(r"\[([a-f0-9]+)\]$", str(left or "").strip(), re.IGNORECASE)
    second = re.search(r"\[([a-f0-9]+)\]$", str(right or "").strip(), re.IGNORECASE)
    if first is None or second is None:
        return True
    first_hash, second_hash = first[1].lower(), second[1].lower()
    return first_hash.startswith(second_hash) or second_hash.startswith(first_hash)


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
        if checkpoint_names_match(actual, requested):
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
            kind = _LOCAL_WRITE_FAILURE_KINDS.get(failure_reason or "", "change_rejected")
            self._raise_failure(requested, actual, detail, kind=kind)

        deadline = self._monotonic() + self._timeout_seconds
        last_actual = actual
        while True:
            last_actual = self._read_actual(requested, phase="after switch")
            if checkpoint_names_match(last_actual, requested):
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
                after_switch=phase == "after switch",
            )
        if not isinstance(actual, str) or not actual.strip():
            self._raise_failure(
                requested,
                None,
                f"WebUI returned no current checkpoint {phase}",
                kind="query_failed",
                after_switch=phase == "after switch",
            )
        return actual.strip()

    @staticmethod
    def _raise_failure(
        requested: str,
        actual: str | None,
        reason: str,
        *,
        kind: str,
        after_switch: bool = False,
    ) -> NoReturn:
        raise ModelSynchronizationError(
            "A1111 checkpoint synchronization failed: "
            f"requested='{requested}', actual='{actual or 'unknown'}'; {reason}",
            kind=kind,
            requested=requested,
            actual=actual,
            switch_requested=after_switch
            or kind in {"change_error", "change_rejected", "not_applied"},
        )


__all__ = [
    "CHECKPOINT_PROBLEM_KINDS",
    "A1111ModelSynchronizer",
    "ModelSynchronizationError",
    "ModelSynchronizationResult",
    "normalize_model_name",
    "operator_model_title",
]
