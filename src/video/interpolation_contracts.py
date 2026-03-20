"""Pluggable interpolation contracts for post-video assembly.

PR-VIDEO-217: Interpolation is modeled as a provider contract so StableNew can
optionally apply frame or clip interpolation without hardwiring one runtime
into the core assembly result schema.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class InterpolationRequest:
    """Typed request passed to an interpolation provider."""

    input_paths: list[str]
    output_dir: str
    clip_name: str
    factor: int = 2
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.input_paths:
            errors.append("input_paths must not be empty")
        if self.factor < 1:
            errors.append("factor must be >= 1")
        if not str(self.output_dir).strip():
            errors.append("output_dir must not be empty")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InterpolationResult:
    """Provider output returned to the assembly service."""

    provider_id: str
    applied: bool
    input_paths: list[str] = field(default_factory=list)
    output_paths: list[str] = field(default_factory=list)
    primary_path: str | None = None
    manifest_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InterpolationResult":
        return cls(
            provider_id=str(data.get("provider_id", "")),
            applied=bool(data.get("applied", False)),
            input_paths=[str(item) for item in data.get("input_paths") or [] if item],
            output_paths=[str(item) for item in data.get("output_paths") or [] if item],
            primary_path=data.get("primary_path"),
            manifest_path=data.get("manifest_path"),
            metadata=dict(data.get("metadata") or {}),
        )


class InterpolationProvider(Protocol):
    """Provider boundary used by the StableNew assembly service."""

    provider_id: str

    def interpolate(self, request: InterpolationRequest) -> InterpolationResult:
        """Interpolate clip inputs and return a typed result."""


class NoOpInterpolationProvider:
    """Default interpolation provider that preserves the current outputs."""

    provider_id = "noop"

    def interpolate(self, request: InterpolationRequest) -> InterpolationResult:
        return InterpolationResult(
            provider_id=self.provider_id,
            applied=False,
            input_paths=list(request.input_paths),
            output_paths=list(request.input_paths),
            primary_path=request.input_paths[0] if request.input_paths else None,
            metadata={"reason": "interpolation disabled"},
        )