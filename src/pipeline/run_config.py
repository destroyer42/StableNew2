# Subsystem: Pipeline
# Role: Run configuration with prompt source tracking for history and learning.

"""Run configuration model with prompt source tracking."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PromptSource(str, Enum):
    """Indicates the origin of a prompt for a run."""

    MANUAL = "manual"
    PACK = "pack"


@dataclass
class RunConfig:
    """Configuration for a pipeline run with prompt origin tracking.

    Attributes:
        prompt_source: Whether the prompt came from manual entry or a pack.
        prompt_pack_id: ID of the prompt pack if source is PACK.
        prompt_keys: Which prompts within the pack were selected.
        prompt_payload: Minimal prompt info for history/learning display.
        run_mode: "direct" or "queue" execution mode.
        source: Additional source context (e.g., "gui", "api").
    """

    prompt_source: PromptSource = PromptSource.MANUAL
    prompt_pack_id: str | None = None
    prompt_keys: Sequence[str] = field(default_factory=list)
    prompt_payload: Mapping[str, Any] = field(default_factory=dict)
    run_mode: str = "direct"
    source: str = "gui"


__all__ = ["PromptSource", "RunConfig"]
