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


def test_build_crash_bundle_includes_runtime_artifacts(tmp_path: Path, monkeypatch) -> None:
    queue_state = tmp_path / "queue_state_v2.json"
    queue_state.write_text(json.dumps({"jobs": [{"queue_id": "job-1"}]}), encoding="utf-8")
    monkeypatch.setattr(
        "src.utils.diagnostics_bundle_v2.get_queue_state_path",
        lambda *_, **__: queue_state,
    )
    monkeypatch.setattr(
        "src.utils.diagnostics_bundle_v2._collect_process_inspector_lines",
        lambda: ["pid=1 StableNew"],
    )

    bundle = build_crash_bundle(
        reason="runtime",
        job_service=DummyJobService(),
        output_dir=tmp_path,
        webui_tail={"stdout_tail": "ready", "stderr_tail": ""},
        include_process_state=True,
        include_queue_state=True,
    )

    assert bundle is not None
    with zipfile.ZipFile(bundle) as zf:
        names = set(zf.namelist())
        assert "runtime/job_snapshot.json" in names
        assert "runtime/queue_state.json" in names
        assert "runtime/webui_tail.json" in names
        assert "metadata/process_inspector.txt" in names
