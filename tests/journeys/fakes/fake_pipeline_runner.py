from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.controller.archive.pipeline_config_types import PipelineConfig


@dataclass
class RunCall:
    config: PipelineConfig
    options: dict[str, Any]


@dataclass
class FakePipelineRunner:
    """Synchronous fake runner that records pipeline configs."""

    should_raise: bool = False
    run_calls: list[RunCall] = field(default_factory=list)

    def run(self, config: PipelineConfig, cancel_token=None, log_fn=None) -> None:  # noqa: D401
        """Record the call and optionally raise."""
        self.run_calls.append(
            RunCall(config=config, options={"cancel_token": cancel_token, "log_fn": log_fn})
        )
        if self.should_raise:
            raise RuntimeError("Fake pipeline failure")
