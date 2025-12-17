"""API result and error types for StableNew V2."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class GenerateErrorCode(str, Enum):
    """Enum for categories of generation failures."""

    CONNECTION = "connection_error"
    INVALID_MODEL = "invalid_model"
    INVALID_SAMPLER = "invalid_sampler"
    INVALID_SCHEDULER = "invalid_scheduler"
    ADETAILER_CONFIG = "adetailer_config_error"
    PAYLOAD_VALIDATION = "payload_validation_error"
    UNKNOWN = "unknown_error"


@dataclass
class GenerateResult:
    """Structured response for a single generation stage."""

    images: list[Any]
    info: dict[str, Any]
    stage: str
    timings: dict[str, float] | None = None


@dataclass
class GenerateError:
    """Structured error emitted when generation fails."""

    code: GenerateErrorCode
    message: str
    stage: str | None = None
    details: dict[str, Any] | None = None


@dataclass
class GenerateOutcome:
    """Wrapper that carries either a GenerateResult or a GenerateError."""

    result: GenerateResult | None = None
    error: GenerateError | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.result is not None
