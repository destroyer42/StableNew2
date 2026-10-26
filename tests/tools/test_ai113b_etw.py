"""PR-AI-QUAL-113B / 114E: tracerpt conversion and event parsing, proven without a live trace.

The capture is started by the operator (``test_ai114e_capture_control.py``); this module is the standard-user parsing half.
Everything here uses synthetic tracerpt-shaped XML, so it proves parsing, timestamps, attribution inputs and loss accounting.
It does NOT prove that this host's real ETW output has the shape assumed here; the live canary does.
"""

from __future__ import annotations

import sys
from pathlib import Path, PureWindowsPath

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.qualification.ai111.etw import (  # noqa: E402
    EtwError,
    check_no_loss,
    convert_trace,
    file_events,
    iter_raw_events,
    make_to_dos,
    network_events,
    parse_system_time,
)

NS = "http://schemas.microsoft.com/win/2004/08/events/event"
NET = "Microsoft-Windows-Kernel-Network"
FILE = "Microsoft-Windows-Kernel-File"
GOOD_SUMMARY = "Total Buffers Processed 3\nTotal Events  Processed 40\nTotal Events  Lost      0\nBuffers Lost 0\n"


def ev(provider: str, event_id: int, pid: int, time: str | None = None, **data: object) -> str:
    items = "".join(f'<Data Name="{k}">{v}</Data>' for k, v in data.items())
    stamp = f'<TimeCreated SystemTime="{time}"/>' if time else ""
    return (
        f'<Event xmlns="{NS}"><System><Provider Name="{provider}"/><EventID>{event_id}</EventID>{stamp}'
        f'<Execution ProcessID="{pid}" ThreadID="1"/></System><EventData>{items}</EventData></Event>'
    )


def doc(*events: str) -> str:
    return "<Events>" + "".join(events) + "</Events>"


def raw(tmp_path: Path, *events: str):
    path = tmp_path / "t.xml"
    path.write_text(doc(*events), encoding="utf-8")
    return iter_raw_events(path)


# -- conversion -------------------------------------------------------------------------------------------------------


def test_conversion_uses_the_absolute_tracerpt_and_discards_stale_output(tmp_path: Path) -> None:
    commands: list[list[str]] = []

    def run(command):
        commands.append(list(command))
        return 0, ""

    (tmp_path / "f.xml").write_text("stale", encoding="utf-8")
    (tmp_path / "f.txt").write_text("stale", encoding="utf-8")
    convert_trace(tmp_path / "f.etl", tmp_path / "f.xml", tmp_path / "f.txt", run)
    assert not (tmp_path / "f.xml").exists() and not (tmp_path / "f.txt").exists(), (
        "a stale output must not survive into the conversion"
    )
    (convert,) = commands
    assert PureWindowsPath(convert[0]).is_absolute(), (
        "the OS tool is never resolved through PATH or the cwd"
    )
    assert PureWindowsPath(convert[0]).name == "tracerpt.exe"
    assert "-of" in convert and convert[convert.index("-of") + 1] == "XML"


def test_a_failing_conversion_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(EtwError, match="Access is denied"):
        convert_trace(
            tmp_path / "x.etl",
            tmp_path / "x.xml",
            tmp_path / "x.txt",
            lambda _c: (5, "Access is denied."),
        )


# -- timestamps -------------------------------------------------------------------------------------------------------


def test_trace_timestamps_become_epoch_nanoseconds_with_their_offset() -> None:
    local = parse_system_time("2026-10-25T15:16:37.258121100-04:00")
    utc = parse_system_time("2026-10-25T19:16:37.258121100Z")
    assert local == utc and utc is not None
    assert utc % 1_000_000_000 == 258_121_100
    assert parse_system_time("2026-10-25T19:16:37Z") == utc - 258_121_100
    assert (
        parse_system_time("2026-10-25T19:16:37.5Z")
        == parse_system_time("2026-10-25T19:16:37Z") + 500_000_000
    )


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "yesterday",
        "2026-10-25 19:16:37Z",
        "2026-13-25T19:16:37Z",
        "2026-10-25T19:16:37",
        "2026-10-25T19:16:37+25:00",
    ],
)
def test_an_unreadable_timestamp_is_none_never_a_guess(text: str | None) -> None:
    assert parse_system_time(text) is None


def test_events_carry_their_timestamp_and_events_without_one_stay_unstamped(tmp_path: Path) -> None:
    events = raw(
        tmp_path,
        ev(NET, 12, 100, "2026-10-25T19:16:37.5Z", daddr="10.0.0.9", dport=443),
        ev(NET, 12, 100, daddr="10.0.0.9", dport=444),
        ev(NET, 12, 100, "not a time", daddr="10.0.0.9", dport=445),
    )
    out = network_events(events, frozenset({100}))
    assert [e.ts_ns is not None for e in out] == [True, False, False]


def test_file_events_keep_the_time_of_the_access(tmp_path: Path) -> None:
    opened = 0x01000000
    events = raw(
        tmp_path,
        ev(
            FILE,
            12,
            100,
            "2026-10-25T19:00:01Z",
            FileObject="0x1",
            CreateOptions=opened,
            FileName="\\Device\\HarddiskVolume3\\a.txt",
        ),
        ev(FILE, 16, 100, "2026-10-25T19:00:05Z", FileObject="0x1"),
        ev(FILE, 26, 100, "2026-10-25T19:00:09Z", FileName="\\Device\\HarddiskVolume3\\gone.txt"),
    )
    out = {
        e.detail: e
        for e in file_events(
            events, frozenset({100}), make_to_dos({"\\device\\harddiskvolume3": "C:"})
        )
    }
    assert out["C:\\a.txt"].mode == "write" and out["C:\\a.txt"].ts_ns == parse_system_time(
        "2026-10-25T19:00:01Z"
    )
    assert out["C:\\gone.txt"].ts_ns == parse_system_time("2026-10-25T19:00:09Z")


def test_the_same_unresolved_kind_in_different_seconds_is_reported_each_time(
    tmp_path: Path,
) -> None:
    events = raw(
        tmp_path,
        ev(FILE, 26, 100, "2026-10-25T19:00:01Z"),
        ev(FILE, 26, 100, "2026-10-25T19:00:01Z"),
        ev(FILE, 26, 100, "2026-10-25T19:00:30Z"),  # a recycled pid later in a long capture
    )
    out = file_events(events, frozenset({100}), make_to_dos({}))
    assert len(out) == 2


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
