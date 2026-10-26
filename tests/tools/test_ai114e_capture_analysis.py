"""PR-AI-QUAL-114E: the unprivileged analysis of a stopped session-level capture, proven on synthetic traces.

One finite capture holds several bounded requests; these tests prove that events are attributed by process identity AND time,
that a clock-domain or integrity problem makes the capture INCONCLUSIVE (never PASS), and that nothing foreign leaks into the
result. They prove the analyzer's logic on tracerpt-shaped XML; the live canary is what proves the real XML has this shape.
"""

from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tests.tools import ai114e_support as sup  # noqa: E402
from tests.tools.ai114e_support import (  # noqa: E402
    FIXED_NOW,
    FakeLogman,
    Scenario,
    add_beacon,
    add_canary,
    add_request,
    canary_scenario,
    drive_mapping,
    make_env,
    request_event,
    started_capture,
    stopped_capture,
    write_capture,
)
from tools.qualification.ai111 import capture_analysis as analysis  # noqa: E402
from tools.qualification.ai111 import capture_control as control  # noqa: E402
from tools.qualification.ai111.ownership import ChannelEvent  # noqa: E402

ALLOWED_READ = "C:\\ai\\root\\input.txt"
ALLOWED_WRITE = "C:\\ai\\root\\work\\out.bin"
OUTSIDE = "C:\\Users\\someone\\private\\secret.txt"


def run_analysis(
    tmp_path: Path,
    build,
    *,
    stop_minutes: int = 0,
    minutes: int = 30,
    convert_wrapper=None,
    free: int = 10**13,
    after_write=None,
    **scenario_overrides: Any,
):
    logman = FakeLogman()
    if stop_minutes:
        target, report, _env = started_capture(tmp_path, logman, minutes=minutes, max_mb=64)
        stop_env = make_env(
            tmp_path, logman, now=lambda: FIXED_NOW + timedelta(minutes=stop_minutes)
        )
        control.stop_capture(report["capture_id"], evidence_dir=target, env=stop_env)
        env = stop_env
    else:
        target, report, env = stopped_capture(tmp_path, logman, minutes=minutes, max_mb=64)
    scenario = build(tmp_path, target)
    for key, value in scenario_overrides.items():
        setattr(scenario, key, value)
    convert = write_capture(scenario, target, report)
    if after_write:
        after_write(target)
    if convert_wrapper:
        convert = convert_wrapper(convert)
    result = analysis.analyze(
        target,
        tools=env.tools,
        convert=convert,
        now=lambda: FIXED_NOW + timedelta(minutes=stop_minutes),
        reports_root=env.reports_root,
        mapping=drive_mapping,
        free_bytes=lambda path: free,
    )
    return result, target, scenario


def qualification(tmp_path: Path, target: Path, body) -> Scenario:
    def middle(s: Scenario) -> None:
        body(s)

    return canary_scenario(tmp_path, target, middle=middle)


def row(result: dict, number: int) -> dict:
    return next(r for r in result["requests"] if r["number"] == number)


# -- a sound capture ----------------------------------------------------------------------------------------------------


def test_a_canary_capture_that_saw_every_known_operation_passes(tmp_path: Path) -> None:
    result, target, _ = run_analysis(tmp_path, lambda t, d: canary_scenario(t, d))
    assert result["verdict"] == "PASS", result["capture_problems"]
    assert result["kind"] == "canary_capture"
    assert result["capture_problems"] == []
    assert result["clock"]["beacons_used"] == 2 and result["clock"]["uncertainty_ms"] < 1
    assert (target / "analysis.json").is_file() and (target / "verification.json").is_file()
    assert not list(target.glob("*.xml")), (
        "the large derived XML is removed after a completed analysis"
    )
    assert result["attribution"]["ambiguous_events"] == 0


def test_a_qualification_capture_with_compliant_requests_passes(tmp_path: Path) -> None:
    def body(s: Scenario) -> None:
        a = add_request(s, pid=6001)
        request_event(s, a, "read", offset_ms=20, path=ALLOWED_READ)
        request_event(s, a, "write", offset_ms=40, path=ALLOWED_WRITE)
        b = add_request(s, pid=6002)
        request_event(s, b, "read", offset_ms=20, path="C:\\Windows\\System32\\kernel32.dll")

    result, _, _ = run_analysis(tmp_path, lambda t, d: qualification(t, d, body))
    assert result["verdict"] == "PASS", (result["capture_problems"], result["requests"])
    assert result["kind"] == "qualification_capture"
    assert row(result, 2)["owned_file_events"] == 2 and row(result, 3)["owned_file_events"] == 1
    assert row(result, 2)["violations"] == [] and row(result, 3)["violations"] == []


def test_several_requests_with_different_pids_are_attributed_separately(tmp_path: Path) -> None:
    def body(s: Scenario) -> None:
        a = add_request(s, pid=6001)
        b = add_request(s, pid=6002)
        request_event(s, a, "read", offset_ms=30, path=ALLOWED_READ)
        request_event(s, b, "write", offset_ms=30, path=OUTSIDE)

    result, _, _ = run_analysis(tmp_path, lambda t, d: qualification(t, d, body))
    assert result["verdict"] == "FAIL"
    assert row(result, 2)["violations"] == [] and row(result, 3)["violations"] == [
        "file_access_outside_policy"
    ]


def test_a_descendant_with_its_own_pid_is_attributed_to_the_request(tmp_path: Path) -> None:
    def body(s: Scenario) -> None:
        members = [
            {"pid": 6001, "start_ns": s.counter + 20_000_000, "end_ns": s.counter + 118_000_000},
            {"pid": 6101, "start_ns": s.counter + 20_000_000, "end_ns": s.counter + 117_000_000},
        ]
        request = add_request(s, pid=6001, members=members, violations=["unexpected_descendants"])
        request_event(s, request, "write", offset_ms=40, pid=6101, path=OUTSIDE)

    result, _, _ = run_analysis(tmp_path, lambda t, d: qualification(t, d, body))
    assert result["verdict"] == "FAIL"
    assert set(row(result, 2)["violations"]) == {
        "unexpected_descendants",
        "file_access_outside_policy",
    }


# -- violations ---------------------------------------------------------------------------------------------------------


def test_a_connection_attempt_by_an_owned_process_is_an_egress_violation(tmp_path: Path) -> None:
    def body(s: Scenario) -> None:
        a = add_request(s, pid=6001)
        request_event(s, a, "connect", offset_ms=40)

    result, _, _ = run_analysis(tmp_path, lambda t, d: qualification(t, d, body))
    assert result["verdict"] == "FAIL"
    assert row(result, 2)["violations"] == ["egress_attempt_observed"]
    assert row(result, 2)["connection_attempts"] == ["203.0.113.9:443"]


def test_a_write_outside_the_write_roots_and_a_read_outside_the_read_roots_fail(
    tmp_path: Path,
) -> None:
    def body(s: Scenario) -> None:
        a = add_request(s, pid=6001)
        request_event(s, a, "read", offset_ms=30, path=OUTSIDE)
        b = add_request(s, pid=6002)
        request_event(s, b, "write", offset_ms=30, path=ALLOWED_READ)  # inside a READ root only

    result, _, _ = run_analysis(tmp_path, lambda t, d: qualification(t, d, body))
    assert result["verdict"] == "FAIL"
    assert (
        row(result, 2)["violations"]
        == row(result, 3)["violations"]
        == ["file_access_outside_policy"]
    )
    assert row(result, 2)["files_outside_policy"] == [OUTSIDE]


def test_realtime_findings_survive_into_the_analysis(tmp_path: Path) -> None:
    def body(s: Scenario) -> None:
        add_request(
            s, pid=6001, violations=["child_token_elevated"], token_elevated=True, complete=False
        )

    result, _, _ = run_analysis(tmp_path, lambda t, d: qualification(t, d, body))
    assert result["verdict"] == "FAIL"
    assert {"child_token_elevated", "teardown_not_verified"} <= set(row(result, 2)["violations"])


# -- pid and time attribution -------------------------------------------------------------------------------------------


def test_a_reused_pid_is_attributed_by_time_not_by_number(tmp_path: Path) -> None:
    def body(s: Scenario) -> None:
        a = add_request(s, pid=7000)
        request_event(s, a, "read", offset_ms=30, path=ALLOWED_READ)
        s.tick(500)
        b = add_request(s, pid=7000)  # the OS reused the number for the next request's root
        request_event(s, b, "write", offset_ms=30, path=OUTSIDE)
        # in the gap between them the same number belongs to some unrelated process
        gap = to_gap = a["end_ns"] + 250_000_000
        s.events["file"].append(
            sup.event_xml(
                sup.FILE, 26, 7000, sup.to_trace(gap), FileName=sup.dos("C:\\other\\unrelated.txt")
            )
        )
        assert to_gap

    result, _, _ = run_analysis(tmp_path, lambda t, d: qualification(t, d, body))
    assert row(result, 2)["violations"] == []
    assert row(result, 3)["violations"] == ["file_access_outside_policy"], (
        "only the second request's own event"
    )
    assert result["attribution"]["recycled_pid_events"] == 1
    assert "unrelated.txt" not in json.dumps(result), (
        "the recycled process's activity is a count, not a record"
    )


def test_an_event_long_before_creation_or_after_termination_is_a_recycled_pid(
    tmp_path: Path,
) -> None:
    def body(s: Scenario) -> None:
        a = add_request(s, pid=6001)
        request_event(s, a, "write", offset_ms=-300, path=OUTSIDE)
        request_event(s, a, "write", offset_ms=400, path=OUTSIDE)
        request_event(s, a, "read", offset_ms=30, path=ALLOWED_READ)

    result, _, _ = run_analysis(tmp_path, lambda t, d: qualification(t, d, body))
    assert result["verdict"] == "PASS", (result["capture_problems"], result["requests"])
    assert result["attribution"]["recycled_pid_events"] == 2


@pytest.mark.parametrize("offset_ms", [-2.0, 99.5, 101.0])
def test_an_event_at_a_window_boundary_is_an_explicit_ambiguity(
    tmp_path: Path, offset_ms: float
) -> None:
    def body(s: Scenario) -> None:
        a = add_request(s, pid=6001)
        request_event(s, a, "write", offset_ms=offset_ms, path=ALLOWED_WRITE)

    result, _, _ = run_analysis(tmp_path, lambda t, d: qualification(t, d, body))
    assert result["verdict"] == "INCONCLUSIVE"
    assert "ambiguous_attribution" in row(result, 2)["violations"]
    assert result["attribution"]["ambiguous_events"] == 1
    assert row(result, 2)["ambiguous_samples"][0]["pid"] == 6001


def test_a_process_that_exits_right_after_an_event_keeps_the_event_owned(tmp_path: Path) -> None:
    def body(s: Scenario) -> None:
        a = add_request(s, pid=6001)  # exits 1 ms before the request ends (99 ms)
        request_event(s, a, "write", offset_ms=40, path=ALLOWED_WRITE)

    result, _, _ = run_analysis(tmp_path, lambda t, d: qualification(t, d, body))
    assert result["verdict"] == "PASS"
    assert row(result, 2)["owned_file_events"] == 1


@pytest.mark.parametrize("offset_ms", [4.0, 98.0, 98.7])
def test_an_event_just_inside_the_measured_window_is_owned_not_ambiguous(
    tmp_path: Path, offset_ms: float
) -> None:
    """Live finding (2026-10-25): shutdown reads of kernel.appcore.dll land within ~0.7 ms of the observed exit."""

    def body(s: Scenario) -> None:
        a = add_request(s, pid=6001)  # the member's window is 0 .. 99 ms
        request_event(s, a, "read", offset_ms=offset_ms, path=ALLOWED_READ)

    result, _, _ = run_analysis(tmp_path, lambda t, d: qualification(t, d, body))
    assert result["verdict"] == "PASS", (result["capture_problems"], result["requests"])
    assert row(result, 2)["owned_file_events"] == 1 and row(result, 2)["ambiguous_events"] == 0


def test_slack_never_widens_what_counts_as_owned_only_what_counts_as_outside() -> None:
    clock = analysis.ClockMap(0, 0, 2)
    request = {
        "number": 1,
        "start_ns": 1_000_000_000,
        "end_ns": 2_000_000_000,
        "members": [{"pid": 10, "start_ns": 1_000_000_000, "end_ns": 2_000_000_000}],
    }

    def place(ts_ns: int):
        return analysis.attribute_events([ChannelEvent(10, "x", ts_ns, "write")], [request], clock)

    assert len(place(1_999_999_000).owned[1]) == 1  # 1 us before the end: owned
    assert len(place(2_000_001_000).ambiguous[1]) == 1  # 1 us after the end: ambiguous, not owned
    assert len(place(2_004_999_000).ambiguous[1]) == 1  # still within the slack: ambiguous
    assert (
        place(2_010_000_000).recycled_pid_events == 1
    )  # 10 ms after the end: clearly another process
    assert place(990_000_000).recycled_pid_events == 1


def test_an_owned_event_with_no_timestamp_is_ambiguous(tmp_path: Path) -> None:
    def body(s: Scenario) -> None:
        add_request(s, pid=6001)
        s.events["file"].append(
            sup.event_xml(sup.FILE, 26, 6001, None, FileName=sup.dos(ALLOWED_WRITE))
        )

    result, _, _ = run_analysis(tmp_path, lambda t, d: qualification(t, d, body))
    assert result["verdict"] == "INCONCLUSIVE"
    assert row(result, 2)["ambiguous_events"] == 1


def test_unrelated_host_activity_is_neither_judged_nor_disclosed(tmp_path: Path) -> None:
    def body(s: Scenario) -> None:
        a = add_request(s, pid=6001)
        request_event(s, a, "read", offset_ms=30, path=ALLOWED_READ)
        request_event(s, a, "connect", offset_ms=30, pid=4242, addr="198.51.100.77", port=8443)
        request_event(s, a, "write", offset_ms=30, pid=4242, path="C:\\Users\\other\\diary.txt")

    result, _, _ = run_analysis(tmp_path, lambda t, d: qualification(t, d, body))
    assert result["verdict"] == "PASS"
    text = json.dumps(result)
    assert "198.51.100.77" not in text and "diary.txt" not in text


def test_events_that_name_no_process_inside_a_request_make_the_capture_inconclusive(
    tmp_path: Path,
) -> None:
    def body(s: Scenario) -> None:
        a = add_request(s, pid=6001)
        request_event(s, a, "read", offset_ms=30, path=ALLOWED_READ)
        s.events["file"].append(
            sup.event_xml(
                sup.FILE, 12, 0, sup.to_trace(a["start_ns"] + 30_000_000), FileName=sup.dos(OUTSIDE)
            )
        )

    result, _, _ = run_analysis(tmp_path, lambda t, d: qualification(t, d, body))
    assert result["verdict"] == "INCONCLUSIVE"
    assert result["attribution"]["unidentified_events_possibly_inside_a_request"] == 1
    assert any("name no process" in p for p in result["capture_problems"])


def test_events_that_name_no_process_outside_every_request_do_not_matter(tmp_path: Path) -> None:
    def body(s: Scenario) -> None:
        a = add_request(s, pid=6001)
        s.events["file"].append(
            sup.event_xml(
                sup.FILE,
                12,
                0,
                sup.to_trace(a["end_ns"] + 2_000_000_000),
                FileName=sup.dos(OUTSIDE),
            )
        )

    result, _, _ = run_analysis(tmp_path, lambda t, d: qualification(t, d, body))
    assert result["verdict"] == "PASS"
    assert result["attribution"]["unidentified_events_total"] >= 1


def test_an_unidentified_event_with_no_timestamp_is_assumed_to_be_inside(tmp_path: Path) -> None:
    def body(s: Scenario) -> None:
        add_request(s, pid=6001)
        s.events["file"].append(sup.event_xml(sup.FILE, 12, 0, None, FileName=sup.dos(OUTSIDE)))

    result, _, _ = run_analysis(tmp_path, lambda t, d: qualification(t, d, body))
    assert result["verdict"] == "INCONCLUSIVE"


# -- the clock ----------------------------------------------------------------------------------------------------------


def test_beacons_that_disagree_about_the_clock_make_the_capture_unusable(tmp_path: Path) -> None:
    result, _, _ = run_analysis(
        tmp_path, lambda t, d: canary_scenario(t, d, beacon_trace_shift={2: 2_000_000_000})
    )
    assert result["verdict"] == "INCONCLUSIVE"
    assert result["clock"] is None
    assert any("disagree about the clock offset" in p for p in result["capture_problems"])


def test_a_beacon_missing_from_the_trace_leaves_the_clock_unestablished(tmp_path: Path) -> None:
    result, _, _ = run_analysis(
        tmp_path, lambda t, d: canary_scenario(t, d, skip_beacon_in_trace={1})
    )
    assert result["verdict"] == "INCONCLUSIVE" and result["clock"] is None
    assert any("beacon 1" in p for p in result["capture_problems"])
    assert any("fewer than two beacons" in p for p in result["capture_problems"])


def test_without_a_clock_every_owned_event_is_ambiguous_not_dropped(tmp_path: Path) -> None:
    def body(s: Scenario) -> None:
        a = add_request(s, pid=6001)
        request_event(s, a, "write", offset_ms=40, path=OUTSIDE)

    result, _, _ = run_analysis(
        tmp_path, lambda t, d: canary_scenario(t, d, middle=body, skip_beacon_in_trace={1, 2})
    )
    assert result["verdict"] == "INCONCLUSIVE"
    assert row(result, 2)["ambiguous_events"] == 1


def test_calibrate_intersects_the_offset_bounds_and_never_guesses() -> None:
    beacons = [
        {"n": 1, "tag": "start", "path": "C:\\b\\one", "before_ns": 1_000, "after_ns": 3_000},
        {"n": 2, "tag": "end", "path": "C:\\b\\two", "before_ns": 11_000, "after_ns": 13_000},
    ]
    stamps = {
        analysis._norm("C:\\b\\one"): [500],
        analysis._norm("C:\\b\\two"): [10_600],
    }
    clock, problems = analysis.calibrate(beacons, stamps)
    assert clock is not None and problems == []
    assert (clock.low, clock.high) == (500, 2_400) or clock.low <= clock.high
    assert 500 <= clock.low <= clock.high <= 2_500
    low, high = clock.interval(10_000)
    assert low < 10_000 + clock.low and high > 10_000 + clock.high, (
        "an event is an interval with slack, not a point"
    )
    assert analysis.calibrate(beacons, {}) == (
        None,
        [
            "beacon 1 (start) was not found in the trace",
            "beacon 2 (end) was not found in the trace",
            "fewer than two beacons were found in the trace; the clocks cannot be related",
        ],
    )


def test_attribute_events_outcomes_directly() -> None:
    clock = analysis.ClockMap(0, 0, 2)
    requests = [
        {
            "number": 1,
            "start_ns": 1_000_000_000,
            "end_ns": 2_000_000_000,
            "members": [{"pid": 10, "start_ns": 1_000_000_000, "end_ns": 1_900_000_000}],
        },
        {
            "number": 2,
            "start_ns": 5_000_000_000,
            "end_ns": 6_000_000_000,
            "members": [{"pid": 10, "start_ns": 5_000_000_000, "end_ns": 5_900_000_000}],
        },
    ]

    def ev(pid, ts):
        return ChannelEvent(pid, "x", ts, "write")

    result = analysis.attribute_events(
        [
            ev(10, 1_500_000_000),  # request 1
            ev(10, 5_500_000_000),  # request 2 (same pid number)
            ev(10, 3_000_000_000),  # between them: recycled
            ev(10, 1_902_000_000),  # 2 ms after exit: inside the slack, ambiguous
            ev(10, None),  # no timestamp: ambiguous for both
            ev(99, 1_500_000_000),  # never owned
        ],
        requests,
        clock,
    )
    assert [e.ts_ns for e in result.owned[1]] == [1_500_000_000]
    assert [e.ts_ns for e in result.owned[2]] == [5_500_000_000]
    assert result.recycled_pid_events == 1 and result.unrelated_events == 1
    assert len(result.ambiguous[1]) == 2 and len(result.ambiguous[2]) == 1


# -- integrity ----------------------------------------------------------------------------------------------------------


def test_lost_events_make_the_capture_inconclusive(tmp_path: Path) -> None:
    result, _, _ = run_analysis(tmp_path, lambda t, d: canary_scenario(t, d), lost=3)
    assert result["verdict"] == "INCONCLUSIVE"
    assert any("lost events" in p for p in result["capture_problems"])


def test_a_truncated_conversion_is_detected_by_the_event_count(tmp_path: Path) -> None:
    result, _, _ = run_analysis(tmp_path, lambda t, d: canary_scenario(t, d), truncate_xml={"file"})
    assert result["verdict"] == "INCONCLUSIVE"
    assert any("processed" in p and "XML holds" in p for p in result["capture_problems"])


def test_a_conversion_failure_is_never_read_as_no_events(tmp_path: Path) -> None:
    result, _, _ = run_analysis(
        tmp_path,
        lambda t, d: canary_scenario(t, d),
        convert_error={"network": "tracerpt failed (5): Access is denied."},
    )
    assert result["verdict"] == "INCONCLUSIVE"
    assert any("network" in p and "Access is denied" in p for p in result["capture_problems"])


def test_format_errors_in_the_summary_are_a_problem(tmp_path: Path) -> None:
    result, _, _ = run_analysis(
        tmp_path, lambda t, d: canary_scenario(t, d), summary_extra={"dns": "Format Errors   2\n"}
    )
    assert result["verdict"] == "INCONCLUSIVE"
    assert any("format errors" in p for p in result["capture_problems"])


def test_a_stale_or_reused_trace_is_refused_by_its_header(tmp_path: Path) -> None:
    result, _, _ = run_analysis(
        tmp_path,
        lambda t, d: canary_scenario(t, d),
        header_session={"file": "StableNewCap-20200101T000000Z-deadbeef-file"},
    )
    assert result["verdict"] == "INCONCLUSIVE"
    assert any("header names session" in p for p in result["capture_problems"])
    assert result["traces"]["file"]["header_ok"] is False


def test_a_trace_file_that_is_empty_is_a_problem(tmp_path: Path) -> None:
    result, _, _ = run_analysis(
        tmp_path, lambda t, d: canary_scenario(t, d), etl_size={"network": 0}
    )
    assert result["verdict"] == "INCONCLUSIVE"
    assert any("network: the trace file is empty" in p for p in result["capture_problems"])


def test_a_trace_file_that_is_missing_is_a_problem(tmp_path: Path) -> None:
    result, _, _ = run_analysis(
        tmp_path, lambda t, d: canary_scenario(t, d), after_write=lambda d: (d / "dns.etl").unlink()
    )
    assert result["verdict"] == "INCONCLUSIVE"
    assert any("dns: the trace file is missing" in p for p in result["capture_problems"])


def test_a_trace_that_reached_its_size_cap_is_incomplete(tmp_path: Path) -> None:
    cap = 64 * 1024 * 1024
    result, _, _ = run_analysis(
        tmp_path, lambda t, d: canary_scenario(t, d), etl_size={"file": cap}
    )
    assert result["verdict"] == "INCONCLUSIVE"
    assert any("cap" in p for p in result["capture_problems"])


def test_read_trace_refuses_a_header_for_a_different_file_and_a_silent_provider(
    tmp_path: Path,
) -> None:
    etl = tmp_path / "network.etl"
    etl.write_bytes(b"x" * 100)
    name = control.session_names("20261025T190000Z-0a1b2c3d")["network"]

    def convert(_etl: Path, xml: Path, summary: Path) -> None:
        xml.write_text(
            "<Events>"
            + sup.header_xml(name, str(tmp_path / "other.etl"), sup.EPOCH0)
            + "</Events>",
            encoding="utf-8",
        )
        summary.write_text("Total Events  Processed 1\nTotal Events  Lost 0\n", encoding="utf-8")

    read = analysis.read_trace(
        "network", control.NETWORK, name, etl, frozenset({1}), to_dos=lambda p: p, convert=convert
    )
    assert read.header_ok is False
    assert any("different file" in p for p in read.problems)
    assert any(
        "holds no event from Microsoft-Windows-Kernel-Network" in p for p in read.problems
    ), "a provider that never spoke is a lost provider, not an empty channel"


def test_a_dns_trace_with_no_events_is_allowed(tmp_path: Path) -> None:
    etl = tmp_path / "dns.etl"
    etl.write_bytes(b"x" * 100)
    name = control.session_names("20261025T190000Z-0a1b2c3d")["dns"]

    def convert(_etl: Path, xml: Path, summary: Path) -> None:
        xml.write_text(
            "<Events>" + sup.header_xml(name, str(etl), sup.EPOCH0) + "</Events>", encoding="utf-8"
        )
        summary.write_text("Total Events  Processed 1\nTotal Events  Lost 0\n", encoding="utf-8")

    read = analysis.read_trace(
        "dns", control.DNS, name, etl, frozenset({1}), to_dos=lambda p: p, convert=convert
    )
    assert read.problems == [] and read.header_ok


# -- preconditions of the capture ---------------------------------------------------------------------------------------


def test_a_capture_the_operator_has_not_stopped_cannot_be_analysed(tmp_path: Path) -> None:
    logman = FakeLogman()
    target, report, env = started_capture(tmp_path, logman)
    convert = write_capture(canary_scenario(tmp_path, target), target, report)
    result = analysis.analyze(
        target,
        tools=env.tools,
        convert=convert,
        now=env.now,
        reports_root=env.reports_root,
        mapping=drive_mapping,
        free_bytes=lambda p: 10**13,
    )
    assert result["verdict"] == "INCONCLUSIVE"
    assert any("must be stopped by the operator" in p for p in result["capture_problems"])
    assert any("no recorded operator stop" in p for p in result["capture_problems"])


def test_a_capture_stopped_after_its_deadline_is_flagged(tmp_path: Path) -> None:
    result, _, _ = run_analysis(
        tmp_path, lambda t, d: canary_scenario(t, d), stop_minutes=45, minutes=30
    )
    assert result["verdict"] == "INCONCLUSIVE"
    assert any("after its deadline" in p for p in result["capture_problems"])


def test_a_session_that_never_logged_its_end_is_inconclusive(tmp_path: Path) -> None:
    result, _, _ = run_analysis(tmp_path, lambda t, d: canary_scenario(t, d), ended=False)
    assert result["verdict"] == "INCONCLUSIVE"
    assert any("never logged its end" in p for p in result["capture_problems"])


def test_a_window_log_from_another_capture_or_run_is_refused(tmp_path: Path) -> None:
    logman = FakeLogman()
    target, report, env = stopped_capture(tmp_path, logman)
    scenario = canary_scenario(tmp_path, target)
    convert = write_capture(scenario, target, report, run_id="some-other-run")
    result = analysis.analyze(
        target,
        tools=env.tools,
        convert=convert,
        now=env.now,
        reports_root=env.reports_root,
        mapping=drive_mapping,
        free_bytes=lambda p: 10**13,
    )
    assert any("different run" in p for p in result["capture_problems"])


def test_a_damaged_window_log_is_reported(tmp_path: Path) -> None:
    logman = FakeLogman()
    target, report, env = stopped_capture(tmp_path, logman)
    convert = write_capture(canary_scenario(tmp_path, target), target, report)
    with (target / "windows.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("{not json\n" + json.dumps({"type": "surprise"}) + "\n")
    result = analysis.analyze(
        target,
        tools=env.tools,
        convert=convert,
        now=env.now,
        reports_root=env.reports_root,
        mapping=drive_mapping,
        free_bytes=lambda p: 10**13,
    )
    assert result["verdict"] == "INCONCLUSIVE"
    assert any("not JSON" in p for p in result["capture_problems"])
    assert any("unknown record type" in p for p in result["capture_problems"])


def test_a_missing_manifest_is_inconclusive_and_writes_nothing(tmp_path: Path) -> None:
    env = make_env(tmp_path, FakeLogman())
    empty = env.reports_root / "empty"
    empty.mkdir()
    result = analysis.analyze(empty, tools=env.tools, reports_root=env.reports_root)
    assert result["verdict"] == "INCONCLUSIVE"
    assert not list(empty.iterdir())


def test_a_request_outside_the_proven_interval_is_a_problem(tmp_path: Path) -> None:
    def build(tmp: Path, target: Path) -> Scenario:
        s = Scenario()
        add_canary(s, pid=5001, grandchild=5002, tmp=tmp, tag="start")  # ran before any beacon
        add_beacon(s, "start", target)
        add_canary(s, pid=5003, grandchild=5004, tmp=tmp, tag="end", port=51235)
        add_beacon(s, "end", target)
        return s

    result, _, _ = run_analysis(tmp_path, build)
    assert result["verdict"] == "INCONCLUSIVE"
    assert any("outside the interval the beacons prove" in p for p in result["capture_problems"])


def test_insufficient_free_space_stops_before_any_conversion(tmp_path: Path) -> None:
    calls: list[str] = []

    def wrapper(convert):
        def run(etl, xml, summary):
            calls.append(etl.name)
            convert(etl, xml, summary)

        return run

    result, _, _ = run_analysis(
        tmp_path, lambda t, d: canary_scenario(t, d), free=1024, convert_wrapper=wrapper
    )
    assert result["verdict"] == "INCONCLUSIVE" and calls == []
    assert any("free space" in p for p in result["capture_problems"])


def test_a_second_analysis_never_overwrites_the_first(tmp_path: Path) -> None:
    logman = FakeLogman()
    target, report, env = stopped_capture(tmp_path, logman)
    convert = write_capture(canary_scenario(tmp_path, target), target, report)
    kwargs = {
        "tools": env.tools,
        "convert": convert,
        "now": env.now,
        "reports_root": env.reports_root,
        "mapping": drive_mapping,
        "free_bytes": lambda p: 10**13,
    }
    analysis.analyze(target, **kwargs)
    first = (target / "analysis.json").read_text(encoding="utf-8")
    again = analysis.analyze(target, **kwargs)
    assert (target / "analysis.json").read_text(encoding="utf-8") == first
    assert again["analysis_file"] == "analysis-2.json"


# -- the trusted canary -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "fragment"),
    [
        ({"omit": ("read",)}, "known file read was not seen"),
        ({"omit": ("write",)}, "write/rename/delete"),
        ({"omit": ("connect",)}, "known connection attempt was not seen"),
        ({"grandchild_owned": False}, "descendant was not in the owned record"),
        ({"reported_elevated": 1}, "non-elevated token"),
        ({"report": False}, "no canary report"),
        ({"complete": False}, "teardown was not verified"),
    ],
)
def test_a_canary_that_did_not_do_its_known_operations_fails_the_capture(
    tmp_path: Path, kwargs: dict, fragment: str
) -> None:
    def build(tmp: Path, target: Path) -> Scenario:
        s = Scenario()
        add_beacon(s, "start", target)
        add_canary(s, pid=5001, grandchild=5002, tmp=tmp, tag="start", **kwargs)
        add_canary(s, pid=5003, grandchild=5004, tmp=tmp, tag="end", port=51235)
        add_beacon(s, "end", target)
        return s

    result, _, _ = run_analysis(tmp_path, build)
    assert result["verdict"] == "INCONCLUSIVE", "a blind capture is not a pass"
    assert any(fragment in p for p in result["capture_problems"]), result["capture_problems"]


def test_qualification_requests_must_be_bracketed_by_canaries(tmp_path: Path) -> None:
    def build(tmp: Path, target: Path) -> Scenario:
        s = Scenario()
        add_beacon(s, "start", target)
        add_canary(s, pid=5001, grandchild=5002, tmp=tmp, tag="start")
        a = add_request(s, pid=6001)
        request_event(s, a, "read", offset_ms=30, path=ALLOWED_READ)
        add_beacon(s, "end", target)
        return s

    result, _, _ = run_analysis(tmp_path, build)
    assert result["verdict"] == "INCONCLUSIVE"
    assert any("no canary ran after" in p for p in result["capture_problems"])
    assert any("both run" in p for p in result["capture_problems"])


def test_a_fail_outranks_a_capture_problem(tmp_path: Path) -> None:
    def body(s: Scenario) -> None:
        a = add_request(s, pid=6001)
        request_event(s, a, "connect", offset_ms=40)

    result, _, _ = run_analysis(
        tmp_path,
        lambda t, d: qualification(t, d, body),
        summary_extra={"dns": "Format Errors   2\n"},
    )
    assert result["verdict"] == "FAIL", (
        "a violation seen with a sound clock is a violation whatever else is wrong"
    )
    assert result["capture_problems"]


def test_a_lossy_file_trace_leaves_the_clock_unestablished_so_nothing_is_attributed(
    tmp_path: Path,
) -> None:
    def body(s: Scenario) -> None:
        a = add_request(s, pid=6001)
        request_event(s, a, "connect", offset_ms=40)

    result, _, _ = run_analysis(tmp_path, lambda t, d: qualification(t, d, body), lost=1)
    assert result["verdict"] == "INCONCLUSIVE", (
        "without the beacons there is no placing events in time"
    )
    assert result["clock"] is None


def test_the_result_names_executables_by_file_name_only(tmp_path: Path) -> None:
    def body(s: Scenario) -> None:
        add_request(s, pid=6001)

    result, _, _ = run_analysis(tmp_path, lambda t, d: qualification(t, d, body))
    assert row(result, 2)["executable"] == "llama-completion.exe"
    assert "C:\\runtime" not in json.dumps(result)


def test_no_analysis_output_contains_raw_event_payloads(tmp_path: Path) -> None:
    def body(s: Scenario) -> None:
        a = add_request(s, pid=6001)
        request_event(s, a, "read", offset_ms=30, path=ALLOWED_READ)

    result, target, _ = run_analysis(tmp_path, lambda t, d: qualification(t, d, body))
    saved = (target / "analysis.json").read_text(encoding="utf-8")
    assert "<Event" not in saved and "SystemTime" not in saved


# -- hardening from the independent review ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"lost": 3},
        {"truncate_xml": {"file"}},
        {"convert_error": {"network": "tracerpt failed (5): Access is denied."}},
        {"summary_extra": {"dns": "Format Errors   2\n"}},
    ],
)
def test_the_derived_trace_text_is_removed_on_every_failure_path(
    tmp_path: Path, overrides: dict
) -> None:
    result, target, _ = run_analysis(tmp_path, lambda t, d: canary_scenario(t, d), **overrides)
    assert result["verdict"] == "INCONCLUSIVE"
    assert not list(target.glob("*.xml")) and not list(target.glob("*.summary.txt"))


def test_keep_xml_keeps_the_derived_text_for_diagnosis(tmp_path: Path) -> None:
    logman = FakeLogman()
    target, report, env = stopped_capture(tmp_path, logman)
    convert = write_capture(canary_scenario(tmp_path, target), target, report)
    analysis.analyze(
        target,
        tools=env.tools,
        convert=convert,
        now=env.now,
        reports_root=env.reports_root,
        mapping=drive_mapping,
        free_bytes=lambda p: 10**13,
        keep_xml=True,
    )
    assert len(list(target.glob("*.xml"))) == 3


def test_a_verification_file_planted_before_the_analysis_is_a_problem_not_an_alibi(
    tmp_path: Path,
) -> None:
    logman = FakeLogman()
    target, report, env = stopped_capture(tmp_path, logman)
    convert = write_capture(canary_scenario(tmp_path, target), target, report)
    (target / "verification.json").write_text('{"state": "VERIFIED"}', encoding="utf-8")
    result = analysis.analyze(
        target,
        tools=env.tools,
        convert=convert,
        now=env.now,
        reports_root=env.reports_root,
        mapping=drive_mapping,
        free_bytes=lambda p: 10**13,
    )
    assert result["verdict"] == "INCONCLUSIVE"
    assert any("pre-seeded" in p for p in result["capture_problems"])
