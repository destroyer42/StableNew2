"""ETW trace conversion and event parsing for the operator-run qualification capture (PR-AI-QUAL-113B, rebuilt in 114E).

The capture itself is started and stopped by the operator from an Administrator terminal (``capture_control.py``); this
module is the standard-user half that turns a stopped capture's ``.etl`` files into events. It never starts or stops a
trace session.

* ``tracerpt`` converts one ETL to XML plus a summary. Every conversion must report zero lost events, buffers and format
  errors, a processed-event count above zero, and that count must equal the number of events read from the XML; any shortfall
  raises, and the caller treats the capture as unusable (never as "no events").
* Events keep their trace timestamp (``TimeCreated``, converted to nanoseconds since the Unix epoch) so that one long capture
  window can be attributed to many bounded requests by process identity *and* time (``capture_analysis.py``). An event with
  no readable timestamp keeps ``ts_ns=None``; it is never given a guessed time.
* The parsers keep events of the pids they are given and return them in a form the ownership layer can attribute
  (``ChannelEvent``). They make no claim about which pids belong to which request.

Residual limits (documented, not hidden): a name lookup is performed by the DNS client service, so Kernel-Network attributes
it to that service; the DNS-Client provider is enabled for it but the canary does not exercise it. A plain open is classed as
a read, so a truncate or memory-mapped write of an existing file opened for read is not seen (see ``file_events``). Only members
of the owned job are attributed, so a process Windows starts outside the job is not (see ``OwnedTreeEvidence``).
"""

from __future__ import annotations

import ctypes
import os
import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree

from tools.qualification.ai111.capture_control import system_tool
from tools.qualification.ai111.ownership import ChannelEvent
from tools.qualification.ai111.tool_runner import bounded_tool


class EtwError(RuntimeError):
    """The trace could not be converted or proven free of loss."""


Run = Callable[[Sequence[str]], tuple[int, str]]


#: ``tracerpt`` seconds budgeted per MB of ETL on top of the base timeout, so a large capture is converted, not abandoned.
CONVERT_SECONDS_PER_MB = 2.0
CONVERT_BASE_SECONDS = 60.0


def conversion_timeout(etl: Path) -> float:
    try:
        megabytes = etl.stat().st_size / (1024 * 1024)
    except OSError:
        megabytes = 0.0
    return CONVERT_BASE_SECONDS + CONVERT_SECONDS_PER_MB * megabytes


def convert_trace(etl: Path, xml: Path, summary: Path, run: Run | None = None) -> None:
    """``tracerpt`` one stopped ETL into XML and a summary. A stale output is removed first, never read as this run's."""

    for stale in (xml, summary):
        stale.unlink(missing_ok=True)
    if run is None:
        timeout = conversion_timeout(etl)

        def run(command: Sequence[str]) -> tuple[int, str]:
            return bounded_tool(command, timeout_seconds=timeout)

    code, text = run(
        [
            system_tool("tracerpt"),
            str(etl),
            "-o",
            str(xml),
            "-of",
            "XML",
            "-summary",
            str(summary),
            "-y",
        ]
    )
    if code != 0:
        raise EtwError(f"tracerpt failed ({code}): {' '.join(text.split())[:300]}")


# -- tracerpt XML parsing ------------------------------------------------------------------------------------------------

_LOST = re.compile(r"(?i)events\s+lost\D{0,12}(\d+)")
_BUFFERS_LOST = re.compile(r"(?i)buffers\s+lost\D{0,12}(\d+)")
_PROCESSED = re.compile(r"(?i)events\s+processed\D{0,12}(\d+)")
_FORMAT_ERRORS = re.compile(r"(?i)format\s+errors\D{0,12}(\d+)")


def check_no_loss(summary_text: str, parsed_events: int | None = None) -> None:
    """Fail closed unless the converted trace states that nothing was lost.

    With ``parsed_events`` the summary's processed-event count must also equal the number of events actually read from
    the XML, so a truncated or partially converted document cannot pass as a complete one."""

    events = _LOST.findall(summary_text)
    if not events:
        raise EtwError("trace loss accounting unavailable in the tracerpt summary")
    if any(int(n) for n in events) or any(int(n) for n in _BUFFERS_LOST.findall(summary_text)):
        raise EtwError("trace lost events or buffers; the capture is not complete")
    if any(int(n) for n in _FORMAT_ERRORS.findall(summary_text)):
        raise EtwError("trace reported format errors; the capture is not complete")
    if parsed_events is not None:
        processed = _PROCESSED.findall(summary_text)
        if not processed or int(processed[0]) <= 0:
            raise EtwError("the tracerpt summary reports no processed events")
        if int(processed[0]) != parsed_events:
            raise EtwError(
                f"tracerpt processed {processed[0]} events but the XML holds {parsed_events}"
            )


@dataclass(slots=True)
class RawEvent:
    provider: str
    event_id: int
    execution_pid: int | None
    data: dict[str, str] = field(default_factory=dict)
    #: ``TimeCreated`` as nanoseconds since the Unix epoch, or ``None`` when absent or unreadable.
    ts_ns: int | None = None
    guid: str = ""


_SYSTEM_TIME = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})$"
)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def parse_system_time(text: str | None) -> int | None:
    """tracerpt's ``SystemTime`` (an offset-aware local or UTC time) as epoch nanoseconds; ``None`` unless fully valid."""

    if not text:
        return None
    match = _SYSTEM_TIME.match(text.strip())
    if match is None:
        return None
    year, month, day, hour, minute, second = (int(match.group(i)) for i in range(1, 7))
    fraction = (match.group(7) or "").ljust(9, "0")
    zone = match.group(8)
    try:
        if zone == "Z":
            tz = UTC
        else:
            sign = 1 if zone[0] == "+" else -1
            offset = timedelta(hours=int(zone[1:3]), minutes=int(zone[4:6]))
            if offset >= timedelta(hours=24):
                return None
            tz = timezone(sign * offset)
        base = datetime(year, month, day, hour, minute, second, tzinfo=tz)
    except ValueError:
        return None
    return int((base - _EPOCH).total_seconds()) * 1_000_000_000 + int(fraction)


def _to_int(text: str | None) -> int | None:
    if text is None:
        return None
    text = text.strip()
    for base in (0, 10, 16):
        try:
            return int(text, base)
        except ValueError:
            continue
    return None


def iter_raw_events(xml: Path) -> Iterator[RawEvent]:
    """Stream ``<Event>`` elements from tracerpt XML; a document that is not event XML is an error."""

    seen_root = False
    root: ElementTree.Element | None = None
    try:
        for phase, element in ElementTree.iterparse(xml, events=("start", "end")):
            tag = element.tag.rpartition("}")[2]
            if phase == "start":
                if root is None:
                    root = element
                if tag == "Events":
                    seen_root = True
                continue
            if tag != "Event":
                continue
            system = next((c for c in element if c.tag.rpartition("}")[2] == "System"), None)
            if system is None:
                element.clear()
                continue
            provider = ""
            guid = ""
            event_id = -1
            pid: int | None = None
            ts_ns: int | None = None
            for child in system:
                name = child.tag.rpartition("}")[2]
                if name == "Provider":
                    provider = child.attrib.get("Name", "")
                    guid = child.attrib.get("Guid", "").strip("{}").lower()
                elif name == "TimeCreated":
                    ts_ns = parse_system_time(child.attrib.get("SystemTime"))
                elif name == "EventID":
                    parsed_id = _to_int(child.text)
                    event_id = -1 if parsed_id is None else parsed_id
                elif name == "Execution":
                    pid = _to_int(child.attrib.get("ProcessID"))
            data: dict[str, str] = {}
            for part in element:
                if part.tag.rpartition("}")[2] in ("EventData", "UserData"):
                    for item in part.iter():
                        label = item.attrib.get("Name") or item.tag.rpartition("}")[2]
                        if item.text is not None and label not in ("EventData", "UserData"):
                            data[label] = item.text.strip()
            yield RawEvent(provider, event_id, pid, data, ts_ns, guid)
            if root is not None:
                root.clear()  # drop the finished event from the tree so memory stays bounded on a large trace
    except ElementTree.ParseError as exc:
        raise EtwError(f"tracerpt output is not valid event XML: {exc}") from exc
    if not seen_root:
        raise EtwError("tracerpt output has no <Events> document")


def _counted(events: Iterator[RawEvent], counter: list[int]) -> Iterator[RawEvent]:
    for event in events:
        counter[0] += 1
        yield event


def _candidate_pids(event: RawEvent) -> set[int]:
    pids = {event.execution_pid} if event.execution_pid else set()
    for key in ("PID", "ProcessId", "ProcessID", "ProcessIdentifier"):
        value = _to_int(event.data.get(key))
        if value:
            pids.add(value)
    return pids


def _get(data: dict[str, str], *names: str) -> str | None:
    lowered = {k.lower(): v for k, v in data.items()}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def network_events(raw: Iterator[RawEvent], owned: frozenset[int]) -> list[ChannelEvent]:
    out: list[ChannelEvent] = []
    for event in raw:
        for pid in _candidate_pids(event) & owned:
            addr = _get(event.data, "daddr", "DestinationAddress", "RemoteAddress") or "?"
            port = _get(event.data, "dport", "DestinationPort", "RemotePort") or "?"
            out.append(ChannelEvent(pid, f"{addr}:{port}", event.ts_ns, "unknown"))
    return out


def dns_events(raw: Iterator[RawEvent], owned: frozenset[int]) -> list[ChannelEvent]:
    out: list[ChannelEvent] = []
    for event in raw:
        for pid in _candidate_pids(event) & owned:
            name = _get(event.data, "QueryName", "Name") or f"event{event.event_id}"
            out.append(ChannelEvent(pid, f"dns:{name}", event.ts_ns, "unknown"))
    return out


# Microsoft-Windows-Kernel-File event ids (manifest): see the module docstring for the verification status.
_CREATE_IDS = {12, 30}
_WRITE_IDS = {16}
_PATH_WRITE_IDS = {17, 18, 19, 26, 27, 28, 29}
_BENIGN_IDS = {10, 11, 13, 14, 15, 20, 21, 22, 23, 24, 25}
_CREATING_DISPOSITIONS = {
    0,
    2,
    4,
    5,
    3,
}  # SUPERSEDE, CREATE, OVERWRITE, OVERWRITE_IF, OPEN_IF (may create)
_FILE_DELETE_ON_CLOSE = 0x1000


def file_events(
    raw: Iterator[RawEvent], owned: frozenset[int], to_dos: Callable[[str], str]
) -> list[ChannelEvent]:
    """Turn Kernel-File events of owned pids into opens/writes.

    A create opens a file object; the intent is a write if the create disposition may create or replace it, if the
    options delete it on close, or if a write event is later seen on that file object; otherwise it is a read.
    Delete, rename and link events are writes. Nothing an owned process did is dropped for lack of a usable field: an
    event of a known access kind whose file name cannot be resolved, or of an unrecognised kind, is reported with mode
    ``unknown`` (the policy treats that as a write) under a placeholder path that no policy root contains.

    Known limits, stated rather than hidden: a plain open is classed as a read, so ``FILE_OPEN`` of an existing file
    followed by a truncate or a memory-mapped write is not seen as a write (those need keyword 0x20 and event 17, which are
    not enabled); and a write on a file object whose create was never seen (a handle inherited from the runner, such as a
    stdio pipe) is not attributed to any path."""

    # file object -> (pid, path, mode, timestamp of the create)
    objects: dict[str, tuple[int, str, str, int | None]] = {}
    out: list[ChannelEvent] = []
    unresolved: set[tuple[int, int, int | None]] = set()

    def note_unresolved(pid: int, event_id: int, ts_ns: int | None) -> None:
        # Only an exact repeat (same process, kind and instant) is collapsed. This runs before attribution, so a coarser key
        # would let an event of a recycled pid number swallow an owned process's event in the same second and the owned one
        # would then be dropped with it.
        key = (pid, event_id, ts_ns)
        if key not in unresolved:
            unresolved.add(key)
            out.append(
                ChannelEvent(pid, f"<unresolved kernel-file event {event_id}>", ts_ns, "unknown")
            )

    for event in raw:
        pids = _candidate_pids(event) & owned
        if not pids:
            continue
        pid = min(pids)
        ts = event.ts_ns
        name = _get(event.data, "FileName", "OpenPath", "FilePath")
        new_name = _get(event.data, "NewFileName", "ExistingFileName")
        file_object = _get(event.data, "FileObject", "FileKey")
        if event.event_id in _CREATE_IDS:
            if not name:
                note_unresolved(pid, event.event_id, ts)
                continue
            options = _to_int(_get(event.data, "CreateOptions")) or 0
            disposition = (options >> 24) & 0xFF
            mode = (
                "write"
                if disposition in _CREATING_DISPOSITIONS or options & _FILE_DELETE_ON_CLOSE
                else "read"
            )
            path = to_dos(name)
            if file_object:
                earlier = objects.get(file_object)
                if (
                    earlier is not None
                ):  # the file object was reused: the earlier access still happened
                    out.append(ChannelEvent(earlier[0], earlier[1], earlier[3], earlier[2]))
                objects[file_object] = (pid, path, mode, ts)
            else:
                out.append(ChannelEvent(pid, path, ts, mode))
        elif event.event_id in _WRITE_IDS:
            if file_object and file_object in objects:
                known_pid, path, _, created = objects[file_object]
                objects[file_object] = (known_pid, path, "write", created)
            elif name:
                out.append(ChannelEvent(pid, to_dos(name), ts, "write"))
        elif event.event_id in _PATH_WRITE_IDS:
            paths = [text for text in (name, new_name) if text]
            if not paths:
                note_unresolved(pid, event.event_id, ts)
            out.extend(ChannelEvent(pid, to_dos(text), ts, "write") for text in paths)
        elif event.event_id in _BENIGN_IDS:
            continue
        elif name:
            out.append(ChannelEvent(pid, to_dos(name), ts, "unknown"))
        else:
            note_unresolved(pid, event.event_id, ts)
    out.extend(ChannelEvent(pid, path, ts, mode) for pid, path, mode, ts in objects.values())
    return out


# -- NT path to DOS path -----------------------------------------------------------------------------------------------


def device_map() -> dict[str, str]:
    """``\\Device\\HarddiskVolumeN`` -> ``C:`` for every mounted drive letter (empty off Windows)."""

    if os.name != "nt":
        return {}
    mapping: dict[str, str] = {}
    buffer = ctypes.create_unicode_buffer(1024)
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        drive = f"{letter}:"
        if kernel32.QueryDosDeviceW(drive, buffer, len(buffer)):
            mapping[buffer.value.lower()] = drive
    return mapping


def make_to_dos(mapping: dict[str, str]) -> Callable[[str], str]:
    ordered = sorted(mapping.items(), key=lambda item: len(item[0]), reverse=True)

    def to_dos(path: str) -> str:
        text = path.replace("/", "\\")
        if text.startswith("\\??\\"):
            text = text[4:]
        lowered = text.lower()
        if lowered.startswith("\\device\\mup\\"):
            return "\\\\" + text[len("\\device\\mup\\") :]
        for device, drive in ordered:
            if lowered == device or lowered.startswith(device + "\\"):
                return drive + text[len(device) :]
        return text

    return to_dos
