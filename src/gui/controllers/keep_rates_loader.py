"""LEARN-JOIN: compose the three read-only sources of the keep-rates report. Blocking; run it on a worker."""

from __future__ import annotations

from pathlib import Path

from src.app.review_gateway_store import read_published_image_digests
from src.learning.decision_rates import Report, load_report
from src.queue.job_repository import JobRepository


def load_keep_rates(
    records_path: Path, repository_path: Path | None, *, ledger_path: Path | None = None
) -> Report:
    """The report from the evidence file, the job repository (``mode=ro``) and the phone publish ledger.

    Without a repository nothing joins, and the report says so; it never creates or changes any file.
    """

    def snapshots(job_ids):  # type: ignore[no-untyped-def]
        if repository_path is None or not repository_path.is_file():
            return {}
        return JobRepository.read_snapshots_for_jobs(repository_path, job_ids)

    return load_report(records_path, snapshots, published=read_published_image_digests(ledger_path))
