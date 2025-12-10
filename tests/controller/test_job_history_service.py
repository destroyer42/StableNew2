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
    assert active[0].status == JobStatus.QUEUED

    recent = service.list_recent_jobs()
    ids = {r.job_id for r in recent}
    assert "done" in ids
    done_entry = next(r for r in recent if r.job_id == "done")
    assert done_entry.status == JobStatus.COMPLETED
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
