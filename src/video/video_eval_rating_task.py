"""Registered rating sets and their result contracts (RG-170).

An eval or harness registers one sitting as a JSON file (``stablenew.rating-set.v1``) in the rating folder, or by
calling ``register_rating_task``. The file names the clips on this PC, what to ask, and where answers go. The phone
review gateway publisher (``src/app/review_gateway_ratings.py``) sends only the ids, text and media; the paths, the
case ids and the key that maps clips to arms stay here, and the key is read only when a submitted answer is applied.

``apply_answers`` writes the eval's own contract and nothing else, all or nothing: a filled cell that disagrees, or a
key file that cannot say which arm every clip was, refuses the whole submission before anything is written. The key
is also checked at registration. Writing the same answers again changes nothing. This module has no Tk, network or GPU use.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.utils.atomic_io import atomic_write_bytes
from src.video.video_eval_ratings_store import (
    ARTIFACT_COLUMN,
    REBIND_TOKEN,
    RatingsFileError,
    load_ratings,
    output_header,
    write_ratings,
)

SCHEMA = "stablenew.rating-set.v1"
KINDS = ("pairs", "scores", "ranking", "choice")
NOTES = "notes"
_TASK_ID = re.compile(r"[a-z0-9][a-z0-9-]{2,63}")
_KEY = re.compile(r"[A-Za-z0-9_-]{1,40}")
#: A drive or UNC path in outgoing text would carry a PC path to the gateway (RG-100 invariant 3).
_PC_PATH = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]|\\\\[A-Za-z0-9]")
_SPEC_LIMIT = 512 * 1024
_FILE_LIMIT = 5 * 1024 * 1024
_MAX_ITEMS = 60
_MAX_CLIPS = 6
_MAX_CRITERIA = 16
_SPEC_FIELDS = frozenset(
    {
        "schema",
        "task_id",
        "title",
        "kind",
        "instructions",
        "created_at",
        "root",
        "criteria",
        "items",
        "result",
        "follow_up",
        "follow_up_of",
    }
)
_ADAPTERS = {
    "pairwise_csv": ({"pairs"}, ("sheet", "key")),
    "ratings_csv": ({"scores"}, ("ratings", "key")),
    "ranking_csv": ({"ranking"}, ("sheet",)),
    "answer_file": (set(KINDS), ("path",)),
}
_CRITERION_TYPES = {
    "pairs": {"choice"},
    "scores": {"score", "enum"},
    "ranking": {"rank"},
    "choice": {"enum"},
}


class RatingSpecError(ValueError):
    """A registration that cannot be used; nothing was written."""


class RatingConflict(ValueError):
    """Answers that cannot be written. ``reason`` is the code the phone shows; nothing was written."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(detail or reason)
        self.reason = reason


@dataclass(frozen=True)
class RatingSpec:
    data: Mapping[str, Any]
    root: Path

    @property
    def task_id(self) -> str:
        return str(self.data["task_id"])

    @property
    def kind(self) -> str:
        return str(self.data["kind"])

    @property
    def criteria(self) -> list[dict[str, Any]]:
        return list(self.data["criteria"])

    @property
    def items(self) -> list[dict[str, Any]]:
        return list(self.data["items"])

    @property
    def adapter(self) -> str:
        return str(self.data["result"]["adapter"])

    def path(self, value: str) -> Path:
        """A spec path: relative to ``root`` unless absolute."""

        return self.root / value

    def result_path(self, name: str) -> Path:
        return self.path(str(self.data["result"][name]))

    def units(self) -> list[tuple[str, str]]:
        """What is answered: each clip of a score sheet, otherwise each item."""

        if self.kind == "scores":
            return [(i["item_id"], c["clip_id"]) for i in self.items for c in i["clips"]]
        return [(i["item_id"], "") for i in self.items]

    def required(self) -> list[str]:
        return [c["criterion_id"] for c in self.criteria if c["required"]]


# --- validation -----------------------------------------------------------------------------------------------------


def _need(condition: Any, message: str) -> None:
    if not condition:
        raise RatingSpecError(message)


def _text(value: Any, limit: int, name: str, *, required: bool = True) -> None:
    _need(
        isinstance(value, str) and len(value) <= limit,
        f"{name} must be text up to {limit} characters",
    )
    _need(value or not required, f"{name} is empty")
    _need(not _PC_PATH.search(value), f"{name} contains a PC path, which would leave this machine")


def _key(value: Any, name: str) -> None:
    _need(isinstance(value, str) and _KEY.fullmatch(value), f"{name} {value!r} is not a short id")


def _options(options: Any) -> None:
    _need(isinstance(options, list) and 2 <= len(options) <= 8, "a choice needs 2 to 8 options")
    for option in options:
        _need(
            isinstance(option, dict) and not option.keys() - {"value", "label", "recommended"},
            "an option has value, label and recommended only",
        )
        _key(option.get("value"), "option value")
        _text(option.get("label"), 120, "option label")
    _need(len({o["value"] for o in options}) == len(options), "option values repeat")


def validate_spec(data: Any) -> RatingSpec:
    """Check a registration. Raises ``RatingSpecError``; reads no file."""

    _need(isinstance(data, dict), "a rating set is a JSON object")
    _need(data.get("schema") == SCHEMA, f"schema must be {SCHEMA}")
    _need(not data.keys() - _SPEC_FIELDS, f"unknown field(s): {sorted(data.keys() - _SPEC_FIELDS)}")
    task_id, kind = data.get("task_id"), data.get("kind")
    _need(
        isinstance(task_id, str) and _TASK_ID.fullmatch(task_id), "task_id: 3-64 of a-z, 0-9 and -"
    )
    _need(kind in KINDS, f"kind must be one of {', '.join(KINDS)}")
    _text(data.get("title"), 120, "title")
    _text(data.get("instructions", ""), 2000, "instructions", required=False)
    try:
        datetime.fromisoformat(str(data.get("created_at")).replace("Z", "+00:00"))
    except ValueError:
        raise RatingSpecError("created_at must be an ISO timestamp") from None
    root = data.get("root")
    _need(isinstance(root, str) and Path(root).is_absolute(), "root must be an absolute folder")

    criteria = data.get("criteria")
    _need(isinstance(criteria, list) and 1 <= len(criteria) <= _MAX_CRITERIA, "1 to 16 criteria")
    for criterion in criteria:
        _need(
            isinstance(criterion, dict)
            and not criterion.keys() - {"criterion_id", "label", "type", "required", "options"},
            "a criterion has criterion_id, label, type, required and options only",
        )
        _key(criterion.get("criterion_id"), "criterion_id")
        _text(criterion.get("label"), 160, "criterion label")
        _need(isinstance(criterion.get("required"), bool), "required must be true or false")
        _need(
            criterion.get("type") in _CRITERION_TYPES[kind],
            f"{kind} criteria are of type {sorted(_CRITERION_TYPES[kind])}",
        )
        if criterion["type"] == "enum":
            _options(criterion.get("options"))
        else:
            _need("options" not in criterion, "only an enum criterion has options")
    ids = [c["criterion_id"] for c in criteria]
    _need(len(set(ids)) == len(ids) and NOTES not in ids, "criterion ids repeat or use 'notes'")
    _need(any(c["required"] for c in criteria), "at least one criterion must be required")

    items = data.get("items")
    _need(isinstance(items, list) and 1 <= len(items) <= _MAX_ITEMS, "1 to 60 items")
    for item in items:
        _need(
            isinstance(item, dict)
            and not item.keys() - {"item_id", "title", "context", "reference", "clips"},
            "an item has item_id, title, context, reference and clips only",
        )
        _key(item.get("item_id"), "item_id")
        if "title" in item:
            _text(item["title"], 120, "item title")
        _text(item.get("context", ""), 2000, "context", required=False)
        _need(isinstance(item.get("reference", ""), str), "reference must be a path")
        clips = item.get("clips", [])
        _need(isinstance(clips, list) and len(clips) <= _MAX_CLIPS, "up to 6 clips per item")
        for clip in clips:
            _need(
                isinstance(clip, dict) and not clip.keys() - {"clip_id", "label", "path", "key"},
                "a clip has clip_id, label, path and key only",
            )
            _key(clip.get("clip_id"), "clip_id")
            _text(clip.get("label"), 40, "clip label")
            _need(isinstance(clip.get("path"), str) and clip["path"], "a clip needs a path")
        clip_ids = [clip["clip_id"] for clip in clips]
        _need(len(set(clip_ids)) == len(clip_ids) and "tie" not in clip_ids, "clip ids repeat")
        wanted = {"pairs": len(clips) == 2, "scores": len(clips) >= 1, "ranking": len(clips) >= 2}
        _need(wanted.get(kind, True), f"wrong number of clips for {kind}")
    item_ids = [item["item_id"] for item in items]
    _need(len(set(item_ids)) == len(item_ids), "item ids repeat")

    result = data.get("result")
    _need(isinstance(result, dict) and result.get("adapter") in _ADAPTERS, "unknown result adapter")
    kinds, paths = _ADAPTERS[result["adapter"]]
    _need(kind in kinds, f"{result['adapter']} does not take {kind} answers")
    for name in paths:
        _need(isinstance(result.get(name), str) and result[name], f"result needs {name}")
    _need(not result.keys() - {"adapter", *paths, "key"}, "unknown result field")
    if result["adapter"] == "ratings_csv":
        _need(
            all(clip.get("key") for item in items for clip in item["clips"]),
            "ratings_csv clips name their entry in the key file",
        )

    follow = data.get("follow_up")
    if follow is not None:
        fields = {"task_id", "title", "instructions", "context", "options", "result"}
        _need(isinstance(follow, dict) and not follow.keys() - fields, "unknown follow_up field")
        _need(
            isinstance(follow.get("task_id"), str)
            and _TASK_ID.fullmatch(follow["task_id"])
            and follow["task_id"] != task_id,
            "follow_up needs its own task_id",
        )
        _text(follow.get("title"), 120, "follow_up title")
        _text(follow.get("context", ""), 1000, "follow_up context", required=False)
        _text(follow.get("instructions", ""), 2000, "follow_up instructions", required=False)
        _options(follow.get("options"))
        _need(
            isinstance(follow.get("result"), dict)
            and follow["result"].get("adapter") == "answer_file"
            and isinstance(follow["result"].get("path"), str),
            "a follow_up is answered into an answer_file",
        )
    return RatingSpec(data, Path(root))


def _check_files(spec: RatingSpec) -> None:
    for item in spec.items:
        for value in [item.get("reference"), *(c["path"] for c in item.get("clips", []))]:
            _need(not value or spec.path(value).is_file(), f"missing file: {value}")
    for name in ("sheet", "ratings", "key"):
        value = spec.data["result"].get(name)
        if value and not (spec.adapter == "ranking_csv" and name == "sheet"):
            _need(spec.path(value).is_file(), f"missing file: {value}")
    try:
        check_key(spec)
    except RatingConflict as error:
        raise RatingSpecError(str(error)) from None


def register_rating_task(data: Mapping[str, Any], folder: str | Path) -> Path:
    """Register one sitting: validate it, check its files and write ``<folder>/<task_id>.json``.

    Registering the same content again is a no-op; different content under a used id is refused.
    """

    spec = validate_spec(dict(data))
    _check_files(spec)
    target = Path(folder) / f"{spec.task_id}.json"
    encoded = (json.dumps(dict(data), indent=1) + "\n").encode("utf-8")
    _need(len(encoded) <= _SPEC_LIMIT, "the rating set is too large")
    if target.exists():
        _need(
            json.loads(target.read_bytes()) == dict(data),
            f"{target.name} is already registered with other content; use a new task_id",
        )
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(target, encoded)
    return target


def load_rating_specs(folder: str | Path) -> list[tuple[Path, RatingSpec | None, str]]:
    """Every ``*.json`` in the folder as ``(path, spec, error)``, oldest name first."""

    found: list[tuple[Path, RatingSpec | None, str]] = []
    for path in sorted(Path(folder).glob("*.json")):
        try:
            spec = validate_spec(json.loads(_read(path, _SPEC_LIMIT)))
            _need(path.stem == spec.task_id, "the file name must be the task_id")
        except (OSError, ValueError, RecursionError) as error:
            found.append((path, None, type(error).__name__))
        else:
            found.append((path, spec, ""))
    return found


def follow_up_spec(spec: RatingSpec, reveal: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """The pick-one task to register after ``spec`` was revealed, with the first reveal table as its context."""

    follow = spec.data.get("follow_up")
    if follow is None:
        return None
    lines = [follow.get("context", "")]
    if reveal:
        table = reveal[0]
        lines += ["", table["title"], " | ".join(table["columns"])]
        lines += [" | ".join(row) for row in table["rows"]]
    return {
        "schema": SCHEMA,
        "task_id": follow["task_id"],
        "title": follow["title"],
        "kind": "choice",
        "instructions": follow.get("instructions", ""),
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "root": str(spec.root),
        "criteria": [
            {
                "criterion_id": "pick",
                "label": "Pick one",
                "type": "enum",
                "required": True,
                "options": follow["options"],
            }
        ],
        "items": [{"item_id": "q1", "context": "\n".join(lines).strip()[:2000]}],
        "result": dict(follow["result"]),
        "follow_up_of": spec.task_id,
    }


# --- reading --------------------------------------------------------------------------------------------------------


def _read(path: Path, limit: int = _FILE_LIMIT) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise OSError(f"{path.name} is too large")
    return data


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_sheet(path: Path) -> tuple[bytes, list[str], list[dict[str, str]]]:
    raw = _read(path)
    reader = csv.DictReader(
        io.StringIO(raw.decode("utf-8-sig"), newline=""), restval="", strict=True
    )
    header = list(reader.fieldnames or ())
    rows = list(reader)
    if not header or any(None in row for row in rows):
        raise RatingConflict("write_failed", f"{path.name} is not a readable sheet")
    return raw, header, rows


def _bad_key(spec: RatingSpec, problem: str) -> RatingConflict:
    """What is wrong with the key file, naming the file only (the text may be logged)."""

    return RatingConflict("write_failed", f"{spec.result_path('key').name}: {problem}")


def _read_key(spec: RatingSpec, section: str) -> dict[str, Any]:
    """The key file's ``section`` object."""

    value = json.loads(_read(spec.result_path("key")))
    if not isinstance(value, dict):
        raise _bad_key(spec, "not a JSON object")
    entries = value.get(section)
    if not isinstance(entries, dict):
        raise _bad_key(spec, f'no "{section}" object')
    return entries


def check_key(spec: RatingSpec) -> None:
    """The key must give an arm for every clip of every item, or the sitting could not be revealed.

    Raises ``RatingConflict`` saying what is wrong. A set without a key (a question) has nothing to check.
    """

    if spec.adapter == "answer_file" or not spec.data["result"].get("key"):
        return
    try:
        _arm_map(spec)
    except RatingConflict:
        raise
    except (OSError, ValueError, KeyError, RecursionError, csv.Error) as error:
        # Type only: a message may carry a path.
        raise _bad_key(spec, f"cannot be read ({type(error).__name__})") from error


def check_clip_identity(spec: RatingSpec) -> None:
    """For ``ratings_csv``: every blind clip must still be the artifact its key entry names."""

    if spec.adapter != "ratings_csv":
        return
    try:
        entries = _read_key(spec, "clips")
        for item in spec.items:
            for clip in item["clips"]:
                if file_digest(spec.path(clip["path"])) != entries[clip["key"]]["artifact_sha256"]:
                    raise RatingConflict("clip_changed")
    except (OSError, KeyError, TypeError, ValueError) as error:
        if isinstance(error, RatingConflict):
            raise
        raise RatingConflict(
            "clip_changed", "the clips cannot be checked against the key"
        ) from error


def _score_rows(spec: RatingSpec) -> dict[tuple[str, str], tuple[tuple[str, str, str], str]]:
    """``(item, clip) -> (ratings.csv row key, artifact sha)`` from the key file."""

    entries = _read_key(spec, "clips")
    fields = ("case_id", "arm_id", "job_id", "artifact_sha256")
    mapping = {}
    for item in spec.items:
        for clip in item["clips"]:
            entry = entries.get(clip["key"])
            if not isinstance(entry, dict):
                raise _bad_key(spec, f"no entry {clip['key']}")
            for name in fields:
                if not isinstance(entry.get(name), str) or not entry[name]:
                    raise _bad_key(spec, f"entry {clip['key']} has no {name}")
            row = (entry["case_id"], entry["arm_id"], entry["job_id"])
            mapping[(item["item_id"], clip["clip_id"])] = (row, entry["artifact_sha256"])
    return mapping


def is_rated(spec: RatingSpec) -> bool:
    """Every required answer is already in the eval's file (rated at the desk, or applied before)."""

    required = spec.required()
    try:
        if spec.adapter == "answer_file":
            return spec.result_path("path").is_file()
        if spec.adapter == "ratings_csv":
            rows = load_ratings(spec.result_path("ratings")).keyed()
            return all(
                all(rows.get(row, {}).get(name, "").strip() for name in required)
                for row, _sha in _score_rows(spec).values()
            )
        column = {"pairwise_csv": ("pair", "{}"), "ranking_csv": ("item_id", "{}_order")}
        id_column, name_format = column[spec.adapter]
        _raw, _header, rows_ = _read_sheet(spec.result_path("sheet"))
        by_item = {row.get(id_column, ""): row for row in rows_}
        return all(
            all(
                by_item.get(item["item_id"], {}).get(name_format.format(c), "").strip()
                for c in required
            )
            for item in spec.items
        )
    except (OSError, KeyError, TypeError, ValueError, csv.Error):
        return False


# --- applying -------------------------------------------------------------------------------------------------------


def _valid_value(criterion: Mapping[str, Any], value: Any, clips: list[str]) -> bool:
    if not isinstance(value, str):
        return False
    kind = criterion["type"]
    if kind == "score":
        return value in {"1", "2", "3", "4", "5"}
    if kind == "enum":
        return value in {option["value"] for option in criterion["options"]}
    if kind == "choice":
        return value == "tie" or value in clips
    return value == "tie" or sorted(re.split(r"[>=]", value)) == sorted(clips)


def _checked(spec: RatingSpec, answers: Any) -> dict[tuple[str, str], dict[str, Any]]:
    """Answers are untrusted: only this task's units, criteria and values, and every required one."""

    units = spec.units()
    criteria = {c["criterion_id"]: c for c in spec.criteria}
    clips = {i["item_id"]: [c["clip_id"] for c in i.get("clips", [])] for i in spec.items}
    found: dict[tuple[str, str], dict[str, Any]] = {}
    invalid = RatingConflict("invalid_record")
    if not isinstance(answers, list):
        raise invalid
    for answer in answers:
        if not isinstance(answer, dict):
            raise invalid
        unit = (answer.get("item_id"), answer.get("clip_id"))
        values, notes = answer.get("values"), answer.get("notes", "")
        if unit not in units or unit in found or not isinstance(values, dict):
            raise invalid
        if not isinstance(notes, str) or len(notes) > 1000:
            raise invalid
        for name, value in values.items():
            if name not in criteria or not _valid_value(criteria[name], value, clips[unit[0]]):
                raise invalid
        found[unit] = {"values": dict(values), "notes": " ".join(notes.split())}
    required = spec.required()
    if any(
        name not in found.get(unit, {}).get("values", {}) for unit in units for name in required
    ):
        raise invalid
    return found


def _fill(row: dict[str, str], column: str, value: str) -> None:
    old = row.get(column, "").strip()
    if old and old.casefold() != value.casefold():
        raise RatingConflict("already_rated")
    if not old:
        row[column] = value


def _add_note(row: dict[str, str], note: str) -> None:
    """Notes never conflict: a phone note is appended to a desk note, once."""

    old = row.get(NOTES, "")
    if note and note not in old:
        row[NOTES] = f"{old} | {note}" if old.strip() else note


def _sheet_bytes(header: Sequence[str], rows: Sequence[Mapping[str, str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(header), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _apply_sheet(spec: RatingSpec, answers: Mapping[tuple[str, str], Mapping[str, Any]]) -> None:
    pairwise = spec.adapter == "pairwise_csv"
    id_column, name_format = ("pair", "{}") if pairwise else ("item_id", "{}_order")
    path = spec.result_path("sheet")
    columns = [name_format.format(c["criterion_id"]) for c in spec.criteria]
    if not pairwise and not path.exists():
        raw: bytes | None = None
        header = [id_column, *columns, NOTES]
        rows = [{**dict.fromkeys(header, ""), id_column: item["item_id"]} for item in spec.items]
    else:
        raw, header, rows = _read_sheet(path)
    if not {id_column, NOTES, *columns} <= set(header):
        raise RatingConflict("write_failed", f"{path.name} does not have the expected columns")
    by_item = {row.get(id_column, ""): row for row in rows}
    for (item_id, _clip), answer in answers.items():
        row = by_item.get(item_id)
        if row is None:
            raise RatingConflict("write_failed", f"{path.name} has no row {item_id}")
        for name, value in answer["values"].items():
            _fill(row, name_format.format(name), value)
        _add_note(row, answer["notes"])
    data = _sheet_bytes(header, rows)
    if raw is not None and _read(path) != raw:
        raise RatingConflict("write_failed", f"{path.name} changed while it was being written")
    if data != raw:
        atomic_write_bytes(path, data)


def _apply_ratings(spec: RatingSpec, answers: Mapping[tuple[str, str], Mapping[str, Any]]) -> None:
    check_clip_identity(spec)
    loaded = load_ratings(spec.result_path("ratings"))
    header = output_header(loaded)
    keyed = {key: dict(row) for key, row in loaded.keyed().items()}
    unknown = [c["criterion_id"] for c in spec.criteria if c["criterion_id"] not in header]
    if unknown:
        raise RatingConflict("write_failed", f"ratings.csv has no column {unknown[0]}")
    for unit, (row_id, digest) in _score_rows(spec).items():
        row = keyed.get(row_id)
        if row is None:
            row = keyed[row_id] = dict.fromkeys(header, "")
            row.update(zip(("case_id", "arm_id", "job_id"), row_id, strict=True))
        bound = row.get(ARTIFACT_COLUMN, "").strip()
        if bound and bound.lower() != REBIND_TOKEN and bound != digest:
            raise RatingConflict("clip_changed")
        row[ARTIFACT_COLUMN] = digest
        answer = answers[unit]
        for name, value in answer["values"].items():
            _fill(row, name, value)
        _add_note(row, answer["notes"])
    rows = [{name: row.get(name, "") for name in header} for row in keyed.values()]
    rows += [{name: row.get(name, "") for name in header} for row in loaded.keyless]
    write_ratings(loaded, header, rows)


def _apply_file(spec: RatingSpec, answers: Mapping[tuple[str, str], Mapping[str, Any]]) -> None:
    path = spec.result_path("path")
    listed = [
        {"item_id": unit[0], "clip_id": unit[1], **answers[unit]}
        for unit in spec.units()
        if unit in answers
    ]
    if path.suffix.lower() == ".json":
        document = {"task_id": spec.task_id, "answers": listed}
        if path.exists():
            old = json.loads(_read(path))
            if not isinstance(old, dict) or {k: old.get(k) for k in document} != document:
                raise RatingConflict("already_rated")
            return
        document["answered_at"] = datetime.now(UTC).isoformat(timespec="seconds")
        data = (json.dumps(document, indent=1) + "\n").encode("utf-8")
    else:
        data = "".join(f"{entry['values'][spec.required()[0]]}\n" for entry in listed).encode(
            "utf-8"
        )
        if path.exists():
            if _read(path).replace(b"\r\n", b"\n") != data:
                raise RatingConflict("already_rated")
            return
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(path, data)


def apply_answers(spec: RatingSpec, answers: Any) -> list[dict[str, Any]]:
    """Write submitted answers into the eval's contract and return the reveal tables.

    Raises ``RatingConflict`` with nothing written. An ``OSError`` from a locked or missing file is the caller's to
    retry.
    """

    checked = _checked(spec, answers)
    try:
        # Built first: it reads the whole key, so a key that cannot be used stops here with nothing written.
        reveal = _reveal(spec, checked)
        if spec.adapter == "ratings_csv":
            _apply_ratings(spec, checked)
        elif spec.adapter == "answer_file":
            _apply_file(spec, checked)
        else:
            _apply_sheet(spec, checked)
        return reveal
    except RatingConflict:
        raise
    except RatingsFileError as error:
        raise RatingConflict("write_failed", "ratings.csv could not be written") from error
    except (KeyError, TypeError, UnicodeError, json.JSONDecodeError, csv.Error) as error:
        raise RatingConflict("write_failed", "an eval file is not in the expected shape") from error


# --- reveal ---------------------------------------------------------------------------------------------------------


def _table(title: str, columns: Sequence[str], rows: Sequence[Sequence[str]]) -> dict[str, Any]:
    return {
        "title": title[:120],
        "columns": [str(column)[:60] for column in columns][:8],
        "rows": [[str(cell)[:120] for cell in row][:8] for row in rows][:_MAX_ITEMS],
    }


def _arm_map(spec: RatingSpec) -> dict[str, dict[str, str]]:
    """``item_id -> {clip_id: arm}`` from the eval's key file, for every item and clip.

    Raises ``RatingConflict`` naming what the key (or the pair sheet's case column) does not give.
    """

    if spec.adapter == "ratings_csv":
        rows = _score_rows(spec)
        found = {
            item["item_id"]: {
                clip["clip_id"]: rows[(item["item_id"], clip["clip_id"])][0][1]
                for clip in item["clips"]
            }
            for item in spec.items
        }
    else:
        key = _read_key(spec, "key")
        cases = {item["item_id"]: item["item_id"] for item in spec.items}
        if spec.adapter == "pairwise_csv":
            _raw, _header, sheet = _read_sheet(spec.result_path("sheet"))
            by_pair = {row.get("pair", ""): row.get("case_id", "") for row in sheet}
            for item_id in cases:
                if not by_pair.get(item_id):
                    raise RatingConflict(
                        "write_failed", f"the pair sheet gives no case_id for {item_id}"
                    )
                cases[item_id] = by_pair[item_id]
        found = {}
        for item in spec.items:
            item_id = item["item_id"]
            entry = key.get(cases[item_id])
            if not isinstance(entry, dict):
                raise _bad_key(spec, f"no entry for item {item_id} ({cases[item_id]})")
            found[item_id] = {}
            for clip in item["clips"]:
                arm = entry.get(clip["clip_id"])
                if not isinstance(arm, str) or not arm:
                    raise _bad_key(
                        spec, f"item {item_id} has no arm name for clip {clip['clip_id']}"
                    )
                found[item_id][clip["clip_id"]] = arm
    # Arm names reach the phone in the reveal.
    for arms in found.values():
        for arm in arms.values():
            if len(arm) > 120 or _PC_PATH.search(arm):
                raise _bad_key(spec, "an arm name is over 120 characters or holds a PC path")
    return found


def _places(order: str, clips: Sequence[str]) -> dict[str, float]:
    """``B>A=C`` as places; tied clips share the mean of the places they cover."""

    groups = [list(clips)] if order == "tie" else [part.split("=") for part in order.split(">")]
    places: dict[str, float] = {}
    taken = 0
    for group in groups:
        for clip in group:
            places[clip] = taken + (len(group) + 1) / 2
        taken += len(group)
    return places


def _reveal(
    spec: RatingSpec, answers: Mapping[tuple[str, str], Mapping[str, Any]]
) -> list[dict[str, Any]]:
    if spec.adapter == "answer_file" or not spec.data["result"].get("key"):
        return []
    arms_of = _arm_map(spec)
    arms = sorted({arm for mapping in arms_of.values() for arm in mapping.values()})
    labels = list(spec.items[0]["clips"])
    which = _table(
        "Which was which",
        ["Item", *(clip["label"] for clip in labels)],
        [
            [
                item["item_id"],
                *(arms_of[item["item_id"]].get(c["clip_id"], "") for c in item["clips"]),
            ]
            for item in spec.items
        ],
    )
    if spec.kind == "pairs":
        rows = []
        for criterion in spec.criteria:
            name = criterion["criterion_id"]
            tally = dict.fromkeys([*arms, "tie"], 0)
            for (item_id, _clip), answer in answers.items():
                value = answer["values"].get(name)
                if value:
                    tally["tie" if value == "tie" else arms_of[item_id][value]] += 1
            rows.append([criterion["label"], *(str(tally[arm]) for arm in arms), str(tally["tie"])])
        return [_table("Wins per arm", ["Criterion", *arms, "Same"], rows), which]

    shown = [c for c in spec.criteria if c["required"]][:7]
    collected: dict[str, dict[str, list[Any]]] = {
        arm: {c["criterion_id"]: [] for c in shown} for arm in arms
    }
    for (item_id, clip_id), answer in answers.items():
        for criterion in shown:
            name = criterion["criterion_id"]
            value = answer["values"].get(name)
            if not value:
                continue
            if spec.kind == "scores":
                collected[arms_of[item_id][clip_id]][name].append(value)
            else:
                for clip, place in _places(value, list(arms_of[item_id])).items():
                    collected[arms_of[item_id][clip]][name].append(place)

    def summary(criterion: Mapping[str, Any], values: list[Any]) -> str:
        if not values:
            return "-"
        if criterion["type"] in ("score", "rank"):
            return f"{sum(float(v) for v in values) / len(values):.2f}"
        return ", ".join(f"{v} {values.count(v)}" for v in sorted(set(values)))

    title = "Per arm" if spec.kind == "scores" else "Mean place per arm (1 is best)"
    rows = [[arm, *(summary(c, collected[arm][c["criterion_id"]]) for c in shown)] for arm in arms]
    return [_table(title, ["Arm", *(c["label"] for c in shown)], rows), which]


__all__ = [
    "SCHEMA",
    "RatingConflict",
    "RatingSpec",
    "RatingSpecError",
    "apply_answers",
    "check_clip_identity",
    "check_key",
    "file_digest",
    "follow_up_spec",
    "is_rated",
    "load_rating_specs",
    "register_rating_task",
    "validate_spec",
]
