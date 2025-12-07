"""Unit tests for diagnostics bundle helpers."""

from __future__ import annotations

import json
import logging
import zipfile
from pathlib import Path

from src.utils.diagnostics_bundle_v2 import build_crash_bundle
from src.utils.logger import InMemoryLogHandler


class DummyJobService:
    def get_diagnostics_snapshot(self) -> dict[str, object]:
        return {
            "jobs": [
                {
                    "job_id": "job-1",
                    "status": "running",
                    "external_pids": [42],
                    "run_mode": "queue",
                    "priority": "NORMAL",
                }
            ]
        }


def test_build_crash_bundle_writes_metadata(tmp_path: Path) -> None:
    handler = InMemoryLogHandler(max_entries=10)
    logger = logging.getLogger("tests.diagnostics_bundle")
    logger.addHandler(handler)
    logger.info("Diag entry")

    bundle = build_crash_bundle(
        reason="phase5",
        log_handler=handler,
        job_service=DummyJobService(),
        output_dir=tmp_path,
    )

    assert bundle is not None
    assert bundle.exists()
    with zipfile.ZipFile(bundle) as zf:
        assert "metadata/info.json" in zf.namelist()
        info = json.loads(zf.read("metadata/info.json"))
        assert info["reason"] == "phase5"
        assert "job_snapshot" in info
    logger.removeHandler(handler)
