"""Unified error envelope for structured errors across StableNew phases."""

from __future__ import annotations

import time
import traceback
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from typing import Any

from src.utils.exceptions_v2 import StableNewError

DEFAULT_REMEDIATION = "Please consult the logs and retry."
_ENVELOPE_ATTR = "_sn_error_envelope"


@dataclass
class UnifiedErrorEnvelope:
    error_type: str
    subsystem: str
    severity: str
    message: str
    cause: Exception | None
    stack: str
    job_id: str | None
    stage: str | None
    timestamp: float = field(default_factory=lambda: time.time())
    remediation: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    retry_info: dict[str, Any] | None = None


def _default_remediation(error_type: str) -> str:
    suggestions: Mapping[str, str] = {
        "PipelineError": "Verify your pipeline config and try again.",
        "WebUIError": "Ensure the WebUI API is reachable and healthy.",
        "ExecutionError": "Check runner logs for more details.",
        "ConfigError": "Validate your configuration values.",
        "ExternalProcessError": "Inspect the external process logs for failures.",
        "WatchdogViolationError": "Review resource caps or job payload sizes.",
        "ResourceLimitError": "Reduce memory/CPU usage per job and retry.",
        "StableNewError": "Refer to StableNew diagnostics for guidance.",
    }
    return suggestions.get(error_type, DEFAULT_REMEDIATION)


def wrap_exception(
    exc: Exception,
    *,
    subsystem: str,
    severity: str = "ERROR",
    message: str | None = None,
    job_id: str | None = None,
    stage: str | None = None,
    context: dict[str, Any] | None = None,
    retry_info: dict[str, Any] | None = None,
) -> UnifiedErrorEnvelope:
    msg = message or str(exc) or exc.__class__.__name__
    stack = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    error_type = exc.__class__.__name__
    remediation = _default_remediation(error_type)
    if isinstance(exc, StableNewError):
        remediation = getattr(exc, "suggested_fix", remediation)
    envelope = UnifiedErrorEnvelope(
        error_type=error_type,
        subsystem=subsystem,
        severity=severity,
        message=msg,
        cause=exc,
        stack=stack,
        job_id=job_id,
        stage=stage,
        remediation=remediation,
        context=dict(context or {}),
        retry_info=retry_info,
    )
    attach_envelope(exc, envelope)
    return envelope


def attach_envelope(exc: Exception, envelope: UnifiedErrorEnvelope) -> None:
    """Associate the envelope with an exception for downstream consumers."""
    setattr(exc, _ENVELOPE_ATTR, envelope)


def get_attached_envelope(exc: Exception) -> UnifiedErrorEnvelope | None:
    return getattr(exc, _ENVELOPE_ATTR, None)


def serialize_envelope(envelope: UnifiedErrorEnvelope | None) -> dict[str, Any] | None:
    if envelope is None:
        return None
    data = {
        field.name: getattr(envelope, field.name)
        for field in fields(UnifiedErrorEnvelope)
        if field.name != "cause"
    }
    return data


def deserialize_envelope(data: Mapping[str, Any] | None) -> UnifiedErrorEnvelope | None:
    """Restore a persisted envelope without attempting to recreate its exception."""
    if not data:
        return None
    return UnifiedErrorEnvelope(
        error_type=str(data.get("error_type") or "StableNewError"),
        subsystem=str(data.get("subsystem") or "unknown"),
        severity=str(data.get("severity") or "ERROR"),
        message=str(data.get("message") or ""),
        cause=None,
        stack=str(data.get("stack") or ""),
        job_id=str(data["job_id"]) if data.get("job_id") is not None else None,
        stage=str(data["stage"]) if data.get("stage") is not None else None,
        timestamp=float(data.get("timestamp") or time.time()),
        remediation=(
            str(data["remediation"]) if data.get("remediation") is not None else None
        ),
        context=dict(data.get("context") or {}),
        retry_info=(dict(data["retry_info"]) if data.get("retry_info") else None),
    )
