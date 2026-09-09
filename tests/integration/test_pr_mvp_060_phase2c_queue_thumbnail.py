"""Focused PR-MVP-060 Phase 2C queue and thumbnail proofs."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from src.gui.preview_panel_v2 import PreviewPanelV2
from src.queue.job_model import Job, JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from tests.helpers.njr_factory import make_pipeline_njr


def _job(job_id: str) -> Job:
    record = make_pipeline_njr(
        job_id=job_id,
        config={"prompt": job_id, "model": "test-model"},
        positive_prompt=job_id,
        base_model="test-model",
    )
    job = Job(job_id=job_id)
    job._normalized_record = record  # type: ignore[attr-defined]
    job.snapshot = {"normalized_job": record.to_dict()}
    return job


def _queued_ids(queue: JobQueue) -> list[str]:
    return [job.job_id for job in queue.list_active_jobs_ordered() if job.status == JobStatus.QUEUED]


def test_queue_controls_reorder_remove_and_clear_preserve_running() -> None:
    queue = JobQueue()
    for job_id in ("a", "b", "c"):
        queue.submit(_job(job_id))

    assert queue.move_to_front("c") is True
    assert _queued_ids(queue) == ["c", "a", "b"]
    assert queue.move_up("b") is True
    assert _queued_ids(queue) == ["c", "b", "a"]
    assert queue.move_down("b") is True
    assert _queued_ids(queue) == ["c", "a", "b"]
    assert queue.move_to_back("c") is True
    assert _queued_ids(queue) == ["a", "b", "c"]

    removed = queue.remove("a")
    assert removed is not None and removed.status == JobStatus.CANCELLED
    assert _queued_ids(queue) == ["b", "c"]
    assert queue.get_next_job().job_id == "b"

    queue.mark_running("c")
    assert queue.clear() == 1
    assert queue.get_job("c") is not None
    assert queue.get_job("c").status == JobStatus.RUNNING  # type: ignore[union-attr]
    assert _queued_ids(queue) == []


def test_queue_reorder_survives_sqlite_reopen(tmp_path: Path) -> None:
    path = tmp_path / "jobs.sqlite3"
    repository = JobRepository(path)
    queue = JobQueue(repository=repository)
    for job_id in ("a", "b", "c"):
        queue.submit(_job(job_id))
    assert queue.move_to_front("c") is True
    repository.close()

    reopened_repository = JobRepository(path)
    reopened = JobQueue(repository=reopened_repository)
    assert _queued_ids(reopened) == ["c", "a", "b"]
    reopened_repository.close()


class _FakeThumbnail:
    def __init__(self) -> None:
        self.placeholder: str | None = None
        self.loaded: Path | None = None
        self.cleared = 0

    def set_placeholder(self, text: str) -> None:
        self.placeholder = text

    def set_image_from_path(self, path: Path) -> None:
        self.loaded = path

    def clear(self) -> None:
        self.cleared += 1


def _thumbnail_panel() -> PreviewPanelV2:
    panel = PreviewPanelV2.__new__(PreviewPanelV2)
    panel.thumbnail = _FakeThumbnail()
    panel._show_preview_var = SimpleNamespace(get=lambda: True)
    panel._record_refresh_metric = lambda *_args: None
    return panel


def test_thumbnail_uses_exact_artifact_and_neutral_no_artifact_state(tmp_path: Path) -> None:
    artifact_a = tmp_path / "a.png"
    artifact_b = tmp_path / "b.png"
    artifact_a.write_bytes(b"a")
    artifact_b.write_bytes(b"b")

    panel = _thumbnail_panel()
    job_a = SimpleNamespace(job_id="a", result={"artifact": {"primary_path": str(artifact_a)}})
    job_b = SimpleNamespace(job_id="b", result={"artifact": {"primary_path": str(artifact_b)}})

    panel._update_thumbnail(job_a, show_preview=True)
    assert panel.thumbnail.loaded == artifact_a
    panel._update_thumbnail(job_b, show_preview=True)
    assert panel.thumbnail.loaded == artifact_b

    no_artifact = SimpleNamespace(job_id="draft", prompt_pack_name="pack")
    panel._update_thumbnail(no_artifact, show_preview=True)
    assert panel.thumbnail.placeholder == "No generated preview yet"
    assert panel._find_recent_thumbnail(no_artifact) is None


def test_thumbnail_unchecked_does_not_lookup_or_display(tmp_path: Path) -> None:
    artifact = tmp_path / "image.png"
    artifact.write_bytes(b"image")
    panel = _thumbnail_panel()
    panel._show_preview_var = SimpleNamespace(get=lambda: False)
    panel._update_thumbnail(
        SimpleNamespace(job_id="job", output_paths=[str(artifact)]),
        show_preview=True,
    )
    assert panel.thumbnail.loaded is None
    assert panel.thumbnail.cleared == 1
