"""Safe, lossless persistence for an eval run's ``ratings.csv`` (PR-VID-QUALITY-351).

``ratings.csv`` is the single operator-rating artifact of the eval kit; this module is its only writer. It
never creates a second store. Guarantees:

* every existing row, value, note and unknown column survives a rebuild, including rows for jobs that are no
  longer in the manifest (they are kept at the end, not dropped);
* a malformed, oversized or ambiguous (duplicate-key) file is refused with an error, never overwritten;
* the first conversion from an older column layout copies the original to ``ratings.csv.legacy-<time>.bak``
  (created exclusively, never replaced) before anything is rewritten;
* the file is re-read just before the replace; if it changed since it was read, nothing is written;
* the write is atomic, and success is reported only after the new file reads back identical to what was meant
  to be written.

``artifact_sha256`` is the digest of the clip bytes the operator's review is bound to. A new, still-blank row
is stamped with the current clip's digest; a row that already holds a digest or a judgment is never re-stamped
automatically. The operator rebinds on purpose by typing ``rebind`` in that cell after watching the current clip.
"""

from __future__ import annotations

import csv
import io
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from src.utils.atomic_io import atomic_write_bytes
from src.video.video_eval_rubric import (
    ACTION_COLUMN,
    BREAK_COLUMN,
    CATEGORIES_COLUMN,
    FIRST_FAILURE_COLUMN,
    NOTES_COLUMN,
    OVERALL_COLUMN,
    SCORE_COLUMNS,
    row_has_content,
)

KEY_COLUMNS = ("case_id", "arm_id", "job_id")
#: The columns of every ratings.csv before PR-VID-QUALITY-351; they keep their positions.
LEGACY_COLUMNS = (*KEY_COLUMNS, OVERALL_COLUMN, ACTION_COLUMN, NOTES_COLUMN)
ARTIFACT_COLUMN = "artifact_sha256"
REBIND_TOKEN = "rebind"
RATING_COLUMNS = (
    *LEGACY_COLUMNS,
    ARTIFACT_COLUMN,
    *SCORE_COLUMNS,
    BREAK_COLUMN,
    CATEGORIES_COLUMN,
    FIRST_FAILURE_COLUMN,
)
MAX_RATINGS_BYTES = 5 * 1024 * 1024

RowKey = tuple[str, str, str]


class RatingsFileError(ValueError):
    """The existing ratings file cannot be used safely; nothing was written."""


@dataclass(frozen=True)
class LoadedRatings:
    path: Path
    raw: bytes | None = None
    header: tuple[str, ...] = ()
    rows: tuple[dict[str, str], ...] = ()
    #: Rows that cannot be matched to a job (blank key); they are carried through unchanged.
    keyless: tuple[dict[str, str], ...] = field(default=())

    @property
    def exists(self) -> bool:
        return self.raw is not None

    def keyed(self) -> dict[RowKey, dict[str, str]]:
        return {row_key(row): row for row in self.rows}


def row_key(row: Mapping[str, str]) -> RowKey:
    return (row.get("case_id", ""), row.get("arm_id", ""), row.get("job_id", ""))


def _parse(raw: bytes, path: Path) -> tuple[tuple[str, ...], list[dict[str, str]]]:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise RatingsFileError(f"{path.name} is not valid UTF-8 text: {exc}") from exc
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), restval="", strict=True)
        header = tuple(reader.fieldnames or ())
        missing = [column for column in KEY_COLUMNS if column not in header]
        if not header or missing:
            raise RatingsFileError(
                f"{path.name} has no usable header (missing {', '.join(missing) or 'all columns'})"
            )
        if len(set(header)) != len(header):
            raise RatingsFileError(f"{path.name} repeats a column name in its header")
        rows: list[dict[str, str]] = []
        for number, row in enumerate(reader, start=2):
            if None in row:
                raise RatingsFileError(f"{path.name} row {number} has more fields than the header")
            rows.append({name: (value or "") for name, value in row.items()})
    except csv.Error as exc:
        raise RatingsFileError(f"{path.name} is not readable as CSV: {exc}") from exc
    return header, rows


def load_ratings(path: str | Path) -> LoadedRatings:
    """Read the existing file, or return an empty result when there is none. Raises ``RatingsFileError``."""

    target = Path(path)
    try:
        if not target.exists():
            return LoadedRatings(path=target)
        if target.stat().st_size > MAX_RATINGS_BYTES:
            raise RatingsFileError(f"{target.name} is larger than {MAX_RATINGS_BYTES // 1024} KiB")
        raw = target.read_bytes()
    except OSError as exc:
        raise RatingsFileError(f"{target.name} cannot be read: {exc}") from exc
    header, rows = _parse(raw, target)
    keyed: list[dict[str, str]] = []
    keyless: list[dict[str, str]] = []
    seen: set[RowKey] = set()
    for row in rows:
        if not row.get("job_id"):
            keyless.append(row)
            continue
        key = row_key(row)
        if key in seen:
            raise RatingsFileError(
                f"{target.name} has two rows for {key[0]} / {key[1]} / {key[2]}; "
                "remove the duplicate before rebuilding"
            )
        seen.add(key)
        keyed.append(row)
    return LoadedRatings(
        path=target, raw=raw, header=header, rows=tuple(keyed), keyless=tuple(keyless)
    )


def output_header(loaded: LoadedRatings) -> tuple[str, ...]:
    """The known columns, then any column this version does not know, in the order the file had them."""

    unknown = tuple(name for name in loaded.header if name not in RATING_COLUMNS)
    return (*RATING_COLUMNS, *unknown)


def bind_artifact(row: dict[str, str], current_sha256: str | None) -> dict[str, str]:
    """Stamp the digest of the clip a review is about. Only a blank, unreviewed row or an explicit ``rebind``."""

    bound = row.get(ARTIFACT_COLUMN, "").strip()
    if current_sha256 and (
        bound.lower() == REBIND_TOKEN or (not bound and not row_has_content(row))
    ):
        row[ARTIFACT_COLUMN] = current_sha256
    return row


def merge_rows(
    loaded: LoadedRatings,
    cells: Iterable[tuple[RowKey, str | None]],
) -> list[dict[str, str]]:
    """One row per manifest cell (existing values kept, digest stamped as above), then every other row."""

    existing = loaded.keyed()
    header = output_header(loaded)
    merged: list[dict[str, str]] = []
    used: set[RowKey] = set()
    for key, current_sha256 in cells:
        row = dict.fromkeys(header, "")
        row.update(existing.get(key, {}))
        row.update(zip(KEY_COLUMNS, key, strict=True))
        merged.append(bind_artifact(row, current_sha256))
        used.add(key)
    for key, row in existing.items():
        if key not in used:
            merged.append({name: row.get(name, "") for name in header})
    merged.extend({name: row.get(name, "") for name in header} for row in loaded.keyless)
    return merged


def render_csv(header: Sequence[str], rows: Sequence[Mapping[str, str]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(header), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def _backup_legacy(loaded: LoadedRatings) -> Path:
    assert loaded.raw is not None
    stamp = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
    for attempt in range(100):
        suffix = f".legacy-{stamp}" + (f"-{attempt}" if attempt else "") + ".bak"
        backup = loaded.path.with_name(loaded.path.name + suffix)
        try:
            with backup.open("xb") as handle:
                handle.write(loaded.raw)
                handle.flush()
                os.fsync(handle.fileno())
            return backup
        except FileExistsError:
            continue
    raise RatingsFileError(f"could not create a recovery copy of {loaded.path.name}")


def _shape(rows: Iterable[Mapping[str, str]], header: Sequence[str]) -> list[dict[str, str]]:
    """Rows restricted to ``header``, keyed rows first: the order ``load_ratings`` returns them in."""

    shaped = [{name: row.get(name, "") for name in header} for row in rows]
    return [row for row in shaped if row["job_id"]] + [row for row in shaped if not row["job_id"]]


def write_ratings(
    loaded: LoadedRatings, header: Sequence[str], rows: Sequence[Mapping[str, str]]
) -> Path | None:
    """Publish ``rows``; returns the recovery copy's path when an older layout was converted.

    Raises ``RatingsFileError`` (with the previous file intact) when the file changed underneath the rebuild,
    the recovery copy cannot be made, or the written file does not read back as intended.
    """

    path = loaded.path
    expected = _shape(rows, header)
    if (
        tuple(loaded.header) == tuple(header)
        and _shape((*loaded.rows, *loaded.keyless), header) == expected
    ):
        return None  # nothing to change; leave the operator's file alone
    backup = (
        _backup_legacy(loaded) if loaded.exists and tuple(loaded.header) != tuple(header) else None
    )
    try:
        on_disk = path.read_bytes() if path.exists() else None
    except OSError as exc:
        raise RatingsFileError(f"{path.name} cannot be re-read before writing: {exc}") from exc
    if on_disk != loaded.raw:
        raise RatingsFileError(
            f"{path.name} changed while the report was being built; nothing was overwritten. "
            "Build the report again."
        )
    try:
        # Bytes, not text: text mode would turn a newline inside a note into CRLF on Windows.
        atomic_write_bytes(path, render_csv(header, expected).encode("utf-8"))
    except OSError as exc:
        raise RatingsFileError(f"{path.name} could not be written: {exc}") from exc
    written = load_ratings(path)
    if (
        tuple(written.header) != tuple(header)
        or _shape((*written.rows, *written.keyless), header) != expected
    ):
        raise RatingsFileError(
            f"{path.name} did not read back as written; check it before using it"
        )
    return backup


__all__ = [
    "ARTIFACT_COLUMN",
    "KEY_COLUMNS",
    "LEGACY_COLUMNS",
    "MAX_RATINGS_BYTES",
    "RATING_COLUMNS",
    "REBIND_TOKEN",
    "LoadedRatings",
    "RatingsFileError",
    "RowKey",
    "bind_artifact",
    "load_ratings",
    "merge_rows",
    "output_header",
    "render_csv",
    "row_key",
    "write_ratings",
]
