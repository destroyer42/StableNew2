"""AI-VL-240: read-only readers over the operator's existing Review evidence.

Review writes three relevant things and this module only reads them:

* the append-only Learning record file (``learning_records.jsonl``): ``metadata.review_context.guided_improvement_review``
  holds a human judgment of one original/corrected pair, bound to both file digests;
* the SQLite job repository: the corrected job's frozen provenance carries ``guided_correction`` (the category and region
  of the finding the operator confirmed, and the action chosen) and the source digest as ``parent_artifact_id``;
* the image files themselves, found only by a path some record names and accepted only when their SHA-256 equals the digest
  the record bound.

Nothing is created, written, locked or launched. The repository is opened with ``mode=ro`` and ``query_only``. Exceptions from
the standard library are converted to a ``Refused`` code so a path never reaches a message.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import sqlite3
import tempfile
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from tools.qualification.vl240 import contract
from tools.qualification.vl240.contract import Refused

_SHA = re.compile(r"[0-9a-f]{64}")
_CLAIM = re.compile(r"sha256:([0-9a-f]{64})")


@dataclass(frozen=True, slots=True)
class Region:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def box(self) -> tuple[int, int, int, int]:
        return self.left, self.top, self.right, self.bottom

    def as_dict(self) -> dict[str, int]:
        return {"left": self.left, "top": self.top, "right": self.right, "bottom": self.bottom}


@dataclass(frozen=True, slots=True)
class RegionJudgment:
    category: str
    region: Region | None
    judgment: str


@dataclass(frozen=True, slots=True)
class JudgmentRecord:
    record_id: str
    timestamp: str
    job_id: str
    source_sha256: str
    result_sha256: str
    judgments: tuple[RegionJudgment, ...]
    overall_preference: str | None


@dataclass(frozen=True, slots=True)
class JobFacts:
    job_id: str
    parent_job_id: str
    parent_artifact_id: str
    source_kind: str
    stages: tuple[str, ...]
    correction: Mapping[str, Any] | None
    status: str


@dataclass(frozen=True, slots=True)
class ImageFacts:
    sha256: str
    width: int
    height: int
    extension: str
    subject: Mapping[str, Any]
    size_bytes: int


def parse_region(value: Any, size: tuple[int, int] | None = None) -> Region | None:
    """A half-open stored-pixel box, or ``None`` for the whole image. Anything else is malformed."""

    if value is None:
        return None
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 4
        or any(type(edge) is not int for edge in value)
    ):
        raise Refused("malformed_region")
    region = Region(*value)
    if not (0 <= region.left < region.right and 0 <= region.top < region.bottom):
        raise Refused("malformed_region")
    if size is not None and (region.right > size[0] or region.bottom > size[1]):
        raise Refused("malformed_region")
    return region


def _sha(value: Any) -> str:
    text = value if isinstance(value, str) else ""
    if not _SHA.fullmatch(text):
        raise Refused("malformed_digest")
    return text


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


# --------------------------------------------------------------------------------------- Learning records (read only)


def read_judgment_records(path: Path) -> tuple[list[JudgmentRecord], list[Refused], int]:
    """Operator pair judgments in the Learning record file: records, refusals and the count of unparseable lines.

    The file is opened for reading only and streamed. Only a record whose own ``source`` says ``operator_review`` and whose
    schema is the guided improvement schema is a judgment; every other record kind is ignored without being interpreted.
    """

    records: list[JudgmentRecord] = []
    refused: list[Refused] = []
    bad_lines = 0
    try:
        handle = path.open("rb")
    except OSError:
        raise Refused("learning_records_unreadable") from None
    with handle:
        for raw in handle:
            if contract.GUIDED_IMPROVEMENT_KEY.encode() not in raw:
                continue
            try:
                payload = json.loads(raw)
            except ValueError:
                bad_lines += 1
                continue
            metadata = _mapping(_mapping(payload).get("metadata"))
            guided = _mapping(
                _mapping(metadata.get("review_context")).get(contract.GUIDED_IMPROVEMENT_KEY)
            )
            if guided.get("schema") != contract.GUIDED_IMPROVEMENT_SCHEMA:
                continue
            record_id = str(_mapping(payload).get("run_id") or "")[:80]
            try:
                records.append(_judgment(payload, guided, record_id))
            except Refused as exc:
                refused.append(Refused(exc.code, record_id))
    return records, refused, bad_lines


def _judgment(payload: Any, guided: Mapping[str, Any], record_id: str) -> JudgmentRecord:
    if not record_id:
        raise Refused("malformed_record")
    if guided.get("source") != "operator_review":
        raise Refused("not_an_operator_judgment")
    job_id = guided.get("result_job_id")
    if not isinstance(job_id, str) or not job_id.strip():
        raise Refused("malformed_record")
    size = guided.get("result_size")
    result_size = (
        (size[0], size[1])
        if isinstance(size, (list, tuple))
        and len(size) == 2
        and all(type(item) is int and item > 0 for item in size)
        else None
    )
    rows = guided.get("judgments")
    if not isinstance(rows, (list, tuple)) or not rows:
        raise Refused("no_judgment_recorded")
    judgments: list[RegionJudgment] = []
    for row in rows:
        item = _mapping(row)
        category = item.get("category")
        outcome = item.get("outcome")
        if category not in contract.CATEGORIES or outcome not in contract.OUTCOME_TO_JUDGMENT:
            raise Refused("malformed_judgment")
        judgments.append(
            RegionJudgment(
                str(category),
                parse_region(item.get("after_region"), result_size),
                contract.OUTCOME_TO_JUDGMENT[str(outcome)],
            )
        )
    preference = guided.get("overall_preference")
    if preference not in contract.PREFERENCE_TO_VALUE:
        raise Refused("malformed_judgment")
    return JudgmentRecord(
        record_id,
        str(_mapping(payload).get("timestamp") or ""),
        job_id.strip(),
        _sha(guided.get("source_sha256")),
        _sha(guided.get("result_sha256")),
        tuple(judgments),
        contract.PREFERENCE_TO_VALUE[str(preference)],
    )


def latest_per_job(records: Iterable[JudgmentRecord]) -> list[JudgmentRecord]:
    """One judgment per corrected job: the latest by timestamp, later file position winning a tie (Undo deletes a record)."""

    best: dict[str, JudgmentRecord] = {}
    for record in records:
        current = best.get(record.job_id)
        if current is None or record.timestamp >= current.timestamp:
            best[record.job_id] = record
    return list(best.values())


# ------------------------------------------------------------------------------------------ job repository (read only)


@contextmanager
def open_repository(path: Path) -> Iterator[sqlite3.Connection]:
    """A connection that cannot write; a missing file is refused, never created.

    A SQLite database in WAL mode cannot be read read-only without creating ``-shm``/``-wal`` files beside it. So a database
    with a ``-wal`` file (the app is running, or closed uncleanly) is read from a private snapshot of the files, removed on
    exit; a database without one has no writer and is opened ``immutable``, which touches nothing.
    """

    snapshot: str | None = None
    connection: sqlite3.Connection | None = None
    try:
        resolved = Path(path).resolve(strict=True)
        wal = resolved.with_name(resolved.name + "-wal")
        if wal.exists():
            snapshot = tempfile.mkdtemp(prefix="vl240-")
            target = Path(snapshot) / "repository.sqlite3"
            shutil.copyfile(resolved, target)
            shutil.copyfile(wal, Path(snapshot) / "repository.sqlite3-wal")
            uri = f"{target.as_uri()}?mode=ro"
        else:
            uri = f"{resolved.as_uri()}?mode=ro&immutable=1"
        connection = sqlite3.connect(uri, uri=True, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.execute("SELECT 1 FROM jobs LIMIT 1").fetchall()
    except (OSError, sqlite3.Error):
        if connection is not None:
            connection.close()
        if snapshot is not None:
            shutil.rmtree(snapshot, ignore_errors=True)
        raise Refused("job_repository_unreadable") from None
    try:
        yield connection
    finally:
        connection.close()
        if snapshot is not None:
            shutil.rmtree(snapshot, ignore_errors=True)


def _loads(text: Any) -> Any:
    try:
        return json.loads(text) if isinstance(text, (str, bytes)) and text else None
    except ValueError:
        return None


def image_strings(value: Any, *, limit: int = contract.MAX_CANDIDATES_PER_JOB * 4) -> list[str]:
    """Strings that look like image file paths anywhere in a decoded JSON document (bounded, deterministic)."""

    found: list[str] = []
    stack = [value]
    while stack and len(found) < limit:
        item = stack.pop()
        if isinstance(item, Mapping):
            stack.extend(item[key] for key in sorted(item, key=str, reverse=True))
        elif isinstance(item, (list, tuple)):
            stack.extend(reversed(item))
        elif isinstance(item, str) and 3 < len(item) <= 1024:
            if Path(item).suffix.lower() in contract.IMAGE_SUFFIXES:
                found.append(item)
    return list(dict.fromkeys(found))


def _facts(row: sqlite3.Row) -> tuple[JobFacts, Any]:
    snapshot = _loads(row["njr_snapshot"])
    normalized = _mapping(_mapping(snapshot).get("normalized_job"))
    source = _mapping(normalized.get("source"))
    provenance = _mapping(_mapping(normalized.get("provenance")).get("metadata"))
    correction = _mapping(provenance.get(contract.GUIDED_CORRECTION_KEY))
    stages = tuple(
        str(_mapping(stage).get("stage_type"))
        for stage in normalized.get("stages") or ()
        if _mapping(stage).get("enabled") is True
    )
    return (
        JobFacts(
            str(row["job_id"]),
            str(row["parent_job_id"] or source.get("parent_job_id") or ""),
            str(row["parent_artifact_id"] or source.get("parent_artifact_id") or ""),
            str(source.get("kind") or ""),
            stages,
            correction if correction.get("schema") == contract.GUIDED_CORRECTION_SCHEMA else None,
            str(row["status"] or ""),
        ),
        snapshot,
    )


def guided_correction_jobs(connection: sqlite3.Connection) -> Iterator[tuple[JobFacts, list[str]]]:
    """Every job whose frozen provenance carries a guided correction, with image paths its own record names."""

    try:
        rows = connection.execute(
            "SELECT job_id, parent_job_id, parent_artifact_id, status, njr_snapshot FROM jobs "
            "WHERE instr(njr_snapshot, ?) > 0 ORDER BY rowid ASC",
            (f'"{contract.GUIDED_CORRECTION_KEY}"',),
        )
        for row in rows:
            facts, snapshot = _facts(row)
            if facts.correction is not None:
                yield facts, image_strings(snapshot)
    except sqlite3.Error:
        raise Refused("job_repository_unreadable") from None


def job_with_paths(
    connection: sqlite3.Connection, job_id: str, *, include_snapshot: bool
) -> tuple[JobFacts, list[str]] | None:
    """One job's facts and the image paths its record names (result paths, and the frozen request when asked)."""

    try:
        row = connection.execute(
            "SELECT job_id, parent_job_id, parent_artifact_id, status, njr_snapshot, result_json, "
            "artifact_references FROM jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
    except sqlite3.Error:
        raise Refused("job_repository_unreadable") from None
    if row is None:
        return None
    facts, snapshot = _facts(row)
    paths = image_strings(_loads(row["result_json"])) + image_strings(
        _loads(row["artifact_references"])
    )
    if include_snapshot:
        paths += image_strings(snapshot)
    return facts, list(dict.fromkeys(paths))


def claim_digest(parent_artifact_id: str) -> str:
    match = _CLAIM.fullmatch(parent_artifact_id or "")
    if match is None:
        raise Refused("no_recorded_source_digest")
    return match.group(1)


# ---------------------------------------------------------------------------------------------------- image files


def analyze_image(path: Path) -> ImageFacts:
    """Hash and decode-header one file read-only. The embedded metadata is read only to classify content visibility."""

    from src.utils.image_metadata import (
        ImageMetadataContractV26,
        decode_payload,
        read_image_metadata,
        resolve_prompt_fields,
    )

    try:
        size_bytes = path.stat().st_size
        if not path.is_file() or size_bytes > contract.MAX_IMAGE_BYTES:
            raise Refused("image_unavailable")
        with path.open("rb") as handle:
            data = handle.read(contract.MAX_IMAGE_BYTES + 1)
    except OSError:
        raise Refused("image_unavailable") from None
    if len(data) > contract.MAX_IMAGE_BYTES:
        raise Refused("image_unavailable")
    try:
        with Image.open(io.BytesIO(data)) as image:
            extension = contract.FORMAT_EXTENSIONS.get(str(image.format))
            width, height = image.size
            if extension is None or getattr(image, "n_frames", 1) != 1:
                raise Refused("image_unsupported")
            if width * height > contract.MAX_IMAGE_PIXELS:
                raise Refused("image_unsupported")
    except (OSError, SyntaxError, Image.DecompressionBombError):
        raise Refused("image_unsupported") from None
    try:
        metadata = read_image_metadata(path, source_bytes=data)
        decoded = (
            decode_payload(metadata, max_decoded_bytes=ImageMetadataContractV26.HARD_LIMIT_BYTES)
            if metadata.get(ImageMetadataContractV26.KEY_SCHEMA) == ImageMetadataContractV26.SCHEMA
            else None
        )
    except Exception:  # noqa: BLE001 - a malformed metadata block must classify as restricted, not crash the export.
        decoded = None
        metadata = {}
    payload = decoded.payload if decoded and decoded.status == "ok" else None
    positive, negative = resolve_prompt_fields(payload)
    # Built the way Review's own inspection builds it. Prompts exist here only to classify visibility and are dropped.
    subject: dict[str, Any] = {
        "positive_prompt": positive,
        "negative_prompt": negative,
        "description": metadata.get(ImageMetadataContractV26.PUBLIC_KEY_PARAMETERS)
        or metadata.get(ImageMetadataContractV26.PUBLIC_KEY_DESCRIPTION, ""),
        "content_visibility": (
            {"rating": "nsfw"}
            if decoded and decoded.status == "corrupt"
            else (payload or {}).get("content_visibility")
        ),
    }
    return ImageFacts(
        hashlib.sha256(data).hexdigest(), width, height, extension, subject, size_bytes
    )


class ImageBinder:
    """Find the file whose bytes hash to a recorded digest among paths a record names. Never guesses, never scans folders."""

    def __init__(self) -> None:
        self._facts: dict[str, ImageFacts | None] = {}

    def _analyze(self, path: str) -> ImageFacts | None:
        if path not in self._facts:
            try:
                self._facts[path] = analyze_image(Path(path))
            except Refused:
                self._facts[path] = None
        return self._facts[path]

    def bind(self, digest: str, candidates: Iterable[str]) -> tuple[Path, ImageFacts]:
        seen_file = False
        for candidate in list(dict.fromkeys(candidates))[: contract.MAX_CANDIDATES_PER_JOB]:
            facts = self._analyze(candidate)
            if facts is None:
                continue
            seen_file = True
            if facts.sha256 == digest:
                return Path(candidate), facts
        raise Refused("image_changed_since_review" if seen_file else "image_unavailable")
