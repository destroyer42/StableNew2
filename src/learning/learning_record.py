# Subsystem: Learning
# Role: Defines learning record schemas and persistence helpers.

"""Learning record models and persistence helpers."""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass
class LearningRecord:
    """Durable record describing an executed pipeline run."""

    run_id: str
    timestamp: str
    base_config: Dict[str, Any]
    variant_configs: List[Dict[str, Any]]
    randomizer_mode: str
    randomizer_plan_size: int
    primary_model: str
    primary_sampler: str
    primary_scheduler: str
    primary_steps: int
    primary_cfg_scale: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    stage_plan: List[str] = field(default_factory=list)
    stage_events: List[Dict[str, Any]] = field(default_factory=list)
    outputs: List[Dict[str, Any]] = field(default_factory=list)
    sidecar_priors: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)

    @staticmethod
    def from_json(text: str) -> "LearningRecord":
        payload = json.loads(text)
        return LearningRecord(
            run_id=payload["run_id"],
            timestamp=payload["timestamp"],
            base_config=payload.get("base_config", {}),
            variant_configs=payload.get("variant_configs", []),
            randomizer_mode=payload.get("randomizer_mode", ""),
            randomizer_plan_size=payload.get("randomizer_plan_size", 0),
            primary_model=payload.get("primary_model", ""),
            primary_sampler=payload.get("primary_sampler", ""),
            primary_scheduler=payload.get("primary_scheduler", ""),
            primary_steps=int(payload.get("primary_steps", 0)),
            primary_cfg_scale=float(payload.get("primary_cfg_scale", 0.0)),
            metadata=payload.get("metadata", {}),
            stage_plan=payload.get("stage_plan", []),
            stage_events=payload.get("stage_events", []),
            outputs=payload.get("outputs", []),
        )

    @staticmethod
    def from_pipeline_context(
        *,
        base_config: Dict[str, Any],
        variant_configs: Iterable[Dict[str, Any]] | None,
        randomizer_mode: str = "",
        randomizer_plan_size: int = 0,
        extract_primary: Callable[[Dict[str, Any]], Dict[str, Any]] | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> "LearningRecord":
        run_id = str(uuid.uuid4())
        timestamp = _now_iso()
        variants = list(variant_configs or [])
        base_cfg = base_config or {}
        primary_cfg = variants[0] if variants else base_cfg

        knob_info = extract_primary(primary_cfg) if extract_primary else {}
        return LearningRecord(
            run_id=run_id,
            timestamp=timestamp,
            base_config=base_cfg,
            variant_configs=variants,
            randomizer_mode=randomizer_mode or "",
            randomizer_plan_size=randomizer_plan_size,
            primary_model=str(knob_info.get("model", "")),
            primary_sampler=str(knob_info.get("sampler", "")),
            primary_scheduler=str(knob_info.get("scheduler", "")),
            primary_steps=_safe_int(knob_info.get("steps"), 0),
            primary_cfg_scale=_safe_float(knob_info.get("cfg_scale"), 0.0),
            metadata=dict(metadata or {}),
            stage_plan=[],
            stage_events=[],
            outputs=[],
        )


class LearningRecordWriter:
    """Writes learning records atomically to append-only JSONL."""

    def __init__(self, records_path: str | os.PathLike[str]) -> None:
        path_obj = Path(records_path)
        if path_obj.is_dir() or not path_obj.suffix:
            path_obj.mkdir(parents=True, exist_ok=True)
            path_obj = path_obj / "learning_records.jsonl"
        else:
            path_obj.parent.mkdir(parents=True, exist_ok=True)
        self.records_path = path_obj

    def append_record(self, record: LearningRecord) -> None:
        """Append a record as a single JSON line with fsync for durability."""
        try:
            line = record.to_json() + "\n"
            temp_path = self.records_path.with_suffix(self.records_path.suffix + ".tmp")
            with open(temp_path, "w", encoding="utf-8") as temp_file:
                temp_file.write(line)
                temp_file.flush()
                os.fsync(temp_file.fileno())
            with open(self.records_path, "a", encoding="utf-8") as dest:
                with open(temp_path, "r", encoding="utf-8") as src:
                    data = src.read()
                dest.write(data)
                dest.flush()
                os.fsync(dest.fileno())
            try:
                temp_path.unlink(missing_ok=True)  # type: ignore[arg-type]
            except Exception:
                pass
        except Exception:
            logger.debug("Failed to write learning record", exc_info=True)

    def write(self, record: LearningRecord) -> None:
        """Backward compatible alias for append_record."""

        self.append_record(record)
logger = logging.getLogger(__name__)
