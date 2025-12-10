from __future__ import annotations

from typing import Any, Callable, Mapping

from src.history.history_record import HistoryRecord
from src.history.history_schema_v26 import InvalidHistoryRecord, validate_entry
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.run_plan import RunPlan, build_run_plan_from_njr
from src.utils.snapshot_builder_v2 import normalized_job_from_snapshot


class ReplayEngine:
    """
    Unified replay pipeline:

        HistoryRecord -> NormalizedJobRecord -> RunPlan -> PipelineRunner.run_njr()
    """

    def __init__(self, runner: Any, *, cancel_token: Any = None) -> None:
        if runner is None or not hasattr(runner, "run_njr"):
            raise ValueError("ReplayEngine requires a runner with run_njr(record, ...) method")
        self._runner = runner
        self._cancel_token = cancel_token

    def replay_njr(self, njr: NormalizedJobRecord) -> Any:
        """Build RunPlan from NJR and invoke runner.run_njr via canonical path."""
        plan = build_run_plan_from_njr(njr)
        return self._runner.run_njr(njr, self._cancel_token, run_plan=plan)

    def replay_history_record(self, record: HistoryRecord | Mapping[str, Any]) -> Any:
        """Validate history entry, hydrate NJR, then delegate to replay_njr."""
        data = record.to_dict() if isinstance(record, HistoryRecord) else dict(record or {})
        ok, errors = validate_entry(data)
        if not ok:
            raise InvalidHistoryRecord(errors)
        snapshot = data.get("njr_snapshot") or {}
        njr = self._hydrate_njr(snapshot)
        if njr is None:
            raise InvalidHistoryRecord(["njr_snapshot could not be hydrated"])
        return self.replay_njr(njr)

    def _hydrate_njr(self, snapshot: Mapping[str, Any]) -> NormalizedJobRecord | None:
        if not snapshot:
            return None
        constructor = getattr(NormalizedJobRecord, "from_snapshot", None)
        if callable(constructor):
            try:
                return constructor(snapshot)
            except Exception:
                pass
        normalized = snapshot if "normalized_job" in snapshot else {"normalized_job": snapshot}
        return normalized_job_from_snapshot(normalized)
