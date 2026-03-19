from __future__ import annotations

import json
from pathlib import Path

from src.history.history_record import HistoryRecord
from src.migrations.queue_history_migrator_v26 import (
    detect_history_schema,
    migrate_history_file,
)


class TestHistoryVersionMigration:
    """Validates one-time migration of legacy history entries into strict v2.6."""

    def _copy_fixture(self, tmp_path: Path, name: str) -> Path:
        fixture_path = Path(__file__).parent / "data" / "history_compat_v2" / name
        target = tmp_path / name
        target.write_text(fixture_path.read_text(encoding="utf-8"), encoding="utf-8")
        return target

    def test_v2_0_history_migrates_to_strict_v26(self, tmp_path: Path) -> None:
        history_path = self._copy_fixture(tmp_path, "v2.0_entry.jsonl")

        report = migrate_history_file(history_path, backup_dir=tmp_path / "backups")
        migrated = HistoryRecord.from_dict(
            json.loads(history_path.read_text(encoding="utf-8").splitlines()[0])
        )

        assert report.detected_schema == "2.0"
        assert report.changed is True
        assert report.backup_path is not None
        assert migrated.history_schema == "2.6"
        assert migrated.njr_snapshot["normalized_job"]["job_id"] == "v2.0-legacy-001"
        assert migrated.to_njr().positive_prompt == "A beautiful sunset over mountains"

    def test_v2_4_history_migrates_to_strict_v26(self, tmp_path: Path) -> None:
        history_path = self._copy_fixture(tmp_path, "v2.4_entry.jsonl")

        report = migrate_history_file(history_path, backup_dir=tmp_path / "backups")
        migrated = HistoryRecord.from_dict(
            json.loads(history_path.read_text(encoding="utf-8").splitlines()[0])
        )

        assert report.detected_schema == "2.4"
        assert report.changed is True
        assert migrated.history_schema == "2.6"
        assert migrated.to_njr().positive_prompt == "A serene lake at dawn, photorealistic"
        assert migrated.to_njr().images_per_prompt == 2

    def test_precanonical_v26_history_is_normalized(self, tmp_path: Path) -> None:
        history_path = self._copy_fixture(tmp_path, "v2.6_entry.jsonl")

        report = migrate_history_file(history_path, backup_dir=tmp_path / "backups")
        migrated = HistoryRecord.from_dict(
            json.loads(history_path.read_text(encoding="utf-8").splitlines()[0])
        )

        assert report.detected_schema == "2.6-precanonical"
        assert migrated.history_schema == "2.6"
        assert migrated.njr_snapshot["normalized_job"]["job_id"] == "v2.6-canonical-003"
        assert migrated.to_njr().positive_prompt == "Futuristic cyberpunk cityscape at night"

    def test_dry_run_reports_without_rewriting(self, tmp_path: Path) -> None:
        history_path = self._copy_fixture(tmp_path, "v2.0_entry.jsonl")
        original = history_path.read_text(encoding="utf-8")

        report = migrate_history_file(history_path, dry_run=True, backup_dir=tmp_path / "backups")

        assert report.changed is True
        assert report.backup_path is None
        assert history_path.read_text(encoding="utf-8") == original

    def test_all_versions_have_required_fields(self) -> None:
        fixture_dir = Path(__file__).parent / "data" / "history_compat_v2"

        for version_file in ["v2.0_entry.jsonl", "v2.4_entry.jsonl", "v2.6_entry.jsonl"]:
            fixture_path = fixture_dir / version_file
            with open(fixture_path, "r", encoding="utf-8") as handle:
                line = handle.readline()
                entry_data = json.loads(line)

            assert "id" in entry_data or "job_id" in entry_data, f"{version_file} missing id/job_id"
            assert "status" in entry_data, f"{version_file} missing status"
            assert "timestamp" in entry_data, f"{version_file} missing timestamp"

    def test_schema_detection_matches_fixture_versions(self) -> None:
        fixture_dir = Path(__file__).parent / "data" / "history_compat_v2"

        assert detect_history_schema(fixture_dir / "v2.0_entry.jsonl") == "2.0"
        assert detect_history_schema(fixture_dir / "v2.4_entry.jsonl") == "2.4"
        assert detect_history_schema(fixture_dir / "v2.6_entry.jsonl") == "2.6-precanonical"
