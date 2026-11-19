"""Project and reconcile a phone judgment using native Review evidence."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.app.site_media_files import SiteOutputError
from src.app.site_output_library import LibraryItem, OutputLibrary
from src.app.site_rating_sync import (
    ROOT_ID,
    edit_stamp,
    field_conflicts,
    fingerprint,
    root_identity,
)
from src.learning.learning_record import (
    SITE_REVIEW_RECEIPT,
    LearningRecordWriter,
    evidence_file_lock,
)
from src.review.review_evidence import (
    IDENTITY_DIGEST,
    EvidenceIndex,
    EvidenceLookup,
    build_disposition_with_prior_settings,
    image_source_job,
    revise_image_rating,
)

_DECISIONS = frozenset({"retain", "rework"})


def _score(value: Any) -> bool:
    return type(value) is int and 1 <= value <= 5


def _row(found: EvidenceLookup) -> dict[str, Any]:
    return (found.row or {}) if found.identity == IDENTITY_DIGEST else {}


def _view(section: str, row: dict[str, Any]) -> dict[str, Any]:
    metadata = row.get("metadata", {})
    if section == "decision":
        value = metadata.get("review_disposition") or ""
        return {"decision": value if value in (*_DECISIONS, "discard") else ""}
    score = metadata.get("user_rating_raw", metadata.get("user_rating"))
    notes = metadata.get("user_notes")
    return {
        "score": score if _score(score) else None,
        "notes": notes if isinstance(notes, str) else "",
    }


def _validate_edit(section: object, base: Any, changes: Any, revision: object) -> None:
    if (
        not isinstance(base, dict)
        or not isinstance(changes, dict)
        or not changes
        or base.keys() != changes.keys()
        or not isinstance(revision, str)
        or not ROOT_ID.fullmatch(revision)
    ):
        raise SiteOutputError("invalid_rating")
    if section == "decision":
        if (
            set(changes) == {"decision"}
            and isinstance(changes["decision"], str)
            and changes["decision"] in _DECISIONS
            and isinstance(base["decision"], str)
            and base["decision"] in ("", *_DECISIONS)
        ):
            return
    if section == "rating" and changes.keys() <= {"score", "notes"}:
        if all(
            (value is None and fields is base or _score(value))
            if key == "score"
            else isinstance(value, str) and len(value) <= 8000
            for fields in (base, changes)
            for key, value in fields.items()
        ):
            return
    raise SiteOutputError("invalid_rating")


class NativeImageReview:
    def __init__(self, library: OutputLibrary, records_path: Path) -> None:
        self._library = library
        self._records_path = records_path

    def _target(self, identifier: object, expected: object) -> tuple[LibraryItem, Path, str]:
        item, _raw, digest = self._library.image(identifier)
        if digest != expected:
            raise SiteOutputError("media_changed")
        return item, self._library.path_for(item), digest

    def inspect(self, identifier: object, expected: object) -> dict[str, Any]:
        _item, path, digest = self._target(identifier, expected)
        with evidence_file_lock(self._records_path):
            index = EvidenceIndex.read(self._records_path, strict_io=True)
        rows = {
            "rating": _row(index.rating(path, digest)),
            "decision": _row(index.disposition_evidence(path, digest)),
        }
        return {
            section: {**_view(section, row), "revision": fingerprint(row)}
            for section, row in rows.items()
        }

    def rework_mark(self, identifier: str, digest: str) -> tuple[Path, str, datetime]:
        _item, path, _digest = self._target(identifier, digest)
        with evidence_file_lock(self._records_path):
            index = EvidenceIndex.read(self._records_path, strict_io=True)
        row = _row(index.disposition_evidence(path, digest))
        if _view("decision", row)["decision"] != "rework":
            raise SiteOutputError("rework_mark_required")
        stamp = row["metadata"].get("decided_at") or row.get("timestamp", "")
        try:
            decided = datetime.fromisoformat(stamp)
        except (ValueError, TypeError) as exc:
            raise SiteOutputError("rework_mark_required") from exc
        if decided.tzinfo is not None:
            decided = decided.astimezone(UTC).replace(tzinfo=None)
        return path, fingerprint(row), decided

    def sync(self, body: dict[str, Any]) -> dict[str, Any]:
        if body["root"] != root_identity(self._library.root):
            raise SiteOutputError("output_folder_changed")
        section, base, changes = (body[key] for key in ("section", "base", "changes"))
        _validate_edit(section, base, changes, body["revision"])
        operation = body["operation"]
        stamp = edit_stamp(
            operation,
            body["actor_time"],
            {key: value for key, value in body.items() if key != "scope"},
        )
        receipt = {"operation": operation, **stamp}
        identifier = self._library.resolve_rating_target(body["target"])
        item, path, digest = self._target(identifier, body["digest"])
        with evidence_file_lock(self._records_path):
            index = EvidenceIndex.read(self._records_path, strict_io=True, operation=operation)
            row = _row(
                index.rating(path, digest)
                if section == "rating"
                else index.disposition_evidence(path, digest)
            )
            revision = fingerprint(row)
            if index.operation_receipts:
                if index.operation_receipts != [receipt]:
                    raise SiteOutputError("rating_operation_reused")
                return {"saved": True, "revision": revision}
            current = _view(section, row)
            if current.get("decision") == "discard":
                raise SiteOutputError("review_archive_required")
            if conflicts := field_conflicts(current, base, changes):
                return {"conflict": conflicts, "revision": revision}
            updated = {**current, **changes}
            if section == "rating":
                if not _score(updated["score"]):
                    raise SiteOutputError("invalid_rating")
                record = revise_image_rating(path, digest, updated["score"], updated["notes"], row)
            else:
                record = build_disposition_with_prior_settings(
                    self._records_path,
                    image_path=path,
                    disposition=updated["decision"],
                    artifact_sha256=digest,
                    source_job_id=image_source_job(path),
                )
            record.metadata[SITE_REVIEW_RECEIPT] = receipt

            def before_replace() -> None:
                self._library.path_for(item)
                self._library.require_active()

            writer = LearningRecordWriter(self._records_path)
            try:
                writer.append_record_atomic(record, before_replace=before_replace)
            except OSError as exc:
                raise SiteOutputError("rating_retry") from exc
            return {"saved": True, "revision": fingerprint(asdict(record))}
