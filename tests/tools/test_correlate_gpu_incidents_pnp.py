from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

GPU_ID = "PCI\\VEN_10DE&DEV_2782&SUBSYS_13B5196E&REV_A1\\4&341ca995&0&0008"
OTHER_ID = "PCI\\VEN_8086&DEV_1234&SUBSYS_00000000&REV_01\\3&11583659&0&FE"
INCIDENT = "2026-10-17T16:49:25.546Z"


def _load_tool():
    path = Path("tools/diagnostics/correlate_gpu_incidents.py")
    spec = importlib.util.spec_from_file_location("correlate_gpu_incidents_pnp", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _event_xml(
    *,
    when: str = "2026-10-17T16:49:24.8062977Z",
    device: str = GPU_ID,
    veto_type: str = "8",
    veto_name: str | None = None,
    provider: str = "Microsoft-Windows-Kernel-PnP",
    channel: str = "Microsoft-Windows-Kernel-PnP/Device Management",
    event_id: int = 1000,
    record_id: int = 3490,
) -> str:
    veto_name = veto_name if veto_name is not None else device
    return (
        "<Event xmlns='http://schemas.microsoft.com/win/2004/08/events/event'><System>"
        f"<Provider Name='{provider}' Guid='{{9c205a39-1250-487d-abd7-e831c6290539}}'/>"
        f"<EventID>{event_id}</EventID><Version>0</Version><Level>3</Level>"
        f"<TimeCreated SystemTime='{when}'/><EventRecordID>{record_id}</EventRecordID>"
        f"<Channel>{channel}</Channel><Computer>Rob-Gaming-Desk</Computer></System>"
        "<EventData>"
        f"<Data Name='DeviceInstanceId'>{device.replace('&', '&amp;')}</Data>"
        f"<Data Name='VetoType'>{veto_type}</Data>"
        f"<Data Name='VetoName'>{veto_name.replace('&', '&amp;')}</Data>"
        "</EventData></Event>"
    )


def _session_sample() -> dict[str, object]:
    return {
        "timestamp_utc": "2026-10-17T16:49:20+00:00",
        "kind": "sample",
        "scope": "session",
        "job_id": "session-4242",
    }


def test_parser_extracts_the_structured_fields_of_event_1000() -> None:
    tool = _load_tool()

    (event,) = tool.parse_pnp_events_xml([_event_xml()])

    assert event["timestamp_utc"].startswith("2026-10-17T16:49:24.8062")
    assert event["device_instance_id"] == GPU_ID
    assert event["veto_type"] == 8
    assert event["veto_type_label"] == "IllegalDeviceRequest"
    assert event["vetoed_by"] == GPU_ID
    assert event["event_record_id"] == 3490
    assert (event["provider"], event["channel"], event["event_id"]) == (
        "Microsoft-Windows-Kernel-PnP",
        "Microsoft-Windows-Kernel-PnP/Device Management",
        1000,
    )


def test_parser_requires_the_exact_provider_channel_and_event_id_and_skips_malformed_input() -> (
    None
):
    tool = _load_tool()

    events = tool.parse_pnp_events_xml(
        [
            _event_xml(event_id=1001),
            _event_xml(provider="Some-Other-Provider"),
            _event_xml(channel="Microsoft-Windows-Kernel-PnP/Configuration"),
            _event_xml(when="not-a-time"),
            "<Event><not-closed>",
            "",
            _event_xml(veto_type="not-a-number"),
        ]
    )

    assert len(events) == 1
    assert events[0]["veto_type"] is None and events[0]["veto_type_label"] is None


def test_marker_near_incident_reports_the_signed_time_difference_and_veto_details() -> None:
    tool = _load_tool()
    pnp = tool.PnpRead(tool.parse_pnp_events_xml([_event_xml(veto_name="SomeDriver.sys")]), "ok")

    result = tool.correlate(
        [{"timestamp_utc": INCIDENT}],
        jobs=[],
        telemetry=[],
        webui_log_files=[],
        pnp=pnp,
        gpu_device_ids=[GPU_ID.lower()],
    )

    section = result[0]["windows_pnp"]
    assert section["status"] == "marker_near_incident"
    (marker,) = section["markers"]
    assert marker["delta_seconds"] == pytest.approx(-0.74, abs=0.001)
    assert marker["relation"] == "before_incident"
    assert marker["veto_type"] == 8 and marker["vetoed_by"] == "SomeDriver.sys"
    assert "does not establish hardware failure" in section["interpretation"]


def test_marker_after_the_incident_has_a_positive_delta() -> None:
    tool = _load_tool()
    pnp = tool.PnpRead(
        tool.parse_pnp_events_xml([_event_xml(when="2026-10-17T16:49:31.546Z")]), "ok"
    )

    (entry,) = tool.correlate(
        [{"timestamp_utc": INCIDENT}],
        jobs=[],
        telemetry=[],
        webui_log_files=[],
        pnp=pnp,
        gpu_device_ids=[GPU_ID],
    )

    (marker,) = entry["windows_pnp"]["markers"]
    assert marker["delta_seconds"] == pytest.approx(6.0)
    assert marker["relation"] == "after_incident"


def test_an_event_for_an_unrelated_device_is_not_a_marker() -> None:
    tool = _load_tool()
    pnp = tool.PnpRead(tool.parse_pnp_events_xml([_event_xml(device=OTHER_ID)]), "ok")

    (entry,) = tool.correlate(
        [{"timestamp_utc": INCIDENT}],
        jobs=[],
        telemetry=[],
        webui_log_files=[],
        pnp=pnp,
        gpu_device_ids=[GPU_ID],
    )

    assert entry["windows_pnp"]["status"] == "no_marker_near_incident"
    assert entry["windows_pnp"]["markers"] == []
    assert "interpretation" not in entry["windows_pnp"]


def test_an_event_outside_the_window_is_not_a_marker_but_a_wider_window_finds_it() -> None:
    tool = _load_tool()
    events = tool.parse_pnp_events_xml([_event_xml(when="2026-10-17T16:40:00Z")])
    kwargs = {
        "jobs": [],
        "telemetry": [],
        "webui_log_files": [],
        "pnp": tool.PnpRead(events, "ok"),
        "gpu_device_ids": [GPU_ID],
    }

    (narrow,) = tool.correlate(
        [{"timestamp_utc": INCIDENT}], pnp_window=timedelta(seconds=120), **kwargs
    )
    (wide,) = tool.correlate(
        [{"timestamp_utc": INCIDENT}], pnp_window=timedelta(minutes=15), **kwargs
    )

    assert narrow["windows_pnp"]["status"] == "no_marker_near_incident"
    assert wide["windows_pnp"]["status"] == "marker_near_incident"
    assert wide["windows_pnp"]["markers"][0]["delta_seconds"] < 0


def test_markers_are_ordered_nearest_first() -> None:
    tool = _load_tool()
    events = tool.parse_pnp_events_xml(
        [
            _event_xml(when="2026-10-17T16:48:40Z", record_id=1),
            _event_xml(when="2026-10-17T16:49:24Z", record_id=2),
        ]
    )

    markers = tool.match_pnp_markers(
        datetime(2026, 10, 17, 16, 49, 25, tzinfo=UTC),
        events,
        device_ids=[GPU_ID],
        window=timedelta(minutes=2),
    )

    assert [marker["event_record_id"] for marker in markers] == [2, 1]


def test_unreadable_event_log_and_unknown_gpu_are_reported_not_guessed() -> None:
    tool = _load_tool()
    common = {"jobs": [], "telemetry": [], "webui_log_files": []}

    (denied,) = tool.correlate(
        [{"timestamp_utc": INCIDENT}],
        pnp=tool.PnpRead(
            None, "log_inaccessible", "Attempted to perform an unauthorized operation."
        ),
        gpu_device_ids=[GPU_ID],
        **common,
    )
    (unknown,) = tool.correlate(
        [{"timestamp_utc": INCIDENT}],
        pnp=tool.PnpRead(tool.parse_pnp_events_xml([_event_xml()]), "ok"),
        gpu_device_ids=[],
        **common,
    )
    (not_requested,) = tool.correlate([{"timestamp_utc": INCIDENT}], **common)

    assert denied["windows_pnp"]["status"] == "unavailable_log_inaccessible"
    assert "unauthorized" in denied["windows_pnp"]["detail"]
    assert denied["windows_pnp"]["markers"] == []
    assert unknown["windows_pnp"]["status"] == "gpu_device_unknown"
    assert unknown["windows_pnp"]["markers"] == []
    assert not_requested["windows_pnp"] == {"status": "not_requested", "markers": []}


def test_a_pnp_marker_does_not_change_the_stablenew_activity_classification() -> None:
    tool = _load_tool()
    pnp = tool.PnpRead(tool.parse_pnp_events_xml([_event_xml()]), "ok")

    (entry,) = tool.correlate(
        [{"timestamp_utc": INCIDENT}],
        jobs=[],
        telemetry=[_session_sample()],
        webui_log_files=[],
        pnp=pnp,
        gpu_device_ids=[GPU_ID],
    )

    assert entry["windows_pnp"]["status"] == "marker_near_incident"
    assert entry["classification"] == "stablenew_open_no_proven_active_generation"


def test_a_marker_with_no_stablenew_evidence_stays_unclassified() -> None:
    tool = _load_tool()
    pnp = tool.PnpRead(tool.parse_pnp_events_xml([_event_xml()]), "ok")

    (entry,) = tool.correlate(
        [{"timestamp_utc": INCIDENT}], jobs=None, telemetry=None, webui_log_files=None, pnp=pnp,
        gpu_device_ids=[GPU_ID],
    )  # fmt: skip

    assert entry["classification"] == "evidence_unavailable"


# --- the reader: environment handling and read-only guarantees ----------------------------------------------------


def _since_until():
    base = datetime(2026, 10, 17, 16, 49, 25, tzinfo=UTC)
    return base - timedelta(minutes=2), base + timedelta(minutes=2)


def test_reader_reports_non_windows_hosts_without_running_anything() -> None:
    tool = _load_tool()
    calls: list[str] = []

    def _runner(script: str):
        calls.append(script)
        return 0, "", ""

    result = tool.read_windows_pnp_events(
        since=_since_until()[0], until=_since_until()[1], runner=_runner, platform="linux"
    )

    assert (result.events, result.status) == (None, "unavailable_not_windows")
    assert calls == []


def test_reader_parses_runner_output_and_treats_no_matching_events_as_an_empty_read() -> None:
    tool = _load_tool()
    since, until = _since_until()

    found = tool.read_windows_pnp_events(
        since=since,
        until=until,
        runner=lambda _s: (
            0,
            _event_xml() + "\n" + _event_xml(device=OTHER_ID, record_id=7) + "\nnoise\n",
            "",
        ),
        platform="win32",
    )
    empty = tool.read_windows_pnp_events(
        since=since, until=until, runner=lambda _s: (0, "", ""), platform="win32"
    )

    assert found.status == "ok" and len(found.events) == 2
    assert empty.status == "ok" and empty.events == []


@pytest.mark.parametrize(
    ("raises", "returncode", "stderr", "expected"),
    [
        (FileNotFoundError("no powershell"), 0, "", "powershell_unavailable"),
        (subprocess.TimeoutExpired(cmd="powershell", timeout=30), 0, "", "timeout"),
        (PermissionError("denied"), 0, "", "error"),
        (None, 3, "Attempted to perform an unauthorized operation.", "log_inaccessible"),
    ],
)
def test_reader_reports_why_the_log_could_not_be_read(raises, returncode, stderr, expected) -> None:
    tool = _load_tool()

    def _runner(_script: str):
        if raises is not None:
            raise raises
        return returncode, "", stderr

    result = tool.read_windows_pnp_events(
        since=_since_until()[0], until=_since_until()[1], runner=_runner, platform="win32"
    )

    assert result.events is None
    assert result.status == expected


def test_reader_scripts_only_read_and_target_the_exact_channel_and_event() -> None:
    tool = _load_tool()
    scripts: list[str] = []

    def _runner(script: str):
        scripts.append(script)
        return 0, "", ""

    tool.read_windows_pnp_events(
        since=_since_until()[0], until=_since_until()[1], runner=_runner, platform="win32"
    )
    tool.read_gpu_device_ids(runner=_runner, platform="win32")

    assert len(scripts) == 2
    assert "Get-WinEvent" in scripts[0] and "Get-PnpDevice" in scripts[1]
    assert "LogName='Microsoft-Windows-Kernel-PnP/Device Management'" in scripts[0]
    assert "Id=1000" in scripts[0]
    forbidden = re.compile(
        r"\b(Set|Remove|Clear|New|Stop|Start|Restart|Disable|Enable|Invoke|Add|Write|Out)-[A-Za-z]+|wevtutil|"
        r"Restart-|taskkill|shutdown|pnputil|devcon",
        re.IGNORECASE,
    )
    for script in scripts:
        assert forbidden.search(script) is None, script


def test_gpu_device_ids_are_limited_to_the_requested_vendor() -> None:
    tool = _load_tool()
    listing = f"{GPU_ID}\n{OTHER_ID}\n"

    ids, status = tool.read_gpu_device_ids(runner=lambda _s: (0, listing, ""), platform="win32")
    unreadable, why = tool.read_gpu_device_ids(runner=lambda _s: (3, "", "boom"), platform="win32")
    off_windows, reason = tool.read_gpu_device_ids(platform="linux")

    assert (ids, status) == ([GPU_ID], "ok")
    assert (unreadable, why) == (None, "log_inaccessible")
    assert (off_windows, reason) == (None, "unavailable_not_windows")


# --- command line ---------------------------------------------------------------------------------------------------


def _run_main(tool, monkeypatch, tmp_path, *extra: str) -> dict:
    out = tmp_path / "timeline.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["correlate_gpu_incidents.py", "--incident", INCIDENT, "--out", str(out), *extra],
    )
    assert tool.main() == 0
    return json.loads(out.read_text(encoding="utf-8"))["timeline"][0]


def test_command_line_matches_offline_exported_events_to_the_given_gpu(
    tmp_path, monkeypatch
) -> None:
    tool = _load_tool()
    exported = tmp_path / "events.xml"
    exported.write_text(
        _event_xml() + "\n" + _event_xml(device=OTHER_ID, record_id=9) + "\n", encoding="utf-8"
    )

    entry = _run_main(
        tool, monkeypatch, tmp_path, "--pnp-events-xml", str(exported), "--gpu-instance-id", GPU_ID
    )

    assert entry["windows_pnp"]["status"] == "marker_near_incident"
    assert [m["device_instance_id"] for m in entry["windows_pnp"]["markers"]] == [GPU_ID]


def test_command_line_reports_a_missing_exported_events_file(tmp_path, monkeypatch) -> None:
    tool = _load_tool()

    entry = _run_main(
        tool,
        monkeypatch,
        tmp_path,
        "--pnp-events-xml",
        str(tmp_path / "absent.xml"),
        "--gpu-instance-id",
        GPU_ID,
    )

    assert entry["windows_pnp"]["status"] == "unavailable_events_file_missing"


def test_command_line_without_pnp_flags_does_not_touch_windows(tmp_path, monkeypatch) -> None:
    tool = _load_tool()

    def _boom(*_a, **_k):
        raise AssertionError("must not read the event log unless asked")

    monkeypatch.setattr(tool, "read_windows_pnp_events", _boom)
    monkeypatch.setattr(tool, "read_gpu_device_ids", _boom)

    entry = _run_main(tool, monkeypatch, tmp_path)

    assert entry["windows_pnp"] == {"status": "not_requested", "markers": []}
