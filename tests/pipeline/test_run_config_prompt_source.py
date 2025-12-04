"""Tests for PR-112: RunConfig → JobHistoryEntry integration.

Validates that job history entries correctly capture prompt source information.
"""

from __future__ import annotations

from datetime import datetime

from src.pipeline.run_config import PromptSource, RunConfig
from src.queue.job_history_store import JobHistoryEntry, job_history_entry_from_run_config
from src.queue.job_model import JobStatus
from src.utils.prompt_packs import (
    build_run_config_for_manual_prompt,
    build_run_config_from_prompt_pack,
)


class TestJobHistoryEntryFromRunConfig:
    """Tests for job_history_entry_from_run_config helper."""

    def test_creates_entry_from_manual_run_config(self) -> None:
        """JobHistoryEntry from manual RunConfig has prompt_source='manual'."""
        run_config = build_run_config_for_manual_prompt("A dragon", "no gore")

        entry = job_history_entry_from_run_config("job-1", run_config)

        assert entry.job_id == "job-1"
        assert entry.prompt_source == "manual"
        assert entry.prompt_pack_id is None
        assert entry.prompt_keys is None or entry.prompt_keys == []

    def test_creates_entry_from_pack_run_config(self) -> None:
        """JobHistoryEntry from pack RunConfig has prompt_source='pack'."""
        pack_data = {
            "prompts": {
                "p1": {"prompt": "A dragon"},
                "p2": {"prompt": "A castle"},
            }
        }
        run_config = build_run_config_from_prompt_pack("pack-xyz", pack_data, ["p1", "p2"])

        entry = job_history_entry_from_run_config("job-2", run_config)

        assert entry.job_id == "job-2"
        assert entry.prompt_source == "pack"
        assert entry.prompt_pack_id == "pack-xyz"
        assert entry.prompt_keys == ["p1", "p2"]

    def test_preserves_run_mode(self) -> None:
        """run_mode is copied from RunConfig."""
        run_config = RunConfig(
            prompt_source=PromptSource.MANUAL,
            run_mode="queue",
        )

        entry = job_history_entry_from_run_config("job-3", run_config)

        assert entry.run_mode == "queue"

    def test_accepts_extra_fields(self) -> None:
        """Extra fields like payload_summary are passed through."""
        run_config = RunConfig(prompt_source=PromptSource.MANUAL)

        entry = job_history_entry_from_run_config(
            "job-4",
            run_config,
            payload_summary="Test summary",
            error_message="Some error",
        )

        assert entry.payload_summary == "Test summary"
        assert entry.error_message == "Some error"

    def test_defaults_status_to_queued(self) -> None:
        """Default status is QUEUED."""
        run_config = RunConfig(prompt_source=PromptSource.MANUAL)

        entry = job_history_entry_from_run_config("job-5", run_config)

        assert entry.status == JobStatus.QUEUED

    def test_accepts_custom_status(self) -> None:
        """Status can be overridden."""
        run_config = RunConfig(prompt_source=PromptSource.MANUAL)

        entry = job_history_entry_from_run_config(
            "job-6",
            run_config,
            status=JobStatus.RUNNING,
        )

        assert entry.status == JobStatus.RUNNING

    def test_uses_provided_created_at(self) -> None:
        """created_at can be provided explicitly."""
        run_config = RunConfig(prompt_source=PromptSource.MANUAL)
        ts = datetime(2025, 1, 1, 12, 0, 0)

        entry = job_history_entry_from_run_config("job-7", run_config, created_at=ts)

        assert entry.created_at == ts


class TestJobHistoryEntryPromptFields:
    """Tests for JobHistoryEntry prompt-related field serialization."""

    def test_to_json_includes_prompt_fields(self) -> None:
        """to_json serializes prompt_source, prompt_pack_id, prompt_keys."""
        entry = JobHistoryEntry(
            job_id="job-test",
            created_at=datetime(2025, 1, 1, 12, 0, 0),
            status=JobStatus.COMPLETED,
            prompt_source="pack",
            prompt_pack_id="my-pack",
            prompt_keys=["a", "b"],
        )

        json_str = entry.to_json()

        assert '"prompt_source": "pack"' in json_str
        assert '"prompt_pack_id": "my-pack"' in json_str
        assert '"prompt_keys": ["a", "b"]' in json_str

    def test_from_json_parses_prompt_fields(self) -> None:
        """from_json correctly parses prompt-related fields."""
        json_str = (
            '{"job_id": "job-x", "created_at": "2025-01-01T12:00:00", '
            '"status": "completed", "prompt_source": "pack", '
            '"prompt_pack_id": "pk1", "prompt_keys": ["k1", "k2"]}'
        )

        entry = JobHistoryEntry.from_json(json_str)

        assert entry.prompt_source == "pack"
        assert entry.prompt_pack_id == "pk1"
        assert entry.prompt_keys == ["k1", "k2"]

    def test_from_json_defaults_prompt_source_to_manual(self) -> None:
        """from_json defaults prompt_source to 'manual' if missing."""
        json_str = '{"job_id": "job-y", "created_at": "2025-01-01T12:00:00", "status": "queued"}'

        entry = JobHistoryEntry.from_json(json_str)

        assert entry.prompt_source == "manual"
        assert entry.prompt_pack_id is None
        assert entry.prompt_keys is None

    def test_roundtrip_preserves_prompt_fields(self) -> None:
        """to_json -> from_json preserves prompt-related fields."""
        original = JobHistoryEntry(
            job_id="job-roundtrip",
            created_at=datetime(2025, 6, 15, 10, 30, 0),
            status=JobStatus.RUNNING,
            prompt_source="pack",
            prompt_pack_id="test-pack-id",
            prompt_keys=["prompt1", "prompt2", "prompt3"],
        )

        json_str = original.to_json()
        restored = JobHistoryEntry.from_json(json_str)

        assert restored.prompt_source == original.prompt_source
        assert restored.prompt_pack_id == original.prompt_pack_id
        assert restored.prompt_keys == original.prompt_keys
