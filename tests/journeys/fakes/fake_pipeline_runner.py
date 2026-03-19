"""Queue/NJR-aware fake pipeline runner for journey tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RunCall:
    record: Any
    options: dict[str, Any]


@dataclass
class FakePipelineRunner:
    """Synchronous fake runner that records NJR executions."""

    should_raise: bool = False
    run_calls: list[RunCall] = field(default_factory=list)

    def run_njr(self, record, cancel_token=None, run_plan=None, log_fn=None, checkpoint_callback=None):
        self.run_calls.append(
            RunCall(
                record=record,
                options={
                    "cancel_token": cancel_token,
                    "run_plan": run_plan,
                    "log_fn": log_fn,
                    "checkpoint_callback": checkpoint_callback,
                },
            )
        )
        if self.should_raise:
            raise RuntimeError("Fake pipeline failure")

        class _Result:
            def to_dict(self_inner):
                return {
                    "success": True,
                    "run_id": getattr(record, "job_id", "fake-run"),
                    "variants": [],
                    "learning_records": [],
                    "metadata": {},
                    "error": None,
                }

        return _Result()
