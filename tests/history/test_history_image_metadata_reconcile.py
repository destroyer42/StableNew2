from __future__ import annotations

from pathlib import Path

from PIL import Image

from src.controller.job_history_service import JobHistoryService
from src.history.history_record import HistoryRecord
from src.queue.job_history_store import JSONLJobHistoryStore
from src.queue.job_queue import JobQueue
from src.utils.image_metadata import build_contract_kv, write_image_metadata


def _write_png(path: Path) -> None:
    image = Image.new("RGB", (4, 4), color=(80, 90, 100))
    image.save(path)


def test_reconcile_metadata_prefers_history_job_id(tmp_path: Path) -> None:
    store = JSONLJobHistoryStore(tmp_path / "history.jsonl")
    queue = JobQueue(history_store=store)
    service = JobHistoryService(queue, store)

    image_path = tmp_path / "sample.png"
    _write_png(image_path)
    payload = {
        "job_id": "job-embedded",
        "run_id": "run-1",
        "stage": "txt2img",
        "image": {"path": "sample.png", "width": 4, "height": 4, "format": "png"},
        "seeds": {"requested_seed": -1, "actual_seed": 10, "actual_subseed": 11},
        "njr": {"snapshot_version": "2.6", "sha256": ""},
        "stage_manifest": {"name": "sample", "timestamp": "", "config_hash": ""},
    }
    kv = build_contract_kv(payload, job_id="job-embedded", run_id="run-1", stage="txt2img")
    assert write_image_metadata(image_path, kv) is True

    record = HistoryRecord(
        id="job-history",
        timestamp="2025-01-01T00:00:00Z",
        status="completed",
        njr_snapshot={"job_id": "job-history"},
    )

    resolved = service.reconcile_image_metadata(image_path, record)
    assert resolved["payload"]["job_id"] == "job-embedded"
    assert resolved["reconciled_payload"]["job_id"] == "job-history"
    assert "job_id" in resolved["conflicts"]


def test_reconcile_metadata_falls_back_to_manifest(tmp_path: Path) -> None:
    store = JSONLJobHistoryStore(tmp_path / "history.jsonl")
    queue = JobQueue(history_store=store)
    service = JobHistoryService(queue, store)

    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    (run_dir / "manifests").mkdir()
    image_path = run_dir / "txt2img" / "sample.png"
    image_path.parent.mkdir()
    _write_png(image_path)

    # PR-METADATA-001: Manifests now include run_id cross-reference
    manifest_path = run_dir / "manifests" / "sample.json"
    manifest_path.write_text(
        '{"name":"sample","stage":"txt2img","timestamp":"t","config":{},"job_id":"job-1","run_id":"run-1"}',
        encoding="utf-8",
    )

    resolved = service.reconcile_image_metadata(image_path)
    assert resolved["source"] == "sidecar"
    assert resolved["payload"]["job_id"] == "job-1"
    # PR-METADATA-001: Verify run_id is present in manifest
    assert resolved["payload"].get("run_id") == "run-1"
