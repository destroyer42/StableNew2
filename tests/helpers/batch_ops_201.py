"""PR-BATCH-OPS-201 test harness: temporary SQLite, synthetic NJRs, a fake runner and a FIFO driver.

Nothing here starts a real process, backend or GPU work, and no user queue/history is read.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from PIL import Image

from src.controller.batch_operations_service import BatchOperationsService
from src.controller.job_service import JobService
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.queue.batch_membership import BATCH_SCHEMA
from src.queue.job_model import Job, JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.utils.error_envelope_v2 import UnifiedErrorEnvelope
from src.utils.watchdog_v2 import WatchdogConfig
from tests.helpers.njr_factory import make_pipeline_njr, make_stage_config

REVIEW_SHA = "a" * 64


class FakeRunner:
    """Satisfies the JobService runner protocol without a worker thread."""

    def __init__(self) -> None:
        self.started = 0
        self.fail_start = False
        self._running = False
        self.current_job = None

    def start(self) -> None:
        if self.fail_start:
            raise RuntimeError("runner refused to start")
        self.started += 1
        self._running = True

    def stop(self, timeout: float | None = None) -> bool:
        self._running = False
        return True

    def is_running(self) -> bool:
        return self._running

    def run_once(self, job: Job) -> dict | None:  # pragma: no cover - never dispatched
        return None

    def cancel_current(self, *, return_to_queue: bool = False) -> None:  # pragma: no cover
        return None

    def begin_shutdown(self) -> None:
        self._running = False

    def is_quiescent(self) -> bool:
        return True


@dataclass
class Stack:
    repository: JobRepository
    queue: JobQueue
    service: JobService
    runner: FakeRunner
    operations: BatchOperationsService
    path: Path

    def reopen(self) -> Stack:
        """A new process view of the same SQLite file (restart)."""
        self.repository.close()
        return make_stack(self.path.parent, name=self.path.name)


def make_stack(tmp_path: Path, *, name: str = "jobs.sqlite3", **service_options: Any) -> Stack:
    repository = JobRepository(tmp_path / name)
    queue = JobQueue(repository=repository)
    runner = FakeRunner()
    service = JobService(queue, runner, watchdog_config=WatchdogConfig(enabled=False))
    operations = BatchOperationsService(job_service=service, **service_options)
    return Stack(repository, queue, service, runner, operations, tmp_path / name)


def image_file(path: Path, color: int = 0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), (color % 256, 20, 40)).save(path)
    return path


def review_njr(
    job_id: str,
    batch_id: str,
    *,
    source: Path | None = None,
    source_count: int = 25,
    sources: tuple[Path, ...] = (),
    top_level: bool = True,
    artifact_sha256: str | None = None,
) -> NormalizedJobRecord:
    """A Review-shaped job: ``review_batch`` descriptor plus the associated top-level ``batch_id``."""

    metadata: dict[str, Any] = {
        "review_batch": {"batch_id": batch_id, "source_count": source_count, "group_by_model": False},
        "submission_source": "review_tab",
    }
    if top_level:
        metadata["batch_id"] = batch_id
    inputs = tuple(str(p) for p in (sources or ((source,) if source else ())))
    record = make_pipeline_njr(
        job_id=job_id,
        extra_metadata=metadata,
        input_image_paths=inputs,
        source_kind="reprocess",
        base_model="sdxl-review.safetensors",
        stage_chain=[make_stage_config(stage_type="img2img")],
    )
    if artifact_sha256:
        record = replace(
            record,
            source=replace(record.source, parent_artifact_id=f"sha256:{artifact_sha256}"),
        )
    return record


def video_njr(
    job_id: str,
    batch_id: str,
    index: int,
    count: int,
    *,
    kind: str = "video_workflow",
    source: Path | None = None,
) -> NormalizedJobRecord:
    """A Video Workflow job carrying the ``stablenew.batch.v1`` descriptor."""

    metadata: dict[str, Any] = {
        "batch": {
            "schema": BATCH_SCHEMA,
            "batch_id": batch_id,
            "batch_kind": kind,
            "source_index": index,
            "source_count": count,
        },
        "video_workflow": {
            "workflow_id": "wan22_ti2v_5b_i2v_v1",
            "display_name": "Wan2.2 TI2V",
            "source_identity": {"original_path": str(source) if source else ""},
        },
    }
    return make_pipeline_njr(
        job_id=job_id,
        extra_metadata=metadata,
        input_image_paths=(str(source),) if source else (),
        stage_chain=[make_stage_config(stage_type="video_workflow")],
        config={"video_workflow": {"enabled": True, "backend_id": "comfy",
                                   "video_execution": {"backend_id": "comfy"}}},
    )


def plain_njr(job_id: str) -> NormalizedJobRecord:
    return make_pipeline_njr(job_id=job_id, positive_prompt="ordinary job")


def admit(stack: Stack, records: list[NormalizedJobRecord]) -> list[str]:
    return stack.service.submit_njrs(records)


def settle_fifo(
    stack: Stack,
    outcomes: dict[int, str] | None = None,
    *,
    count: int | None = None,
    error: str = "synthetic failure",
    result: dict[str, Any] | None = None,
    results: dict[int, dict[str, Any]] | None = None,
    envelope: UnifiedErrorEnvelope | None = None,
) -> list[str]:
    """Claim jobs in queue order exactly as the runner does and settle them.

    ``outcomes`` maps the claim ordinal to ``failed``/``completed``/``running`` (default completed); the
    job a ``running`` ordinal claims is left RUNNING. Returns the claimed job ids in order.
    """

    claimed: list[str] = []
    for ordinal in range(count if count is not None else 10_000):
        job = stack.queue.claim_next_job()
        if job is None:
            break
        claimed.append(job.job_id)
        outcome = (outcomes or {}).get(ordinal, "completed")
        if outcome == "running":
            continue
        chosen = (results or {}).get(ordinal, result)
        if outcome == "failed":
            if envelope is not None:
                job.error_envelope = envelope
            stack.queue.mark_failed(job.job_id, error, result=chosen)
        else:
            stack.queue.mark_completed(
                job.job_id, chosen or {"success": True, "variants": [], "metadata": {}}
            )
    return claimed


def status_of(stack: Stack, job_id: str) -> JobStatus:
    entry = stack.repository.get_job(job_id)
    assert entry is not None
    return entry.status
