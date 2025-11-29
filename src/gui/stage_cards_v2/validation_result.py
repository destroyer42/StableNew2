"""Validation result for stage cards."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Dict, Any


@dataclass
class ValidationResult:
    ok: bool
    message: Optional[str] = None
    errors: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        return self.ok
