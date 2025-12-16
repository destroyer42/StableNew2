"""API result and error types for StableNew V2."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


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

    images: List[Any]
    info: Dict[str, Any]
    stage: str
    timings: Optional[Dict[str, float]] = None


@dataclass
class GenerateError:
    """Structured error emitted when generation fails."""

    code: GenerateErrorCode
    message: str
    stage: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


@dataclass
class GenerateOutcome:
    """Wrapper that carries either a GenerateResult or a GenerateError."""

    result: Optional[GenerateResult] = None
    error: Optional[GenerateError] = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.result is not None
