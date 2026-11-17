"""PR-DEVEX-QUIET-LOCAL-TESTS: ``tools/ci/quiet_run.py`` with a fake Win32 surface (no desktop, job or process)."""

from __future__ import annotations

import struct
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ci"))

import quiet_run as qr  # noqa: E402
import run_pr_gate  # noqa: E402
import run_sharded_census  # noqa: E402

LOCAL = {"PATH": str(Path(sys.executable).parent)}


class FakeWin32:
    def __init__(
        self,
        *,
        desktop_fails: bool = False,
        desktop_start_fails: bool = False,
        assign_ok: bool = True,
        exit_code: int = 0,
        cores: list[qr.Core] | None = None,
        job: int = 50,
        waits: list[object] | None = None,
    ) -> None:
        self.calls: list[tuple] = []
        self.desktop_fails = desktop_fails
        self.desktop_start_fails = desktop_start_fails
        self.assign_ok = assign_ok
        self.code = exit_code
        self.cores = cores if cores is not None else []
        self.job = job
        self.waits = list(waits or [True])
        self.closed: list[int] = []
        self.started: list[dict] = []

    def window_station(self) -> str:
        return "WinSta0"

    def open_desktop(self, name: str) -> int:
        self.calls.append(("open_desktop", name))
        if self.desktop_fails:
            raise OSError(5, "denied")
        return 7

    def processor_cores(self) -> list[qr.Core]:
        return self.cores

    def create_job(self, *, priority_class: int, affinity: int | None) -> int:
        self.calls.append(("create_job", priority_class, affinity))
        return self.job

    def create_suspended(
        self, application, command_line, *, desktop, environment, cwd, priority_class
    ):
        self.started.append(
            {
                "application": application,
                "command_line": command_line,
                "desktop": desktop,
                "environment": dict(environment),
                "cwd": cwd,
                "priority_class": priority_class,
            }
        )
        if desktop and self.desktop_start_fails:
            raise OSError(5, "desktop access denied")
        return 100, 101

    def assign(self, job: int, process: int) -> bool:
        self.calls.append(("assign", job, process))
        return self.assign_ok

    def set_affinity(self, process: int, mask: int) -> bool:
        self.calls.append(("set_affinity", process, mask))
        return True

    def resume(self, thread: int) -> None:
        self.calls.append(("resume", thread))

    def wait(self, process: int, timeout_ms: int) -> bool:
        self.calls.append(("wait", timeout_ms))
        outcome = self.waits.pop(0) if self.waits else True
        if isinstance(outcome, BaseException):
            raise outcome
        return bool(outcome)

    def exit_code(self, process: int) -> int:
        return self.code

    def terminate(self, job: int, process: int, code: int) -> None:
        self.calls.append(("terminate", job, process, code))

    def close(self, handle: int) -> None:
        self.closed.append(handle)


HYBRID = [qr.Core(1, 0, 0b11 << (2 * i)) for i in range(8)] + [
    qr.Core(0, 0, 1 << (16 + i)) for i in range(16)
]


def _run(fake: FakeWin32, command=None, env=None, **kwargs) -> tuple[int, list[str]]:
    warnings: list[str] = []
    code = qr.run(
        command or [sys.executable, "-c", "pass"],
        env=LOCAL if env is None else env,
        win32=fake,
        platform="win32",
        warn=warnings.append,
        **kwargs,
    )
    return code, warnings


# -- when it applies -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("environ", "platform", "quiet"),
    [
        ({}, "win32", True),
        ({}, "linux", False),
        ({"CI": "true"}, "win32", False),
        ({"STABLENEW_QUIET_RUN": "1"}, "win32", False),
        ({"STABLENEW_TESTS_VISIBLE": "1"}, "win32", False),
        ({"STABLENEW_TESTS_VISIBLE": "0"}, "win32", True),
        ({"STABLENEW_DESKTOP_LANE": "1"}, "win32", False),
    ],
)
def test_quiet_applies_only_to_local_windows_runs(environ, platform, quiet) -> None:
    assert qr.should_quiet(environ, platform) is quiet


def test_wrap_prefixes_the_quiet_runner_only_when_quiet() -> None:
    command = ["ruff", "check", "."]
    wrapped = qr.wrap(command, environ={}, platform="win32", python="py")
    assert wrapped == ["py", str(qr.SCRIPT), "--", "ruff", "check", "."]
    assert qr.wrap(command, environ={"CI": "1"}, platform="win32") == command
    assert qr.wrap(command, environ={}, platform="darwin") == command


def test_pass_through_runs_the_command_unchanged(monkeypatch) -> None:
    seen = {}

    def fake_subprocess_run(command, **kwargs):
        seen.update(command=command, **kwargs)
        return SimpleNamespace(returncode=3)

    monkeypatch.setattr(qr.subprocess, "run", fake_subprocess_run)
    fake = FakeWin32()
    code, _ = _run(fake, ["tool", "a"], env={"STABLENEW_TESTS_VISIBLE": "1"})
    assert code == 3 and seen["command"] == ["tool", "a"]
    assert "STABLENEW_QUIET_RUN" not in seen["env"]
    assert fake.calls == [] and fake.started == []


# -- the quiet launch -------------------------------------------------------------------------------------------------


def test_quiet_launch_uses_hidden_desktop_low_priority_job_and_efficiency_cores(
    monkeypatch,
) -> None:
    monkeypatch.setattr(qr.os, "cpu_count", lambda: 32)
    fake = FakeWin32(cores=HYBRID, exit_code=4)
    code, warnings = _run(fake, [sys.executable, "-c", "print('a b')"], cwd="C:\\work")

    assert code == 4 and warnings == []
    started = fake.started[0]
    assert started["desktop"] == "WinSta0\\StableNewTests"
    assert started["priority_class"] == qr.BELOW_NORMAL_PRIORITY_CLASS
    assert started["environment"]["STABLENEW_QUIET_RUN"] == "1"
    assert started["cwd"] == "C:\\work"
    assert started["command_line"].endswith("-c \"print('a b')\"")
    assert ("create_job", qr.BELOW_NORMAL_PRIORITY_CLASS, 0xFFFF0000) in fake.calls
    # created suspended, put in the job, then resumed: no instant outside the job's limits
    order = [call[0] for call in fake.calls]
    assert order.index("assign") < order.index("resume") < order.index("wait")
    assert "set_affinity" not in order
    assert sorted(fake.closed) == [50, 100, 101]


@pytest.mark.parametrize(
    ("value", "affinity"),
    [("all", None), ("ALL ", None), ("efficiency", 0xFFFF0000), ("bogus", 0xFFFF0000)],
)
def test_cores_setting_chooses_efficiency_affinity_or_priority_only(
    monkeypatch, value, affinity
) -> None:
    monkeypatch.setattr(qr.os, "cpu_count", lambda: 32)
    fake = FakeWin32(cores=HYBRID)
    assert _run(fake, env={**LOCAL, "STABLENEW_TESTS_CORES": value})[0] == 0
    assert ("create_job", qr.BELOW_NORMAL_PRIORITY_CLASS, affinity) in fake.calls
    if value.strip() != "efficiency" and value != "bogus":
        assert qr.cores_setting({"STABLENEW_TESTS_CORES": value}) == "all"


def test_missing_desktop_warns_once_and_runs_visibly_at_low_priority() -> None:
    fake = FakeWin32(desktop_fails=True)
    code, warnings = _run(fake)
    assert code == 0
    assert len(warnings) == 1 and "running visibly at low priority" in warnings[0]
    assert fake.started[0]["desktop"] is None
    assert fake.started[0]["priority_class"] == qr.BELOW_NORMAL_PRIORITY_CLASS


def test_desktop_start_failure_falls_back_to_a_visible_start() -> None:
    fake = FakeWin32(desktop_start_fails=True)
    code, warnings = _run(fake)
    assert code == 0 and len(warnings) == 1
    assert [s["desktop"] for s in fake.started] == ["WinSta0\\StableNewTests", None]


def test_without_a_job_the_child_still_gets_priority_and_affinity(monkeypatch) -> None:
    monkeypatch.setattr(qr.os, "cpu_count", lambda: 32)
    fake = FakeWin32(cores=HYBRID, assign_ok=False)
    assert _run(fake)[0] == 0
    assert ("set_affinity", 100, 0xFFFF0000) in fake.calls
    assert fake.started[0]["priority_class"] == qr.BELOW_NORMAL_PRIORITY_CLASS


def test_interrupt_ends_the_tree_when_the_child_does_not_exit() -> None:
    fake = FakeWin32(waits=[KeyboardInterrupt(), False, True], exit_code=130)
    assert _run(fake)[0] == 130
    assert ("terminate", 50, 100, 130) in fake.calls


def test_interrupt_leaves_a_child_that_exits_on_its_own() -> None:
    fake = FakeWin32(waits=[False, KeyboardInterrupt(), True], exit_code=2)
    assert _run(fake)[0] == 2
    assert not [call for call in fake.calls if call[0] == "terminate"]


def test_unknown_program_is_reported_not_started() -> None:
    fake = FakeWin32()
    code, warnings = _run(fake, ["definitely-not-a-real-program-xyz"])
    assert code == qr.STARTUP_FAILURE_EXIT and "cannot find" in warnings[0]
    assert fake.started == []


# -- efficiency cores ------------------------------------------------------------------------------------------------


def test_efficiency_mask_selects_the_lowest_class_on_a_hybrid_cpu() -> None:
    assert qr.efficiency_mask(HYBRID, 32) == 0xFFFF0000


@pytest.mark.parametrize(
    ("cores", "logical"),
    [
        ([qr.Core(0, 0, 0b11), qr.Core(0, 0, 0b1100)], 4),  # not hybrid
        (HYBRID, 65),  # beyond one 64-bit affinity mask
        ([qr.Core(1, 0, 1), qr.Core(0, 1, 1)], 2),  # more than one processor group
        ([], 8),
    ],
)
def test_efficiency_mask_is_priority_only_when_affinity_is_not_meaningful(cores, logical) -> None:
    assert qr.efficiency_mask(cores, logical) is None


def _core_record(efficiency: int, mask: int, group: int = 0) -> bytes:
    body = struct.pack("<BB20sH", 0, efficiency, b"\0" * 20, 1) + struct.pack(
        "<QH6s", mask, group, b"\0" * 6
    )
    return struct.pack("<II", 0, 8 + len(body)) + body


def test_parse_processor_cores_reads_processor_core_records() -> None:
    other = struct.pack("<II", 2, 16) + b"\0" * 8  # a non-core record is skipped by its Size
    raw = _core_record(1, 0b11) + other + _core_record(0, 1 << 16, group=0)
    assert qr.parse_processor_cores(raw) == [qr.Core(1, 0, 0b11), qr.Core(0, 0, 1 << 16)]


def test_environment_block_is_sorted_and_double_nul_terminated() -> None:
    assert qr.environment_block({"b": "2", "A": "1"}) == "A=1\0b=2\0\0"


# -- pytest relaunch -------------------------------------------------------------------------------------------------


def _relaunch(argv, orig, environ=None):
    launched: list[list[str]] = []
    exits: list[int] = []
    done = qr.relaunch_pytest_session(
        argv=argv,
        orig_argv=orig,
        environ={} if environ is None else environ,
        platform="win32",
        runner=lambda command: launched.append(list(command)) or 9,
        exit=exits.append,
    )
    return done, launched, exits


def test_command_line_pytest_relaunches_with_the_same_arguments() -> None:
    done, launched, exits = _relaunch(
        ["C:\\venv\\Lib\\site-packages\\pytest\\__main__.py", "tests/x", "-q"],
        ["C:\\venv\\Scripts\\python.exe", "-X", "dev", "-m", "pytest", "tests/x", "-q"],
    )
    assert done and exits == [9]
    assert launched == [[sys.executable, "-X", "dev", "-m", "pytest", "tests/x", "-q"]]


def test_pytest_console_script_relaunches() -> None:
    done, launched, _ = _relaunch(
        ["C:\\venv\\Scripts\\pytest", "-k", "a b"],
        ["C:\\venv\\Scripts\\python.exe", "C:\\venv\\Scripts\\pytest.exe", "-k", "a b"],
    )
    assert done and launched == [[sys.executable, "C:\\venv\\Scripts\\pytest.exe", "-k", "a b"]]


@pytest.mark.parametrize(
    ("argv", "orig", "environ"),
    [
        (
            ["tools/ci/census_shards.py", "run"],
            ["python", "tools/ci/census_shards.py", "run"],
            {},
        ),  # pytest.main()
        (["-c"], ["python", "-c", "import pytest; pytest.main()"], {}),
        (
            ["C:\\p\\pytest\\__main__.py", "-q"],
            ["python", "-m", "pytest", "-q"],
            {"STABLENEW_QUIET_RUN": "1"},
        ),
        (["C:\\p\\pytest\\__main__.py", "-q"], ["python", "-m", "pytest", "-q"], {"CI": "1"}),
        (
            ["C:\\p\\pytest\\__main__.py", "-q"],
            ["python", "-m", "pytest", "-q"],
            {"STABLENEW_TESTS_VISIBLE": "1"},
        ),
        (
            ["C:\\p\\pytest\\__main__.py", "-q"],
            ["python", "-m", "pytest", "-x"],
            {},
        ),  # argv was rewritten
    ],
)
def test_no_relaunch_for_in_process_nested_ci_or_opted_out_runs(argv, orig, environ) -> None:
    done, launched, exits = _relaunch(argv, orig, environ)
    assert not done and launched == [] and exits == []


# -- gate and census wiring ------------------------------------------------------------------------------------------


def test_pr_gate_routes_every_step_through_quiet_run(monkeypatch) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(run_pr_gate.quiet_run, "should_quiet", lambda *a, **k: True)
    monkeypatch.setattr(run_pr_gate, "missing_required_tools", lambda: [])
    monkeypatch.setattr(
        run_pr_gate.subprocess,
        "run",
        lambda command, **_: commands.append(list(command)) or SimpleNamespace(returncode=0),
    )
    assert run_pr_gate.main() == 0
    assert len(commands) == len(run_pr_gate.GATE_STEPS)
    for command, (_, step) in zip(commands, run_pr_gate.GATE_STEPS, strict=True):
        assert command[1:3] == [str(qr.SCRIPT), "--"] and command[3:] == list(step)


def test_sharded_census_workers_run_through_quiet_run(monkeypatch, tmp_path) -> None:
    started: list[list[str]] = []

    class FakePopen:
        def __init__(self, command, **_kwargs):
            started.append(list(command))

        def wait(self):
            return 0

    monkeypatch.setattr(run_sharded_census.quiet_run, "should_quiet", lambda *a, **k: True)
    monkeypatch.setattr(run_sharded_census.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(run_sharded_census.census_shards, "verify_results", lambda *_: ([], {}))
    monkeypatch.setattr(run_sharded_census.census_shards, "render_aggregate", lambda *_: "")
    assert (
        run_sharded_census.main(["--workers", "2", "--shared-tree", "--out-dir", str(tmp_path)])
        == 0
    )
    assert len(started) == 2
    for index, command in enumerate(started):
        assert command[1:3] == [str(qr.SCRIPT), "--"]
        assert command[3:] == run_sharded_census.worker_command(2, index, tmp_path)
