from __future__ import annotations

from typing import Any

HISTORY_SCHEMA_VERSION = "2.6"

# Keys required in every history entry
REQUIRED_FIELDS: dict[str, type] = {
    "id": str,
    "timestamp": str,
    "status": str,
    "njr_snapshot": dict,
    "history_schema": str,
}

# Optional or auto-generated fields
OPTIONAL_FIELDS: dict[str, type] = {
    "runtime": dict,  # timings, kernel_info, performance data
    "ui_summary": dict,  # display-friendly snapshot extracted from NJR
    "metadata": dict,  # run metadata, safe for GUI/history and lineage
    "result": dict,  # canonical run result DTO
    "history_version": str,  # transitional compatibility; ignored on write
}

DEPRECATED_FIELDS: set[str] = {
    "pipeline_config",
    "job_bundle_summary",
    "draft_bundle_summary",
    "bundle",
    "legacy_job",
    "_normalized_record",
    "config_blob",
    "legacy_config_blob",
}

ALLOWED_FIELDS = set(REQUIRED_FIELDS) | set(OPTIONAL_FIELDS)


class HistorySchemaError(Exception):
    """Raised when a history entry violates the v2.6 schema."""


class InvalidHistoryRecord(HistorySchemaError):
    """Raised when replay is attempted on an invalid history record."""


def validate_entry(entry: dict[str, Any]) -> tuple[bool, list[str]]:
    """
    Returns (is_valid, list_of_errors).
    Enforces:
        - required fields exist
        - no deprecated fields
        - field types conform to expected types
        - history_schema == "2.6"
        - no unknown fields
    """
    errors: list[str] = []
    if not isinstance(entry, dict):
        return False, ["entry is not a dict"]

    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in entry:
            errors.append(f"missing required field: {field}")
        else:
            if not isinstance(entry[field], expected_type):
                errors.append(f"field {field} must be {expected_type.__name__}")

    for deprecated in DEPRECATED_FIELDS:
        if deprecated in entry:
            errors.append(f"deprecated field present: {deprecated}")

    for field in entry:
        if field not in ALLOWED_FIELDS:
            errors.append(f"unknown field: {field}")
        elif field in OPTIONAL_FIELDS and not isinstance(entry[field], OPTIONAL_FIELDS[field]):
            errors.append(f"field {field} must be {OPTIONAL_FIELDS[field].__name__}")

    schema_value = entry.get("history_schema")
    if schema_value != HISTORY_SCHEMA_VERSION:
        errors.append(f"history_schema must be {HISTORY_SCHEMA_VERSION}")

    return len(errors) == 0, errors
