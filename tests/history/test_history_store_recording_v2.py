from __future__ import annotations

from datetime import datetime

from src.queue.job_history_store import JobHistoryEntry, JSONLJobHistoryStore
from src.queue.job_model import JobStatus


def test_history_store_save_entry_triggers_callback(tmp_path) -> None:
    store = JSONLJobHistoryStore(tmp_path / "history.jsonl")
    collected: list[str] = []

    def _on_entry(entry: JobHistoryEntry) -> None:
        collected.append(entry.job_id)

    store.register_callback(_on_entry)
    entry = JobHistoryEntry(
        job_id="recorded",
        created_at=datetime.utcnow(),
        status=JobStatus.COMPLETED,
        payload_summary="test",
    )
    store.save_entry(entry)
    assert collected == ["recorded"]


def test_history_store_save_entry_is_listed(tmp_path) -> None:
    store = JSONLJobHistoryStore(tmp_path / "history.jsonl")
    entry = JobHistoryEntry(
        job_id="listed",
        created_at=datetime.utcnow(),
        status=JobStatus.COMPLETED,
        payload_summary="test",
    )
    store.save_entry(entry)
    entries = store.list_jobs()
    assert entries
    assert entries[0].job_id == "listed"
