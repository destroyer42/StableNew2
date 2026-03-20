from src.controller.job_history_service import JobHistoryService
from src.queue.job_history_store import JSONLJobHistoryStore
from src.queue.job_model import Job, JobPriority, JobStatus
from src.queue.job_queue import JobQueue


def test_history_service_merges_active_and_history(tmp_path):
    store = JSONLJobHistoryStore(tmp_path / "history.jsonl")
    queue = JobQueue(history_store=store)
    service = JobHistoryService(queue, store)

    completed_job = Job(job_id="done", priority=JobPriority.NORMAL)
    queue.submit(completed_job)
    queue.mark_running(completed_job.job_id)
    queue.mark_completed(completed_job.job_id)

    active_job = Job(job_id="active", priority=JobPriority.NORMAL)
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


def test_history_service_cancel_and_retry(tmp_path):
    store = JSONLJobHistoryStore(tmp_path / "history.jsonl")
    queue = JobQueue(history_store=store)

    class StubController:
        def __init__(self):
            self.cancelled = []
            self.submitted = 0

        def cancel_job(self, job_id: str):
            self.cancelled.append(job_id)

        def submit_pipeline_run(self, payload, priority=None):
            self.submitted += 1
            return f"job-new-{self.submitted}"

    stub = StubController()
    service = JobHistoryService(queue, store, job_controller=stub)

    queued = Job(job_id="queued", priority=JobPriority.NORMAL)
    queue.submit(queued)

    completed = Job(job_id="done", priority=JobPriority.NORMAL, payload=lambda: None)
    queue.submit(completed)
    queue.mark_running(completed.job_id)
    queue.mark_completed(completed.job_id)

    assert service.cancel_job("queued") is True
    assert "queued" in stub.cancelled

    new_id = service.retry_job("done")
    assert new_id == "job-new-1"


def test_history_service_records_result(tmp_path):
    store = JSONLJobHistoryStore(tmp_path / "history.jsonl")
    queue = JobQueue(history_store=store)
    service = JobHistoryService(queue, store)

    job = Job(job_id="finished", priority=JobPriority.NORMAL)
    queue.submit(job)
    queue.mark_running(job.job_id)
    queue.mark_completed(job.job_id, result={"mode": "test"})

    entry = service.get_job("finished")
    assert entry is not None
    assert entry.result == {"mode": "test"}


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
    store = JSONLJobHistoryStore(tmp_path / "history.jsonl")
    queue = JobQueue(history_store=store)
    service = JobHistoryService(queue, store)

    job = Job(job_id="video-job", priority=JobPriority.NORMAL)
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
