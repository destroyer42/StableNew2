"""PR-AI-QUAL-113: ownership-bound session monitoring, proven with deterministic synthetic children.

Nothing downloaded is executed. The process-tree and teardown evidence is real (the owned job object, through the real
bounded runner); the connection and file channels are fed by a cooperative journal that the synthetic children write to,
because no unprivileged provider can observe those channels for the whole life of a process on this host.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.utils.process_observation import ProcessLifecycleEvent  # noqa: E402
from tests.ai_assist.ai113_support import (  # noqa: E402
    WRAPPER,
    JournalProvider,
    journal_monitor,
)
from tools.qualification.ai111 import ownership  # noqa: E402
from tools.qualification.ai111.ownership import (  # noqa: E402
    COMPLETE,
    SAMPLED,
    UNAVAILABLE,
    ChannelEvent,
    OwnedSessionMonitor,
    OwnershipPolicy,
    attribute,
    default_host_monitor,
    descendant_findings,
    owned_windows,
)

windows_only = pytest.mark.skipif(os.name != "nt", reason="Windows job objects")

#: The base interpreter has no venv launcher, so a clean child is exactly one process in the job.
PY = getattr(sys, "_base_executable", sys.executable)


def _ev(kind: str, pid: int | None, ns: int) -> ProcessLifecycleEvent:
    return ProcessLifecycleEvent(kind, pid, ns)


# -- attribution (pure) -----------------------------------------------------------------------------------------------


def test_events_are_attributed_only_to_pids_in_the_owned_record_and_their_lifetime() -> None:
    windows = owned_windows(
        [_ev("new", 10, 100), _ev("new", 11, 150), _ev("exit", 11, 400), _ev("exit", 10, 900)],
        request_start_ns=50,
    )
    events = [
        ChannelEvent(10, "mine", 120),
        ChannelEvent(11, "child-during-life", 300),
        ChannelEvent(11, "pid-reused-after-exit", 500),
        ChannelEvent(99, "someone-else", 200),
        ChannelEvent(10, "before-the-request", 10),
        ChannelEvent(10, "no-timestamp", None),
    ]
    owned, foreign, ambiguous = attribute(events, windows)
    assert [e.detail for e in owned] == ["mine", "child-during-life", "no-timestamp"]
    assert foreign == 1, "pid 99 was never in the owned record"
    assert ambiguous == 2, (
        "owned pids at a time outside their window are flagged, never silently dropped"
    )


def test_a_terminated_member_keeps_its_window_open_until_termination() -> None:
    windows = owned_windows([_ev("new", 10, 100), _ev("terminated", 10, 700)], request_start_ns=0)
    owned, foreign, ambiguous = attribute(
        [ChannelEvent(10, "late", 650), ChannelEvent(10, "gone", 800)], windows
    )
    assert [e.detail for e in owned] == ["late"] and foreign == 0 and ambiguous == 1


def test_a_reused_root_pid_or_a_member_without_a_pid_is_a_finding() -> None:
    policy = OwnershipPolicy()
    conhost = os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "System32", "conhost.exe")
    clean = [ProcessLifecycleEvent("new", 100, 1, "C:\\x\\root.exe")]
    assert descendant_findings(clean, 100, policy) == []
    reused = [*clean, _ev("exit", 100, 2), ProcessLifecycleEvent("new", 100, 3, "C:\\evil.exe")]
    assert "pid_reused_in_tree" in descendant_findings(reused, 100, policy)
    assert "unexpected_descendants" in descendant_findings(reused, 100, policy)
    assert "unresolved_member_pid" in descendant_findings(
        [*clean, _ev("new", None, 4)], 100, policy
    )
    helper = [*clean, ProcessLifecycleEvent("new", 101, 2, conhost)]
    assert descendant_findings(helper, 100, policy) == []
    two_helpers = [*helper, ProcessLifecycleEvent("new", 102, 3, conhost)]
    assert descendant_findings(two_helpers, 100, policy) == ["unexpected_descendants"]


# -- fail closed before anything runs ---------------------------------------------------------------------------------


def test_this_hosts_default_monitor_is_not_ready_because_its_channels_are_only_sampled() -> None:
    monitor = default_host_monitor(OwnershipPolicy())
    problems = monitor.provider_problems()
    if os.name == "nt":
        assert not any("Windows job object" in p for p in problems)
    for channel in ("connections", "files"):
        assert any(p.startswith(f"{channel}: no {COMPLETE} provider") for p in problems)
    assert {p.coverage for p in monitor.providers} == {SAMPLED}
    assert monitor.readiness(), "sampled coverage must never be treated as ready"


def test_a_monitor_with_a_missing_or_unavailable_channel_is_not_ready(tmp_path: Path) -> None:
    journal = tmp_path / "j.jsonl"
    only_connections = OwnedSessionMonitor(
        OwnershipPolicy(), [JournalProvider("connections", journal)], kind="hermetic"
    )
    assert any(p == "files: no provider" for p in only_connections.provider_problems())
    unavailable = OwnedSessionMonitor(
        OwnershipPolicy(),
        [JournalProvider("connections", journal), JournalProvider("files", journal, UNAVAILABLE)],
        kind="hermetic",
    )
    assert any("files: no lifetime_complete provider" in p for p in unavailable.provider_problems())


# -- canary ----------------------------------------------------------------------------------------------------------


@windows_only
def test_canary_proves_each_channel_and_the_descendant(tmp_path: Path) -> None:
    monitor, _journal = journal_monitor(tmp_path)
    report = monitor.run_canary()
    assert report == {
        "passed": True,
        "saw": {
            "descendant": True,
            "standard_user": True,
            "files": True,
            "writes": True,
            "connections": True,
        },
    }
    assert monitor.readiness() == [] or monitor.readiness() == (
        ["ownership evidence requires the Windows job object; this host has none"]
        if os.name != "nt"
        else []
    )
    assert monitor.violations() == [], "the canary's expected activity is never a session violation"


@windows_only
def test_a_blind_provider_fails_the_canary_and_the_monitor_refuses(tmp_path: Path) -> None:
    monitor, _journal = journal_monitor(tmp_path, silent_canary=True)
    report = monitor.run_canary()
    assert report["passed"] is False
    problems = monitor.readiness()
    assert any(p.startswith("connections: the canary did not show") for p in problems)
    assert any(p.startswith("files: the canary did not show") for p in problems)


def test_an_unrun_canary_is_not_ready(tmp_path: Path) -> None:
    monitor, _ = journal_monitor(tmp_path)
    if os.name == "nt":
        assert monitor.readiness() == ["monitor canary has not been run"]
    assert "monitor canary has not been run" in monitor.readiness()


# -- monitored requests -----------------------------------------------------------------------------------------------


class Rig:
    def __init__(self, tmp_path: Path, **monitor_options) -> None:
        self.tmp = tmp_path
        self.ai_root = tmp_path / "ai-root"
        (self.ai_root / "work").mkdir(parents=True)
        self.monitor, self.journal = journal_monitor(tmp_path, **monitor_options)
        self.monitor.bind_roots(read_roots=(self.ai_root,), write_roots=(self.ai_root / "work",))
        self.wrapper = tmp_path / "wrapper.py"
        self.wrapper.write_text(WRAPPER, encoding="utf-8")
        self.model = self.ai_root / "model.gguf"
        self.model.write_bytes(b"m")
        self.count = 0

    def run(self, *behaviors: str, sleep: float = 0.0, extra_paths=(), **runner_kwargs):
        self.count += 1
        fake = self.tmp / f"fake{self.count}.py"
        fake.write_text(f"import time; time.sleep({sleep}); print('ok')\n", encoding="utf-8")
        prompt = self.tmp / f"prompt{self.count}.txt"
        prompt.write_text(
            "\n".join(
                [
                    *(f"TEST_BEHAVIOR:{b}" for b in behaviors),
                    *(f"TEST_PATH:{p}" for p in extra_paths),
                ]
            ),
            encoding="utf-8",
        )
        command = [
            PY,
            str(self.wrapper),
            str(self.journal),
            str(fake),
            "-m",
            str(self.model),
            "-f",
            str(prompt),
        ]
        outcome = self.monitor.runner()(
            command, timeout_seconds=30.0, max_stdout_bytes=4096, **runner_kwargs
        )
        return outcome, self.monitor.records[-1]


@windows_only
def test_a_clean_request_has_a_complete_owned_record_and_no_violations(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    outcome, record = rig.run("read_model")
    assert outcome.returncode == 0 and outcome.stdout.strip() == b"ok"
    assert record.violations == []
    assert record.process["complete"] is True
    helpers = [
        e for e in record.process["events"] if e[0] == "new" and e[1] != record.process["root_pid"]
    ]
    assert record.process["total_processes"] == 2 and len(helpers) == 1
    assert helpers[0][2].lower().endswith("\\system32\\conhost.exe"), (
        "the OS console host, by image"
    )
    assert record.process["active_after_teardown"] == 0
    assert record.files == [f"read:{rig.model}"]
    assert record.executable == PY and record.executable_sha256 is not None
    assert rig.monitor.teardown_verified() is True


@windows_only
def test_a_connection_attempt_is_attributed_to_the_owned_child_and_is_a_violation(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path)
    _, record = rig.run("egress", "foreign_noise")
    assert len(record.connections) == 1 and record.connections[0].startswith("127.0.0.1:")
    assert record.foreign_events == 1, "an event from a pid outside the owned tree is not ours"
    assert record.violations == ["egress_attempt_observed"]
    assert rig.monitor.connection_attempts() == 1
    assert rig.monitor.violations() == ["egress_attempt_observed"]


@windows_only
def test_file_access_outside_the_session_directories_is_a_violation(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    outside = tmp_path / "elsewhere.bin"
    _, record = rig.run("write_outside", extra_paths=[outside])
    assert record.violations == ["file_access_outside_policy"]
    allowed = rig.ai_root / "work" / "scratch.bin"
    _, clean = rig.run("write_outside", extra_paths=[allowed])
    assert clean.violations == []


@windows_only
def test_an_unexpected_descendant_stops_the_request_and_the_whole_tree_is_cleaned_up(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path)
    outcome, record = rig.run("descendant", sleep=60.0)
    assert outcome.cancelled, "the runner's own cancel path stopped the tree"
    assert "unexpected_descendants" in record.violations
    assert record.process["complete"] is True and record.process["active_after_teardown"] == 0
    kinds = {event[0] for event in record.process["events"]}
    assert "terminated" in kinds or "exit" in kinds
    assert rig.monitor.teardown_verified() is True


@windows_only
def test_a_descendant_that_outlives_its_parent_is_terminated_and_attributed(tmp_path: Path) -> None:
    # One descendant is allowed here so the request is not stopped mid-run: this test is about what happens to a
    # member still alive when its parent has exited.
    rig = Rig(tmp_path, policy=OwnershipPolicy(max_descendants=1))
    pidfile = tmp_path / "survivor.pid"
    _, record = rig.run("survivor", extra_paths=[pidfile])
    survivor = int(pidfile.read_text())
    assert record.violations == []
    assert record.process["runner_terminated_tree"] is True
    assert ["terminated", survivor, None] in record.process["events"]
    assert record.process["active_after_teardown"] == 0
    assert "teardown_not_verified" not in record.violations


@windows_only
def test_a_failing_provider_is_a_violation_never_a_clean_record(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    next(p for p in rig.monitor.providers if p.channel == "files").fail_end = True
    _, record = rig.run()
    assert "provider_failed:files" in record.violations


@windows_only
def test_a_provider_that_cannot_open_its_window_means_the_child_is_never_launched(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path)
    next(p for p in rig.monitor.providers if p.channel == "connections").fail_begin = True
    outcome, record = rig.run("write_outside", extra_paths=[tmp_path / "must-not-exist.bin"])
    assert outcome.returncode is None and outcome.launch_error
    assert record.violations == ["provider_failed:connections"]
    assert not (tmp_path / "must-not-exist.bin").exists()
    assert rig.monitor.teardown_verified() is False


@windows_only
def test_a_file_access_of_unknown_mode_is_treated_as_a_write(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    target = str(rig.model)  # inside the read roots, outside the write roots
    record = rig.monitor._policy_violations(
        ownership.RequestOwnership(1, "x", None, {}, [], [f"unknown:{target}"], 0, [])
    )
    assert record == ["file_access_outside_policy"]
    read = rig.monitor._policy_violations(
        ownership.RequestOwnership(1, "x", None, {}, [], [f"read:{target}"], 0, [])
    )
    assert read == []


@windows_only
def test_a_stale_canary_pass_does_not_survive_a_canary_that_raises(tmp_path: Path) -> None:
    monitor, _ = journal_monitor(tmp_path)
    assert monitor.run_canary()["passed"] is True

    def explode(_command, **_kwargs):
        raise RuntimeError("runner failed")

    with pytest.raises(RuntimeError):
        monitor.run_canary(explode)
    assert monitor.canary_report is None
    assert "monitor canary has not been run" in monitor.readiness()


@windows_only
def test_the_callers_own_cancellation_still_works_through_the_monitor(tmp_path: Path) -> None:
    import threading

    stop = threading.Event()
    stop.set()
    rig = Rig(tmp_path)
    outcome, record = rig.run(sleep=60.0, cancel=stop)
    assert outcome.cancelled and record.process["active_after_teardown"] == 0


@windows_only
def test_every_request_leaves_a_durable_ownership_record(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.monitor.evidence_dir = tmp_path / "evidence"
    rig.run("read_model")
    files = sorted((tmp_path / "evidence").glob("ownership-request-*.json"))
    assert [f.name for f in files] == ["ownership-request-00001.json"]
    import json

    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["process"]["complete"] is True and data["violations"] == []


def test_unverifiable_teardown_is_a_violation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.utils import managed_process
    from src.utils.process_observation import OwnedTreeEvidence

    def runner(_command, **kwargs):
        observe = kwargs["observe"]  # the capability exists but the record never completes
        assert callable(observe)
        return managed_process.ProcessOutcome(
            returncode=0,
            stdout=b"ok",
            ownership=OwnedTreeEvidence(
                root_pid=1,
                events=(),
                total_processes=1,
                survivors_at_end=0,
                runner_terminated_survivors=False,
                active_after_teardown=-1,
                io_read_bytes=0,
                io_write_bytes=0,
                io_other_bytes=0,
                complete=False,
                problems=("teardown_verification_failed",),
            ),
        )

    monitor, _ = journal_monitor(tmp_path)
    monitor.runner(runner)([sys.executable], timeout_seconds=1.0, max_stdout_bytes=1)
    record = monitor.records[-1]
    assert {"ownership_record_incomplete", "teardown_not_verified"} <= set(record.violations)
    assert monitor.teardown_verified() is False


def test_a_runner_that_raises_leaves_an_unverified_record_and_still_raises(tmp_path: Path) -> None:
    def explode(_command, **_kwargs):
        raise RuntimeError("runner failed after launch")

    monitor, _ = journal_monitor(tmp_path)
    with pytest.raises(RuntimeError):
        monitor.runner(explode)([sys.executable], timeout_seconds=1.0, max_stdout_bytes=1)
    assert monitor.records[-1].violations == ["runner_raised"]
    assert monitor.teardown_verified() is False


def test_a_missing_ownership_record_is_a_violation(tmp_path: Path) -> None:
    from src.utils import managed_process

    monitor, _ = journal_monitor(tmp_path)
    monitor.runner(lambda _c, **_k: managed_process.ProcessOutcome(returncode=0))(
        [sys.executable], timeout_seconds=1.0, max_stdout_bytes=1
    )
    assert "ownership_record_missing" in monitor.records[-1].violations
    assert monitor.teardown_verified() is False


def test_module_exposes_no_process_discovery_or_kill_api() -> None:
    source = Path(ownership.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "process_iter",
        "cmdline",
        ".kill(",
        ".terminate(",
        "taskkill",
        "TerminateProcess",
    ):
        assert forbidden not in source, forbidden
