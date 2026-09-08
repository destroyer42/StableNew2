from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from src.migrations.sqlite_job_importer import LegacyImportError, import_legacy_state
from src.pipeline.cli_njr_builder import build_cli_njr
from src.queue.job_repository import JobRepository


def _record(job_id: str, prompt: str = "legacy prompt") -> dict:
    njr = build_cli_njr(
        prompt=prompt,
        batch_size=1,
        run_name=job_id,
        config={
            "txt2img": {
                "model": "legacy.safetensors",
                "steps": 10,
                "cfg_scale": 6.0,
                "width": 64,
                "height": 64,
            }
        },
    )
    return {
        "queue_id": job_id,
        "job_id": job_id,
        "status": "queued",
        "priority": 1,
        "njr_snapshot": {"normalized_job": njr.to_dict()},
    }


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_dry_run_does_not_create_or_change_any_state(tmp_path: Path) -> None:
    source = tmp_path / "queue.json"
    source.write_text(json.dumps({"jobs": [_record("one")]}), encoding="utf-8")
    database = tmp_path / "jobs.sqlite3"
    before = _checksum(source)

    result = import_legacy_state(
        database_path=database,
        sources=[(source, "queue")],
        dry_run=True,
    )

    assert result.analysis.can_import
    assert result.analysis.records_discovered == 1
    assert result.analysis.expected_resulting_count == 1
    assert not database.exists()
    assert _checksum(source) == before


def test_dry_run_translates_pre_njr_queue_record(tmp_path: Path) -> None:
    source = tmp_path / "queue_state_v2.json"
    source.write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "job_id": "legacy-direct",
                        "status": "queued",
                        "pipeline_config": {
                            "prompt": "old prompt",
                            "negative_prompt": "old negative",
                            "model_name": "old-model.safetensors",
                            "steps": 12,
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = import_legacy_state(
        database_path=tmp_path / "jobs.sqlite3",
        sources=[(source, "queue")],
        dry_run=True,
    )

    assert result.analysis.can_import
    assert result.analysis.valid_identities == ["legacy-direct"]
    job, _fingerprint, _source = result.analysis._jobs[0]
    assert job._normalized_record.positive_prompt == "old prompt"
    assert job._normalized_record.base_model == "old-model.safetensors"


def test_apply_is_backup_first_validated_and_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "history.jsonl"
    item = _record("done")
    item.update({"status": "completed", "result": {"image_paths": ["image.png"]}})
    source.write_text(json.dumps(item) + "\n", encoding="utf-8")
    database = tmp_path / "jobs.sqlite3"
    before = _checksum(source)

    first = import_legacy_state(
        database_path=database,
        sources=[(source, "history")],
        dry_run=False,
    )
    second = import_legacy_state(
        database_path=database,
        sources=[(source, "history")],
        dry_run=False,
    )

    assert first.imported == ["done"]
    assert first.validation["actual_count"] == 1
    assert first.backup_directory is not None
    assert (Path(first.backup_directory) / source.name).exists()
    assert (Path(first.backup_directory) / "manifest.json").exists()
    assert second.imported == []
    assert second.analysis.duplicates == ["done"]
    assert _checksum(source) == before
    with JobRepository(database) as repository:
        assert repository.count() == 1
        assert repository.get_artifact_references("done") == ["image.png"]


def test_conflict_is_reported_and_rejected_without_mutation(tmp_path: Path) -> None:
    source_one = tmp_path / "one.json"
    source_two = tmp_path / "two.json"
    source_one.write_text(json.dumps(_record("same", "first")), encoding="utf-8")
    source_two.write_text(json.dumps(_record("same", "second")), encoding="utf-8")
    database = tmp_path / "jobs.sqlite3"
    hashes = (_checksum(source_one), _checksum(source_two))

    dry_run = import_legacy_state(
        database_path=database,
        sources=[(source_one, "queue"), (source_two, "history")],
        dry_run=True,
    )
    assert dry_run.analysis.conflicts == ["legacy records disagree for same"]
    with pytest.raises(LegacyImportError):
        import_legacy_state(
            database_path=database,
            sources=[(source_one, "queue"), (source_two, "history")],
            dry_run=False,
        )

    assert not database.exists()
    assert (_checksum(source_one), _checksum(source_two)) == hashes
    assert not (tmp_path / "migration_backups").exists()


def test_invalid_batch_leaves_existing_repository_recoverable(tmp_path: Path) -> None:
    valid = tmp_path / "valid.json"
    invalid = tmp_path / "invalid.jsonl"
    valid.write_text(json.dumps(_record("valid")), encoding="utf-8")
    invalid.write_text("{not-json}\n", encoding="utf-8")
    database = tmp_path / "jobs.sqlite3"
    with JobRepository(database) as repository:
        assert repository.count() == 0
    database_before = _checksum(database)

    with pytest.raises(LegacyImportError):
        import_legacy_state(
            database_path=database,
            sources=[(valid, "queue"), (invalid, "history")],
            dry_run=False,
        )

    assert _checksum(database) == database_before
    with JobRepository(database) as repository:
        assert repository.count() == 0


def test_mid_import_failure_rolls_back_and_restores_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "queue.json"
    source.write_text(
        json.dumps({"jobs": [_record("one"), _record("two")]}), encoding="utf-8"
    )
    database = tmp_path / "jobs.sqlite3"
    with JobRepository(database) as repository:
        assert repository.count() == 0
    before = _checksum(database)
    original = JobRepository._insert_imported_job
    calls = 0

    def fail_second(self, connection, job):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise sqlite3.IntegrityError("injected import failure")
        return original(self, connection, job)

    monkeypatch.setattr(JobRepository, "_insert_imported_job", fail_second)
    with pytest.raises(sqlite3.IntegrityError, match="injected import failure"):
        import_legacy_state(
            database_path=database,
            sources=[(source, "queue")],
            dry_run=False,
        )

    assert _checksum(database) == before
    with JobRepository(database) as repository:
        assert repository.count() == 0
