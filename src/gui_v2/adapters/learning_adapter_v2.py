# Subsystem: Adapters
# Role: Connects learning GUI controls to the learning subsystem.

"""Tk-free helpers for GUI v2 learning hooks."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from src.learning.learning_adapter import prepare_learning_run
from src.learning.learning_record import LearningRecord, LearningRecordWriter
from src.learning.learning_plan import LearningPlan, LearningRunStep
from src.learning.learning_runner import LearningRunner


def create_learning_context(
    base_config: Dict[str, Any] | None,
    one_click_action: str | None = None,
    run_metadata: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    Return a normalized context payload for future learning flows.

    This does not trigger any GUI behavior and remains Tk-free.
    """

    return {
        "base_config": deepcopy(base_config or {}),
        "one_click_action": one_click_action,
        "metadata": deepcopy(run_metadata or {}),
    }


def prepare_learning_plan_and_steps(
    base_config: Dict[str, Any],
    options: Dict[str, Any],
) -> Tuple[LearningPlan, list[LearningRunStep]]:
    """Small wrapper around the existing learning adapter for GUI-facing code."""

    return prepare_learning_run(deepcopy(base_config), deepcopy(options))


def get_runner(base_config: Dict[str, Any] | None = None) -> LearningRunner:
    """Return a LearningRunner instance without importing GUI modules."""

    return LearningRunner(deepcopy(base_config or {}))


@dataclass
class LearningRecordSummary:
    run_id: str
    timestamp: str
    prompt_summary: str
    pipeline_summary: str
    rating: int | None
    tags: list[str]


def _record_to_summary(record: LearningRecord) -> LearningRecordSummary:
    metadata = record.metadata or {}
    prompt = str(metadata.get("prompt", metadata.get("pack_name", "")))
    pipeline_summary = record.primary_model
    rating = metadata.get("rating")
    try:
        rating = int(rating) if rating is not None else None
    except Exception:
        rating = None
    tags_val = metadata.get("tags", [])
    if isinstance(tags_val, str):
        tags = [t.strip() for t in tags_val.split(",") if t.strip()]
    else:
        try:
            tags = [str(t) for t in tags_val]
        except Exception:
            tags = []
    return LearningRecordSummary(
        run_id=record.run_id,
        timestamp=record.timestamp,
        prompt_summary=prompt,
        pipeline_summary=pipeline_summary,
        rating=rating,
        tags=tags,
    )


def list_recent_learning_records(records_path: Path, limit: int = 10) -> List[LearningRecord]:
    """Return the most recent learning records from a JSONL file."""

    path = Path(records_path)
    if path.is_dir():
        path = path / "learning_records.jsonl"
    if not path.exists():
        return []
    records: List[LearningRecord] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    for line in lines[-limit:]:
        try:
            records.append(LearningRecord.from_json(line))
        except Exception:
            continue
    records.reverse()
    return records


def list_recent_summaries(records_path: Path, limit: int = 10) -> list[LearningRecordSummary]:
    return [_record_to_summary(r) for r in list_recent_learning_records(records_path, limit=limit)]


def update_record_feedback(
    records_path: Path,
    run_or_record: str | LearningRecord,
    rating: int | None = None,
    tags: str | Sequence[str] | None = None,
) -> LearningRecord | None:
    """Append a LearningRecord with updated rating/tags for a prior run."""

    run_id = run_or_record if isinstance(run_or_record, str) else run_or_record.run_id
    records = list_recent_learning_records(records_path, limit=1000)
    target = next((r for r in records if r.run_id == run_id), None)
    if target is None and not isinstance(run_or_record, str):
        target = run_or_record
    if target is None:
        return None
    metadata = dict(target.metadata or {})
    if rating is not None:
        try:
            metadata["rating"] = int(rating)
        except Exception:
            metadata["rating"] = rating
    if tags is not None:
        if isinstance(tags, str):
            metadata["tags"] = tags
        else:
            metadata["tags"] = ",".join([str(t).strip() for t in tags])
    updated = LearningRecord(
        run_id=target.run_id,
        timestamp=target.timestamp,
        base_config=target.base_config,
        variant_configs=target.variant_configs,
        randomizer_mode=target.randomizer_mode,
        randomizer_plan_size=target.randomizer_plan_size,
        primary_model=target.primary_model,
        primary_sampler=target.primary_sampler,
        primary_scheduler=target.primary_scheduler,
        primary_steps=target.primary_steps,
        primary_cfg_scale=target.primary_cfg_scale,
        metadata=metadata,
        stage_plan=target.stage_plan,
        stage_events=target.stage_events,
        outputs=target.outputs,
    )
    try:
        writer = LearningRecordWriter(records_path)
        writer.append_record(updated)
        return updated
    except Exception:
        return None
