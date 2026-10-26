"""PR-AI-QUAL-114E: the operator-run, elevated capture start/stop/cleanup state machine, proven without any trace session.

``FakeLogman`` answers in the format measured on the target host. These tests prove the logic and its failure handling; they do
NOT prove that a live Administrator ``logman`` accepts the exact arguments. That is the operator-run canary, NOT TESTED here.
"""

from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tests.tools.ai114e_support import (  # noqa: E402
    FIXED_NOW,
    FakeLogman,
    make_env,
    query_text,
    started_capture,
)
from tools.qualification.ai111 import capture_control as control  # noqa: E402

REAL_QUERY = """
Name:                 StableNewCap-20261025T190000Z-0a1b2c3d-network
Status:               Running
Root Path:            C:\\repo\\reports\\ai114\\run-1\\capture
Segment:              Off
Schedules:            On
Segment Max Size:     64 MB

Name:                 StableNewCap-20261025T190000Z-0a1b2c3d-network\\StableNewCap-20261025T190000Z-0a1b2c3d-network
Type:                 Trace
Output Location:      C:\\repo\\reports\\ai114\\run-1\\capture\\network.etl
Append:               Off
Circular:             Off
Overwrite:            Off
Buffer Size:          1024
Buffers Lost:         0
Buffers Written:      1
Buffer Flush Timer:   0
Clock Type:           Performance
File Mode:            File

Provider:
Name:                 Microsoft-Windows-Kernel-Network
Provider Guid:        {7DD42A49-5329-4832-8DFD-43D979153A88}
Level:                4 (win:Informational)
KeywordsAll:          0x0
KeywordsAny:          0x30 (ut:TCPIPDatasent,ut:TCPIPDatarecv)
Properties:           64
Filter Type:          0

The command completed successfully.
"""


def _only_file(directory: Path, name: str) -> dict:
    return json.loads((directory / name).read_text(encoding="utf-8"))


# -- parsing what logman reports ----------------------------------------------------------------------------------------


def test_parse_query_reads_the_measured_logman_format() -> None:
    info = control.parse_query(REAL_QUERY)
    assert info["status"] == "running"
    assert (
        info["circular"] == "off" and info["clock"] == "performance" and info["file_mode"] == "file"
    )
    assert info["segment_max_mb"] == 64 and info["buffers_lost"] == 0
    assert info["output"].endswith("network.etl")
    (provider,) = info["providers"]
    assert provider["name"] == "Microsoft-Windows-Kernel-Network"
    assert provider["level"] == 4 and provider["keywords_any"] == 0x30
    assert provider["guid"] == "{7dd42a49-5329-4832-8dfd-43d979153a88}"


def test_verify_session_accepts_exactly_the_requested_configuration() -> None:
    info = control.parse_query(REAL_QUERY)
    etl = Path("C:\\repo\\reports\\ai114\\run-1\\capture\\network.etl")
    assert control.verify_session(info, control.NETWORK, etl, 64) == []


@pytest.mark.parametrize(
    ("old", "new", "fragment"),
    [
        ("Status:               Running", "Status:               Stopped", "not running"),
        ("Circular:             Off", "Circular:             On", "circular"),
        ("Clock Type:           Performance", "Clock Type:           System", "clock type"),
        ("KeywordsAny:          0x30", "KeywordsAny:          0x10", "keywords"),
        ("Level:                4", "Level:                5", "level"),
        ("Segment Max Size:     64 MB", "Segment Max Size:     512 MB", "size cap"),
        ("network.etl", "elsewhere.etl", "output location"),
        (
            "Name:                 Microsoft-Windows-Kernel-Network",
            "Name:                 Microsoft-Windows-Other",
            "provider is",
        ),
    ],
)
def test_a_session_that_is_not_as_requested_is_reported(old: str, new: str, fragment: str) -> None:
    assert old in REAL_QUERY
    text = REAL_QUERY.replace(old, new, 1)
    info = control.parse_query(text)
    etl = Path("C:\\repo\\reports\\ai114\\run-1\\capture\\network.etl")
    problems = control.verify_session(info, control.NETWORK, etl, 64)
    assert any(fragment in p for p in problems), problems


def test_a_missing_required_provider_is_a_problem() -> None:
    text = REAL_QUERY.split("Provider:")[0]
    info = control.parse_query(text)
    etl = Path("C:\\repo\\reports\\ai114\\run-1\\capture\\network.etl")
    assert any("0 providers" in p for p in control.verify_session(info, control.NETWORK, etl, 64))


def test_unreadable_or_localized_output_fails_closed() -> None:
    info = control.parse_query("Nom : introuvable\n")
    problems = control.verify_session(info, control.NETWORK, Path("C:\\x\\network.etl"), 64)
    assert problems, "output the parser cannot read is never a pass"


# -- identities ---------------------------------------------------------------------------------------------------------


def test_session_names_derive_only_from_a_validated_capture_id() -> None:
    capture_id = control.new_capture_id(FIXED_NOW)
    names = control.session_names(capture_id)
    assert set(names) == {"network", "file", "dns"}
    assert all(n.startswith(control.CAPTURE_PREFIX) and n.endswith(k) for k, n in names.items())
    for bad in ("", "../x", "20261025T190000Z-zzzzzzzz", f"{capture_id}-network", "x" * 80):
        with pytest.raises(control.CaptureRefused):
            control.session_names(bad)


def test_only_capture_session_names_can_be_started_stopped_or_queried() -> None:
    logman = FakeLogman()
    tools = control.TraceTools(logman.run)
    for call in (
        lambda: tools.stop("SomeOtherApp-Trace"),
        lambda: tools.query("Circular Kernel Context Logger"),
        lambda: tools.start("NT Kernel Logger", control.NETWORK, Path("x.etl"), 64),
    ):
        with pytest.raises(control.CaptureRefused):
            call()
    assert logman.calls == [], "a foreign name never reaches logman"


def test_two_captures_get_distinct_identities() -> None:
    assert control.new_capture_id(FIXED_NOW) != control.new_capture_id(FIXED_NOW)


def test_logman_is_resolved_by_absolute_path_never_through_path() -> None:
    logman = FakeLogman()
    control.TraceTools(logman.run).live()
    assert Path(logman.calls[0][0]).is_absolute()


# -- start --------------------------------------------------------------------------------------------------------------


def test_a_successful_start_leaves_three_verified_sessions_and_a_state_trail(
    tmp_path: Path,
) -> None:
    logman = FakeLogman()
    target, report, _env = started_capture(tmp_path, logman)
    assert report["state"] == "ACTIVE"
    assert len(logman.sessions) == 3
    assert {n.rsplit("-", 1)[1] for n in logman.sessions} == {"network", "file", "dns"}
    manifest = _only_file(target, "capture.json")
    assert manifest["capture_id"] == report["capture_id"]
    assert manifest["provider_config_sha256"] == control.provider_config_sha256()
    assert manifest["tool_sha256"] == control.tool_sha256()
    assert {p.name for p in target.glob("state-*.json")} == {
        "state-01-starting.json",
        "state-02-active.json",
    }
    # the trace is bounded: sequential file mode with a size cap, never circular, on the performance counter
    for config in logman.sessions.values():
        command = config["command"]
        assert "-max" in command and "-ets" in command
        assert command[command.index("-ct") + 1] == "perf"
        assert "-rf" not in command, "logman -ets cannot take a run-for time"
        assert "-f" not in command and "circular" not in " ".join(command).lower()


def test_no_command_contains_a_model_a_downloaded_binary_or_a_caller_supplied_name(
    tmp_path: Path,
) -> None:
    logman = FakeLogman()
    started_capture(tmp_path, logman)
    flat = " ".join(" ".join(c) for c in logman.calls).lower()
    for forbidden in (
        ".gguf",
        "llama",
        "prompt",
        "python",
        "powershell",
        "cmd.exe",
        "netsh",
        "reg.exe",
    ):
        assert forbidden not in flat
    assert {Path(c[0]).name.lower() for c in logman.calls} == {"logman.exe"}


def test_start_needs_an_administrator_terminal_and_starts_nothing_otherwise(tmp_path: Path) -> None:
    for elevated in (False, None):
        logman = FakeLogman()
        env = make_env(tmp_path, logman, elevated=elevated)
        with pytest.raises(control.CaptureRefused, match="Administrator"):
            control.start_capture(env.reports_root / "ai114" / "r" / "c", run_id="r", env=env)
        assert logman.calls == [] and not (env.reports_root / "ai114").exists()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"run_id": ""},
        {"run_id": "../escape"},
        {"run_id": "has space"},
        {"run_id": "x" * 65},
        {"run_id": "ok", "max_mb": 8},
        {"run_id": "ok", "max_mb": control.MAX_MB_LIMIT + 1},
        {"run_id": "ok", "minutes": 0},
        {"run_id": "ok", "minutes": control.MAX_MINUTES + 1},
    ],
)
def test_unbounded_or_malformed_parameters_are_refused_before_anything_starts(
    tmp_path: Path, kwargs: dict
) -> None:
    logman = FakeLogman()
    env = make_env(tmp_path, logman)
    with pytest.raises(control.CaptureRefused):
        control.start_capture(env.reports_root / "ai114" / "r" / "c", env=env, **kwargs)
    assert logman.calls == []


def test_the_evidence_directory_must_be_fresh_and_inside_reports(tmp_path: Path) -> None:
    logman = FakeLogman()
    env = make_env(tmp_path, logman)
    existing = env.reports_root / "old"
    existing.mkdir()
    for bad in (existing, tmp_path / "elsewhere", env.reports_root, env.reports_root / ".." / "x"):
        with pytest.raises(control.CaptureRefused):
            control.start_capture(bad, run_id="r", env=env)
    assert logman.calls == []


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are a Windows reparse point")
def test_a_reparse_point_in_the_destination_chain_is_refused(tmp_path: Path) -> None:
    import subprocess

    logman = FakeLogman()
    env = make_env(tmp_path, logman)
    real = tmp_path / "real"
    real.mkdir()
    link = env.reports_root / "ai114"
    made = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(real)], capture_output=True, check=False
    )
    if made.returncode != 0:
        pytest.skip("cannot create a junction here")
    # The link is resolved first, so a junction leading out of ``reports`` is refused as outside it (and a link met while
    # walking the chain is refused as a reparse point): either way nothing is written through it.
    with pytest.raises(control.CaptureRefused, match="inside|link or reparse"):
        control.start_capture(link / "r" / "c", run_id="r", env=env)
    assert logman.calls == []
    assert not (real / "r").exists(), "nothing was written through the link"


def test_a_start_with_sessions_already_running_is_refused_not_adopted(tmp_path: Path) -> None:
    logman = FakeLogman()
    started_capture(tmp_path, logman, run_id="first")
    env = make_env(tmp_path, logman)
    with pytest.raises(control.CaptureRefused, match="already running"):
        control.start_capture(env.reports_root / "ai114" / "second" / "c", run_id="second", env=env)
    assert len(logman.sessions) == 3, "the earlier capture is untouched"
    assert not (env.reports_root / "ai114" / "second").exists()


def test_insufficient_disk_space_refuses_and_leaves_no_directory(tmp_path: Path) -> None:
    logman = FakeLogman()
    env = make_env(tmp_path, logman, free=10 * 1024**2)
    target = env.reports_root / "ai114" / "r" / "c"
    with pytest.raises(control.CaptureRefused, match="free space"):
        control.start_capture(target, run_id="r", env=env)
    assert not target.exists()
    assert [c for c in logman.calls if c[1] in ("start", "stop")] == []


def test_the_budget_includes_the_conversion_expansion() -> None:
    assert control.required_free_bytes(256) > 2 * 256 * 1024**2 * control.CONVERSION_FACTOR


def test_a_broadly_readable_evidence_directory_is_refused(tmp_path: Path) -> None:
    logman = FakeLogman()
    acl = "{dir} BUILTIN\\Users:(OI)(CI)(R)\n   NT AUTHORITY\\SYSTEM:(OI)(CI)(F)\n"
    env = make_env(tmp_path, logman, acl=acl)
    target = env.reports_root / "ai114" / "r" / "c"
    with pytest.raises(control.CaptureRefused, match="builtin.users"):
        control.start_capture(target, run_id="r", env=env)
    assert [c for c in logman.calls if c[1] in ("start", "stop")] == [] and not target.exists()


def test_acl_problems_ignore_deny_entries_and_narrow_principals() -> None:
    narrow = "C:\\x\\c DESKTOP\\rob:(OI)(CI)(F)\n   BUILTIN\\Administrators:(OI)(CI)(F)\n   BUILTIN\\Users:(DENY)(R)\n"
    assert control.acl_problems(narrow, Path("C:\\x\\c")) == []
    broad = "C:\\x\\c Everyone:(OI)(CI)(R)\n"
    assert control.acl_problems(broad, Path("C:\\x\\c")) == [
        "the directory grants access to everyone"
    ]


# -- failures during start ----------------------------------------------------------------------------------------------


def test_access_denied_before_any_session_exists_leaves_nothing_running(tmp_path: Path) -> None:
    logman = FakeLogman()
    logman.deny_kinds = {"network"}
    env = make_env(tmp_path, logman)
    target = env.reports_root / "ai114" / "r" / "c"
    report = control.start_capture(target, run_id="r", env=env)
    assert report["state"] == "FAILED" and report["sessions_left"] == []
    assert any("Access is denied" in p for p in report["problems"])
    assert logman.sessions == {}
    assert (target / "state-02-failed.json").is_file() and not (
        target / "state-02-active.json"
    ).exists()


def test_a_denied_start_that_still_created_a_session_is_stopped_and_proved_gone(
    tmp_path: Path,
) -> None:
    logman = FakeLogman()
    logman.deny_kinds = {"network"}
    logman.create_on_deny = True
    env = make_env(tmp_path, logman)
    report = control.start_capture(env.reports_root / "ai114" / "r" / "c", run_id="r", env=env)
    assert report["state"] == "FAILED", (
        "cleanup succeeded, so the attempt is a clean failure, not a pass"
    )
    assert logman.sessions == {}, "the leftover named session was found and stopped"
    stops = [c for c in logman.calls if c[1] == "stop"]
    assert stops, "a denied start is still followed by a stop of the session it may have created"


def test_a_partial_start_stops_the_sessions_that_did_start(tmp_path: Path) -> None:
    logman = FakeLogman()
    logman.deny_kinds = {"file"}
    env = make_env(tmp_path, logman)
    report = control.start_capture(env.reports_root / "ai114" / "r" / "c", run_id="r", env=env)
    assert report["state"] == "FAILED"
    assert logman.sessions == {}, "the network session that had started was stopped"


def test_a_failed_cleanup_after_a_failed_start_is_cleanup_required_with_instructions(
    tmp_path: Path,
) -> None:
    logman = FakeLogman()
    logman.deny_kinds = {"file"}
    env = make_env(tmp_path, logman)
    capture_names = {}
    original = logman.run

    def run(command):
        if command[1] == "start":
            capture_names[command[2]] = True
            logman.stuck.add(command[2])
        return original(command)

    env = make_env(tmp_path, logman)
    env = control.Environment(
        tools=control.TraceTools(run),
        now=env.now,
        elevated=env.elevated,
        free_bytes=env.free_bytes,
        acl_reader=env.acl_reader,
        reports_root=env.reports_root,
        runtime_check=env.runtime_check,
    )
    report = control.start_capture(env.reports_root / "ai114" / "r" / "c", run_id="r", env=env)
    assert report["state"] == "CLEANUP_REQUIRED"
    assert report["sessions_left"], "the unproven session is named"
    assert all(
        line.startswith("logman stop") or "StableNewCap-" in line for line in report["cleanup"]
    )


def test_a_session_that_comes_up_misconfigured_is_stopped_and_the_capture_fails(
    tmp_path: Path,
) -> None:
    logman = FakeLogman()
    env = make_env(tmp_path, logman)
    original = logman.run

    def run(command):
        code, text = original(command)
        if command[1] == "start":
            logman.sessions[command[2]]["circular"] = "On"
        return code, text

    env = control.Environment(
        tools=control.TraceTools(run),
        now=env.now,
        elevated=env.elevated,
        free_bytes=env.free_bytes,
        acl_reader=env.acl_reader,
        reports_root=env.reports_root,
        runtime_check=env.runtime_check,
    )
    report = control.start_capture(env.reports_root / "ai114" / "r" / "c", run_id="r", env=env)
    assert report["state"] == "FAILED"
    assert any("circular" in p for p in report["problems"])
    assert logman.sessions == {}


def test_an_unreadable_session_list_after_failure_is_never_read_as_clean(tmp_path: Path) -> None:
    logman = FakeLogman()
    logman.deny_kinds = {"network"}
    original = logman.run

    def run(command):
        if (
            command[1] == "query"
            and len(command) == 3
            and any(c[1] == "start" for c in logman.calls)
        ):
            return 1, "Error: cannot list."
        return original(command)

    env = make_env(tmp_path, logman)
    # the first list (before starting) must work; later lists fail
    state = {"n": 0}

    def flaky(command):
        if command[1] == "query" and len(command) == 3:
            state["n"] += 1
            if state["n"] > 1:
                return 1, "Error: cannot list."
        return original(command)

    env = control.Environment(
        tools=control.TraceTools(flaky),
        now=env.now,
        elevated=env.elevated,
        free_bytes=env.free_bytes,
        acl_reader=env.acl_reader,
        reports_root=env.reports_root,
        runtime_check=env.runtime_check,
    )
    report = control.start_capture(env.reports_root / "ai114" / "r" / "c", run_id="r", env=env)
    assert report["state"] == "CLEANUP_REQUIRED"
    assert report["sessions_left"] == ["<session list unreadable>"]


# -- stop and cleanup ---------------------------------------------------------------------------------------------------


def test_stop_ends_exactly_the_three_sessions_and_records_it(tmp_path: Path) -> None:
    logman = FakeLogman()
    target, started, env = started_capture(tmp_path, logman)
    (target / "network.etl").write_bytes(b"x" * 10)
    result = control.stop_capture(started["capture_id"], evidence_dir=target, env=env)
    assert result["state"] == "STOPPED" and result["sessions_left"] == []
    assert logman.sessions == {}
    assert logman.foreign == ["Circular Kernel Context Logger", "SomeOtherApp-Trace"]
    assert (target / "state-04-stopped.json").is_file()
    assert result["etl_bytes"]["network"] == 10
    stopped_names = {c[2] for c in logman.calls if c[1] == "stop"}
    assert stopped_names == set(control.session_names(started["capture_id"]).values()), (
        "no foreign session is touched"
    )


def test_stop_failure_is_cleanup_required_never_stopped(tmp_path: Path) -> None:
    logman = FakeLogman()
    target, started, env = started_capture(tmp_path, logman)
    stuck = control.session_names(started["capture_id"])["file"]
    logman.stuck.add(stuck)
    result = control.stop_capture(started["capture_id"], evidence_dir=target, env=env)
    assert result["state"] == "CLEANUP_REQUIRED"
    assert result["sessions_left"] == [stuck]
    assert not (target / "state-04-stopped.json").exists(), (
        "an unproven stop is not recorded as stopped"
    )
    assert control.cleanup_instructions(started["capture_id"])[0].startswith("logman stop")


def test_stop_is_repeatable_and_a_missing_session_is_not_an_error(tmp_path: Path) -> None:
    logman = FakeLogman()
    target, started, env = started_capture(tmp_path, logman)
    first = control.stop_capture(started["capture_id"], evidence_dir=target, env=env)
    again = control.stop_capture(started["capture_id"], evidence_dir=target, env=env)
    assert first["state"] == again["state"] == "STOPPED"
    assert all(not s["was_running"] for s in again["sessions"].values())


def test_cleanup_works_without_the_evidence_directory_after_a_crash(tmp_path: Path) -> None:
    logman = FakeLogman()
    _target, started, env = started_capture(tmp_path, logman)
    result = control.stop_capture(started["capture_id"], env=env)
    assert result["state"] == "STOPPED" and logman.sessions == {}


def test_stop_with_the_wrong_directory_or_id_is_refused(tmp_path: Path) -> None:
    logman = FakeLogman()
    target, started, env = started_capture(tmp_path, logman)
    other = control.new_capture_id(FIXED_NOW)
    with pytest.raises(control.CaptureRefused, match="does not name"):
        control.stop_capture(other, evidence_dir=target, env=env)
    with pytest.raises(control.CaptureRefused):
        control.stop_capture("not-a-capture-id", env=env)
    assert len(logman.sessions) == 3, "nothing was stopped by a refused command"


def test_stop_needs_an_administrator_terminal(tmp_path: Path) -> None:
    logman = FakeLogman()
    target, started, _ = started_capture(tmp_path, logman)
    env = make_env(tmp_path, logman, elevated=False)
    with pytest.raises(control.CaptureRefused, match="Administrator"):
        control.stop_capture(started["capture_id"], evidence_dir=target, env=env)
    assert len(logman.sessions) == 3


# -- derived state ------------------------------------------------------------------------------------------------------


def test_the_state_machine_from_not_started_to_stopped(tmp_path: Path) -> None:
    logman = FakeLogman()
    env = make_env(tmp_path, logman)
    empty = env.reports_root / "nothing"
    empty.mkdir()
    assert control.capture_status(empty, env=env)["state"] == "NOT_STARTED"
    target, started, env = started_capture(tmp_path, logman)
    assert control.capture_status(target, env=env)["state"] == "ACTIVE"
    control.stop_capture(started["capture_id"], evidence_dir=target, env=env)
    assert control.capture_status(target, env=env)["state"] == "STOPPED"
    (target / "verification.json").write_text("{}", encoding="utf-8")
    assert control.capture_status(target, env=env)["state"] == "VERIFIED"


def test_an_expired_capture_is_not_active(tmp_path: Path) -> None:
    logman = FakeLogman()
    target, started, env = started_capture(tmp_path, logman, minutes=10)
    late = make_env(tmp_path, logman, now=lambda: FIXED_NOW + timedelta(minutes=11))
    state = control.capture_status(target, env=late)
    assert state["state"] == "EXPIRED"


def test_sessions_still_running_outside_a_clean_active_state_need_cleanup(tmp_path: Path) -> None:
    logman = FakeLogman()
    target, started, env = started_capture(tmp_path, logman)
    (target / "state-03-stopping.json").write_text("{}", encoding="utf-8")
    assert control.capture_status(target, env=env)["state"] == "CLEANUP_REQUIRED"


def test_only_some_sessions_running_is_cleanup_required(tmp_path: Path) -> None:
    logman = FakeLogman()
    target, started, env = started_capture(tmp_path, logman)
    del logman.sessions[control.session_names(started["capture_id"])["dns"]]
    state = control.capture_status(target, env=env)
    assert state["state"] == "CLEANUP_REQUIRED"


def test_sessions_that_vanished_without_a_stop_are_not_a_clean_stop(tmp_path: Path) -> None:
    logman = FakeLogman()
    target, started, env = started_capture(tmp_path, logman)
    logman.sessions.clear()  # reboot or killed
    state = control.capture_status(target, env=env)
    assert state["state"] == "STOPPED" and state["problems"], "flagged: no recorded operator stop"


def test_an_interrupted_start_is_visible_as_starting(tmp_path: Path) -> None:
    logman = FakeLogman()
    env = make_env(tmp_path, logman)
    target = env.reports_root / "crashed"
    target.mkdir()
    capture_id = control.new_capture_id(FIXED_NOW)
    (target / "capture.json").write_text(json.dumps({"capture_id": capture_id}), encoding="utf-8")
    (target / "state-01-starting.json").write_text("{}", encoding="utf-8")
    assert control.capture_status(target, env=env)["state"] == "STARTING"


def test_a_forged_capture_id_in_the_manifest_is_invalid(tmp_path: Path) -> None:
    logman = FakeLogman()
    env = make_env(tmp_path, logman)
    target = env.reports_root / "forged"
    target.mkdir()
    (target / "capture.json").write_text(json.dumps({"capture_id": "../../x"}), encoding="utf-8")
    assert control.capture_status(target, env=env)["state"] == "FAILED"


def test_status_lists_only_this_tools_sessions() -> None:
    logman = FakeLogman()
    logman.sessions["StableNewCap-20261025T190000Z-0a1b2c3d-network"] = {
        "provider": "p",
        "keywords": 1,
        "level": 4,
        "etl": "C:\\x.etl",
        "max_mb": 64,
        "circular": "Off",
        "clock": "Performance",
        "status": "Running",
        "command": [],
    }
    assert set(control.TraceTools(logman.run).live()) == {
        "StableNewCap-20261025T190000Z-0a1b2c3d-network"
    }


def test_query_text_round_trips_through_the_parser() -> None:
    config = {
        "provider": "Microsoft-Windows-Kernel-File",
        "keywords": 0x1000 | 0x10,
        "level": 4,
        "etl": "C:\\r\\file.etl",
        "max_mb": 32,
        "circular": "Off",
        "clock": "Performance",
        "status": "Running",
    }
    info = control.parse_query(query_text("StableNewCap-20261025T190000Z-0a1b2c3d-file", config))
    assert info["providers"][0]["keywords_any"] == 0x1010 and info["segment_max_mb"] == 32


# -- the command line ---------------------------------------------------------------------------------------------------


def test_the_command_line_refuses_without_elevation_and_exits_2(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    from tools.qualification.ai111 import tokens

    # Were the suite itself run elevated this would start a real trace: refuse to even try.
    if tokens.current_process_elevated() is not False:
        pytest.skip("the test suite must run from an ordinary terminal")
    code = control.main(
        [
            "start",
            "--evidence-dir",
            str(control.REPORTS_ROOT / "ai114" / "unit-test-never-created"),
            "--run-id",
            "r",
        ]
    )
    out = capsys.readouterr().out
    assert code == 2 and "Administrator" in out
    assert not (control.REPORTS_ROOT / "ai114" / "unit-test-never-created").exists()


# -- hardening from the independent review ---------------------------------------------------------------------------------


def test_the_elevated_file_imports_only_the_standard_library() -> None:
    import ast

    tree = ast.parse(Path(control.__file__).read_text(encoding="utf-8"))
    imported = {
        (node.module or "").split(".")[0]
        if isinstance(node, ast.ImportFrom)
        else alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in (node.names if isinstance(node, ast.Import) else [None])
    }
    assert imported <= set(sys.stdlib_module_names), imported - set(sys.stdlib_module_names)


def test_the_elevated_file_runs_in_isolated_mode_without_the_repository_on_the_path(
    tmp_path: Path,
) -> None:
    import json
    import subprocess

    done = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            str(Path(control.__file__)),
            "status",
            "--evidence-dir",
            str(tmp_path / "none"),
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        check=False,
    )
    assert done.returncode == 2 and json.loads(done.stdout)["state"] == "REFUSED", done.stderr


def test_the_elevated_runner_only_runs_the_two_system_tools_by_absolute_path() -> None:
    for command in (
        ["logman.exe", "query"],
        ["C:\\Windows\\System32\\cmd.exe", "/c", "dir"],
        ["python", "-c", "1"],
    ):
        with pytest.raises(control.CaptureRefused):
            control.run_tool(command)


def test_a_pre_seeded_trace_file_is_refused_before_logman_is_asked_to_write_it(
    tmp_path: Path,
) -> None:
    logman = FakeLogman()
    base = make_env(tmp_path, logman)

    def plant(directory: Path) -> int:
        (directory / "network.etl").write_bytes(b"planted")
        return 10**13

    env = control.Environment(
        tools=base.tools,
        now=base.now,
        elevated=base.elevated,
        free_bytes=plant,
        acl_reader=base.acl_reader,
        reports_root=base.reports_root,
        runtime_check=base.runtime_check,
    )
    report = control.start_capture(env.reports_root / "ai114" / "r" / "c", run_id="r", env=env)
    assert report["state"] == "FAILED" and any("already exists" in p for p in report["problems"])
    assert [c for c in logman.calls if c[1] == "start"] == [], (
        "logman never opened the planted path"
    )


def test_an_acl_listing_that_cannot_be_read_is_refused(tmp_path: Path) -> None:
    logman = FakeLogman()
    env = make_env(tmp_path, logman, acl="Error: cannot access the file.\n")
    with pytest.raises(control.CaptureRefused, match="could not be read"):
        control.start_capture(env.reports_root / "ai114" / "r" / "c", run_id="r", env=env)


def test_broad_principals_are_matched_by_the_machines_own_names_too() -> None:
    localized = frozenset({"jeder", "vordefiniert\\benutzer"})
    text = "C:\\x Jeder:(OI)(CI)(R)\n   VORDEFINIERT\\Benutzer:(OI)(CI)(R)\n"
    assert len(control.acl_problems(text, Path("C:\\x"), localized)) == 2
    assert {"everyone", "builtin\\users"} <= control.broad_principal_names()
