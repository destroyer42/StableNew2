"""Controller wrapper for learning execution (non-GUI)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, List

from src.learning.learning_execution import (
    LearningExecutionContext,
    LearningExecutionResult,
    LearningExecutionRunner,
)
from src.learning.learning_plan import LearningPlan
from src.gui_v2.adapters.learning_adapter_v2 import (
    list_recent_learning_records,
    update_record_feedback,
)
from src.pipeline.pipeline_runner import PipelineRunResult
from src.config.app_config import get_learning_enabled, set_learning_enabled


class LearningExecutionController:
    """Expose a high-level API to run learning plans via an injected pipeline run callable."""

    def __init__(self, run_callable: Callable[[dict, Any], PipelineRunResult] | None = None) -> None:
        self._run_callable = run_callable
        self._last_result: LearningExecutionResult | None = None
        self._records_path: Path = Path("output/learning/learning_records.jsonl")
        self._learning_enabled = get_learning_enabled()

    def run_learning_plan(
        self,
        plan: LearningPlan,
        base_config: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> LearningExecutionResult:
        if self._run_callable is None:
            raise RuntimeError("No pipeline run callable provided for learning execution.")
        context = LearningExecutionContext(plan=plan, base_config=base_config, metadata=metadata or {})
        runner = LearningExecutionRunner(run_callable=self._wrap_callable())
        self._last_result = runner.run(context)
        return self._last_result

    def _wrap_callable(self):
        def _call(cfg: dict[str, Any], step: Any) -> PipelineRunResult:
            return self._run_callable(cfg, step)

        return _call

    # GUI helper APIs -------------------------------------------------
    def list_recent_records(self, limit: int = 10):
        """Return recent learning records for display."""

        return list_recent_learning_records(self._records_path, limit=limit)

    def save_feedback(self, record, rating: int, tags: str | None = None):
        """Persist rating/tags for a run result."""

        return update_record_feedback(self._records_path, record, rating=rating, tags=tags)

    def submit_feedback(self, record, rating: int, tags: str | None = None) -> None:
        self.save_feedback(record, rating=rating, tags=tags)

    def set_records_path(self, path: Path) -> None:
        """Override records path for tests."""

        self._records_path = Path(path)

    def set_learning_enabled(self, enabled: bool) -> None:
        self._learning_enabled = bool(enabled)
        set_learning_enabled(self._learning_enabled)

    def get_learning_enabled(self) -> bool:
        return bool(self._learning_enabled)

    def get_last_learning_execution_result_for_tests(self) -> LearningExecutionResult | None:
        return self._last_result
