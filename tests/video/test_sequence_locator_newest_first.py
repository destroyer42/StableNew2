"""A job re-queued by an app close has one run folder per attempt; the newest ledger is the one to resume."""

from __future__ import annotations

import json
from pathlib import Path

from src.video.sequence_ledger import LEDGER_FILE_NAME
from src.video.sequence_locator import folder_token, locate_ledger


def test_the_newest_attempt_of_a_job_is_located(tmp_path: Path) -> None:
    job_id = "job-requeued-0001"
    for stamp in ("20261127_090000", "20261127_100000"):
        run_dir = tmp_path / f"{stamp}_{folder_token(job_id)}"
        run_dir.mkdir()
        (run_dir / LEDGER_FILE_NAME).write_text(json.dumps({"job_id": job_id}), encoding="utf-8")

    found = locate_ledger(job_id, [tmp_path])

    assert found is not None and Path(found).parent.name.startswith("20261127_100000")
