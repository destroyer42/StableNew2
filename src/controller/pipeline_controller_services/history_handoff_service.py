from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable

from src.history.history_record import HistoryRecord
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.utils.snapshot_builder_v2 import normalized_job_from_snapshot


class HistoryHandoffService:
    """Own replay/handoff hydration from queue history into canonical NJRs."""

    def hydrate_history_record(self, entry: Any) -> HistoryRecord | None:
        if entry is None:
            return None
        if isinstance(entry, HistoryRecord):
            return entry
        raw: dict[str, Any] = {}
        if isinstance(entry, Mapping):
            raw.update(entry)
        else:
            raw.update(getattr(entry, "__dict__", {}) or {})
        if hasattr(entry, "job_id"):
            raw.setdefault("job_id", entry.job_id)
            raw.setdefault("id", entry.job_id)
        if hasattr(entry, "status"):
            raw.setdefault("status", entry.status)
        if hasattr(entry, "created_at"):
            raw.setdefault("timestamp", entry.created_at)
        snapshot = getattr(entry, "snapshot", None)
        if snapshot is not None:
            raw.setdefault("snapshot", snapshot)
        return HistoryRecord.from_dict(raw)

    def hydrate_njr_from_snapshot(
        self, snapshot: Mapping[str, Any] | None
    ) -> NormalizedJobRecord | None:
        if not snapshot:
            return None
        constructor = getattr(NormalizedJobRecord, "from_snapshot", None)
        if callable(constructor):
            try:
                return constructor(snapshot)
            except Exception:
                pass
        if "normalized_job" in snapshot:
            return normalized_job_from_snapshot(snapshot)
        return normalized_job_from_snapshot({"normalized_job": snapshot})

    def replay_job_from_history(
        self,
        *,
        job_id: str,
        history_service: Any,
        app_state: Any,
        submit_normalized_jobs: Callable[..., int],
        set_last_run_config: Callable[[dict[str, Any]], None],
    ) -> int:
        if history_service is None:
            return 0
        entry = history_service.get_job(job_id)
        record = self.hydrate_history_record(entry)
        if record is None:
            return 0
        njr = self.hydrate_njr_from_snapshot(record.njr_snapshot)
        if njr is None:
            return 0
        records = [njr]
        setter = getattr(app_state, "set_preview_jobs", None)
        if callable(setter):
            try:
                setter(records)
            except Exception:
                pass
        run_config = record.metadata or record.njr_snapshot.get("run_config") or {}
        if run_config:
            set_last_run_config(dict(run_config))
        return submit_normalized_jobs(
            records,
            run_config=run_config,
            source=record.njr_snapshot.get("source", "gui"),
            prompt_source=record.njr_snapshot.get("prompt_source", "manual"),
        )


__all__ = ["HistoryHandoffService"]
