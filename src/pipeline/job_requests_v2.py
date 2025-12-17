from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.gui.app_state_v2 import PackJobEntry


class PipelineRunSource(Enum):
    RUN_NOW = "run_now"
    ADD_TO_QUEUE = "add_to_queue"
    HISTORY_RESTORE = "history_restore"
    DEBUG_REPLAY = "debug_replay"


class PipelineRunMode(Enum):
    DIRECT = "direct"
    QUEUE = "queue"


def _ensure_json_serializable(value: Any) -> None:
    try:
        json.dumps(value)
    except Exception as exc:
        raise ValueError(f"Value is not JSON serializable: {exc}") from exc


@dataclass(frozen=True)
class PipelineRunRequest:
    prompt_pack_id: str
    selected_row_ids: list[str]
    config_snapshot_id: str
    run_mode: PipelineRunMode = PipelineRunMode.QUEUE
    source: PipelineRunSource = PipelineRunSource.ADD_TO_QUEUE
    sweep_state: dict[str, Any] | None = None
    randomizer_plan: dict[str, Any] | None = None
    explicit_output_dir: str | None = None
    tags: list[str] = field(default_factory=list)
    requested_job_label: str | None = None
    max_njr_count: int = 256
    allow_legacy_fallback: bool = False
    pack_entries: list[PackJobEntry] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.prompt_pack_id:
            raise ValueError("PipelineRunRequest requires prompt_pack_id")
        if not self.selected_row_ids:
            raise ValueError("PipelineRunRequest requires at least one selected_row_ids entry")
        if not self.config_snapshot_id:
            raise ValueError("PipelineRunRequest requires config_snapshot_id")
        if self.max_njr_count <= 0:
            raise ValueError("max_njr_count must be positive")
        if self.run_mode == PipelineRunMode.DIRECT and self.max_njr_count > 32:
            raise ValueError("DIRECT runs may not exceed 32 NJRs in a single request")
        for value in self.tags:
            if not value:
                raise ValueError("PipelineRunRequest tags must be non-empty strings")
        if self.sweep_state is not None:
            _ensure_json_serializable(self.sweep_state)
        if self.randomizer_plan is not None:
            _ensure_json_serializable(self.randomizer_plan)

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt_pack_id": self.prompt_pack_id,
            "selected_row_ids": list(self.selected_row_ids),
            "config_snapshot_id": self.config_snapshot_id,
            "run_mode": self.run_mode.value,
            "source": self.source.value,
            "sweep_state": self.sweep_state,
            "randomizer_plan": self.randomizer_plan,
            "explicit_output_dir": self.explicit_output_dir,
            "tags": list(self.tags),
            "requested_job_label": self.requested_job_label,
            "max_njr_count": self.max_njr_count,
            "allow_legacy_fallback": self.allow_legacy_fallback,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PipelineRunRequest:
        run_mode = PipelineRunMode(data.get("run_mode", PipelineRunMode.QUEUE.value))
        source = PipelineRunSource(data.get("source", PipelineRunSource.ADD_TO_QUEUE.value))
        return cls(
            prompt_pack_id=str(data.get("prompt_pack_id", "")),
            selected_row_ids=list(data.get("selected_row_ids", [])),
            config_snapshot_id=str(data.get("config_snapshot_id", "")),
            run_mode=run_mode,
            source=source,
            sweep_state=data.get("sweep_state"),
            randomizer_plan=data.get("randomizer_plan"),
            explicit_output_dir=data.get("explicit_output_dir"),
            tags=list(data.get("tags") or []),
            requested_job_label=data.get("requested_job_label"),
            max_njr_count=int(data.get("max_njr_count", 256)),
            allow_legacy_fallback=bool(data.get("allow_legacy_fallback", False)),
        )
