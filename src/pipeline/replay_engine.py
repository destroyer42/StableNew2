from __future__ import annotations

import logging
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from src.history.history_record import HistoryRecord
from src.history.history_schema_v26 import InvalidHistoryRecord, validate_entry
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.run_plan import build_run_plan_from_njr
from src.utils.snapshot_builder_v2 import normalized_job_from_snapshot

logger = logging.getLogger(__name__)


def _record_stage_sequence(njr: NormalizedJobRecord) -> list[str]:
    stage_names: list[str] = []
    for stage in getattr(njr, "stage_chain", []) or []:
        stage_name = getattr(stage, "stage_type", None) or getattr(stage, "stage_name", None)
        if stage_name:
            stage_names.append(str(stage_name))
    return stage_names


def _build_resumed_record(
    njr: NormalizedJobRecord,
    checkpoints: list[Any],
) -> tuple[NormalizedJobRecord, dict[str, Any] | None]:
    if not checkpoints:
        return njr, None
    stage_sequence = _record_stage_sequence(njr)
    if not stage_sequence:
        return njr, None

    for checkpoint in reversed(checkpoints):
        stage_name = str(getattr(checkpoint, "stage_name", "") or "").strip()
        output_paths = [str(path) for path in (getattr(checkpoint, "output_paths", None) or []) if path]
        if stage_name not in stage_sequence or not output_paths:
            continue
        if not all(Path(path).exists() for path in output_paths):
            logger.warning(
                "Ignoring resume checkpoint for stage %s because one or more output paths are missing",
                stage_name,
            )
            continue
        try:
            current_index = stage_sequence.index(stage_name)
        except ValueError:
            continue
        next_index = current_index + 1
        if next_index >= len(stage_sequence):
            return njr, None
        resumed = deepcopy(njr)
        resumed.input_image_paths = list(output_paths)
        resumed.start_stage = stage_sequence[next_index]
        resumed.output_paths = []
        resumed.extra_metadata = dict(getattr(njr, "extra_metadata", {}) or {})
        resumed.extra_metadata["resumed_from_stage"] = stage_name
        resumed.extra_metadata["resume_input_count"] = len(output_paths)
        return resumed, {
            "from_stage": stage_name,
            "to_stage": stage_sequence[next_index],
            "input_count": len(output_paths),
        }
    return njr, None


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

    def replay_njr(self, njr: NormalizedJobRecord, *, job: Any | None = None) -> Any:
        """Build RunPlan from NJR and invoke runner.run_njr via canonical path."""
        record = njr
        resume_details: dict[str, Any] | None = None
        stage_checkpoints = []
        if job is not None:
            stage_checkpoints = list(
                getattr(getattr(job, "execution_metadata", None), "stage_checkpoints", None) or []
            )
            record, resume_details = _build_resumed_record(njr, stage_checkpoints)
            if resume_details:
                logger.info(
                    "QUEUE_RESUME | job_id=%s | from_stage=%s | to_stage=%s | inputs=%s",
                    getattr(job, "job_id", None),
                    resume_details["from_stage"],
                    resume_details["to_stage"],
                    resume_details["input_count"],
                )
        plan = build_run_plan_from_njr(record)

        checkpoint_callback = None
        if job is not None:
            from src.queue.job_model import StageCheckpoint

            def checkpoint_callback(
                stage_name: str, output_paths: list[str], metadata: dict[str, Any] | None = None
            ) -> None:
                execution_metadata = getattr(job, "execution_metadata", None)
                if execution_metadata is None:
                    return
                sanitized_paths = [str(path) for path in output_paths if path]
                checkpoint = StageCheckpoint(
                    stage_name=str(stage_name),
                    output_paths=sanitized_paths,
                    metadata=dict(metadata or {}),
                )
                existing = [
                    cp for cp in execution_metadata.stage_checkpoints if cp.stage_name != checkpoint.stage_name
                ]
                existing.append(checkpoint)
                execution_metadata.stage_checkpoints = existing[-10:]

        if checkpoint_callback is not None:
            try:
                return self._runner.run_njr(
                    record,
                    self._cancel_token,
                    run_plan=plan,
                    checkpoint_callback=checkpoint_callback,
                )
            except TypeError:
                return self._runner.run_njr(record, self._cancel_token, run_plan=plan)
        return self._runner.run_njr(record, self._cancel_token, run_plan=plan)

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
