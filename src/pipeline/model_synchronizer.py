"""Deterministic A1111 checkpoint synchronization for pipeline execution."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, NoReturn

DEFAULT_MODEL_SWITCH_TIMEOUT_SECONDS = 30.0
DEFAULT_MODEL_SWITCH_POLL_INTERVAL_SECONDS = 0.5


class ModelSynchronizationError(RuntimeError):
    """Raised when A1111 cannot verify the checkpoint requested by an NJR."""


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
                "A1111 checkpoint synchronization failed: requested checkpoint is empty"
            )

        actual = self._read_actual(requested, phase="before switch")
        if normalize_model_name(actual) == requested_key:
            return ModelSynchronizationResult(actual_model=actual, switched=False)

        if not bool(getattr(self._client, "options_write_enabled", False)):
            self._raise_failure(
                requested,
                actual,
                "WebUI options writes are disabled",
            )

        try:
            changed = self._client.set_model(requested)
        except Exception as exc:
            self._raise_failure(requested, actual, f"model change request failed: {exc}")
        if changed is not True:
            failure_reason = getattr(self._client, "last_options_write_failure", None)
            detail = (
                f"model change request returned false ({failure_reason})"
                if failure_reason
                else "model change request returned false"
            )
            self._raise_failure(requested, actual, detail)

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
            )
        if not isinstance(actual, str) or not actual.strip():
            self._raise_failure(
                requested,
                None,
                f"WebUI returned no current checkpoint {phase}",
            )
        return actual.strip()

    @staticmethod
    def _raise_failure(
        requested: str,
        actual: str | None,
        reason: str,
    ) -> NoReturn:
        raise ModelSynchronizationError(
            "A1111 checkpoint synchronization failed: "
            f"requested='{requested}', actual='{actual or 'unknown'}'; {reason}"
        )


__all__ = [
    "A1111ModelSynchronizer",
    "ModelSynchronizationError",
    "ModelSynchronizationResult",
    "normalize_model_name",
]
