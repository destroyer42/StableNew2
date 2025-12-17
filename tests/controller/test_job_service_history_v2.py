from datetime import datetime

from src.controller.job_history_service import JobHistoryService
from src.controller.job_service import JobService
from src.queue.job_history_store import JobHistoryStore
from src.queue.job_model import Job, JobPriority, JobStatus
from src.queue.job_queue import JobQueue
from src.queue.single_node_runner import SingleNodeJobRunner


class FakeHistoryStore(JobHistoryStore):
    def __init__(self) -> None:
        self.entries: list = []
        self._callbacks: list = []

    def record_job_submission(self, job: Job) -> None:
        pass

    def record_status_change(
        self,
        job_id: str,
        status: JobStatus,
        ts: datetime,
        error: str | None = None,
        result: dict | None = None,
    ) -> None:
        pass

    def list_jobs(self, status: JobStatus | None = None, limit: int = 50, offset: int = 0) -> list:
        return []

    def get_job(self, job_id: str):
        return None

    def save_entry(self, entry) -> None:
        self.entries.append(entry)

    def register_callback(self, callback) -> None:
        self._callbacks.append(callback)


def _make_job_service(store: FakeHistoryStore) -> JobService:
    queue = JobQueue(history_store=store)
    runner = SingleNodeJobRunner(queue, run_callable=lambda job: {})
    history_service = JobHistoryService(queue, store)
    return JobService(queue, runner, store, history_service=history_service)


def test_job_service_records_completion() -> None:
    store = FakeHistoryStore()
    service = _make_job_service(store)
    job = Job(job_id="done", priority=JobPriority.NORMAL)
    job.result = {"mode": "test"}
    service._handle_job_status_change(job, JobStatus.COMPLETED)

    assert len(store.entries) == 1
    entry = store.entries[0]
    assert entry.job_id == "done"
    assert entry.status == JobStatus.COMPLETED
    assert entry.result == {"mode": "test"}


def test_job_service_records_failure() -> None:
    store = FakeHistoryStore()
    service = _make_job_service(store)
    job = Job(job_id="fail", priority=JobPriority.NORMAL)
    job.error_message = "boom"
    service._handle_job_status_change(job, JobStatus.FAILED)

    assert len(store.entries) == 1
    entry = store.entries[0]
    assert entry.job_id == "fail"
    assert entry.status == JobStatus.FAILED
    assert entry.error_message == "boom"
