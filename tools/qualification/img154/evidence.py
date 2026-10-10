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
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from .core import MIB, Finding, canonical_json, digest, valid_time, valid_utc
from .manifest import QualificationManifest

EVIDENCE_SCHEMA = "stablenew.img154.evidence.v1"

# ----------------------------------------------------------------------------------------------------- redaction

_USER_PATH = re.compile(r"(?i)(?:[A-Z]:)?[\\/]+(?:Users|home)[\\/]+[^\"'\r\n<>|;,]+")
_SERIAL_PAIR = re.compile(
    r"(?i)\b(serial(?:number|_number)?|uuid|guid|machineguid|hwid)\b(\s*[=:]\s*)\S+"
)
_MAC = re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b")
_PROMPT_KEYS = frozenset({"prompt", "negative_prompt"})
_SECRET_KEY = re.compile(
    r"(?i)(?:^|_)(serial(?:number|_number)?|uuid|guid|machineguid|hwid|machine_?id|username|user_?name|password|token|secret)(?:$|_)"
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

    def append_exclusive(self, record: Mapping[str, Any]) -> int:
        """Create the stream with its first record, atomically: ``FileExistsError`` when another caller created it first.

        ``O_EXCL`` creation is the supported cross-process claim mechanism (``CreateFile(CREATE_NEW)`` on Windows): exactly one
        caller can ever create a given path, whatever the working directory, process or workspace that caller came from.
        """

        line = self._line(record)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        try:
            descriptor = os.open(self.path, flags, 0o600)
        except OSError:
            self._seq -= 1
            raise
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(line)
            stream.flush()
            self._sync(stream.fileno())
        return self._seq

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
    if not valid_utc(before.taken_utc) or not valid_utc(after.taken_utc):
        gaps.append("snapshot_timestamp_invalid")
    elif datetime.fromisoformat(after.taken_utc) < datetime.fromisoformat(before.taken_utc):
        gaps.append("snapshot_time_reversed")
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
        elif old.coverage == now.coverage == COMPLETE and not old.record_ids <= now.record_ids:
            gaps.append(f"{name}:records_disappeared")
        added = tuple(sorted(now.record_ids - old.record_ids))
        if added:
            new[name] = added
    if not valid_time(seconds_after_run) or seconds_after_run < FAULT_SETTLE_S:
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
        if (
            torn
            or corrupt
            or not records
            or any(
                record.get("schema") != EVIDENCE_SCHEMA or record.get("seq") != index
                for index, record in enumerate(records, start=1)
            )
        ):
            # A file that exists but holds no complete record is a claimed-and-interrupted ledger, never a clean one.
            raise OSError(
                "ledger is torn, corrupt, empty or discontinuous; ambiguous, not repaired"
            )
        return records

    def append(self, record: dict[str, Any]) -> None:
        self._writer.append(record)


#: Lifecycle stages of ONE claimed case (PR-IMG-MODELS-154B), in the only order they may be recorded. ``claimed`` is the
#: ``attempt`` record itself; ``terminal_evidence`` may follow any open stage because a case can end anywhere. Every
#: ``*_attempted`` record and ``generation_dispatched`` is written BEFORE the action it announces.
LEDGER_STAGES = (
    "claimed",
    "managed_start_attempted",
    "startup_observed",
    "selection_attempted",
    "selection_confirmed",
    "generation_dispatched",
    "terminal_evidence",
)


def stage_order_ok(history: Sequence[str], stage: str) -> bool:
    """``stage`` may follow ``history`` (which starts at ``claimed``): the next stage, or ``terminal_evidence``."""

    if stage not in LEDGER_STAGES[1:] or not history or history[0] != "claimed":
        return False
    if history[-1] == "terminal_evidence":
        return False
    if stage == "terminal_evidence":
        return True
    return len(history) < len(LEDGER_STAGES) - 1 and LEDGER_STAGES[len(history)] == stage


class DispatchLedger:
    """Records the INTENT to attempt before anything is sent, so an interrupted attempt stays ambiguous and is never replayed.

    Attempts are claimed with the store's atomic ``claim`` when it has one (a per-case exclusive-create store does), so two
    processes can never both record an attempt there; a plain ``FileLedgerStore`` keeps the 154A check-then-append and still
    needs the single-instance lock. PR-154B adds ordered lifecycle ``stage`` records between the attempt and its outcome.
    """

    def __init__(self, store: LedgerStore) -> None:
        self._store = store

    def state(self, manifest: QualificationManifest) -> str:
        """State for the stable owner case; malformed/legacy history fails closed."""
        try:
            identity = manifest.attempt_identity()
            history = self._store.read()
            attempts: dict[str, dict[str, Any]] = {}
            outcomes: set[str] = set()
            stages: dict[str, list[str]] = {}
            for record in history:
                key = record["attempt_identity"]
                if record["kind"] == "attempt":
                    frozen = record["manifest"]
                    if (
                        key in attempts
                        or not isinstance(frozen, dict)
                        or key
                        != digest(
                            {
                                "namespace": "stablenew.img154.attempt.v1",
                                "case_id": frozen["case_id"],
                            }
                        )
                        or frozen["attempt_identity"] != key
                        or digest(frozen) != record["manifest_digest"]
                        or digest(frozen["intent"]) != record["request_digest"]
                    ):
                        return "unknown"
                    attempts[key] = record
                    stages[key] = ["claimed"]
                elif record["kind"] == "stage":
                    if (
                        key not in attempts
                        or key in outcomes
                        or record["manifest_digest"] != attempts[key]["manifest_digest"]
                        or not isinstance(record["stage"], str)
                        or not isinstance(record.get("facts", {}), dict)
                        or not stage_order_ok(stages[key], record["stage"])
                    ):
                        return "unknown"
                    stages[key].append(record["stage"])
                elif record["kind"] == "outcome":
                    if (
                        key not in attempts
                        or key in outcomes
                        or not isinstance(record["outcome"], str)
                    ):
                        return "unknown"
                    if record["manifest_digest"] != attempts[key]["manifest_digest"]:
                        return "unknown"
                    outcomes.add(key)
                else:
                    return "unknown"
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            return "unknown"
        if identity not in attempts:
            return "none"
        return "completed" if identity in outcomes else "ambiguous"

    def preflight_state(self, manifest: QualificationManifest) -> str:
        state = self.state(manifest)
        return {"none": "none", "ambiguous": "ambiguous", "completed": "dispatched"}.get(
            state, "unknown"
        )

    def stage_history(self, manifest: QualificationManifest) -> tuple[str, ...] | None:
        """Recorded stages of the case (``claimed`` first), ``()`` before any attempt, ``None`` when the ledger is unknown."""

        if self.state(manifest) == "unknown":
            return None
        identity = manifest.attempt_identity()
        history: list[str] = []
        for record in self._store.read():
            if record.get("attempt_identity") != identity:
                continue
            if record.get("kind") == "attempt":
                history.append("claimed")
            elif record.get("kind") == "stage":
                history.append(str(record.get("stage")))
        return tuple(history)

    def record_stage(
        self, manifest: QualificationManifest, stage: str, facts: Mapping[str, Any] | None = None
    ) -> None:
        """Append the next lifecycle stage of the open attempt; an out-of-order, repeated or unverifiable stage is refused."""

        if self.state(manifest) != "ambiguous":
            raise LedgerRefusal("a stage can only extend a recorded, unresolved attempt")
        history = self.stage_history(manifest) or ()
        if not stage_order_ok(history, stage):
            raise LedgerRefusal(f"stage {stage!r} is not the next stage after {history[-1:]!r}")
        try:
            self._store.append(
                {
                    "kind": "stage",
                    "attempt_identity": manifest.attempt_identity(),
                    "manifest_digest": manifest.digest(),
                    "stage": stage,
                    "facts": dict(facts or {}),
                }
            )
        except (OSError, TypeError, ValueError) as exc:
            raise LedgerRefusal(
                f"stage record could not be made durable ({type(exc).__name__})"
            ) from exc

    def record_attempt(
        self, manifest: QualificationManifest, *, claimant: Mapping[str, Any] | None = None
    ) -> None:
        state = self.state(manifest)
        if state != "none":
            raise LedgerRefusal(
                f"attempt refused: ledger state is {state!r}; there is no retry or replay"
            )
        record: dict[str, Any] = {
            "kind": "attempt",
            "attempt_identity": manifest.attempt_identity(),
            "manifest_digest": manifest.digest(),
            "request_digest": manifest.request_digest(),
            "manifest": manifest.as_dict(),
        }
        if claimant is not None:
            record["claimant"] = dict(claimant)
        claim = getattr(self._store, "claim", None)
        try:
            (claim or self._store.append)(record)
        except FileExistsError as exc:
            raise LedgerRefusal("attempt refused: another process claimed this case first") from exc

    def record_outcome(self, manifest: QualificationManifest, outcome: str) -> None:
        if self.state(manifest) != "ambiguous":
            raise LedgerRefusal("an outcome can only close a recorded, unresolved attempt")
        if not isinstance(outcome, str) or not outcome:
            raise LedgerRefusal("an outcome must be stated")
        attempt = next(
            r
            for r in self._store.read()
            if r["kind"] == "attempt" and r["attempt_identity"] == manifest.attempt_identity()
        )
        self._store.append(
            {
                "kind": "outcome",
                "attempt_identity": manifest.attempt_identity(),
                "manifest_digest": attempt["manifest_digest"],
                "outcome": outcome,
            }
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
