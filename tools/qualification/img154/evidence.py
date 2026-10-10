"""D5: durable, redacted evidence, fault-event preservation contracts, the dispatch ledger and future result classes.

Writers only ever APPEND to a path the caller names (an ignored local directory); nothing here writes to, clears or scrubs a
Windows event log. A failed, delayed or inaccessible evidence source is ``unknown`` and never becomes a "no faults" claim.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .core import MIB, Finding, canonical_json, digest

EVIDENCE_SCHEMA = "stablenew.img154.evidence.v1"

# ----------------------------------------------------------------------------------------------------- redaction

_USER_PATH = re.compile(r"(?i)(?:[A-Z]:)?[\\/]+(?:Users|home)[\\/]+[^\\/\s\"']+")
_SERIAL_PAIR = re.compile(
    r"(?i)\b(serial(?:number|_number)?|uuid|guid|machineguid|hwid)\b(\s*[=:]\s*)\S+"
)
_MAC = re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b")
_PROMPT_KEYS = frozenset({"prompt", "negative_prompt"})
_SECRET_KEY = re.compile(
    r"(?i)(serial|uuid|guid|hwid|machine_?id|username|user_?name|password|token|secret)"
)


def redact_text(text: str) -> str:
    text = _USER_PATH.sub("<USER_PROFILE>", text)
    text = _SERIAL_PAIR.sub(lambda m: f"{m.group(1)}{m.group(2)}<REDACTED>", text)
    return _MAC.sub("<REDACTED_MAC>", text)


def redact_value(value: Any, *, key: str | None = None) -> Any:
    """Shared reports carry no raw prompt, no personal profile path and no hardware identifier by default."""

    if key is not None and key.lower() in _PROMPT_KEYS and isinstance(value, str):
        return {
            "redacted": "prompt",
            "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
            "chars": len(value),
        }
    if key is not None and _SECRET_KEY.search(key):
        return "<REDACTED>"
    if isinstance(value, Mapping):
        return {str(k): redact_value(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [redact_value(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


# --------------------------------------------------------------------------------------------- durable JSONL


class DurableJsonlWriter:
    """Append-only, bounded, size-rotated JSON Lines with a flush and fsync after EVERY record.

    The file is opened, written, flushed, synced and closed per record, so a crash (or a Python ``finally`` that never runs)
    loses at most the record being written. Each record carries a monotonically increasing ``seq`` so a missing range is
    detectable; rotation keeps ``max_files`` files and states how many older ones were dropped.
    """

    def __init__(
        self,
        path: Path | str,
        *,
        max_bytes: int = 4 * MIB,
        max_files: int = 3,
        sync: Callable[[int], None] = os.fsync,
        redact: bool = True,
        rotate: bool = True,
    ) -> None:
        if max_bytes < 1024 or max_files < 1:
            raise ValueError("max_bytes must be at least 1024 and max_files at least 1")
        self.path = Path(path)
        self.max_bytes = int(max_bytes)
        self.max_files = int(max_files)
        self._sync = sync
        self._redact = redact
        #: ``False`` for append-only authorities (the dispatch ledger): a full stream refuses, never drops history.
        self.rotate = rotate
        self._seq = 0
        self._seeded = False
        self.dropped_files = 0
        self.truncated_records = 0

    def _seed(self) -> None:
        """Continue the sequence of an existing stream so a restart never repeats a ``seq``."""

        if self._seeded:
            return
        self._seeded = True
        if self.path.exists():
            records, _, _ = read_jsonl(self.path)
            self._seq = max((int(r.get("seq", 0)) for r in records), default=0)

    def _line(self, record: Mapping[str, Any]) -> bytes:
        self._seed()
        self._seq += 1
        payload = redact_value(dict(record)) if self._redact else dict(record)
        # reserved keys are written last: a record can never spoof its own schema or sequence number
        body = {**payload, "schema": EVIDENCE_SCHEMA, "seq": self._seq}
        line = (canonical_json(body) + "\n").encode("utf-8")
        if len(line) > self.max_bytes // 2:
            if not self.rotate:
                self._seq -= 1
                raise OSError(
                    "record exceeds the bound of an append-only stream; nothing was written"
                )
            self.truncated_records += 1
            stub = {
                "schema": EVIDENCE_SCHEMA,
                "seq": self._seq,
                "truncated": True,
                "original_bytes": len(line),
                "sha256": hashlib.sha256(line).hexdigest(),
            }
            line = (canonical_json(stub) + "\n").encode("utf-8")
        return line

    def _rotate(self) -> None:
        oldest = self.path.with_name(f"{self.path.name}.{self.max_files - 1}")
        if self.max_files > 1 and oldest.exists():
            oldest.unlink()
            self.dropped_files += 1
        for index in range(self.max_files - 2, 0, -1):
            source = self.path.with_name(f"{self.path.name}.{index}")
            if source.exists():
                source.replace(self.path.with_name(f"{self.path.name}.{index + 1}"))
        if self.max_files > 1:
            self.path.replace(self.path.with_name(f"{self.path.name}.1"))
        else:
            self.path.unlink()
            self.dropped_files += 1

    def append(self, record: Mapping[str, Any]) -> int:
        line = self._line(record)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        current = self.path.stat().st_size if self.path.exists() else 0
        if current and current + len(line) > self.max_bytes:
            if not self.rotate:
                self._seq -= 1
                raise OSError("append-only stream is full; it is never rotated or truncated")
            self._rotate()
        with self.path.open("ab") as stream:
            stream.write(line)
            stream.flush()
            self._sync(stream.fileno())
        return self._seq


def read_jsonl(path: Path | str) -> tuple[list[dict[str, Any]], bool, int]:
    """``(records, truncated_tail, corrupt_lines)``: a torn final line is reported, never silently accepted."""

    records: list[dict[str, Any]] = []
    corrupt = 0
    truncated_tail = False
    data = Path(path).read_bytes()
    lines = data.split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()
    elif lines:
        truncated_tail = True
        lines.pop()
    for raw in lines:
        try:
            value = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            corrupt += 1
            continue
        if isinstance(value, dict):
            records.append(value)
        else:
            corrupt += 1
    return records, truncated_tail, corrupt


# --------------------------------------------------------------------------------------- fault-event preservation

FAULT_SOURCES = ("system_log", "application_log", "wer_reports", "live_kernel", "whea")
COMPLETE, PARTIAL, INACCESSIBLE, NOT_COLLECTED = (
    "complete",
    "partial",
    "inaccessible",
    "not_collected",
)
#: The newest N records were read and the log holds at least that many, so older records may be unseen. Acceptable for a
#: baseline ONLY because continuity is proven at diff time (the before and after windows must overlap).
BOUNDED = "bounded_lookback"
ACCEPTED_BASELINE_COVERAGE = (COMPLETE, BOUNDED)
#: Seconds the "after" snapshot must trail the end of the workload: WER and live-kernel records post late.
FAULT_SETTLE_S = 120.0

NEW_EVENTS = "NEW_EVENTS"
BOOT_CHANGED = "BOOT_CHANGED"
NO_NEW_EVENTS_COMPLETE_COVERAGE = "NO_NEW_EVENTS_COMPLETE_COVERAGE"
UNKNOWN_COVERAGE_GAP = "UNKNOWN_COVERAGE_GAP"


@dataclass(frozen=True)
class FaultSourceSnapshot:
    source: str
    coverage: str  # complete | partial | inaccessible | not_collected
    record_ids: frozenset[str] = frozenset()
    detail: str = ""


@dataclass(frozen=True)
class FaultSnapshot:
    taken_utc: str
    boot_id: str | None
    sources: Mapping[str, FaultSourceSnapshot] = field(default_factory=dict)

    def coverage(self) -> dict[str, str]:
        return {
            name: (self.sources[name].coverage if name in self.sources else NOT_COLLECTED)
            for name in FAULT_SOURCES
        }


@dataclass(frozen=True)
class FaultClassification:
    status: str
    new_records: Mapping[str, tuple[str, ...]]
    gaps: tuple[str, ...]
    boot_changed: bool


def classify_faults(
    before: FaultSnapshot | None,
    after: FaultSnapshot | None,
    *,
    seconds_after_run: float | None = None,
) -> FaultClassification:
    """Never reports "no faults": the best outcome is ``NO_NEW_EVENTS_COMPLETE_COVERAGE`` and only on complete coverage."""

    if before is None or after is None:
        return FaultClassification(UNKNOWN_COVERAGE_GAP, {}, ("snapshot_missing",), False)
    new: dict[str, tuple[str, ...]] = {}
    gaps: list[str] = []
    for name in FAULT_SOURCES:
        old, now = before.sources.get(name), after.sources.get(name)
        if old is None or now is None:
            gaps.append(f"{name}:{now.coverage if now else NOT_COLLECTED}")
            continue
        if (
            old.coverage not in ACCEPTED_BASELINE_COVERAGE
            or now.coverage not in ACCEPTED_BASELINE_COVERAGE
        ):
            gaps.append(f"{name}:{now.coverage}")
        elif BOUNDED in (old.coverage, now.coverage) and not (old.record_ids & now.record_ids):
            gaps.append(f"{name}:lookback_continuity_unproven")
        added = tuple(sorted(now.record_ids - old.record_ids))
        if added:
            new[name] = added
    if seconds_after_run is None or seconds_after_run < FAULT_SETTLE_S:
        gaps.append("settle_time_not_elapsed")
    if before.boot_id and after.boot_id and before.boot_id != after.boot_id:
        return FaultClassification(BOOT_CHANGED, new, tuple(gaps), True)
    if not before.boot_id or not after.boot_id:
        gaps.append("boot_identity_unknown")
    if new:
        return FaultClassification(NEW_EVENTS, new, tuple(gaps), False)
    if gaps:
        return FaultClassification(UNKNOWN_COVERAGE_GAP, new, tuple(gaps), False)
    return FaultClassification(NO_NEW_EVENTS_COMPLETE_COVERAGE, new, (), False)


# ---------------------------------------------------------------------------------------------- dispatch ledger


class LedgerRefusal(RuntimeError):
    """A second, replayed or unverifiable attempt is refused."""


class LedgerStore(Protocol):
    def read(self) -> list[dict[str, Any]]: ...

    def append(self, record: dict[str, Any]) -> None: ...


class MemoryLedgerStore:
    """A fake for tests; ``fail_reads`` simulates an unreadable store."""

    def __init__(self, *, fail_reads: bool = False) -> None:
        self.records: list[dict[str, Any]] = []
        self.fail_reads = fail_reads

    def read(self) -> list[dict[str, Any]]:
        if self.fail_reads:
            raise OSError("ledger unreadable")
        return list(self.records)

    def append(self, record: dict[str, Any]) -> None:
        self.records.append(dict(record))


class FileLedgerStore:
    """Durable ledger on the same fsync-per-record writer as the evidence stream."""

    def __init__(self, path: Path | str, *, sync: Callable[[int], None] = os.fsync) -> None:
        self.path = Path(path)
        self._writer = DurableJsonlWriter(
            self.path, max_bytes=16 * MIB, max_files=1, sync=sync, redact=False, rotate=False
        )

    def read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records, torn, corrupt = read_jsonl(self.path)
        if torn or corrupt:
            raise OSError("ledger is torn or corrupt; ambiguous, not repaired")
        return records

    def append(self, record: dict[str, Any]) -> None:
        self._writer.append(record)


class DispatchLedger:
    """Records the INTENT to attempt before anything is sent, so an interrupted attempt stays ambiguous and is never replayed.

    Phase A only exercises this contract against fakes: there is no network or process code in this package.
    """

    def __init__(self, store: LedgerStore) -> None:
        self._store = store

    def state(self, manifest_digest: str) -> str:
        """``none`` | ``ambiguous`` (attempt without outcome) | ``completed`` | ``unknown`` (unreadable store)."""

        try:
            records = [r for r in self._store.read() if r.get("manifest_digest") == manifest_digest]
        except (OSError, ValueError):
            return "unknown"
        if not records:
            return "none"
        if any(r.get("kind") == "outcome" for r in records):
            return "completed"
        return "ambiguous"

    def preflight_state(self, manifest_digest: str) -> str:
        """The value the preflight evaluator consumes."""

        state = self.state(manifest_digest)
        return {"none": "none", "ambiguous": "ambiguous", "completed": "dispatched"}.get(
            state, "unknown"
        )

    def record_attempt(self, manifest_digest: str, request_digest: str) -> None:
        state = self.state(manifest_digest)
        if state != "none":
            raise LedgerRefusal(
                f"attempt refused: ledger state is {state!r}; there is no retry or replay"
            )
        self._store.append(
            {
                "kind": "attempt",
                "manifest_digest": manifest_digest,
                "request_digest": request_digest,
            }
        )

    def record_outcome(self, manifest_digest: str, outcome: str) -> None:
        if self.state(manifest_digest) != "ambiguous":
            raise LedgerRefusal("an outcome can only close a recorded, unresolved attempt")
        self._store.append(
            {"kind": "outcome", "manifest_digest": manifest_digest, "outcome": outcome}
        )


# ----------------------------------------------------------------------------------------------- result classes

PREFLIGHT_REFUSED = "PREFLIGHT_REFUSED"
LOADER_FAILED = "LOADER_FAILED"
RESOURCE_ABORT_REQUESTED = "RESOURCE_ABORT_REQUESTED"
AMBIGUOUS_DISPATCH = "AMBIGUOUS_DISPATCH"
SYSTEM_OR_GPU_FAULT = "SYSTEM_OR_GPU_FAULT"
INSTRUMENTATION_GAP = "INSTRUMENTATION_GAP"
OUTPUT_VALIDATION_FAIL = "OUTPUT_VALIDATION_FAIL"
TECHNICAL_PASS_CONSTRAINED = "TECHNICAL_PASS_CONSTRAINED"

#: The only state this package can never produce. A pass would also require one validated output, telemetry coverage and a
#: clean owned shutdown, and even then claims no general stability: that adjudication belongs to a separately authorized package.
PHASE_A_UNREACHABLE_RESULT_CLASSES = frozenset({TECHNICAL_PASS_CONSTRAINED})
RESULT_CLASSES = (
    PREFLIGHT_REFUSED,
    LOADER_FAILED,
    RESOURCE_ABORT_REQUESTED,
    AMBIGUOUS_DISPATCH,
    SYSTEM_OR_GPU_FAULT,
    INSTRUMENTATION_GAP,
    OUTPUT_VALIDATION_FAIL,
    TECHNICAL_PASS_CONSTRAINED,
)


@dataclass(frozen=True)
class ResultFacts:
    preflight_prepared: bool
    dispatched: bool
    outcome_recorded: bool = False
    loader_failed: bool = False
    stop_requested: bool = False
    fault_status: str = UNKNOWN_COVERAGE_GAP
    telemetry_complete: bool = False
    output_valid: bool | None = None


def classify_non_pass(facts: ResultFacts) -> tuple[str | None, tuple[str, ...]]:
    """``(primary, also)``. ``None`` means no failure class applies: this package never declares a pass."""

    found: list[str] = []
    if not facts.preflight_prepared and not facts.dispatched:
        found.append(PREFLIGHT_REFUSED)
    if facts.fault_status in (NEW_EVENTS, BOOT_CHANGED):
        found.append(SYSTEM_OR_GPU_FAULT)
    if facts.dispatched and not facts.outcome_recorded:
        found.append(AMBIGUOUS_DISPATCH)
    if facts.stop_requested:
        found.append(RESOURCE_ABORT_REQUESTED)
    if facts.loader_failed:
        found.append(LOADER_FAILED)
    if facts.dispatched and (
        not facts.telemetry_complete or facts.fault_status == UNKNOWN_COVERAGE_GAP
    ):
        found.append(INSTRUMENTATION_GAP)
    if facts.dispatched and facts.output_valid is False:
        found.append(OUTPUT_VALIDATION_FAIL)
    if not found:
        return None, ()
    return found[0], tuple(found[1:])


# ------------------------------------------------------------------------------------------------- bundle spec

REQUIRED_EVIDENCE_ITEMS = (
    "manifest",
    "manifest_sha256",
    "sample_stream",
    "event_stream",
    "fault_baseline_before",
    "fault_baseline_after",
    "boot_identity",
    "timezone",
    "process_ownership",
    "environment_snapshot",
    "log_and_source_hashes",
    "coverage_gaps",
    "ledger",
)


def evidence_gaps(bundle: Mapping[str, Any]) -> list[Finding]:
    return [
        Finding(
            "EVIDENCE_ITEM_MISSING", "inconclusive", f"required evidence item {item!r} is absent"
        )
        for item in REQUIRED_EVIDENCE_ITEMS
        if bundle.get(item) in (None, "", [], {})
    ]


def hash_files(paths: Iterable[Path | str], *, chunk: int = 1 << 20) -> dict[str, str]:
    """SHA-256 of small log/source files (never model weights); an unreadable file is recorded as ``unreadable``."""

    result: dict[str, str] = {}
    for item in paths:
        path = Path(item)
        try:
            hasher = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(chunk), b""):
                    hasher.update(block)
            result[path.name] = hasher.hexdigest()
        except OSError:
            result[path.name] = "unreadable"
    return result


def manifest_record(manifest_dict: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "kind": "manifest",
        "manifest": dict(manifest_dict),
        "manifest_sha256": digest(dict(manifest_dict)),
    }


def coverage_summary(snapshot: FaultSnapshot | None) -> dict[str, str]:
    return (
        snapshot.coverage() if snapshot is not None else dict.fromkeys(FAULT_SOURCES, NOT_COLLECTED)
    )


def sequence_gaps(sequence_numbers: Sequence[int]) -> list[tuple[int, int]]:
    """Missing ``seq`` ranges in a (possibly rotated) stream, as inclusive ``(first, last)`` pairs."""

    gaps: list[tuple[int, int]] = []
    ordered = sorted(sequence_numbers)
    for previous, current in zip(ordered, ordered[1:], strict=False):
        if current - previous > 1:
            gaps.append((previous + 1, current - 1))
    return gaps
