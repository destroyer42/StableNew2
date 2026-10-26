"""PR-AI-QUAL-114E closeout repairs: the protected elevated runtime and the review's analyzer/admission findings.

F1  the elevated interpreter and script must be protected; F2 beacon offsets must intersect; F3 loss counters;
F4  relative beacon files; F5 unresolved events keep their instant; F6 directory inventory and a deny-write window log;
F7  admission projects capacity and the deadline; F10 analyses are listed and a failed one voids a proof.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import timedelta
from pathlib import Path, PureWindowsPath

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tests.tools.ai114e_support import (  # noqa: E402
    FIXED_NOW,
    FakeLogman,
    canary_scenario,
    make_env,
    started_capture,
)
from tests.tools.test_ai114e_capture_analysis import run_analysis  # noqa: E402
from tests.tools.test_ai114e_capture_session import (  # noqa: E402
    PY,
    admission_for,
    lines,
    make_proof,
    monitor_for,
)
from tools.qualification.ai111 import capture_analysis as analysis  # noqa: E402
from tools.qualification.ai111 import capture_control as control  # noqa: E402
from tools.qualification.ai111 import capture_session as session  # noqa: E402
from tools.qualification.ai111.etw import RawEvent, file_events  # noqa: E402

windows_only = pytest.mark.skipif(os.name != "nt", reason="Windows share modes and ACLs")

ADMIN = "BUILTIN\\Administrators"
SYSTEM = "NT AUTHORITY\\SYSTEM"
TRUSTED = control.trusted_principal_names()


# -- F1: the elevated runtime must itself be protected -------------------------------------------------------------------


def grants(path: str, *entries: str) -> str:
    first, *rest = entries
    return "\n".join([f"{path} {first}", *(f"{' ' * (len(path) + 1)}{e}" for e in rest)]) + "\n"


def test_a_user_who_can_modify_a_loaded_path_is_reported() -> None:
    path = Path("C:/py/Lib")
    text = grants(
        str(path), f"{SYSTEM}:(I)(OI)(CI)(F)", f"{ADMIN}:(I)(OI)(CI)(F)", "HOST\\rob:(I)(OI)(CI)(M)"
    )
    assert control.write_grant_problems(text, path, TRUSTED, control._REPLACE_RIGHTS) == [
        f"host\\rob can modify {path} (M)"
    ]


@pytest.mark.parametrize("rights", ["F", "M", "W", "WD", "AD", "DC", "WDAC", "WO", "D", "GA", "GW"])
def test_every_replace_or_write_right_is_a_finding(rights: str) -> None:
    path = Path("C:/py/python.exe")
    text = grants(str(path), f"{ADMIN}:(F)", f"HOST\\users:({rights})")
    assert control.write_grant_problems(text, path, TRUSTED, control._REPLACE_RIGHTS)


@pytest.mark.parametrize("rights", ["RX", "R", "GR,GE", "REA,RA,X", "RC"])
def test_read_and_execute_rights_are_not_findings(rights: str) -> None:
    path = Path("C:/py/python.exe")
    text = grants(str(path), f"{ADMIN}:(F)", f"HOST\\users:({rights})")
    assert control.write_grant_problems(text, path, TRUSTED, control._REPLACE_RIGHTS) == []


def test_inherit_only_and_deny_entries_do_not_apply_to_the_object_itself() -> None:
    path = Path("C:/py")
    text = grants(
        str(path),
        f"{ADMIN}:(OI)(CI)(F)",
        "HOST\\users:(OI)(CI)(IO)(M)",
        "HOST\\guests:(DENY)(W)",
    )
    assert control.write_grant_problems(text, path, TRUSTED, control._REPLACE_RIGHTS) == []


def test_an_unreadable_acl_listing_is_a_problem_not_a_pass() -> None:
    path = Path("C:/py")
    problems = control.write_grant_problems(
        "Access is denied.\n", path, TRUSTED, control._REPLACE_RIGHTS
    )
    assert problems == [f"the ACL of {path} could not be read"]


def test_an_unresolved_sid_that_can_write_is_a_finding_but_the_trusted_sids_are_not() -> None:
    path = Path("C:/py")
    text = grants(str(path), "S-1-5-18:(F)", "S-1-5-32-544:(F)", "S-1-5-21-1-2-3-1001:(M)")
    assert control.write_grant_problems(text, path, TRUSTED, control._REPLACE_RIGHTS) == [
        f"s-1-5-21-1-2-3-1001 can modify {path} (M)"
    ]


def protected_facts(**overrides) -> control.RuntimeFacts:
    base = Path("C:/Program Files/Python314")
    values = {
        "script": Path("C:/ProgramData/StableNewCap/capture_control.py"),
        "executable": base / "python.exe",
        "stdlib_file": base / "Lib" / "os.py",
        "base_prefix": base,
        "sys_path_dirs": (base / "Lib", base / "DLLs"),
        "sys_path_files": (base / "python314.zip",),
        "module_files": (base / "Lib" / "json" / "__init__.py",),
        "isolated": True,
        "bytecode_disabled": True,
        "in_venv": False,
        **overrides,
    }
    return control.RuntimeFacts(**values)


def reader(acl: dict[str, str], default: str):
    def read(path: Path) -> str:
        return acl.get(str(path), default).replace("{p}", str(path))

    return read


PROTECTED = (
    "{p} " + f"{SYSTEM}:(OI)(CI)(F)\n   {ADMIN}:(OI)(CI)(F)\n   BUILTIN\\Users:(OI)(CI)(RX)\n"
)
SYSTEM_SID = "S-1-5-18"


def test_a_protected_runtime_has_no_problems() -> None:
    assert (
        control.runtime_trust_problems(
            protected_facts(),
            acl_reader=reader({}, PROTECTED),
            owner_reader=lambda p: SYSTEM_SID,
            trusted=TRUSTED,
        )
        == []
    )


def test_a_user_writable_interpreter_or_script_refuses() -> None:
    facts = protected_facts()
    writable = "{p} HOST\\rob:(I)(F)\n   " + f"{ADMIN}:(I)(F)\n"
    for victim in (facts.executable, facts.script, facts.stdlib_file, facts.base_prefix / "DLLs"):
        problems = control.runtime_trust_problems(
            facts,
            acl_reader=reader({str(victim): writable}, PROTECTED),
            owner_reader=lambda p: SYSTEM_SID,
            trusted=TRUSTED,
        )
        assert any(str(victim) in p and "can modify" in p for p in problems), victim


def test_a_user_owned_path_refuses_even_with_a_clean_acl() -> None:
    facts = protected_facts()
    problems = control.runtime_trust_problems(
        facts,
        acl_reader=reader({}, PROTECTED),
        owner_reader=lambda p: "S-1-5-21-1-2-3-1001" if p == facts.executable else SYSTEM_SID,
        trusted=TRUSTED,
    )
    assert problems == [
        f"{facts.executable} is owned by S-1-5-21-1-2-3-1001, not an administrator-class principal"
    ]


def test_an_unreadable_owner_is_a_problem() -> None:
    problems = control.runtime_trust_problems(
        protected_facts(),
        acl_reader=reader({}, PROTECTED),
        owner_reader=lambda p: None,
        trusted=TRUSTED,
    )
    assert problems and all("could not be read" in p for p in problems)


def test_a_user_who_can_delete_or_rename_an_ancestor_refuses_but_creating_a_child_does_not() -> (
    None
):
    facts = protected_facts()
    ancestor = str(Path("C:/Program Files"))
    deletes = "{p} HOST\\users:(M)\n   " + f"{ADMIN}:(F)\n"
    creates = "{p} HOST\\users:(CI)(WD,AD)\n   " + f"{ADMIN}:(F)\n"
    bad = control.runtime_trust_problems(
        facts,
        acl_reader=reader({ancestor: deletes}, PROTECTED),
        owner_reader=lambda p: SYSTEM_SID,
        trusted=TRUSTED,
    )
    ok = control.runtime_trust_problems(
        facts,
        acl_reader=reader({ancestor: creates}, PROTECTED),
        owner_reader=lambda p: SYSTEM_SID,
        trusted=TRUSTED,
    )
    assert any(ancestor in p for p in bad)
    assert ok == []


def test_an_unreadable_acl_is_a_problem_through_the_whole_scan() -> None:
    def read(path: Path) -> str:
        raise control.CaptureRefused("icacls timed out")

    problems = control.runtime_trust_problems(
        protected_facts(), acl_reader=read, owner_reader=lambda p: SYSTEM_SID, trusted=TRUSTED
    )
    assert problems and all("could not be read" in p for p in problems)


@pytest.mark.parametrize(
    ("override", "fragment"),
    [
        ({"isolated": False}, "-I (isolated mode)"),
        ({"bytecode_disabled": False}, "-B (no bytecode files)"),
        ({"in_venv": True}, "virtual environment"),
        (
            {"module_files": (Path("C:/Users/rob/evil/json.py"),)},
            "loaded from outside the protected locations",
        ),
    ],
)
def test_interpreter_mode_venv_and_stray_modules_refuse(override: dict, fragment: str) -> None:
    problems = control.runtime_trust_problems(
        protected_facts(**override),
        acl_reader=reader({}, PROTECTED),
        owner_reader=lambda p: SYSTEM_SID,
        trusted=TRUSTED,
    )
    assert any(fragment in p for p in problems)


@pytest.mark.parametrize("command", ["start", "stop", "cleanup"])
def test_an_unprotected_runtime_starts_and_stops_nothing(tmp_path: Path, command: str) -> None:
    logman = FakeLogman()
    env = make_env(tmp_path, logman)
    refusing = control.Environment(
        tools=env.tools,
        now=env.now,
        elevated=env.elevated,
        free_bytes=env.free_bytes,
        acl_reader=env.acl_reader,
        reports_root=env.reports_root,
        runtime_check=lambda: ["C:\\Users\\rob\\Python314 is user-writable"],
    )
    cid = "20261025T190000Z-0123abcd"
    with pytest.raises(control.CaptureRefused, match="runtime is not protected"):
        if command == "start":
            control.start_capture(
                refusing.reports_root / "ai114" / "r" / "c", run_id="r", env=refusing
            )
        elif command == "stop":
            control.stop_capture(cid, env=refusing)
        else:
            control.stop_capture(cid, env=refusing)
    assert logman.calls == [], "no logman command of any kind ran"
    assert not (refusing.reports_root / "ai114").exists()


def test_the_protection_is_checked_after_elevation_and_the_refusal_names_causes(
    tmp_path: Path,
) -> None:
    logman = FakeLogman()
    env = make_env(tmp_path, logman, elevated=False)
    with pytest.raises(control.CaptureRefused, match="Administrator terminal"):
        control.start_capture(env.reports_root / "a" / "b", run_id="r", env=env)


def test_a_successful_start_records_the_runtime(tmp_path: Path) -> None:
    target, _report, _env = started_capture(tmp_path, FakeLogman())
    manifest = json.loads((target / "capture.json").read_text(encoding="utf-8"))
    assert manifest["runtime"]["protection_verified"] is True
    assert manifest["runtime"]["script"] == str(Path(control.__file__).resolve())


@windows_only
def test_the_system_directory_comes_from_the_os_not_the_environment(monkeypatch) -> None:
    real = control.system_directory()
    monkeypatch.setenv("SystemRoot", "C:\\attacker")
    monkeypatch.setenv("windir", "C:\\attacker")
    assert control.system_directory() == real
    assert str(real).lower().endswith("system32")
    assert control.system_tool("logman") == str(real / "logman.exe")
    assert "attacker" not in control.system_tool("icacls")


@windows_only
def test_this_hosts_user_writable_python_would_be_refused_and_system_files_pass() -> None:
    """Real icacls and real owners: a user-profile interpreter fails, Windows' own tree passes."""

    system = Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32"
    ok = control.RuntimeFacts(
        script=system / "notepad.exe",
        executable=system / "cmd.exe",
        stdlib_file=system / "kernel32.dll",
        base_prefix=Path("C:/Program Files/Common Files"),
        sys_path_dirs=(system,),
        sys_path_files=(),
        module_files=(),
        isolated=True,
        bytecode_disabled=True,
        in_venv=False,
    )
    assert control.runtime_trust_problems(ok) == []
    profile = Path(os.environ["USERPROFILE"])
    bad = control.RuntimeFacts(
        **{
            **{f: getattr(ok, f) for f in ok.__slots__},
            "executable": profile / "x" / "python.exe",
            "sys_path_dirs": (profile,),
        }
    )
    assert control.runtime_trust_problems(bad)


def test_repo_root_must_be_absolute_a_checkout_and_the_same_tool(tmp_path: Path) -> None:
    with pytest.raises(control.CaptureRefused, match="absolute"):
        control.resolve_reports_root(Path("relative"))
    with pytest.raises(control.CaptureRefused, match="not a StableNew checkout"):
        control.resolve_reports_root(tmp_path)
    tool = tmp_path / control._TOOL_RELATIVE
    tool.parent.mkdir(parents=True)
    tool.write_text("# a different capture_control.py\n", encoding="utf-8")
    with pytest.raises(control.CaptureRefused, match="differs from the copy being run"):
        control.resolve_reports_root(tmp_path)
    shutil.copyfile(control.__file__, tool)
    assert control.resolve_reports_root(tmp_path) == tmp_path.resolve() / "reports"


def test_a_checkout_link_for_reports_is_refused(tmp_path: Path) -> None:
    tool = tmp_path / control._TOOL_RELATIVE
    tool.parent.mkdir(parents=True)
    shutil.copyfile(control.__file__, tool)
    target = tmp_path / "elsewhere"
    target.mkdir()
    try:
        os.symlink(target, tmp_path / "reports", target_is_directory=True)
    except OSError:
        pytest.skip("symlinks need privilege on this host")
    with pytest.raises(control.CaptureRefused, match="link"):
        control.resolve_reports_root(tmp_path)


# -- F2: beacons must intersect --------------------------------------------------------------------------------------------


@windows_only
def test_beacons_that_miss_each_other_by_more_than_a_timestamp_are_unusable(tmp_path: Path) -> None:
    result, _, _ = run_analysis(
        tmp_path, lambda t, d: canary_scenario(t, d, beacon_trace_shift={2: 8_000_000})
    )
    assert result["verdict"] == "INCONCLUSIVE"
    assert any("disagree about the clock offset" in p for p in result["capture_problems"])
    assert result["clock"] is None


@windows_only
def test_beacons_that_miss_by_less_than_one_slack_widen_the_interval(tmp_path: Path) -> None:
    result, _, _ = run_analysis(
        tmp_path, lambda t, d: canary_scenario(t, d, beacon_trace_shift={2: 3_000_000})
    )
    assert result["clock"]["intersection_gap_ms"] > 0
    assert not any("disagree" in p for p in result["capture_problems"])


# -- F3: loss counters ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("extra", "fragment"),
    [
        ({"EventsLost": "3"}, "EventsLost = 3"),
        ({"BuffersLost": "1"}, "BuffersLost = 1"),
        ({"BuffersLost": "many"}, "BuffersLost is unreadable"),
    ],
)
@windows_only
def test_a_header_that_reports_loss_is_inconclusive(
    tmp_path: Path, extra: dict, fragment: str
) -> None:
    result, _, _ = run_analysis(
        tmp_path, lambda t, d: canary_scenario(t, d), header_extra={"file": extra}
    )
    assert result["verdict"] == "INCONCLUSIVE"
    assert any(fragment in p for p in result["capture_problems"])


@windows_only
def test_a_header_that_reports_zero_loss_passes(tmp_path: Path) -> None:
    result, _, _ = run_analysis(
        tmp_path,
        lambda t, d: canary_scenario(t, d),
        header_extra={"file": {"EventsLost": "0", "BuffersLost": "0"}},
    )
    assert result["verdict"] == "PASS", result["capture_problems"]


@windows_only
def test_a_live_session_that_does_not_report_buffers_lost_is_not_admitted(tmp_path: Path) -> None:
    logman = FakeLogman()
    target, _report, env = started_capture(tmp_path, logman)
    logman.buffers_lost = None
    problems = admission_for(target, env, tmp_path).live_problems()
    assert any("buffers lost = None" in p for p in problems)


# -- F4: beacon paths ------------------------------------------------------------------------------------------------------


@windows_only
def test_a_beacon_path_is_rebuilt_under_the_validated_directory(tmp_path: Path) -> None:
    good = f"beacon-001-{'a' * 8}.tmp"
    expected = str(tmp_path / "beacons" / good)
    assert analysis.beacon_path(tmp_path, {"file": f"beacons/{good}"}) == expected
    assert analysis.beacon_path(tmp_path, {"path": f"C:\\anywhere\\else\\{good}"}) == expected
    for hostile in ("..\\..\\x\\beacon-001-aaaaaaaa.tmp.exe", "../secret.txt", "", "beacons/"):
        assert analysis.beacon_path(tmp_path, {"file": hostile}) == ""
    assert analysis.beacon_path(tmp_path, {}) == ""


@windows_only
def test_a_log_whose_beacon_names_no_beacon_file_is_inconclusive(tmp_path: Path) -> None:
    def tamper(target: Path) -> None:
        text = (target / "windows.jsonl").read_text(encoding="utf-8").splitlines()
        out = []
        for line in text:
            row = json.loads(line)
            if row.get("type") == "beacon" and row["n"] == 1:
                row["file"] = "..\\..\\somewhere\\else.txt"
            out.append(json.dumps(row))
        (target / "windows.jsonl").write_text("\n".join(out) + "\n", encoding="utf-8")

    result, _, _ = run_analysis(tmp_path, lambda t, d: canary_scenario(t, d), after_write=tamper)
    assert result["verdict"] == "INCONCLUSIVE"
    assert any("does not name a beacon file" in p for p in result["capture_problems"])


@windows_only
def test_the_monitor_logs_a_relative_beacon_file_and_no_absolute_path(tmp_path: Path) -> None:
    target, _report, env = started_capture(tmp_path, FakeLogman())
    monitor = monitor_for(admission_for(target, env, tmp_path))
    monitor.beacon("start")
    monitor.log.close()
    beacon = next(e for e in lines(target) if e["type"] == "beacon")
    assert "path" not in beacon
    assert beacon["file"].startswith("beacons/beacon-001-") and "\\" not in beacon["file"]
    assert str(tmp_path) not in json.dumps(lines(target))


# -- F5: unresolved events keep their instant --------------------------------------------------------------------------------


def test_unresolved_events_in_one_second_are_not_collapsed_but_exact_repeats_are() -> None:
    def create(ts_ns: int) -> RawEvent:
        return RawEvent("Microsoft-Windows-Kernel-File", 12, 700, {}, ts_ns)

    stamp = 1_700_000_000 * 1_000_000_000
    events = [create(stamp + 100_000_000), create(stamp + 400_000_000), create(stamp + 400_000_000)]
    out = file_events(iter(events), frozenset({700}), lambda p: p)
    assert [e.ts_ns for e in out] == [stamp + 100_000_000, stamp + 400_000_000]
    assert all(e.mode == "unknown" for e in out)


# -- F6: the capture directory and the window log -------------------------------------------------------------------------


@windows_only
def test_an_entry_this_tool_chain_does_not_create_makes_the_analysis_inconclusive(
    tmp_path: Path,
) -> None:
    result, _, _ = run_analysis(
        tmp_path,
        lambda t, d: canary_scenario(t, d),
        after_write=lambda target: (target / "note.txt").write_text("x", encoding="utf-8"),
    )
    assert result["verdict"] == "INCONCLUSIVE"
    assert any("does not create" in p and "note.txt" in p for p in result["capture_problems"])


@windows_only
def test_a_stray_file_in_the_beacons_directory_is_reported(tmp_path: Path) -> None:
    def plant(target: Path) -> None:
        (target / "beacons").mkdir()
        (target / "beacons" / "payload.dll").write_bytes(b"MZ")

    result, _, _ = run_analysis(tmp_path, lambda t, d: canary_scenario(t, d), after_write=plant)
    assert result["verdict"] == "INCONCLUSIVE"
    assert any("beacons directory holds unexpected" in p for p in result["capture_problems"])


@windows_only
def test_a_clean_directory_has_no_inventory_problem(tmp_path: Path) -> None:
    result, target, _ = run_analysis(tmp_path, lambda t, d: canary_scenario(t, d))
    assert result["verdict"] == "PASS", result["capture_problems"]
    assert analysis.directory_problems(target) == []


@windows_only
def test_the_window_log_cannot_be_opened_for_writing_by_another_process_while_the_session_runs(
    tmp_path: Path,
) -> None:
    log = session.WindowLog(tmp_path / "windows.jsonl")
    log.write({"type": "header"})
    try:
        with pytest.raises(PermissionError):
            (tmp_path / "windows.jsonl").open("a", encoding="utf-8")
        with pytest.raises(PermissionError):
            (tmp_path / "windows.jsonl").unlink()
        assert json.loads((tmp_path / "windows.jsonl").read_text(encoding="utf-8")) == {
            "type": "header"
        }
    finally:
        log.close()
    with (tmp_path / "windows.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("\n")


@windows_only
def test_a_closed_window_log_reopens_for_later_lines(tmp_path: Path) -> None:
    log = session.WindowLog(tmp_path / "w.jsonl")
    log.write({"n": 1})
    log.close()
    log.write({"n": 2})
    log.close()
    written = (tmp_path / "w.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(x)["n"] for x in written] == [1, 2]


# -- F7: admission projects capacity and the deadline ---------------------------------------------------------------------


def test_a_request_that_could_outlive_the_deadline_is_refused(tmp_path: Path) -> None:
    target, _report, env = started_capture(tmp_path, FakeLogman(), minutes=2)
    admission = admission_for(target, env, tmp_path)
    assert admission.projection_problems(30.0) == []
    assert any("outlive the capture deadline" in p for p in admission.projection_problems(90.0))


def test_a_small_cap_cannot_take_a_request_the_trace_volume_would_overflow(tmp_path: Path) -> None:
    target, _report, env = started_capture(tmp_path, FakeLogman(), max_mb=64)
    problems = admission_for(target, env, tmp_path).projection_problems(30.0)
    assert any(p.startswith("file: projected size") for p in problems)
    (tmp_path / "big").mkdir()
    big, _report, big_env = started_capture(tmp_path / "big", FakeLogman(), max_mb=1024)
    assert admission_for(big, big_env, tmp_path).projection_problems(600.0) == []


def test_the_projection_uses_the_larger_of_the_measured_and_the_floor_rate(tmp_path: Path) -> None:
    target, _report, env = started_capture(tmp_path, FakeLogman(), max_mb=256)
    admission = admission_for(target, env, tmp_path)
    admission.now = lambda: FIXED_NOW + timedelta(minutes=10)
    with (target / "file.etl").open("wb") as handle:
        handle.truncate(150 * 1024 * 1024)
    assert admission.projection_problems(30.0) == []  # 150 + 36 + 32 MB < 230 MB
    with (target / "file.etl").open("wb") as handle:
        handle.truncate(190 * 1024 * 1024)
    assert any("file: projected size" in p for p in admission.projection_problems(30.0))
    # a rate faster than the floor is believed over the floor: 150 MB in 1 minute ~ 2.5 MB/s
    admission.now = lambda: FIXED_NOW + timedelta(minutes=1)
    with (target / "file.etl").open("wb") as handle:
        handle.truncate(100 * 1024 * 1024)
    assert any("file: projected size" in p for p in admission.projection_problems(60.0))


def test_the_stop_flush_alone_can_exceed_a_tiny_cap(tmp_path: Path) -> None:
    target, _report, env = started_capture(tmp_path, FakeLogman(), max_mb=16)
    problems = admission_for(target, env, tmp_path).projection_problems(None)
    assert any("exceeds 90% of the 16 MB cap" in p for p in problems)


@windows_only
def test_a_request_the_projection_refuses_is_never_launched(tmp_path: Path) -> None:
    target, _report, env = started_capture(tmp_path, FakeLogman(), max_mb=64)
    marker = tmp_path / "must-not-exist.txt"
    monitor = monitor_for(admission_for(target, env, tmp_path))
    outcome = monitor.runner()(
        [PY, "-I", "-c", f"open({str(marker)!r}, 'w').write('ran')"],
        timeout_seconds=20.0,
        max_stdout_bytes=1024,
    )
    assert outcome.launch_error and outcome.returncode is None
    assert not marker.exists()
    assert monitor.admission.pending_timeout is None


# -- F10: analyses are listed and bind the analyzer ----------------------------------------------------------------------


def test_earlier_analyses_are_listed_in_the_next_result(tmp_path: Path) -> None:
    (tmp_path / "analysis.json").write_text(
        json.dumps({"verdict": "INCONCLUSIVE", "analyzer_version": "1", "finished_utc": "t"}),
        encoding="utf-8",
    )
    (tmp_path / "analysis-2.json").write_text("{broken", encoding="utf-8")
    rows = analysis.earlier_analyses(tmp_path)
    assert [(r["file"], r["verdict"]) for r in rows] == [
        ("analysis-2.json", "UNREADABLE"),
        ("analysis.json", "INCONCLUSIVE"),
    ] or [(r["file"], r["verdict"]) for r in rows] == [
        ("analysis.json", "INCONCLUSIVE"),
        ("analysis-2.json", "UNREADABLE"),
    ]


@windows_only
def test_a_result_carries_the_analyzer_hash_and_the_earlier_analyses(tmp_path: Path) -> None:
    result, _, _ = run_analysis(tmp_path, lambda t, d: canary_scenario(t, d))
    assert result["analyzer_sha256"] == analysis.analyzer_sha256()
    assert result["earlier_analyses"] == []


def test_a_proof_from_another_analyzer_file_is_refused(tmp_path: Path) -> None:
    target, _report, env = started_capture(tmp_path, FakeLogman())
    stale = make_proof(tmp_path, analyzer_sha256="0" * 64)
    admission = admission_for(target, env, tmp_path, proof_path=stale)
    assert any("different capture_analysis.py" in p for p in admission.static_problems())


def test_a_failed_sibling_analysis_voids_the_proof_but_an_inconclusive_one_does_not(
    tmp_path: Path,
) -> None:
    target, _report, env = started_capture(tmp_path, FakeLogman())
    home = tmp_path / "proofs"
    home.mkdir()
    proof = make_proof(home, **{"analyzer_sha256": analysis.analyzer_sha256()})
    (home / "analysis-1.json").write_text(json.dumps({"verdict": "INCONCLUSIVE"}), encoding="utf-8")
    admission = admission_for(target, env, tmp_path, proof_path=proof)
    assert admission.static_problems() == []
    (home / "analysis-2.json").write_text(json.dumps({"verdict": "FAIL"}), encoding="utf-8")
    assert any("analysis-2.json" in p and "FAIL" in p for p in admission.static_problems())
    (home / "analysis-2.json").write_text("{nope", encoding="utf-8")
    assert any("analysis-2.json" in p and "unreadable" in p for p in admission.static_problems())


# -- F7b: the conversion timeout scales with the trace ----------------------------------------------------------------------


def test_the_conversion_timeout_grows_with_the_trace(tmp_path: Path) -> None:
    from tools.qualification.ai111 import etw

    small = tmp_path / "s.etl"
    small.write_bytes(b"0")
    large = tmp_path / "l.etl"
    with large.open("wb") as handle:
        handle.truncate(512 * 1024 * 1024)
    assert etw.conversion_timeout(small) == pytest.approx(etw.CONVERT_BASE_SECONDS, abs=0.01)
    assert etw.conversion_timeout(large) == pytest.approx(
        etw.CONVERT_BASE_SECONDS + 512 * etw.CONVERT_SECONDS_PER_MB
    )
    assert etw.conversion_timeout(tmp_path / "missing.etl") == etw.CONVERT_BASE_SECONDS


def test_the_default_converter_passes_the_scaled_timeout_to_the_bounded_tool(
    tmp_path: Path, monkeypatch
) -> None:
    from tools.qualification.ai111 import etw

    seen: dict = {}

    def fake_tool(command, *, timeout_seconds=60.0):
        seen["timeout"] = timeout_seconds
        seen["tool"] = PureWindowsPath(command[0]).name
        return 0, ""

    monkeypatch.setattr(etw, "bounded_tool", fake_tool)
    etl = tmp_path / "f.etl"
    with etl.open("wb") as handle:
        handle.truncate(100 * 1024 * 1024)
    etw.convert_trace(etl, tmp_path / "f.xml", tmp_path / "f.txt")
    assert seen["timeout"] == pytest.approx(
        etw.CONVERT_BASE_SECONDS + 100 * etw.CONVERT_SECONDS_PER_MB
    )
    assert seen["tool"].lower() == "tracerpt.exe"
