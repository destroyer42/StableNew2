"""PR-AI-QUAL-114E: standard-user analysis of a stopped, operator-run ETW capture.

One finite capture window covers many bounded requests. Each request keeps its own owned job-object record (its members and
lifetimes, logged by ``capture_session.RetrospectiveMonitor`` in ``windows.jsonl``); this module reads the stopped trace and
attributes each event to a request by process identity **and** time, and then judges the capture and every request.

What it will not do: guess a clock offset, attribute by pid alone, or let anything that could belong to an owned process
disappear.

* Clock domains. The harness's performance counter and the trace's ``TimeCreated`` are different clocks. Beacon files (a
  uniquely named file the harness creates and deletes at the start and end of the session, with the counter read around it)
  appear in the trace; each gives a bounded offset, the intersection of all of them is the offset interval, and an empty
  intersection beyond a small tolerance (clock drift, a clock-domain mismatch or a missing trace) makes the capture unusable.
  Every event is then placed in an *interval* of counter time, never at a point.
* Windows. An owned pid is attributable only inside the interval from its request's launch to that pid's exit as the runner
  observed it. An event for such a pid clearly outside every one of its windows is a recycled pid of some other process and is
  counted as foreign; one that overlaps a window boundary, one with no timestamp, and one whose process identity is missing
  while it falls inside a request are explicit ambiguities that the capture verdict cannot ignore.
* Integrity. The conversion must report zero lost events/buffers/format errors, the trace header must name this capture's own
  session and file (a stale or reused ETL is refused), the file must be below its size cap, the operator's stop must be
  recorded, the closing beacon and canary must be present, and both bracketing canaries must be seen doing their known file and
  network operations. Anything less is INCONCLUSIVE, never PASS.
* Privacy. Only evidence about owned processes is written out; unrelated host activity appears as counts. The raw ETL stays in
  the (ignored, access-checked) capture directory, the large derived XML is deleted after a completed analysis unless asked
  to keep it, and nothing here exports a raw trace.

This is retrospective evidence of what happened in the captured interval. It is not real-time containment (that stays with
``run_bounded``) and it is not the outbound firewall restriction, which is the independent barrier against egress.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import sys
from collections import defaultdict
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.qualification.ai111 import capture_control as control
from tools.qualification.ai111 import tokens
from tools.qualification.ai111.etw import (
    EtwError,
    RawEvent,
    _candidate_pids,
    check_no_loss,
    convert_trace,
    device_map,
    dns_events,
    file_events,
    iter_raw_events,
    make_to_dos,
    network_events,
)
from tools.qualification.ai111.ownership import (
    CANARY_MOVED,
    CANARY_WRITTEN,
    ChannelEvent,
    OwnershipPolicy,
    _norm,
    policy_violations,
)
from tools.qualification.ai111.tool_runner import bounded_tool

ANALYZER_VERSION = "2"  # 2: an event is owned on the measured clock interval alone; slack only guards the "outside" test
SCHEMA = 1
#: Counter/trace offsets from different beacons may differ by at most this much before the clocks are declared inconsistent.
DRIFT_TOLERANCE_NS = 50_000_000
#: Trace timestamp granularity and scheduling skew, added to the offset interval on each side of every event.
SLACK_NS = 5_000_000
PROVIDER_GUIDS = {
    "network": "7dd42a49-5329-4832-8dfd-43d979153a88",
    "file": "edd08927-9cc4-4e65-b970-c2560fb5c289",
    "dns": "1c95126e-7eea-49a9-a3fe-a378b03ddb4d",
}
_MAX_UNIDENTIFIED = 200_000
_AMBIGUOUS_SAMPLES = 20


# -- the window log -----------------------------------------------------------------------------------------------------


@dataclass
class WindowLogData:
    header: dict[str, Any] | None = None
    beacons: list[dict[str, Any]] = field(default_factory=list)
    requests: list[dict[str, Any]] = field(default_factory=list)
    canary_reports: dict[int, dict[str, Any]] = field(default_factory=dict)
    ended: bool = False
    end_failed: str = ""
    problems: list[str] = field(default_factory=list)


def read_window_log(path: Path) -> WindowLogData:
    data = WindowLogData()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        data.problems.append(f"windows.jsonl is unreadable: {exc}")
        return data
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            data.problems.append(f"windows.jsonl line {number} is not JSON")
            continue
        kind = entry.get("type") if isinstance(entry, dict) else None
        if kind == "header":
            if data.header is not None:
                data.problems.append("windows.jsonl has more than one header")
            data.header = entry
        elif kind == "beacon":
            data.beacons.append(entry)
        elif kind == "request":
            if any(r["number"] == entry.get("number") for r in data.requests):
                data.problems.append(f"request {entry.get('number')} is logged twice")
            data.requests.append(entry)
        elif kind == "canary_report":
            data.canary_reports[int(entry.get("request", -1))] = entry
        elif kind == "end":
            data.ended = True
        elif kind == "end_failed":
            data.end_failed = str(entry.get("error", "unknown"))
        else:
            data.problems.append(f"windows.jsonl line {number} has an unknown record type")
    if data.header is None:
        data.problems.append("windows.jsonl has no header")
    return data


# -- clock calibration --------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ClockMap:
    """``counter_ns = trace_epoch_ns + offset`` with ``offset`` somewhere in ``[low, high]``."""

    low: int
    high: int
    beacons_used: int

    @property
    def spread_ns(self) -> int:
        return abs(self.high - self.low)

    @property
    def consistent(self) -> bool:
        return self.low - self.high <= DRIFT_TOLERANCE_NS

    def interval(self, trace_ns: int, slack_ns: int = SLACK_NS) -> tuple[int, int]:
        a, b = sorted((self.low, self.high))
        return trace_ns + a - slack_ns, trace_ns + b + slack_ns


def calibrate(
    beacons: list[dict[str, Any]], trace_ts: dict[str, list[int]]
) -> tuple[ClockMap | None, list[str]]:
    """The offset interval from every beacon whose file operations were found in the trace (path -> trace timestamps).

    Each trace event of a beacon's file happened between the counter readings taken around it, so each one bounds the offset."""

    problems: list[str] = []
    lows: list[int] = []
    highs: list[int] = []
    for beacon in beacons:
        found = trace_ts.get(_norm(beacon.get("path", "")))
        if not found:
            problems.append(
                f"beacon {beacon.get('n')} ({beacon.get('tag')}) was not found in the trace"
            )
            continue
        for stamp in found:
            lows.append(int(beacon["before_ns"]) - stamp)
            highs.append(int(beacon["after_ns"]) - stamp)
    found_count = len(
        {_norm(b.get("path", "")) for b in beacons if trace_ts.get(_norm(b.get("path", "")))}
    )
    if found_count < 2:
        problems.append(
            "fewer than two beacons were found in the trace; the clocks cannot be related"
        )
        return None, problems
    clock = ClockMap(max(lows), min(highs), found_count)
    if not clock.consistent:
        problems.append(
            f"the beacons disagree about the clock offset by {(clock.low - clock.high) / 1e6:.1f} ms "
            "(drift or a clock-domain mismatch)"
        )
        return None, problems
    return clock, problems


# -- attribution --------------------------------------------------------------------------------------------------------


@dataclass
class Attribution:
    owned: dict[int, list[ChannelEvent]] = field(default_factory=lambda: defaultdict(list))
    ambiguous: dict[int, list[ChannelEvent]] = field(default_factory=lambda: defaultdict(list))
    recycled_pid_events: int = 0
    unrelated_events: int = 0


def attribute_events(
    events: list[ChannelEvent],
    requests: list[dict[str, Any]],
    clock: ClockMap | None,
) -> Attribution:
    """Place each event in a request by pid and counter-time interval; see the module docstring for the three outcomes."""

    result = Attribution()
    windows: dict[int, list[tuple[int, int, int]]] = defaultdict(list)
    for request in requests:
        for member in request.get("members", []):
            end = member["end_ns"] if member.get("end_ns") is not None else request["end_ns"]
            windows[int(member["pid"])].append(
                (int(request["number"]), int(member["start_ns"]), int(end))
            )
    for event in events:
        candidates = windows.get(event.pid)
        if not candidates:
            result.unrelated_events += 1
            continue
        if event.ts_ns is None or clock is None:
            for number, _start, _end in candidates:
                result.ambiguous[number].append(event)
            continue
        # A window already contains the process's true lifetime on both sides (it opens at the launch and closes when the
        # harness observed the exit, which is after the real one), so "owned" needs only the measured clock interval. The
        # slack widens only the test for being clearly outside, so a borderline event is an ambiguity, never dropped.
        low, high = clock.interval(event.ts_ns, 0)
        wide_low, wide_high = clock.interval(event.ts_ns)
        inside = [n for n, ws, we in candidates if low >= ws and high <= we]
        touching = [
            n
            for n, ws, we in candidates
            if not (wide_high < ws or wide_low > we) and n not in inside
        ]
        if len(inside) == 1 and not touching:
            result.owned[inside[0]].append(event)
        elif inside or touching:
            for number in [*inside, *touching]:
                result.ambiguous[number].append(event)
        else:
            result.recycled_pid_events += 1
    return result


# -- reading one stopped trace ------------------------------------------------------------------------------------------


@dataclass
class TraceRead:
    kind: str
    etl_bytes: int = 0
    events: int = 0
    provider_events: int = 0
    header_ok: bool = False
    problems: list[str] = field(default_factory=list)
    channel_events: list[ChannelEvent] = field(default_factory=list)
    #: Timestamps (or ``None``) of events that name no process at all, so they can be tested against the request intervals.
    unidentified: list[int | None] = field(default_factory=list)
    unidentified_total: int = 0


def read_trace(
    kind: str,
    spec: control.SessionSpec,
    session_name: str,
    etl: Path,
    owned_all: frozenset[int],
    *,
    to_dos: Callable[[str], str],
    convert: Callable[[Path, Path, Path], None] = convert_trace,
    keep_xml: bool = False,
    max_mb: int = control.DEFAULT_MAX_MB,
) -> TraceRead:
    out = TraceRead(kind)
    try:
        info = etl.lstat()
    except OSError:
        out.problems.append(f"{kind}: the trace file is missing")
        return out
    if control._is_reparse(etl):
        out.problems.append(f"{kind}: the trace file is a link")
        return out
    out.etl_bytes = info.st_size
    if info.st_size <= 0:
        out.problems.append(f"{kind}: the trace file is empty")
        return out
    if info.st_size >= max_mb * 1024 * 1024 * 0.98:
        out.problems.append(
            f"{kind}: the trace reached its {max_mb} MB cap, so later events were not recorded"
        )
    xml, summary = etl.with_suffix(".xml"), etl.with_suffix(".summary.txt")
    try:
        return _read_converted(
            out, kind, spec, session_name, etl, xml, summary, owned_all, to_dos, convert, keep_xml
        )
    finally:
        # The derived XML is a cleartext system-wide trace: it goes on every exit, a failed conversion included.
        if not keep_xml:
            xml.unlink(missing_ok=True)
            summary.unlink(missing_ok=True)


def _read_converted(
    out: TraceRead,
    kind: str,
    spec: control.SessionSpec,
    session_name: str,
    etl: Path,
    xml: Path,
    summary: Path,
    owned_all: frozenset[int],
    to_dos: Callable[[str], str],
    convert: Callable[[Path, Path, Path], None],
    keep_xml: bool,
) -> TraceRead:
    try:
        convert(etl, xml, summary)
        summary_text = summary.read_text(encoding="utf-8", errors="replace")
        seen = [0]
        header: dict[str, str] = {}

        def tap(stream: Iterator[RawEvent]) -> Iterator[RawEvent]:
            for event in stream:
                seen[0] += 1
                if "SessionNameString" in event.data and not header:
                    header.update(event.data)
                if event.provider == spec.provider or event.guid == PROVIDER_GUIDS[kind]:
                    out.provider_events += 1
                if not _candidate_pids(event):
                    out.unidentified_total += 1
                    if len(out.unidentified) < _MAX_UNIDENTIFIED:
                        out.unidentified.append(event.ts_ns)
                yield event

        stream = tap(iter_raw_events(xml))
        if kind == "network":
            out.channel_events = network_events(stream, owned_all)
        elif kind == "dns":
            out.channel_events = dns_events(stream, owned_all)
        else:
            out.channel_events = file_events(stream, owned_all, to_dos)
        for _unread in stream:  # the XML is only complete if every event it holds was read
            pass
        out.events = seen[0]
        check_no_loss(summary_text, seen[0])
    except (EtwError, OSError) as exc:
        out.problems.append(f"{kind}: {exc}")
        return out
    expected_log = os.path.normcase(os.path.normpath(str(etl)))
    if header.get("SessionNameString") != session_name:
        out.problems.append(
            f"{kind}: the trace header names session {header.get('SessionNameString')!r}, not this capture's"
        )
    elif os.path.normcase(os.path.normpath(header.get("LogFileNameString", ""))) != expected_log:
        out.problems.append(f"{kind}: the trace header names a different file than this capture's")
    else:
        out.header_ok = True
    if out.provider_events == 0 and kind != "dns":
        out.problems.append(f"{kind}: the trace holds no event from {spec.provider}")
    return out


# -- judging ------------------------------------------------------------------------------------------------------------


def _within_any(ts: int | None, intervals: list[tuple[int, int]], clock: ClockMap | None) -> bool:
    """Whether an unidentified event could fall inside a request (conservative: no timestamp or clock means it could)."""

    if ts is None or clock is None:
        return True
    low, high = clock.interval(ts)
    return any(not (high < ws or low > we) for ws, we in intervals)


def _canary_problems(
    request: dict[str, Any],
    report: dict[str, Any] | None,
    owned: list[ChannelEvent],
    connections: list[ChannelEvent],
) -> list[str]:
    """The known events a trusted canary child must have produced, as seen through the capture."""

    expect = request.get("canary_expect") or {}
    problems: list[str] = []
    if not expect:
        return ["the canary request carries no expectations"]
    if report is None:
        problems.append("no canary report was logged for this request")
    else:
        if report.get("returncode") != 0:
            problems.append("the canary child did not exit cleanly")
        members = {int(m["pid"]) for m in request.get("members", [])}
        grandchild = report.get("grandchild_pid")
        if grandchild is None or int(grandchild) not in members:
            problems.append("the canary's short-lived descendant was not in the owned record")
        if report.get("reported_elevated") != 0 or request.get("token_elevated") is True:
            problems.append("the canary child did not show a non-elevated token")
    if not request.get("process_complete") or request.get("active_after_teardown") != 0:
        problems.append("the canary request's teardown was not verified")
    marker = _norm(expect["marker"])
    scratch = expect["scratch"]
    reads = [e for e in owned if e.mode == "read" and _norm(e.detail) == marker]
    if not reads:
        problems.append("the known file read was not seen")
    for name in (CANARY_WRITTEN, CANARY_MOVED):
        target = _norm(Path(scratch) / name)
        if not any(e.mode == "write" and _norm(e.detail) == target for e in owned):
            problems.append(f"the known file write/rename/delete of {name} was not seen")
    port = int(expect["port"])
    swapped = ((port & 0xFF) << 8) | (port >> 8)
    if not any(e.detail.rpartition(":")[2] in (str(port), str(swapped)) for e in connections):
        problems.append("the known connection attempt was not seen")
    return problems


def _request_row(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "number": request["number"],
        "canary": bool(request.get("canary")),
        "executable": Path(str(request.get("executable", ""))).name,
        "executable_sha256": request.get("executable_sha256"),
        "members": len(request.get("members", [])),
    }


def analyze(
    capture_dir: Path,
    *,
    tools: control.TraceTools | None = None,
    convert: Callable[[Path, Path, Path], None] = convert_trace,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    reports_root: Path = control.REPORTS_ROOT,
    mapping: Callable[[], dict[str, str]] = device_map,
    keep_xml: bool = False,
    free_bytes: Callable[[Path], int] = lambda p: shutil.disk_usage(p).free,
) -> dict[str, Any]:
    """Analyse one stopped capture. Returns the (also written) analysis record."""

    tools = tools or control.TraceTools(bounded_tool)
    directory = control.validate_existing_directory(capture_dir, reports_root)
    problems: list[str] = []
    manifest = control._read_json(directory / "capture.json")
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "analyzer_version": ANALYZER_VERSION,
        "analyzer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "host": platform.node(),
        "finished_utc": None,
        "verdict": "INCONCLUSIVE",
        "kind": "unknown",
        "capture_problems": problems,
        "clock": None,
    }
    if manifest is None:
        problems.append("capture.json is missing or unreadable")
        return _finish(directory, result, write=False)
    capture_id = str(manifest.get("capture_id", ""))
    result.update(
        {
            "capture_id": capture_id,
            "run_id": manifest.get("run_id"),
            "provider_config_sha256": manifest.get("provider_config_sha256"),
            "tool_sha256": manifest.get("tool_sha256"),
        }
    )
    if manifest.get("provider_config_sha256") != control.provider_config_sha256():
        problems.append("the capture's provider configuration differs from this tool version's")
    try:
        live = tools.live()
    except control.CaptureRefused as exc:
        live = {}
        problems.append(f"the live session list is unreadable: {exc}")
    state = control.derive_state(directory, live, now())
    result["state"] = state.get("state")
    if state.get("state") not in ("STOPPED", "VERIFIED"):
        problems.append(
            f"the capture is {state.get('state')}; it must be stopped by the operator first"
        )
    stopped = control._read_json(directory / "state-04-stopped.json")
    if stopped is None:
        problems.append("no recorded operator stop (state-04-stopped.json)")
    else:
        deadline = control._parse_utc(manifest.get("deadline_utc"))
        stop_time = control._parse_utc(stopped.get("stopped_utc"))
        if deadline and stop_time and stop_time > deadline:
            problems.append("the capture was stopped after its deadline")
    if (directory / "verification.json").exists() and not list(directory.glob("analysis*.json")):
        problems.append(
            "verification.json exists although no analysis was ever written (pre-seeded)"
        )
    log = read_window_log(directory / "windows.jsonl")
    problems += log.problems
    header = log.header or {}
    if header and header.get("capture_id") != capture_id:
        problems.append("windows.jsonl belongs to a different capture")
    if header and header.get("run_id") != manifest.get("run_id"):
        problems.append("windows.jsonl belongs to a different run")
    if log.end_failed:
        problems.append(f"the closing bracket failed: {log.end_failed}")
    if not log.ended:
        problems.append(
            "the session never logged its end (the closing canary and beacon are missing)"
        )
    requests = log.requests
    harness_pid = int(header["harness_pid"]) if header.get("harness_pid") is not None else None
    result["requests"] = [_request_row(r) for r in requests]
    non_canary = [r for r in requests if not r.get("canary")]
    result["kind"] = "qualification_capture" if non_canary else "canary_capture"
    owned_all = {int(m["pid"]) for r in requests for m in r.get("members", [])}
    if harness_pid is not None:
        owned_all.add(harness_pid)
    needed = [r for r in requests if r.get("canary")]
    if not needed:
        problems.append("the session logged no canary request")
    beacons = log.beacons
    if len(beacons) < 2 or {b.get("tag") for b in beacons} < {"start", "end"}:
        problems.append("the start and end beacons are not both present")

    # -- the traces
    max_mb = int(manifest.get("max_mb_per_session", control.DEFAULT_MAX_MB))
    names = control.session_names(capture_id) if control.CAPTURE_ID.fullmatch(capture_id) else {}
    etl_total = sum(
        (directory / f"{s.kind}.etl").stat().st_size
        for s in control.SESSIONS
        if (directory / f"{s.kind}.etl").is_file()
    )
    need_free = control.CONVERSION_FACTOR * etl_total + control.RESERVE_BYTES // 2
    reads: dict[str, TraceRead] = {}
    if names and free_bytes(directory) < need_free:
        problems.append(
            f"free space is below the {need_free} bytes the trace conversion budgets for; free some and re-run"
        )
    elif names:
        to_dos = make_to_dos(mapping())
        for spec in control.SESSIONS:
            read = read_trace(
                spec.kind,
                spec,
                names[spec.kind],
                directory / f"{spec.kind}.etl",
                frozenset(owned_all),
                to_dos=to_dos,
                convert=convert,
                keep_xml=keep_xml,
                max_mb=max_mb,
            )
            reads[spec.kind] = read
            problems += read.problems
    result["traces"] = {
        kind: {
            "etl_bytes": r.etl_bytes,
            "events": r.events,
            "provider_events": r.provider_events,
            "header_ok": r.header_ok,
        }
        for kind, r in reads.items()
    }

    # -- the clock
    clock: ClockMap | None = None
    if "file" in reads and not reads["file"].problems and harness_pid is not None:
        trace_ts: dict[str, list[int]] = defaultdict(list)
        for event in reads["file"].channel_events:
            if event.pid == harness_pid and event.ts_ns is not None:
                trace_ts[_norm(event.detail)].append(event.ts_ns)
        clock, clock_problems = calibrate(beacons, trace_ts)
        problems += clock_problems
    if clock is not None:
        result["clock"] = {
            "offset_low_ns": clock.low,
            "offset_high_ns": clock.high,
            "uncertainty_ms": round(clock.spread_ns / 1e6, 3),
            "beacons_used": clock.beacons_used,
            "slack_ms": SLACK_NS / 1e6,
        }

    # -- the session must sit inside the proven interval
    if beacons and requests:
        first, last = min(b["before_ns"] for b in beacons), max(b["after_ns"] for b in beacons)
        result["window_seconds"] = round((last - first) / 1e9, 3)
        if any(r["start_ns"] < first or r["end_ns"] > last for r in requests):
            problems.append("a request ran outside the interval the beacons prove was captured")
    elif beacons:
        result["window_seconds"] = round(
            (max(b["after_ns"] for b in beacons) - min(b["before_ns"] for b in beacons)) / 1e9, 3
        )

    # -- attribution
    channel_events = [
        e
        for kind in ("network", "dns", "file")
        if kind in reads
        for e in reads[kind].channel_events
    ]
    connection_ids = {
        id(e) for kind in ("network", "dns") if kind in reads for e in reads[kind].channel_events
    }
    request_events = [e for e in channel_events if e.pid != harness_pid or harness_pid is None]
    attribution = attribute_events(request_events, requests, clock)
    unidentified_inside = 0
    intervals = [(r["start_ns"], r["end_ns"]) for r in requests]
    for read in reads.values():
        unidentified_inside += sum(
            1 for ts in read.unidentified if _within_any(ts, intervals, clock)
        )
    if unidentified_inside:
        problems.append(
            f"{unidentified_inside} trace events name no process and could fall inside a request interval"
        )
    result["attribution"] = {
        "recycled_pid_events": attribution.recycled_pid_events,
        "unrelated_events_for_owned_pids": attribution.unrelated_events,
        "unidentified_events_total": sum(r.unidentified_total for r in reads.values()),
        "unidentified_events_possibly_inside_a_request": unidentified_inside,
        "ambiguous_events": sum(len(v) for v in attribution.ambiguous.values()),
    }

    # -- per request
    rows: list[dict[str, Any]] = []
    any_violation = False
    for request in requests:
        number = int(request["number"])
        owned = attribution.owned.get(number, [])
        connections = [e for e in owned if id(e) in connection_ids]
        files = [e for e in owned if id(e) not in connection_ids]
        ambiguous = attribution.ambiguous.get(number, [])
        row = _request_row(request)
        row.update(
            {
                "owned_file_events": len(files),
                "owned_connection_events": len(connections),
                "ambiguous_events": len(ambiguous),
            }
        )
        violations = list(request.get("realtime_violations", []))
        if request.get("canary"):
            report = log.canary_reports.get(number)
            canary_problems = _canary_problems(request, report, owned, connections)
            row["canary_problems"] = canary_problems
            problems += [f"canary request {number}: {p}" for p in canary_problems]
            violations = [v for v in violations if v != "unexpected_descendants"]
        else:
            policy = OwnershipPolicy(
                max_descendants=int((request.get("policy") or {}).get("max_descendants", 0)),
                read_roots=tuple(
                    Path(p) for p in (request.get("policy") or {}).get("read_roots", [])
                ),
                write_roots=tuple(
                    Path(p) for p in (request.get("policy") or {}).get("write_roots", [])
                ),
                allow_connections=bool(
                    (request.get("policy") or {}).get("allow_connections", False)
                ),
            )
            violations += policy_violations(
                policy,
                [e.detail for e in connections],
                [f"{e.mode}:{e.detail}" for e in files],
            )
            if ambiguous:
                violations.append("ambiguous_attribution")
                row["ambiguous_samples"] = [
                    {
                        "pid": e.pid,
                        "kind": "network" if id(e) in connection_ids else "file",
                        "mode": e.mode,
                    }
                    for e in ambiguous[:_AMBIGUOUS_SAMPLES]
                ]
            if connections:
                row["connection_attempts"] = [e.detail for e in connections]
            outside = [
                e.detail for e in files if policy_violations(policy, [], [f"{e.mode}:{e.detail}"])
            ]
            if outside:
                row["files_outside_policy"] = sorted(set(outside))[:20]
            if not request.get("process_complete") or request.get("active_after_teardown") != 0:
                violations.append("teardown_not_verified")
            if request.get("token_elevated") is True:
                violations.append("child_token_elevated")
        row["violations"] = sorted(set(violations))
        hard = [v for v in row["violations"] if v != "ambiguous_attribution"]
        any_violation = any_violation or bool(hard)
        rows.append(row)
    result["requests"] = rows

    # -- bracketing canaries
    canary_numbers = sorted(int(r["number"]) for r in requests if r.get("canary"))
    if non_canary and canary_numbers:
        first_real = min(int(r["number"]) for r in non_canary)
        last_real = max(int(r["number"]) for r in non_canary)
        if not any(n < first_real for n in canary_numbers):
            problems.append("no canary ran before the first qualification request")
        if not any(n > last_real for n in canary_numbers):
            problems.append("no canary ran after the last qualification request")

    if len(canary_numbers) < 2:
        problems.append("the start and end canary children were not both run")
    ambiguity = result["attribution"]["ambiguous_events"] > 0
    if any_violation:
        verdict = "FAIL"
    elif problems or ambiguity:
        verdict = "INCONCLUSIVE"
    else:
        verdict = "PASS"
    result["verdict"] = verdict
    result["stop_record"] = stopped
    return _finish(directory, result, write=True)


def _finish(directory: Path, result: dict[str, Any], *, write: bool) -> dict[str, Any]:
    result["finished_utc"] = datetime.now(UTC).isoformat()
    if not write:
        return result
    name = "analysis.json"
    counter = 1
    while (directory / name).exists():
        counter += 1
        name = f"analysis-{counter}.json"
    with (directory / name).open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    verification = directory / "verification.json"
    try:
        with verification.open("x", encoding="utf-8") as handle:
            json.dump(
                {
                    "state": "VERIFIED",
                    "analysis": name,
                    "verdict": result["verdict"],
                    "utc": result["finished_utc"],
                },
                handle,
                indent=2,
            )
            handle.write("\n")
    except FileExistsError:
        pass  # a repeat analysis; a pre-seeded file was already reported as a problem before the verdict
    result["analysis_file"] = name
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("analyze", help="analyse a stopped capture (ordinary terminal)")
    run.add_argument("--capture-dir", type=Path, required=True)
    run.add_argument(
        "--keep-xml", action="store_true", help="keep the large derived XML for diagnosis"
    )
    args = parser.parse_args(argv)
    if tokens.current_process_elevated() is not False:
        print(json.dumps({"refused": "analysis must run in an ordinary terminal"}, indent=2))
        return 2
    try:
        result = analyze(args.capture_dir, keep_xml=args.keep_xml)
    except control.CaptureRefused as exc:
        print(json.dumps({"verdict": "INCONCLUSIVE", "refused": str(exc)}, indent=2))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
