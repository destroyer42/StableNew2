"""Shared fakes for the PR-AI-QUAL-114E capture tests: a ``logman`` simulator and a synthetic stopped-capture builder.

Nothing here starts a trace session or runs a downloaded binary. The simulator answers the three ``logman`` verbs the capture
uses (``start``, ``stop``, ``query``) in the format measured on the target host on 2026-10-25, and can be told to deny a start
(optionally leaving the session behind, as the OS does) or to refuse a stop.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path, PureWindowsPath
from typing import Any

from tools.qualification.ai111 import capture_control as control

FIXED_NOW = datetime(2026, 10, 25, 19, 0, 0, tzinfo=UTC)
NS = "http://schemas.microsoft.com/win/2004/08/events/event"

LIST_HEADER = (
    "Data Collector Set                      Type                          Status\n"
    "-------------------------------------------------------------------------------\n"
)


class FakeLogman:
    """A ``logman`` stand-in. ``sessions`` maps a session name to its configuration."""

    def __init__(self) -> None:
        self.sessions: dict[str, dict[str, Any]] = {}
        self.foreign = ["Circular Kernel Context Logger", "SomeOtherApp-Trace"]
        self.calls: list[list[str]] = []
        self.deny_kinds: set[str] = set()
        self.create_on_deny = False
        self.stuck: set[str] = set()  # names whose stop is refused
        self.list_fails = False
        self.query_override: dict[str, str] = {}
        self.buffers_lost = 0

    # the injected ``Run`` -------------------------------------------------------------------------------------------------
    def run(self, command) -> tuple[int, str]:
        self.calls.append([str(c) for c in command])
        verb = command[1]
        if verb == "start":
            return self._start(command)
        if verb == "stop":
            return self._stop(command[2])
        if verb == "query" and len(command) == 3:
            return self._list()
        if verb == "query":
            return self._query(command[2])
        return 1, f"unexpected logman verb {verb}"

    def _start(self, command) -> tuple[int, str]:
        name = command[2]
        provider = command[command.index("-p") + 1]
        keywords = int(command[command.index("-p") + 2], 16)
        level = int(command[command.index("-p") + 3], 16)
        etl = command[command.index("-o") + 1]
        max_mb = int(command[command.index("-max") + 1])
        kind = name.rsplit("-", 1)[1]
        config = {
            "provider": provider,
            "keywords": keywords,
            "level": level,
            "etl": etl,
            "max_mb": max_mb,
            "circular": "Off",
            "clock": "Performance",
            "status": "Running",
            "command": [str(c) for c in command],
        }
        if kind in self.deny_kinds:
            if self.create_on_deny:
                self.sessions[name] = (
                    config  # the OS can leave the named session behind after "Access is denied"
                )
            return 0x80070005 - (
                1 << 32
            ), "Error:\r\nAccess is denied.\r\nTry running this command as an administrator."
        self.sessions[name] = config
        return 0, "The command completed successfully."

    def _stop(self, name: str) -> tuple[int, str]:
        if name in self.stuck:
            return 1, "Error: the session did not stop."
        if name not in self.sessions:
            return 0x80300104 - (1 << 32), "Data Collector Set was not found."
        del self.sessions[name]
        return 0, "The command completed successfully."

    def _list(self) -> tuple[int, str]:
        if self.list_fails:
            return 1, "Error: cannot list."
        rows = [f"{n:<39} {'Trace':<29} Running" for n in [*self.foreign, *self.sessions]]
        return 0, LIST_HEADER + "\n".join(rows) + "\nThe command completed successfully.\n"

    def _query(self, name: str) -> tuple[int, str]:
        if name in self.query_override:
            return 0, self.query_override[name]
        config = self.sessions.get(name)
        if config is None:
            return 1, "Data Collector Set was not found."
        return 0, query_text(name, config, buffers_lost=self.buffers_lost)


def query_text(name: str, config: dict[str, Any], *, buffers_lost: int = 0) -> str:
    folder = str(PureWindowsPath(config["etl"]).parent)
    return (
        f"\nName:                 {name}\n"
        f"Status:               {config['status']}\n"
        f"Root Path:            {folder}\n"
        "Segment:              Off\n"
        "Schedules:            On\n"
        f"Segment Max Size:     {config['max_mb']} MB\n"
        f"\nName:                 {name}\\{name}\n"
        "Type:                 Trace\n"
        f"Output Location:      {config['etl']}\n"
        "Append:               Off\n"
        f"Circular:             {config['circular']}\n"
        "Overwrite:            Off\n"
        "Buffer Size:          1024\n"
        f"Buffers Lost:         {buffers_lost}\n"
        "Buffers Written:      1\n"
        "Buffer Flush Timer:   0\n"
        f"Clock Type:           {config['clock']}\n"
        "File Mode:            File\n"
        "\nProvider:\n"
        f"Name:                 {config['provider']}\n"
        "Provider Guid:        {A0C1853B-5C40-4B15-8766-3CF1C58F985A}\n"
        f"Level:                {config['level']} (win:Informational)\n"
        "KeywordsAll:          0x0\n"
        f"KeywordsAny:          {hex(config['keywords'])} (Anything,Else)\n"
        "Properties:           64\n"
        "Filter Type:          0\n"
        "\nThe command completed successfully.\n"
    )


def make_env(
    tmp_path: Path,
    logman: FakeLogman,
    *,
    elevated: bool | None = True,
    free: int = 10**13,
    acl: str = "{dir} NT AUTHORITY\\SYSTEM:(OI)(CI)(F)\n   BUILTIN\\Administrators:(OI)(CI)(F)\n",
    now: Callable[[], datetime] | None = None,
) -> control.Environment:
    root = tmp_path / "reports"
    root.mkdir(exist_ok=True)
    return control.Environment(
        tools=control.TraceTools(logman.run),
        now=now or (lambda: FIXED_NOW),
        elevated=lambda: elevated,
        free_bytes=lambda path: free,
        acl_reader=lambda path: acl.replace("{dir}", str(path)),
        reports_root=root,
    )


def started_capture(
    tmp_path: Path,
    logman: FakeLogman,
    *,
    run_id: str = "run-1",
    name: str = "capture",
    minutes: int = 30,
    max_mb: int = 64,
) -> tuple[Path, dict[str, Any], control.Environment]:
    env = make_env(tmp_path, logman)
    target = env.reports_root / "ai114" / run_id / name
    report = control.start_capture(target, run_id=run_id, max_mb=max_mb, minutes=minutes, env=env)
    assert report["state"] == "ACTIVE", report
    return target, report, env


def stopped_capture(
    tmp_path: Path, logman: FakeLogman, **kwargs: Any
) -> tuple[Path, dict[str, Any], control.Environment]:
    target, report, env = started_capture(tmp_path, logman, **kwargs)
    result = control.stop_capture(report["capture_id"], evidence_dir=target, env=env)
    assert result["state"] == "STOPPED", result
    return target, report, env


# -- synthetic traces ---------------------------------------------------------------------------------------------------


def iso(epoch_ns: int) -> str:
    seconds, nanos = divmod(epoch_ns, 1_000_000_000)
    stamp = datetime.fromtimestamp(seconds, UTC).strftime("%Y-%m-%dT%H:%M:%S")
    return f"{stamp}.{nanos:09d}Z"


def event_xml(provider: str, event_id: int, pid: int, epoch_ns: int | None, **data: object) -> str:
    items = "".join(f'<Data Name="{k}">{v}</Data>' for k, v in data.items())
    stamp = f'<TimeCreated SystemTime="{iso(epoch_ns)}"/>' if epoch_ns is not None else ""
    return (
        f'<Event xmlns="{NS}"><System><Provider Name="{provider}"/><EventID>{event_id}</EventID>{stamp}'
        f'<Execution ProcessID="{pid}" ThreadID="1"/></System><EventData>{items}</EventData></Event>'
    )


def header_xml(session_name: str, etl: str, epoch_ns: int) -> str:
    return (
        f'<Event xmlns="{NS}"><System><Provider Guid="{{9e814aad-3204-11d2-9a82-006008a86939}}"/>'
        f'<EventID>0</EventID><TimeCreated SystemTime="{iso(epoch_ns)}"/>'
        '<Execution ProcessID="4" ThreadID="1"/></System><EventData>'
        f'<Data Name="SessionNameString">{session_name}</Data><Data Name="LogFileNameString">{etl}</Data>'
        "</EventData></Event>"
    )


NET = "Microsoft-Windows-Kernel-Network"
FILE = "Microsoft-Windows-Kernel-File"
DNS = "Microsoft-Windows-DNS-Client"
OPEN = 0x01000000
CREATE = 0x02000000

#: counter = trace + OFFSET: the arbitrary relationship between the two clock domains in the synthetic captures
EPOCH0 = 1_793_000_000 * 1_000_000_000
COUNTER0 = 5_000_000_000_000
OFFSET = COUNTER0 - EPOCH0


def to_trace(counter_ns: int, offset: int = OFFSET) -> int:
    return counter_ns - offset


def dos(path: str | Path) -> str:
    """A DOS path as the synthetic trace spells it (device ``\\Device\\HarddiskVolume3`` maps to ``C:``)."""

    text = str(path)
    assert text[1:3] == ":\\", text
    return f"\\Device\\HarddiskVolume{ord(text[0].upper()) - 64}" + text[2:]


def drive_mapping() -> dict[str, str]:
    """The injected NT-device -> drive map matching :func:`dos` for every letter (nothing is read from the host)."""

    return {f"\\device\\harddiskvolume{ord(c) - 64}": f"{c}:" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"}


@dataclass
class Scenario:
    """A synthetic stopped capture: the window log, the events each trace holds and what the conversion should report."""

    counter: int = COUNTER0
    requests: list[dict[str, Any]] = field(default_factory=list)
    events: dict[str, list[str]] = field(
        default_factory=lambda: {"network": [], "file": [], "dns": []}
    )
    beacons: list[dict[str, Any]] = field(default_factory=list)
    canary_reports: list[dict[str, Any]] = field(default_factory=list)
    harness_pid: int = 9000
    ended: bool = True
    lost: int = 0
    header_session: dict[str, str] = field(default_factory=dict)
    skip_beacon_in_trace: set[int] = field(default_factory=set)
    beacon_trace_shift: dict[int, int] = field(default_factory=dict)
    convert_error: dict[str, str] = field(default_factory=dict)
    summary_extra: dict[str, str] = field(default_factory=dict)
    truncate_xml: set[str] = field(default_factory=set)
    etl_size: dict[str, int] = field(default_factory=dict)

    def tick(self, delta_ms: float = 10.0) -> int:
        self.counter += int(delta_ms * 1_000_000)
        return self.counter


def add_beacon(scenario: Scenario, tag: str, directory: Path) -> dict[str, Any]:
    n = len(scenario.beacons) + 1
    before = scenario.tick(5)
    after = before + 200_000
    path = directory / "beacons" / f"beacon-{n:03d}-deadbeef.tmp"
    entry = {
        "type": "beacon",
        "n": n,
        "tag": tag,
        "pid": scenario.harness_pid,
        "path": str(path),
        "before_ns": before,
        "after_ns": after,
    }
    scenario.beacons.append(entry)
    if n not in scenario.skip_beacon_in_trace:
        shift = scenario.beacon_trace_shift.get(n, 0)
        at = to_trace(before + 100_000) + shift
        scenario.events["file"].append(
            event_xml(
                FILE,
                12,
                scenario.harness_pid,
                at,
                FileObject=f"0xB{n}",
                CreateOptions=CREATE,
                FileName=dos(path),
            )
        )
        scenario.events["file"].append(
            event_xml(FILE, 26, scenario.harness_pid, at + 50_000, FileName=dos(path))
        )
    return entry


def add_request(
    scenario: Scenario,
    *,
    pid: int,
    canary: bool = False,
    duration_ms: float = 100.0,
    members: list[dict[str, Any]] | None = None,
    violations: list[str] | None = None,
    policy: dict[str, Any] | None = None,
    expect: dict[str, Any] | None = None,
    complete: bool = True,
    token_elevated: bool | None = False,
) -> dict[str, Any]:
    number = len(scenario.requests) + 1
    start = scenario.tick(20)
    end = start + int(duration_ms * 1_000_000)
    scenario.counter = end
    exit_ns = end - 1_000_000
    request = {
        "type": "request",
        "number": number,
        "canary": canary,
        "executable": "C:\\py\\python.exe" if canary else "C:\\runtime\\llama-completion.exe",
        "executable_sha256": "ab" * 32,
        "start_ns": start,
        "end_ns": end,
        "root_pid": pid,
        "members": members or [{"pid": pid, "start_ns": start, "end_ns": exit_ns}],
        "process_complete": complete,
        "active_after_teardown": 0,
        "token_elevated": token_elevated,
        "realtime_violations": violations or [],
        "provider_errors": {},
        "canary_expect": expect,
        "policy": policy
        or {
            "read_roots": ["C:\\ai\\root", "C:\\Windows"],
            "write_roots": ["C:\\ai\\root\\work"],
            "allow_connections": False,
            "max_descendants": 0,
        },
    }
    scenario.requests.append(request)
    return request


def add_canary(
    scenario: Scenario,
    *,
    pid: int,
    grandchild: int,
    tmp: Path,
    tag: str,
    port: int = 51234,
    omit: tuple[str, ...] = (),
    grandchild_owned: bool = True,
    reported_elevated: int = 0,
    report: bool = True,
    **request_fields: Any,
) -> dict[str, Any]:
    """A trusted canary request that did its known operations. ``omit`` drops "read", "write" or "connect" events."""

    scratch = tmp / f"canary-{tag}"
    marker = scratch / "canary-marker.bin"
    expect = {"tag": tag, "marker": str(marker), "scratch": str(scratch), "port": port}
    request = add_request(
        scenario,
        pid=pid,
        canary=True,
        duration_ms=80,
        members=None,
        expect=expect,
        **request_fields,
    )
    start, end = request["start_ns"], request["end_ns"]
    request["members"] = [{"pid": pid, "start_ns": start, "end_ns": end - 1_000_000}]
    if grandchild_owned:
        request["members"].append({"pid": grandchild, "start_ns": start, "end_ns": end - 2_000_000})
    mid = start + 20_000_000
    if "read" not in omit:
        scenario.events["file"].append(
            event_xml(
                FILE,
                12,
                pid,
                to_trace(mid),
                FileObject=f"0xC{pid}",
                CreateOptions=OPEN,
                FileName=dos(marker),
            )
        )
    if "write" not in omit:
        scenario.events["file"] += [
            event_xml(
                FILE,
                12,
                pid,
                to_trace(mid + 1_000_000),
                FileObject=f"0xD{pid}",
                CreateOptions=CREATE,
                FileName=dos(scratch / "canary-written.bin"),
            ),
            event_xml(FILE, 16, pid, to_trace(mid + 2_000_000), FileObject=f"0xD{pid}"),
            event_xml(
                FILE,
                19,
                pid,
                to_trace(mid + 3_000_000),
                FileName=dos(scratch / "canary-written.bin"),
                NewFileName=dos(scratch / "canary-moved.bin"),
            ),
            event_xml(
                FILE, 26, pid, to_trace(mid + 4_000_000), FileName=dos(scratch / "canary-moved.bin")
            ),
        ]
    if "connect" not in omit:
        scenario.events["network"].append(
            event_xml(
                NET, 12, pid, to_trace(mid + 5_000_000), PID=pid, daddr="127.0.0.1", dport=port
            )
        )
    if report:
        scenario.canary_reports.append(
            {
                "type": "canary_report",
                "request": request["number"],
                "tag": tag,
                "grandchild_pid": grandchild,
                "reported_elevated": reported_elevated,
                "returncode": 0,
            }
        )
    return request


def canary_scenario(
    tmp: Path,
    directory: Path,
    *,
    middle: Callable[[Scenario], None] | None = None,
    **fields: Any,
) -> Scenario:
    """Start beacon, start canary, optional qualification requests, end canary, end beacon.

    ``fields`` are ``Scenario`` fields that must be known while the events are generated (the beacon ones)."""

    scenario = Scenario(**fields)
    add_beacon(scenario, "start", directory)
    add_canary(scenario, pid=5001, grandchild=5002, tmp=tmp, tag="start")
    if middle is not None:
        middle(scenario)
    add_canary(scenario, pid=5003, grandchild=5004, tmp=tmp, tag="end", port=51235)
    add_beacon(scenario, "end", directory)
    return scenario


def request_event(
    scenario: Scenario,
    request: dict[str, Any],
    kind: str,
    *,
    offset_ms: float,
    pid: int | None = None,
    **fields: Any,
) -> None:
    """One file/network event for ``pid`` (default the request's root) at ``offset_ms`` after the request began."""

    pid = request["root_pid"] if pid is None else pid
    at = to_trace(request["start_ns"] + int(offset_ms * 1_000_000))
    if kind == "read":
        scenario.events["file"].append(
            event_xml(
                FILE,
                12,
                pid,
                at,
                FileObject=f"0xA{len(scenario.events['file'])}",
                CreateOptions=OPEN,
                FileName=dos(fields["path"]),
            )
        )
    elif kind == "write":
        scenario.events["file"].append(event_xml(FILE, 26, pid, at, FileName=dos(fields["path"])))
    elif kind == "connect":
        scenario.events["network"].append(
            event_xml(
                NET,
                12,
                pid,
                at,
                PID=pid,
                daddr=fields.get("addr", "203.0.113.9"),
                dport=fields.get("port", 443),
            )
        )
    else:
        raise AssertionError(kind)


def write_capture(
    scenario: Scenario,
    directory: Path,
    report: dict[str, Any],
    *,
    run_id: str = "run-1",
) -> Callable[[Path, Path, Path], None]:
    """Write ``windows.jsonl`` and the ETL placeholders, and return the fake ``convert`` for the analyzer."""

    capture_id = report["capture_id"]
    names = control.session_names(capture_id)
    lines: list[dict[str, Any]] = [
        {
            "type": "header",
            "schema": 1,
            "capture_id": capture_id,
            "run_id": run_id,
            "harness_pid": scenario.harness_pid,
            "host": "test-host",
        },
        *scenario.beacons,
        *scenario.requests,
        *scenario.canary_reports,
    ]
    if scenario.ended:
        lines.append({"type": "end"})
    (directory / "windows.jsonl").write_text(
        "\n".join(json.dumps(line, sort_keys=True) for line in lines) + "\n", encoding="utf-8"
    )
    for kind in names:
        etl = directory / f"{kind}.etl"
        etl.write_bytes(b"\0" * scenario.etl_size.get(kind, 4096))

    def convert(etl: Path, xml: Path, summary: Path) -> None:
        kind = etl.stem
        for stale in (xml, summary):
            stale.unlink(missing_ok=True)
        if kind in scenario.convert_error:
            from tools.qualification.ai111.etw import EtwError

            raise EtwError(scenario.convert_error[kind])
        header_names = scenario.header_session
        head = header_xml(header_names.get(kind, names[kind]), str(etl), EPOCH0)
        body = [head, *scenario.events.get(kind, [])]
        if kind == "network" and not any(NET in e for e in body):
            body.append(event_xml(NET, 99, 4, EPOCH0 + 1))  # the provider has spoken at least once
        count = len(body)
        shown = count - 1 if kind in scenario.truncate_xml else count
        xml.write_text("<Events>" + "".join(body[:shown]) + "</Events>", encoding="utf-8")
        lost = scenario.lost if kind == "file" else 0
        summary.write_text(
            f"Total Buffers Processed 3\nTotal Events  Processed {count}\nTotal Events  Lost      {lost}\n"
            + scenario.summary_extra.get(kind, ""),
            encoding="utf-8",
        )

    return convert


def fixed_clock(offset_minutes: float = 0.0) -> Callable[[], datetime]:
    return lambda: FIXED_NOW + timedelta(minutes=offset_minutes)
