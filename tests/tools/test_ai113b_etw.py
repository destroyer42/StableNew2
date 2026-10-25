"""PR-AI-QUAL-113B: the ETW providers, proven without a live trace.

An unelevated process cannot start a kernel trace, so everything here uses a fake ``logman``/``tracerpt`` backend that
writes synthetic tracerpt-shaped XML. That proves command construction, parsing, attribution, loss accounting, window
lifecycle and canary plumbing. It does NOT prove that this host's real ETW output has the shape assumed here; that is
what the elevated ``python -m tools.qualification.ai111.etw`` canary (and the elevated live test below) is for.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.utils.managed_process import run_bounded  # noqa: E402
from tools.qualification.ai111 import etw  # noqa: E402
from tools.qualification.ai111.etw import (  # noqa: E402
    EtwCapture,
    EtwError,
    LogmanBackend,
    check_no_loss,
    etw_host_monitor,
    file_events,
    iter_raw_events,
    make_to_dos,
    network_events,
)
from tools.qualification.ai111.ownership import COMPLETE, UNAVAILABLE, OwnershipPolicy  # noqa: E402

windows_only = pytest.mark.skipif(os.name != "nt", reason="Windows job objects")

NS = "http://schemas.microsoft.com/win/2004/08/events/event"
NET = "Microsoft-Windows-Kernel-Network"
FILE = "Microsoft-Windows-Kernel-File"
GOOD_SUMMARY = "Total Buffers Processed 3\nTotal Events  Processed 40\nTotal Events  Lost      0\nBuffers Lost 0\n"


def ev(provider: str, event_id: int, pid: int, **data: object) -> str:
    items = "".join(f'<Data Name="{k}">{v}</Data>' for k, v in data.items())
    return (
        f'<Event xmlns="{NS}"><System><Provider Name="{provider}"/><EventID>{event_id}</EventID>'
        f'<Execution ProcessID="{pid}" ThreadID="1"/></System><EventData>{items}</EventData></Event>'
    )


def doc(*events: str) -> str:
    return "<Events>" + "".join(events) + "</Events>"


def raw(tmp_path: Path, *events: str):
    path = tmp_path / "t.xml"
    path.write_text(doc(*events), encoding="utf-8")
    return iter_raw_events(path)


# -- commands ---------------------------------------------------------------------------------------------------------


def test_sessions_are_transient_unique_and_use_perf_clock(tmp_path: Path) -> None:
    commands: list[list[str]] = []

    def run(command):
        commands.append(list(command))
        return 0, ""

    backend = LogmanBackend(run)
    backend.start("StableNewAi113-abc", etw.FILE, tmp_path / "f.etl")
    backend.stop("StableNewAi113-abc")
    (tmp_path / "f.xml").write_text("stale", encoding="utf-8")
    (tmp_path / "f.txt").write_text("stale", encoding="utf-8")
    backend.convert(tmp_path / "f.etl", tmp_path / "f.xml", tmp_path / "f.txt")
    assert not (tmp_path / "f.xml").exists() and not (tmp_path / "f.txt").exists(), (
        "a stale output must not survive into the conversion"
    )
    start, stop, convert = commands
    for tool in (start[0], stop[0], convert[0]):
        assert Path(tool).is_absolute(), "the OS tools are never resolved through PATH or the cwd"
    assert [Path(start[0]).name, Path(stop[0]).name, Path(convert[0]).name] == [
        "logman.exe",
        "logman.exe",
        "tracerpt.exe",
    ]
    assert start[1:3] == ["start", "StableNewAi113-abc"]
    assert "-ets" in start and "-ct" in start and start[start.index("-ct") + 1] == "perf"
    assert start[start.index("-p") + 1] == "Microsoft-Windows-Kernel-File"
    assert int(start[start.index("-p") + 2], 16) == 0x10 | 0x80 | 0x200 | 0x400 | 0x800 | 0x1000
    assert stop[1:] == ["stop", "StableNewAi113-abc", "-ets"]
    assert "-of" in convert and convert[convert.index("-of") + 1] == "XML"
    assert not any("create" in c for c in commands[0]), "no persistent collector is ever registered"


def test_a_failing_tool_is_an_error() -> None:
    backend = LogmanBackend(lambda _c: (5, "Access is denied."))
    with pytest.raises(EtwError, match="Access is denied"):
        backend.start("StableNewAi113-x", etw.NETWORK, Path("x.etl"))


# -- loss accounting ---------------------------------------------------------------------------------------------------


def test_loss_accounting_fails_closed() -> None:
    check_no_loss(GOOD_SUMMARY)
    with pytest.raises(EtwError, match="lost"):
        check_no_loss(GOOD_SUMMARY.replace("Lost      0", "Lost      7"))
    with pytest.raises(EtwError, match="lost"):
        check_no_loss(GOOD_SUMMARY.replace("Buffers Lost 0", "Buffers Lost 2"))
    with pytest.raises(EtwError, match="unavailable"):
        check_no_loss("Total Events Processed 5\n")
    with pytest.raises(EtwError, match="format errors"):
        check_no_loss(GOOD_SUMMARY + "Total Format Errors 2\n")


def test_the_processed_count_must_match_what_the_xml_holds() -> None:
    check_no_loss(GOOD_SUMMARY, 40)
    with pytest.raises(EtwError, match="processed 40 events but the XML holds 39"):
        check_no_loss(GOOD_SUMMARY, 39)
    with pytest.raises(EtwError, match="no processed events"):
        check_no_loss(GOOD_SUMMARY.replace("Processed 40", "Processed 0"), 0)
    with pytest.raises(EtwError, match="no processed events"):
        check_no_loss("Total Events  Lost 0\nBuffers Lost 0\n", 0)


# -- parsing ----------------------------------------------------------------------------------------------------------


def test_malformed_or_foreign_documents_are_errors(tmp_path: Path) -> None:
    bad = tmp_path / "bad.xml"
    bad.write_text("<Events><Event>", encoding="utf-8")
    with pytest.raises(EtwError, match="not valid"):
        list(iter_raw_events(bad))
    other = tmp_path / "other.xml"
    other.write_text("<html></html>", encoding="utf-8")
    with pytest.raises(EtwError, match="no <Events>"):
        list(iter_raw_events(other))


def test_network_events_are_kept_for_owned_pids_only(tmp_path: Path) -> None:
    events = raw(
        tmp_path,
        ev(
            NET, 12, 4, PID=100, daddr="10.0.0.9", dport=443
        ),  # logged in system context for owned pid 100
        ev(NET, 12, 100, daddr="127.0.0.1", dport=80),
        ev(NET, 12, 999, PID=999, daddr="8.8.8.8", dport=53),  # someone else
    )
    out = network_events(events, frozenset({100}))
    assert sorted((e.pid, e.detail) for e in out) == [(100, "10.0.0.9:443"), (100, "127.0.0.1:80")]


def test_file_open_write_delete_and_unknown_kinds(tmp_path: Path) -> None:
    flags = 0x01000000  # FILE_OPEN disposition
    creating = 0x02000000  # FILE_CREATE disposition
    events = raw(
        tmp_path,
        ev(
            FILE,
            12,
            100,
            FileObject="0xA",
            CreateOptions=flags,
            FileName="\\Device\\HarddiskVolume3\\ai\\model.gguf",
        ),
        ev(
            FILE,
            12,
            100,
            FileObject="0xB",
            CreateOptions=flags,
            FileName="\\Device\\HarddiskVolume3\\ai\\log.txt",
        ),
        ev(FILE, 16, 100, FileObject="0xB"),  # a write to the second file
        ev(
            FILE,
            12,
            100,
            FileObject="0xC",
            CreateOptions=creating,
            FileName="\\Device\\HarddiskVolume3\\ai\\new.bin",
        ),
        ev(FILE, 26, 100, FileName="\\Device\\HarddiskVolume3\\ai\\gone.bin"),  # delete path
        ev(FILE, 15, 100, FileObject="0xA"),  # read: benign
        ev(
            FILE, 99, 100, FileName="\\Device\\HarddiskVolume3\\ai\\odd.bin"
        ),  # unknown kind with a name
        ev(
            FILE,
            12,
            777,
            FileObject="0xD",
            CreateOptions=flags,
            FileName="\\Device\\HarddiskVolume3\\other.txt",
        ),
    )
    to_dos = make_to_dos({"\\device\\harddiskvolume3": "C:"})
    modes = {e.detail: e.mode for e in file_events(events, frozenset({100}), to_dos)}
    assert modes == {
        "C:\\ai\\model.gguf": "read",
        "C:\\ai\\log.txt": "write",
        "C:\\ai\\new.bin": "write",
        "C:\\ai\\gone.bin": "write",
        "C:\\ai\\odd.bin": "unknown",
    }


def test_a_reused_file_object_keeps_the_earlier_access(tmp_path: Path) -> None:
    opened = 0x01000000
    events = raw(
        tmp_path,
        ev(
            FILE,
            12,
            100,
            FileObject="0x1",
            CreateOptions=opened,
            FileName="\\Device\\HarddiskVolume3\\a.txt",
        ),
        ev(FILE, 16, 100, FileObject="0x1"),  # a.txt was written ...
        ev(
            FILE,
            12,
            100,
            FileObject="0x1",  # ... and the kernel then reuses the same file object for b.txt
            CreateOptions=opened,
            FileName="\\Device\\HarddiskVolume3\\b.txt",
        ),
    )
    to_dos = make_to_dos({"\\device\\harddiskvolume3": "C:"})
    modes = {e.detail: e.mode for e in file_events(events, frozenset({100}), to_dos)}
    assert modes == {"C:\\a.txt": "write", "C:\\b.txt": "read"}


def test_owned_events_that_cannot_be_resolved_are_reported_not_dropped(tmp_path: Path) -> None:
    events = raw(
        tmp_path,
        ev(FILE, 12, 100, FileObject="0x1", CreateOptions=0x01000000),  # a create with no file name
        ev(FILE, 26, 100),  # a delete with no path
        ev(FILE, 26, 100),  # the same kind again: reported once
        ev(FILE, 77, 100, Irp="0x5"),  # an unrecognised kind without a name
        ev(FILE, 77, 555),  # a foreign pid
        ev(FILE, 10, 100),  # benign
    )
    out = file_events(events, frozenset({100}), make_to_dos({}))
    assert sorted((e.detail, e.mode) for e in out) == [
        ("<unresolved kernel-file event 12>", "unknown"),
        ("<unresolved kernel-file event 26>", "unknown"),
        ("<unresolved kernel-file event 77>", "unknown"),
    ]


def test_nt_paths_map_to_dos_and_unc_and_unmapped_stay_nt() -> None:
    to_dos = make_to_dos({"\\device\\harddiskvolume3": "C:", "\\device\\harddiskvolume31": "D:"})
    assert to_dos("\\Device\\HarddiskVolume3\\a\\b") == "C:\\a\\b"
    assert to_dos("\\Device\\HarddiskVolume31\\a") == "D:\\a"
    assert to_dos("\\Device\\Mup\\srv\\share\\x") == "\\\\srv\\share\\x"
    assert to_dos("\\??\\C:\\a") == "C:\\a"
    assert to_dos("\\Device\\Unknown\\x") == "\\Device\\Unknown\\x"


# -- capture window lifecycle ------------------------------------------------------------------------------------------


class FakeBackend:
    def __init__(self) -> None:
        self.started: list[str] = []
        self.stopped: list[str] = []
        self.live: list[str] = []
        self.xml_for = lambda kind: doc()
        self.summary: str | None = (
            None  # None: a clean summary whose processed count matches the XML
        )
        self.fail_start_at: int | None = None

    def start(self, name, spec, etl) -> None:
        if self.fail_start_at is not None and len(self.started) == self.fail_start_at:
            raise EtwError("start failed")
        self.started.append(name)
        etl.parent.mkdir(parents=True, exist_ok=True)
        assert etl.is_absolute()

    def stop(self, name) -> None:
        self.stopped.append(name)

    def live_sessions(self) -> list[str]:
        return list(self.live)

    def convert(self, etl: Path, xml: Path, summary: Path) -> None:
        kind = etl.stem.rsplit("-", 1)[1]
        # a real trace always starts with its own header event, so a window is never legitimately empty
        header = ev("MSNT_SystemTrace", 0, 0)
        text = self.xml_for(kind).replace("<Events>", "<Events>" + header, 1)
        xml.write_text(text, encoding="utf-8")
        count = text.count("<Event ")
        summary.write_text(
            self.summary
            if self.summary is not None
            else GOOD_SUMMARY.replace("Processed 40", f"Processed {count}"),
            encoding="utf-8",
        )


def capture(tmp_path: Path, backend: FakeBackend, *, elevated: bool = True) -> EtwCapture:
    return EtwCapture(
        tmp_path / "etw",
        backend,  # type: ignore[arg-type]
        mapping=lambda: {"\\device\\harddiskvolume3": "C:"},
        elevated=lambda: elevated,
    )


@windows_only
def test_one_window_serves_both_channels_and_is_stopped_once(tmp_path: Path) -> None:
    backend = FakeBackend()
    backend.xml_for = lambda kind: (
        doc(ev(NET, 12, 100, daddr="1.2.3.4", dport=1)) if kind == "network" else doc()
    )
    cap = capture(tmp_path, backend)
    cap.begin()
    cap.begin()  # the second channel provider joins the window
    assert len(backend.started) == 3
    assert [e.detail for e in cap.collect("connections", frozenset({100}))] == ["1.2.3.4:1"]
    assert cap.collect("files", frozenset({100})) == []
    assert sorted(backend.stopped) == sorted(backend.started)
    assert len(backend.stopped) == 3
    cap.begin()  # a fresh window after both channels collected
    assert len(backend.started) == 6


@windows_only
def test_a_window_that_was_never_collected_is_stopped_before_the_next(tmp_path: Path) -> None:
    backend = FakeBackend()
    cap = capture(tmp_path, backend)
    cap.begin()
    cap.begin()
    first = list(backend.started)
    cap.begin()  # the request failed before its end: the stale window must not leak
    assert set(first) <= set(backend.stopped)
    assert len(backend.started) == 6


@windows_only
def test_a_partial_start_stops_what_was_started(tmp_path: Path) -> None:
    backend = FakeBackend()
    backend.fail_start_at = 2
    cap = capture(tmp_path, backend)
    with pytest.raises(EtwError, match="start failed"):
        cap.begin()
    # the session whose start failed half-way is stopped too: its name was recorded before the attempt
    assert len(backend.started) == 2 and len(backend.stopped) == 3
    assert set(backend.started) <= set(backend.stopped)


@windows_only
def test_leaked_sessions_from_an_earlier_run_are_swept_once(tmp_path: Path) -> None:
    backend = FakeBackend()
    backend.live = ["StableNewAi113-0123456789ab"]
    cap = capture(tmp_path, backend)
    cap.begin()
    assert "StableNewAi113-0123456789ab" in backend.stopped
    cap.abort()
    backend.stopped.clear()
    cap.begin()
    assert "StableNewAi113-0123456789ab" not in backend.stopped


def test_the_sweep_only_matches_our_own_session_names_at_the_start_of_a_line() -> None:
    listing = (
        "Data Collector Set                      Type                          Status\n"
        "-------------------------------------------------------------------------------\n"
        "StableNewAi113-0123456789ab             Trace                         Running\n"
        "  StableNewAi113-ba9876543210           Trace                         Running\n"
        "OtherTool for StableNewAi113-deadbeef0000 Trace                       Running\n"
        "StableNewAi113-short                    Trace                         Running\n"
    )
    backend = LogmanBackend(lambda _c: (0, listing))
    assert backend.live_sessions() == ["StableNewAi113-0123456789ab", "StableNewAi113-ba9876543210"]


@windows_only
def test_the_capture_directory_is_absolute_and_a_truncated_xml_is_refused(tmp_path: Path) -> None:
    backend = FakeBackend()
    backend.xml_for = lambda kind: doc(ev(NET, 12, 100, daddr="1.2.3.4", dport=1))
    backend.summary = GOOD_SUMMARY.replace("Processed 40", "Processed 9")  # more than the XML holds
    cap = EtwCapture(
        Path("relative-etw"),
        backend,  # type: ignore[arg-type]
        mapping=lambda: {},
        elevated=lambda: True,
    )
    cap.directory = tmp_path / ".." / tmp_path.name / "etw"
    cap.begin()
    assert cap.directory == cap.directory.resolve()
    with pytest.raises(EtwError, match="processed 9 events but the XML holds"):
        cap.collect("connections", frozenset({100}))


@windows_only
def test_a_lossy_or_unverifiable_trace_raises_at_collection(tmp_path: Path) -> None:
    backend = FakeBackend()
    backend.summary = GOOD_SUMMARY.replace("Lost      0", "Lost      3")
    cap = capture(tmp_path, backend)
    cap.begin()
    with pytest.raises(EtwError, match="lost"):
        cap.collect("connections", frozenset({100}))


def test_without_elevation_coverage_is_unavailable_and_nothing_starts(tmp_path: Path) -> None:
    backend = FakeBackend()
    monitor = etw_host_monitor(
        OwnershipPolicy(), tmp_path / "ev", capture=capture(tmp_path, backend, elevated=False)
    )
    assert {p.coverage for p in monitor.providers} == {UNAVAILABLE}
    problems = monitor.provider_problems()
    assert any(p.startswith("connections: no lifetime_complete provider") for p in problems)
    assert any(p.startswith("files: no lifetime_complete provider") for p in problems)
    with pytest.raises(EtwError, match="elevated"):
        monitor.providers[0].begin()
    assert backend.started == []


@windows_only
def test_elevated_capture_declares_complete_coverage(tmp_path: Path) -> None:
    monitor = etw_host_monitor(
        OwnershipPolicy(), tmp_path / "ev", capture=capture(tmp_path, FakeBackend())
    )
    assert {p.coverage for p in monitor.providers} == {COMPLETE}
    assert monitor.provider_problems() == []


# -- the canary through the monitor (plumbing; the child's events are synthesised) --------------------------------------


@windows_only
def test_canary_plumbing_with_nt_paths_foreign_noise_and_byte_swapped_ports(tmp_path: Path) -> None:
    drive = os.path.splitdrive(str(tmp_path))[0]
    facts: dict[str, object] = {}

    def inner(command, **kwargs):
        facts["marker"], facts["port"] = command[-2], int(command[-1])
        observe = kwargs["observe"]

        def capture_root(child):
            facts["root"] = child.pid
            observe(child)

        return run_bounded(command, **{**kwargs, "observe": capture_root})

    backend = FakeBackend()

    def xml_for(kind: str) -> str:
        root, port, marker = facts["root"], facts["port"], str(facts["marker"])
        swapped = ((port & 0xFF) << 8) | (port >> 8)
        if kind == "network":
            return doc(
                ev(NET, 12, root, PID=root, daddr="127.0.0.1", dport=swapped),
                ev(NET, 12, 1, PID=1, daddr="9.9.9.9", dport=53),
            )
        if kind == "file":
            nt = "\\Device\\HarddiskVolume3" + marker[len(drive) :]
            scratch_nt = nt.rpartition("\\")[0]
            return doc(
                ev(FILE, 12, root, FileObject="0x1", CreateOptions=0x01000000, FileName=nt),
                ev(
                    FILE,
                    12,
                    root,
                    FileObject="0x3",
                    CreateOptions=0x02000000,
                    FileName=scratch_nt + "\\canary-written.bin",
                ),
                ev(
                    FILE,
                    19,
                    root,
                    FileName=scratch_nt + "\\canary-written.bin",
                    NewFileName=scratch_nt + "\\canary-moved.bin",
                ),
                ev(FILE, 26, root, FileName=scratch_nt + "\\canary-moved.bin"),
                ev(
                    FILE,
                    12,
                    2,
                    FileObject="0x2",
                    CreateOptions=0x01000000,
                    FileName="\\Device\\HarddiskVolume3\\noise",
                ),
            )
        return doc()

    backend.xml_for = xml_for
    cap = EtwCapture(
        tmp_path / "etw",
        backend,  # type: ignore[arg-type]
        mapping=lambda: {"\\device\\harddiskvolume3": drive},
        elevated=lambda: True,
    )
    monitor = etw_host_monitor(OwnershipPolicy(), tmp_path / "ev", capture=cap)
    report = monitor.run_canary(inner)
    assert report == {
        "passed": True,
        "saw": {"descendant": True, "files": True, "writes": True, "connections": True},
    }
    assert monitor.readiness() == []
    assert sorted(backend.stopped) == sorted(backend.started)


@windows_only
def test_canary_fails_when_the_trace_does_not_contain_the_childs_events(tmp_path: Path) -> None:
    backend = FakeBackend()  # every converted trace is empty: a blind capture
    cap = capture(tmp_path, backend)
    monitor = etw_host_monitor(OwnershipPolicy(), tmp_path / "ev", capture=cap)
    report = monitor.run_canary()
    assert report["passed"] is False
    assert any("canary did not show" in p for p in monitor.readiness())


# -- live (elevated only) ------------------------------------------------------------------------------------------------


@pytest.mark.skipif(not etw.is_elevated(), reason="a live ETW trace needs an elevated process")
def test_live_etw_canary_proves_the_channels(tmp_path: Path) -> None:
    monitor = etw_host_monitor(OwnershipPolicy(), tmp_path / "ev")
    try:
        report = monitor.run_canary()
        assert monitor.readiness() == [], report
    finally:
        monitor.close()
    assert LogmanBackend().live_sessions() == [], "no trace session is left running"
