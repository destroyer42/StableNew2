from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final, Protocol

from src.contracts.models import PackJobEntry
from src.pipeline.job_models_v2 import NormalizedJobRecord, RuntimeJobStatus, UnifiedJobSummary
from src.queue.job_history_store import JobHistoryEntry


UNSET: Final[object] = object()


@dataclass(frozen=True)
class QueueProjection:
    revision: int
    queue_items: tuple[str, ...] = ()
    queue_jobs: tuple[UnifiedJobSummary, ...] = ()


@dataclass(frozen=True)
class HistoryProjection:
    revision: int
    history_items: tuple[JobHistoryEntry, ...] = ()


@dataclass(frozen=True)
class PreviewProjection:
    revision: int
    preview_jobs: tuple[NormalizedJobRecord, ...] = ()


@dataclass(frozen=True)
class WebUIProjection:
    revision: int
    resources: dict[str, list[Any]]


@dataclass(frozen=True)
class RuntimeProjection:
    revision: int
    running_job: UnifiedJobSummary | None | object = UNSET
    runtime_status: RuntimeJobStatus | None | object = UNSET
    queue_status: str | object = UNSET
    webui_state: str | object = UNSET
    last_error: str | None | object = UNSET


@dataclass(frozen=True)
class OperatorLogEntry:
    revision: int
    line: str
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass(frozen=True)
class PreviewRequest:
    pack_entries: tuple[PackJobEntry, ...] = ()
    base_config: Any | None = None
    use_state_fallback: bool = True


@dataclass(frozen=True)
class SubmissionRequest:
    records: tuple[NormalizedJobRecord, ...] = ()
    source: str = "gui"
    prompt_source: str = "pack"
    run_config: dict[str, Any] | None = None


class ProjectionSink(Protocol):
    def apply_runtime_projection(self, projection: RuntimeProjection) -> None: ...
    def apply_queue_projection(self, projection: QueueProjection) -> None: ...
    def apply_history_projection(self, projection: HistoryProjection) -> None: ...
    def apply_preview_projection(self, projection: PreviewProjection) -> None: ...
    def apply_webui_projection(self, projection: WebUIProjection) -> None: ...
    def append_operator_log(self, entry: OperatorLogEntry) -> None: ...

