from __future__ import annotations

from src.history.history_schema_v26 import (
    HISTORY_SCHEMA_VERSION,
    validate_entry,
)


def _valid_entry() -> dict:
    return {
        "id": "job-1",
        "timestamp": "2025-01-01T00:00:00Z",
        "status": "completed",
        "history_schema": HISTORY_SCHEMA_VERSION,
        "njr_snapshot": {
            "normalized_job": {
                "job_id": "job-1",
                "config": {"prompt": "test prompt"},
                "positive_prompt": "test prompt",
            }
        },
        "ui_summary": {},
        "metadata": {},
        "runtime": {},
    }


def test_validate_entry_accepts_minimal_valid_entry() -> None:
    ok, errors = validate_entry(_valid_entry())
    assert ok, errors


def test_validate_entry_rejects_missing_required() -> None:
    entry = _valid_entry()
    entry.pop("status")
    ok, errors = validate_entry(entry)
    assert not ok
    assert any("missing required field: status" in err for err in errors)


def test_validate_entry_rejects_deprecated_fields() -> None:
    entry = _valid_entry()
    entry["pipeline_config"] = {}
    ok, errors = validate_entry(entry)
    assert not ok
    assert any("deprecated field present: pipeline_config" in err for err in errors)


def test_validate_entry_rejects_wrong_types() -> None:
    entry = _valid_entry()
    entry["id"] = 123  # type: ignore[assignment]
    ok, errors = validate_entry(entry)
    assert not ok
    assert any("field id must be str" in err for err in errors)


def test_validate_entry_requires_schema_version() -> None:
    entry = _valid_entry()
    entry["history_schema"] = "2.5"
    ok, errors = validate_entry(entry)
    assert not ok
    assert any("history_schema must be" in err for err in errors)
