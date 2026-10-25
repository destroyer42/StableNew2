"""PR-AI-QUAL-113B: ETW-backed connection and file-access providers for the ownership monitor.

A Windows process that holds the OS's delegated trace-control right (membership of the ``Performance Log Users`` group,
granted once by an administrator) can ask the kernel to log every file open/write/delete/rename
(``Microsoft-Windows-Kernel-File``), every TCP/UDP network event (``Microsoft-Windows-Kernel-Network``) and every DNS
client query (``Microsoft-Windows-DNS-Client``) for the whole time a request runs. That is the only unprivileged-process-
independent source of connection *attempts* and file *opens*; it is what makes these two channels ``lifetime_complete``.

How it is used here, and what it deliberately is not:

* The built-in ``logman`` and ``tracerpt`` tools do the tracing and the conversion. Sessions are started with ``-ets``
  (no persistent collector is registered, nothing is written to the system configuration), have a unique
  ``StableNewAi113-`` name, are stopped after every request, are swept if a previous run leaked one, and are stopped at
  interpreter exit. Both tools run through the bounded runner.
* The trace is system-wide but each request has its own window: the sessions start before the child is launched and stop
  after teardown is verified. Events are kept only for pids the owned container reported, so attribution is by owned pid
  inside the request window (timestamps are not used; an owned pid reused by a foreign process in that window can only
  cause a false violation, never a missed one).
* PRIVILEGE BOUNDARY (PR-AI-QUAL-114): the harness, the runtime import and every downloaded binary run under a
  standard-user token. No privileged process exists: the trace sessions are created by the harness itself under the
  delegated trace-control right, and the monitor refuses an elevated harness and stops a child whose token reads as elevated
  (``ownership.py``). If the OS refuses to start a session, the provider raises and nothing is launched.
* A provider *declares* ``lifetime_complete`` when the process holds that right on Windows; that declaration is a claim, not
  a check. What backs it is per window: every converted trace must report zero lost events, buffers and format errors, a
  processed-event count above zero, and that count must equal the number of events read from the XML. Any shortfall
  raises, which the monitor records as a provider failure and a violation. Because the sessions are system-wide and the
  events are filtered to owned pids, ``events_not_attributed_to_the_owned_tree`` is always 0 for this provider.
* It proves nothing the canary has not shown: the monitor still has to see a known file read, a created, written, renamed
  and deleted file, and a known connection attempt of its own canary child through these sessions before a physical session
  is allowed.

Residual limits (documented, not hidden): a name lookup is performed by the DNS client service, so Kernel-Network
attributes it to that service; the DNS-Client provider is enabled for it but the canary does not exercise it. A plain open
is classed as a read, so a truncate or memory-mapped write of an existing file opened for read is not seen (see
``file_events``). Only members
of the owned job are attributed, so a process Windows starts outside the job is not (see ``OwnedTreeEvidence``).
"""

from __future__ import annotations

import atexit
import ctypes
import os
import re
import uuid
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from src.utils.managed_process import ProcessOutcome, run_bounded
from tools.qualification.ai111 import tokens
from tools.qualification.ai111.ownership import (
    COMPLETE,
    UNAVAILABLE,
    ChannelEvent,
    OwnedSessionMonitor,
    OwnershipPolicy,
)

SESSION_PREFIX = "StableNewAi113-"
_TOOL_TIMEOUT_SECONDS = 120.0
_TOOL_OUTPUT_BYTES = 1024 * 1024


class EtwError(RuntimeError):
    """The trace could not be started, stopped, converted or proven free of loss."""


@dataclass(frozen=True, slots=True)
class SessionSpec:
    kind: str  # "network" | "file" | "dns"
    provider: str
    keywords: int
    level: int = 0x05


# Keyword values read from ``logman query providers`` on the target host (2026-10-24).
NETWORK = SessionSpec("network", "Microsoft-Windows-Kernel-Network", 0x10 | 0x20, 0x04)
FILE = SessionSpec(
    "file",
    "Microsoft-Windows-Kernel-File",
    0x10
    | 0x80
    | 0x200
    | 0x400
    | 0x800
    | 0x1000,  # FILENAME CREATE WRITE DELETE_PATH RENAME_SETLINK CREATE_NEW_FILE
    0x04,
)
DNS = SessionSpec("dns", "Microsoft-Windows-DNS-Client", 0xFFFFFFFFFFFFFFFF, 0x05)
SESSIONS = (NETWORK, FILE, DNS)
_CHANNELS = 2  # the connection and file providers share one capture window

Run = Callable[[Sequence[str]], tuple[int, str]]


def is_elevated() -> bool:
    if os.name != "nt":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return False


def can_control_traces() -> bool:
    """Whether this process may create and control trace sessions: the delegated right, or (for tooling only) elevation.

    A physical session additionally refuses an elevated harness (the monitor's privilege boundary), so in practice this
    means ``Performance Log Users`` membership in an unelevated token."""

    return os.name == "nt" and (tokens.in_performance_log_users() or is_elevated())


def bounded_tool(command: Sequence[str]) -> tuple[int, str]:
    """Run a short OS tool (logman/tracerpt) through the bounded runner."""

    outcome: ProcessOutcome = run_bounded(
        command, timeout_seconds=_TOOL_TIMEOUT_SECONDS, max_stdout_bytes=_TOOL_OUTPUT_BYTES
    )
    if outcome.launch_error:
        raise EtwError(f"{command[0]}: {outcome.launch_error}")
    text = (outcome.stdout + outcome.stderr).decode("utf-8", "replace")
    if outcome.timed_out:
        raise EtwError(f"{command[0]} timed out")
    return int(outcome.returncode or 0), text


# -- logman / tracerpt command layer ------------------------------------------------------------------------------------


def system_tool(name: str) -> str:
    """Absolute path of an OS tool, so an elevated process never resolves ``logman``/``tracerpt`` through PATH or cwd."""

    root = os.environ.get("SystemRoot") or "C:\\Windows"
    return str(Path(root) / "System32" / f"{name}.exe")


class LogmanBackend:
    """Starts, stops and converts ETW sessions with the OS tools. ``run`` is injectable so commands can be tested."""

    def __init__(self, run: Run = bounded_tool) -> None:
        self._run = run
        self._logman = system_tool("logman")
        self._tracerpt = system_tool("tracerpt")

    def available(self) -> bool:
        return can_control_traces()

    def _ok(self, command: Sequence[str]) -> str:
        code, text = self._run(command)
        if code != 0:
            raise EtwError(
                f"{command[0]} {command[1] if len(command) > 1 else ''} failed ({code}): {text.strip()[:300]}"
            )
        return text

    def start(self, name: str, spec: SessionSpec, etl: Path) -> None:
        self._ok(
            [
                self._logman,
                "start",
                name,
                "-p",
                spec.provider,
                hex(spec.keywords),
                hex(spec.level),
                "-ct",
                "perf",
                "-bs",
                "1024",
                "-nb",
                "32",
                "128",
                "-o",
                str(etl),
                "-ets",
            ]
        )

    def stop(self, name: str) -> None:
        self._ok([self._logman, "stop", name, "-ets"])

    def live_sessions(self) -> list[str]:
        code, text = self._run([self._logman, "query", "-ets"])
        if code != 0:
            raise EtwError(f"logman query failed ({code})")
        return [m.group(1) for line in text.splitlines() if (m := _SESSION_LINE.match(line))]

    def convert(self, etl: Path, xml: Path, summary: Path) -> None:
        for stale in (xml, summary):
            stale.unlink(
                missing_ok=True
            )  # a leftover from an earlier run must never be mistaken for this output
        self._ok(
            [
                self._tracerpt,
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


# -- tracerpt XML parsing ------------------------------------------------------------------------------------------------

_SESSION_LINE = re.compile(r"^\s*(" + re.escape(SESSION_PREFIX) + r"[0-9a-f]{12})\b")
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
            event_id = -1
            pid: int | None = None
            for child in system:
                name = child.tag.rpartition("}")[2]
                if name == "Provider":
                    provider = child.attrib.get("Name", "")
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
            yield RawEvent(provider, event_id, pid, data)
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
            out.append(ChannelEvent(pid, f"{addr}:{port}", None, "unknown"))
    return out


def dns_events(raw: Iterator[RawEvent], owned: frozenset[int]) -> list[ChannelEvent]:
    out: list[ChannelEvent] = []
    for event in raw:
        for pid in _candidate_pids(event) & owned:
            name = _get(event.data, "QueryName", "Name") or f"event{event.event_id}"
            out.append(ChannelEvent(pid, f"dns:{name}", None, "unknown"))
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

    objects: dict[str, tuple[int, str, str]] = {}  # file object -> (pid, path, mode)
    out: list[ChannelEvent] = []
    unresolved: set[tuple[int, int]] = set()

    def note_unresolved(pid: int, event_id: int) -> None:
        if (pid, event_id) not in unresolved:
            unresolved.add((pid, event_id))
            out.append(
                ChannelEvent(pid, f"<unresolved kernel-file event {event_id}>", None, "unknown")
            )

    for event in raw:
        pids = _candidate_pids(event) & owned
        if not pids:
            continue
        pid = min(pids)
        name = _get(event.data, "FileName", "OpenPath", "FilePath")
        new_name = _get(event.data, "NewFileName", "ExistingFileName")
        file_object = _get(event.data, "FileObject", "FileKey")
        if event.event_id in _CREATE_IDS:
            if not name:
                note_unresolved(pid, event.event_id)
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
                    out.append(ChannelEvent(earlier[0], earlier[1], None, earlier[2]))
                objects[file_object] = (pid, path, mode)
            else:
                out.append(ChannelEvent(pid, path, None, mode))
        elif event.event_id in _WRITE_IDS:
            if file_object and file_object in objects:
                known_pid, path, _ = objects[file_object]
                objects[file_object] = (known_pid, path, "write")
            elif name:
                out.append(ChannelEvent(pid, to_dos(name), None, "write"))
        elif event.event_id in _PATH_WRITE_IDS:
            paths = [text for text in (name, new_name) if text]
            if not paths:
                note_unresolved(pid, event.event_id)
            out.extend(ChannelEvent(pid, to_dos(text), None, "write") for text in paths)
        elif event.event_id in _BENIGN_IDS:
            continue
        elif name:
            out.append(ChannelEvent(pid, to_dos(name), None, "unknown"))
        else:
            note_unresolved(pid, event.event_id)
    out.extend(ChannelEvent(pid, path, None, mode) for pid, path, mode in objects.values())
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


# -- the capture shared by both channel providers ----------------------------------------------------------------------


class EtwCapture:
    """One trace window per request: start before launch, stop and convert after teardown, hand out per-channel events."""

    def __init__(
        self,
        directory: Path,
        backend: LogmanBackend | None = None,
        *,
        specs: Sequence[SessionSpec] = SESSIONS,
        mapping: Callable[[], dict[str, str]] = device_map,
        elevated: Callable[[], bool] = can_control_traces,
    ) -> None:
        self.directory = directory
        self._backend = backend or LogmanBackend()
        self._specs = tuple(specs)
        self._mapping = mapping
        self._elevated = elevated
        self._active: dict[str, tuple[SessionSpec, str, Path]] = {}
        self._results: dict[str, list[ChannelEvent]] | None = None
        self._pending_channels: set[str] = set()
        self._joined = 0
        self._window = 0
        self._swept = False
        atexit.register(self.abort)

    def available(self) -> bool:
        return os.name == "nt" and self._elevated()

    # -- lifecycle -----------------------------------------------------------------------------------------------

    def begin(self) -> None:
        if self._active:
            if self._results is None and self._joined < _CHANNELS:
                self._joined += 1  # the other channel's provider joining the window just opened
                return
            self.abort()  # a window that was never collected (its request failed before the end)
        if not self.available():
            raise EtwError(
                "ETW capture needs trace-control rights (Performance Log Users membership; a physical session "
                "refuses an elevated process)"
            )
        self.directory = self.directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        if not self._swept:
            for leaked in self._backend.live_sessions():
                self._backend.stop(leaked)
            self._swept = True
        self._window += 1
        self._results = None
        started: dict[str, tuple[SessionSpec, str, Path]] = {}
        try:
            for spec in self._specs:
                name = f"{SESSION_PREFIX}{uuid.uuid4().hex[:12]}"
                etl = self.directory / f"window-{self._window:05d}-{spec.kind}.etl"
                started[spec.kind] = (
                    spec,
                    name,
                    etl,
                )  # recorded first: a start that fails half-way is still rolled back
                self._backend.start(name, spec, etl)
        except BaseException:
            for _spec, name, _etl in started.values():
                try:
                    self._backend.stop(name)
                except EtwError:
                    pass
            raise
        self._active = started
        self._joined = 1
        self._pending_channels = {"connections", "files"}

    def leaked_sessions(self) -> list[str]:
        """Trace sessions of this tool still live in the OS (after ``close``: none may remain). Raises if unreadable."""

        return self._backend.live_sessions()

    def abort(self) -> None:
        for _spec, name, _etl in list(self._active.values()):
            try:
                self._backend.stop(name)
            except Exception:  # noqa: BLE001 - best effort, the next start sweeps by prefix
                pass
        self._active = {}
        self._results = None
        self._pending_channels = set()
        self._joined = 0

    close = abort

    def collect(self, channel: str, owned: frozenset[int]) -> list[ChannelEvent]:
        if self._results is None:
            if not self._active:
                raise EtwError("no trace window is open")
            self._results = self._stop_and_parse(owned)
        events = self._results.get(channel, [])
        self._pending_channels.discard(channel)
        if not self._pending_channels:
            self._active = {}
            self._results = None
            self._joined = 0
        return events

    def _stop_and_parse(self, owned: frozenset[int]) -> dict[str, list[ChannelEvent]]:
        errors: list[str] = []
        for _spec, name, _etl in self._active.values():
            try:
                self._backend.stop(name)
            except EtwError as exc:
                errors.append(str(exc))
        if errors:
            raise EtwError("; ".join(errors))
        to_dos = make_to_dos(self._mapping())
        parsed: dict[str, list[ChannelEvent]] = {"connections": [], "files": []}
        for kind, (_spec, _name, etl) in self._active.items():
            xml, summary = etl.with_suffix(".xml"), etl.with_suffix(".summary.txt")
            self._backend.convert(etl, xml, summary)
            summary_text = summary.read_text(encoding="utf-8", errors="replace")
            check_no_loss(summary_text)
            seen = [0]
            stream = _counted(iter_raw_events(xml), seen)
            if kind == "network":
                parsed["connections"] += network_events(stream, owned)
            elif kind == "dns":
                parsed["connections"] += dns_events(stream, owned)
            else:
                parsed["files"] += file_events(stream, owned, to_dos)
            for _unread in stream:  # the XML is only complete if every event it holds was read
                pass
            check_no_loss(summary_text, seen[0])
        return parsed


class EtwChannelProvider:
    """One monitor channel backed by the shared capture. Coverage is complete only where the capture can run."""

    def __init__(self, capture: EtwCapture, channel: str) -> None:
        self._capture = capture
        self.channel = channel

    @property
    def coverage(self) -> str:
        return COMPLETE if self._capture.available() else UNAVAILABLE

    def begin(self) -> None:
        self._capture.begin()

    def poll(self, owned_pids: frozenset[int]) -> None:
        return None

    def end(self, owned_pids: frozenset[int]) -> list[ChannelEvent]:
        return self._capture.collect(self.channel, owned_pids)

    def bind_directory(self, directory: Path) -> None:
        self._capture.directory = directory / "etw"

    def close(self) -> None:
        self._capture.abort()

    def leaked(self) -> list[str]:
        return self._capture.leaked_sessions()


def etw_host_monitor(
    policy: OwnershipPolicy,
    evidence_dir: Path,
    *,
    capture: EtwCapture | None = None,
    canary_script: str | None = None,
    forbid_elevation: bool = True,
    self_elevated: Callable[[], bool | None] = tokens.current_process_elevated,
    token_probe: Callable[[int], bool | None] = tokens.process_token_elevated,
) -> OwnedSessionMonitor:
    """The monitor a physical session needs: lifetime-complete connection and file channels, canary-proven.

    Ready only from an unelevated Windows process that holds the trace-control right; otherwise both providers report
    ``unavailable`` (or the privilege check refuses) and every session refuses before creating anything."""

    capture = capture or EtwCapture(evidence_dir / "etw")
    return OwnedSessionMonitor(
        policy,
        [EtwChannelProvider(capture, "connections"), EtwChannelProvider(capture, "files")],
        kind="host",
        evidence_dir=evidence_dir,
        canary_script=canary_script,
        forbid_elevation=forbid_elevation,
        self_elevated=self_elevated,
        token_probe=token_probe,
    )


def main(argv: list[str] | None = None) -> int:
    """Standard-user canary: prove the ETW providers see this monitor's known events. Runs no model and no downloaded file."""

    import argparse
    import json

    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if tokens.current_process_elevated() is not False:
        print(
            "This process is elevated or its token is unreadable. Run from an ordinary (non-Administrator) terminal; "
            "nothing was started.",
            flush=True,
        )
        return 2
    if not can_control_traces():
        print(
            "This account cannot control trace sessions (not in 'Performance Log Users'); nothing was started.",
            flush=True,
        )
        return 2
    args.evidence_dir.mkdir(parents=True, exist_ok=False)
    monitor = etw_host_monitor(OwnershipPolicy(), args.evidence_dir)
    try:
        report = monitor.run_canary()
        problems = monitor.readiness()
    finally:
        monitor.close()
    leaked = LogmanBackend().live_sessions()
    if leaked:
        problems = [*problems, f"trace sessions left running: {leaked}"]
    summary: dict[str, Any] = {
        "canary": report,
        "problems": problems,
        "harness_elevated": tokens.current_process_elevated(),
        "performance_log_users": tokens.in_performance_log_users(),
        "trace_sessions_left_running": leaked,
        "provider_errors": {
            channel: message
            for record in monitor.records
            for channel, message in record.provider_errors.items()
        },
    }
    (args.evidence_dir / "etw-canary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
