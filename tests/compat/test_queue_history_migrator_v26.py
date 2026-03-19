from __future__ import annotations

import json
from pathlib import Path

from src.migrations.queue_history_migrator_v26 import (
    detect_queue_schema,
    migrate_queue_and_history,
    migrate_queue_state_file,
)
from src.services.queue_store_v2 import load_queue_snapshot


def _copy_fixture(tmp_path: Path, relative: str) -> Path:
    fixture = Path(__file__).parent / "data" / relative
    target = tmp_path / Path(relative).name
    target.write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def test_queue_migrator_detects_fixture_versions() -> None:
    base = Path(__file__).parent / "data" / "queue_compat_v2"
    assert detect_queue_schema(base / "v2.0_job.json") == "2.0"
    assert detect_queue_schema(base / "v2.4_job.json") == "2.4"
    assert detect_queue_schema(base / "v2.6_job.json") == "2.4"


def test_queue_migrator_dry_run_leaves_file_unchanged(tmp_path: Path) -> None:
    queue_path = _copy_fixture(tmp_path, "queue_compat_v2/v2.0_job.json")
    original = queue_path.read_text(encoding="utf-8")

    report = migrate_queue_state_file(queue_path, dry_run=True, backup_dir=tmp_path / "backups")

    assert report.changed is True
    assert report.backup_path is None
    assert queue_path.read_text(encoding="utf-8") == original


def test_queue_migrator_writes_strict_v26_snapshot_and_backup(tmp_path: Path) -> None:
    queue_path = _copy_fixture(tmp_path, "queue_compat_v2/v2.4_job.json")

    report = migrate_queue_state_file(queue_path, backup_dir=tmp_path / "backups")
    loaded = load_queue_snapshot(queue_path)

    assert report.detected_schema == "2.4"
    assert report.backup_path is not None
    assert loaded is not None
    assert loaded.schema_version == "2.6"
    assert len(loaded.jobs) == 1
    job = loaded.jobs[0]
    assert job["queue_schema"] == "2.6"
    assert job["queue_id"] == "queue-v2.4-migration-002"
    assert (
        job["njr_snapshot"]["normalized_job"]["positive_prompt"]
        == "A serene lake at dawn, photorealistic"
    )


def test_combined_queue_history_migration_returns_structured_report(tmp_path: Path) -> None:
    queue_path = _copy_fixture(tmp_path, "queue_compat_v2/v2.0_job.json")
    history_path = _copy_fixture(tmp_path, "history_compat_v2/v2.0_entry.jsonl")

    report = migrate_queue_and_history(
        queue_path=queue_path,
        history_path=history_path,
        backup_dir=tmp_path / "backups",
    )

    payload = report.to_dict()
    assert payload["queue"]["changed"] is True
    assert payload["history"]["changed"] is True
    assert payload["queue"]["backup_path"]
    assert payload["history"]["backup_path"]

    history_lines = history_path.read_text(encoding="utf-8").splitlines()
    assert len(history_lines) == 1
    assert json.loads(history_lines[0])["history_schema"] == "2.6"
