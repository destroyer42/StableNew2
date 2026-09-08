from src.controller.job_history_service import JobHistoryService
from src.queue.job_model import JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from tests.helpers.njr_factory import make_queue_job


def test_history_service_merges_active_and_history(tmp_path):
    store = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=store)
    service = JobHistoryService(queue, store)

    completed_job = make_queue_job("done")
    queue.submit(completed_job)
    queue.mark_running(completed_job.job_id)
    queue.mark_completed(completed_job.job_id)

    active_job = make_queue_job("active")
    queue.submit(active_job)

    active = service.list_active_jobs()
    assert len(active) == 1
    assert active[0].job_id == "active"
    assert active[0].is_active is True
    assert active[0].status == JobStatus.QUEUED.value

    recent = service.list_recent_jobs()
    ids = {r.job_id for r in recent}
    assert "done" in ids
    done_entry = next(r for r in recent if r.job_id == "done")
    assert done_entry.status == JobStatus.COMPLETED.value
    assert done_entry.is_active is False

    fetched = service.get_job("active")
    assert fetched is not None
    assert fetched.job_id == "active"


def test_history_service_cancel(tmp_path):
    store = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=store)

    class StubController:
        def __init__(self):
            self.cancelled = []

        def cancel_job(self, job_id: str):
            self.cancelled.append(job_id)

    stub = StubController()
    service = JobHistoryService(queue, store, job_controller=stub)

    queued = make_queue_job("queued")
    queue.submit(queued)

    assert service.cancel_job("queued") is True
    assert "queued" in stub.cancelled


def test_history_service_retry_uses_canonical_replay(tmp_path):
    store = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=store)

    class StubController:
        def __init__(self):
            self.records = []

        def replay(self, record):
            self.records.append(record)
            return "replay-new"

    stub = StubController()
    service = JobHistoryService(queue, store, job_controller=stub)
    completed = make_queue_job("done")
    queue.submit(completed)
    queue.mark_running(completed.job_id)
    queue.mark_completed(completed.job_id)

    assert service.retry_job("done") == "replay-new"
    assert stub.records == [completed._normalized_record]


def test_history_service_records_result(tmp_path):
    store = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=store)
    service = JobHistoryService(queue, store)

    job = make_queue_job("finished")
    queue.submit(job)
    queue.mark_running(job.job_id)
    queue.mark_completed(job.job_id, result={"mode": "test"})

    entry = service.get_job("finished")
    assert entry is not None
    assert entry.result == {"mode": "test"}


def test_history_service_filters_explicit_legacy_payload_summary_in_sfw(tmp_path):
    store = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=store)
    service = JobHistoryService(queue, store)

    legacy_job = make_queue_job("legacy-explicit", positive_prompt="studio nude portrait")
    queue.submit(legacy_job)
    queue.mark_running(legacy_job.job_id)
    queue.mark_completed(legacy_job.job_id)

    filtered = service.list_recent_jobs(visibility_mode="sfw")
    assert [entry.job_id for entry in filtered] == []

    detail = service.get_job("legacy-explicit", visibility_mode="sfw")
    assert detail is not None
    assert detail.positive_preview == "[Hidden in SFW mode]"


def test_history_service_keeps_unknown_legacy_entries_visible_in_sfw(tmp_path):
    store = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=store)
    service = JobHistoryService(queue, store)

    legacy_job = make_queue_job("legacy-unknown", positive_prompt="portrait study")
    queue.submit(legacy_job)
    queue.mark_running(legacy_job.job_id)
    queue.mark_completed(legacy_job.job_id)

    filtered = service.list_recent_jobs(visibility_mode="sfw")
    assert [entry.job_id for entry in filtered] == ["legacy-unknown"]

    detail = service.get_job("legacy-unknown", visibility_mode="sfw")
    assert detail is not None
    assert detail.positive_preview == "portrait study"


# ---------------------------------------------------------------------------
# PR-VIDEO-215: video bundle normalisation
# ---------------------------------------------------------------------------


def test_normalize_result_video_bundle_stamps_video_bundle():
    """_normalize_result_video_bundle adds top-level video_bundle from metadata."""
    result = {
        "success": True,
        "metadata": {
            "video_primary_artifact": {
                "stage": "video_workflow",
                "backend_id": "comfy",
                "primary_path": "/out/clip.mp4",
                "thumbnail_path": "/out/frame_001.png",
                "manifest_paths": ["/out/manifests/clip.json"],
                "output_paths": ["/out/clip.mp4"],
                "frame_paths": ["/out/frame_001.png"],
                "source_image_path": "/out/source.png",
                "count": 1,
            }
        },
        "variants": [
            {
                "handoff_bundle": {
                    "frame_paths": ["/out/frame_001.png"],
                    "source_image_path": "/out/source.png",
                }
            }
        ],
    }
    normalized = JobHistoryService._normalize_result_video_bundle(result)
    assert normalized is not result  # new dict, not mutated
    bundle = normalized.get("video_bundle")
    assert isinstance(bundle, dict)
    assert bundle["stage"] == "video_workflow"
    assert bundle["backend_id"] == "comfy"
    assert bundle["primary_path"] == "/out/clip.mp4"
    assert bundle["thumbnail_path"] == "/out/frame_001.png"
    assert bundle["artifact_type"] == "video"
    assert bundle["frame_paths"] == ["/out/frame_001.png"]
    assert bundle["source_image_path"] == "/out/source.png"


def test_normalize_result_video_bundle_no_op_without_video():
    """No video_bundle added when metadata has no video_primary_artifact."""
    result = {"success": True, "metadata": {"output_dir": "/out"}}
    normalized = JobHistoryService._normalize_result_video_bundle(result)
    assert normalized is result  # unchanged
    assert "video_bundle" not in normalized


def test_normalize_result_video_bundle_no_op_if_already_present():
    """No-op when video_bundle is already stamped."""
    result = {"video_bundle": {"stage": "video_workflow"}, "metadata": {}}
    normalized = JobHistoryService._normalize_result_video_bundle(result)
    assert normalized is result


def test_normalize_result_video_bundle_handles_none():
    assert JobHistoryService._normalize_result_video_bundle(None) is None


def test_build_entry_stamps_video_bundle_for_video_job(tmp_path):
    """record() stamps video_bundle when pipeline result contains video metadata."""
    store = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=store)
    service = JobHistoryService(queue, store)

    job = make_queue_job("video-job")
    queue.submit(job)
    queue.mark_running(job.job_id)

    video_result = {
        "success": True,
        "metadata": {
            "video_primary_artifact": {
                "stage": "video_workflow",
                "backend_id": "comfy",
                "primary_path": "/out/clip.mp4",
                "thumbnail_path": "/out/frame_001.png",
                "manifest_paths": ["/out/manifests/clip.json"],
                "output_paths": ["/out/clip.mp4"],
                "frame_paths": ["/out/frame_001.png"],
                "source_image_path": "/out/source.png",
                "count": 1,
            }
        },
        "variants": [
            {
                "handoff_bundle": {
                    "frame_paths": ["/out/frame_001.png"],
                    "source_image_path": "/out/source.png",
                }
            }
        ],
    }
    service.record(job, result=video_result)

    # Read directly from history store to inspect the saved entry
    history_entry = service._history.get_job("video-job")
    assert history_entry is not None
    assert isinstance(history_entry.result, dict)
    assert "video_bundle" in history_entry.result
    assert history_entry.result["video_bundle"]["stage"] == "video_workflow"
    assert history_entry.result["video_bundle"]["frame_paths"] == ["/out/frame_001.png"]
    assert history_entry.result["video_bundle"]["source_image_path"] == "/out/source.png"
