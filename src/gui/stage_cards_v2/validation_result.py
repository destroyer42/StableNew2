"""Validation result for stage cards."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ValidationResult:
    ok: bool
    message: str | None = None
    errors: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return self.ok

    def is_empty(self) -> bool:
        """Return True if there are no validation messages to display."""
        return not self.message and not self.errors and not self.warnings and not self.info
