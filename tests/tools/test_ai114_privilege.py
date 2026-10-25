"""PR-AI-QUAL-114 privilege boundary: the harness and every child are standard-user; tracing failures stop execution.

Process evidence is real (the bounded runner and its job object); the ETW layer is the fake backend of the AI-113B tests,
and elevation/token answers are injected where a test must simulate the privileged case. Nothing here needs, or can
create, a privileged process.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.ai_assist.host import HostMemory  # noqa: E402
from src.ai_assist.manifests import load_model_registry  # noqa: E402
from tests.ai_assist.ai113_support import CANARY, JournalProvider  # noqa: E402
from tests.tools import test_ai113b_etw as etw_tests  # noqa: E402
from tools.qualification.ai111 import d12a, physical, tokens  # noqa: E402
from tools.qualification.ai111 import plan as plan_module  # noqa: E402
from tools.qualification.ai111.etw import EtwError, etw_host_monitor  # noqa: E402
from tools.qualification.ai111.ownership import OwnedSessionMonitor, OwnershipPolicy  # noqa: E402

windows_only = pytest.mark.skipif(os.name != "nt", reason="job objects and tokens are Windows-only")
PYTHON = getattr(sys, "_base_executable", sys.executable)

#: The AI-113 journal canary, extended to report its own token exactly as the real canary does.
STANDARD_USER_CANARY = CANARY.replace(
    "print(done.stdout.strip())",
    "import ctypes\nprint(done.stdout.strip(), int(bool(ctypes.windll.shell32.IsUserAnAdmin())))",
)


def _monitor(tmp_path: Path, **kwargs) -> OwnedSessionMonitor:
    journal = tmp_path / "journal.jsonl"
    return OwnedSessionMonitor(
        OwnershipPolicy(),
        [JournalProvider("connections", journal), JournalProvider("files", journal)],
        kind="hermetic",
        canary_script=STANDARD_USER_CANARY.format(journal=str(journal), silent=False),
        **kwargs,
    )


# -- the probes ---------------------------------------------------------------------------------------------------------


@windows_only
def test_the_token_probes_read_this_process_and_a_live_child(tmp_path: Path) -> None:
    mine = tokens.current_process_elevated()
    assert mine in (True, False)
    assert tokens.process_token_elevated(os.getpid()) is mine
    assert (
        tokens.process_token_elevated(0x7FFFFFF0) is None
    )  # no such process: unknown, never "not elevated"
    assert isinstance(tokens.in_performance_log_users(), bool)


# -- the harness itself must be unelevated ------------------------------------------------------------------------------


@pytest.mark.parametrize("answer", [True, None])
def test_an_elevated_or_unreadable_harness_token_is_refused(tmp_path: Path, answer) -> None:
    monitor = _monitor(tmp_path, forbid_elevation=True, self_elevated=lambda: answer)
    assert any(p.startswith("privilege:") for p in monitor.provider_problems())


@windows_only
def test_a_session_with_an_elevated_harness_refuses_before_creating_anything(
    tmp_path: Path,
) -> None:
    monitor = _monitor(tmp_path, forbid_elevation=True, self_elevated=lambda: True)
    result = physical.run_session(
        plan={},
        paths=None,
        stage="A",
        arms=[],
        cases=[],
        authorization_text="x",
        monitor=monitor,
    )
    assert result["verdict"] == "NOT TESTED" and any("privilege" in r for r in result["refused"])


def test_an_unelevated_harness_passes_the_privilege_check(tmp_path: Path) -> None:
    monitor = _monitor(tmp_path, forbid_elevation=True, self_elevated=lambda: False)
    assert not [p for p in monitor.provider_problems() if p.startswith("privilege:")]


# -- the canary child and the live child --------------------------------------------------------------------------------


@windows_only
def test_the_canary_proves_a_non_elevated_child_or_the_monitor_is_not_ready(tmp_path: Path) -> None:
    if tokens.current_process_elevated() is not False:
        pytest.skip("needs an unelevated test process")
    monitor = _monitor(tmp_path, forbid_elevation=True, self_elevated=lambda: False)
    report = monitor.run_canary()
    assert report["saw"]["standard_user"] is True and report["passed"], report
    assert monitor.records[-1].child_token_elevated is False
    assert monitor.readiness() == []


@windows_only
def test_a_canary_that_cannot_show_its_token_fails_readiness(tmp_path: Path) -> None:
    journal = tmp_path / "journal.jsonl"
    monitor = OwnedSessionMonitor(
        OwnershipPolicy(),
        [JournalProvider("connections", journal), JournalProvider("files", journal)],
        kind="hermetic",
        canary_script=CANARY.format(journal=str(journal), silent=False),  # prints only a pid
        forbid_elevation=True,
        self_elevated=lambda: False,
    )
    monitor.run_canary()
    assert any("privilege" in p for p in monitor.readiness())


@windows_only
def test_a_child_whose_token_reads_as_elevated_is_stopped_through_the_runner(
    tmp_path: Path,
) -> None:
    monitor = _monitor(
        tmp_path,
        forbid_elevation=True,
        self_elevated=lambda: False,
        token_probe=lambda pid: True,
    )
    outcome = monitor.runner()(
        [PYTHON, "-I", "-c", "import time; time.sleep(60)"],
        timeout_seconds=60.0,
        max_stdout_bytes=1024,
    )
    record = monitor.records[-1]
    assert outcome.cancelled and "child_token_elevated" in record.violations
    assert record.child_token_elevated is True
    assert record.process["complete"] is True and record.process["active_after_teardown"] == 0


@windows_only
def test_a_real_unelevated_child_token_is_read_and_recorded(tmp_path: Path) -> None:
    if tokens.current_process_elevated() is not False:
        pytest.skip("needs an unelevated test process")
    monitor = _monitor(tmp_path, forbid_elevation=True, self_elevated=lambda: False)
    monitor.runner()(
        [PYTHON, "-I", "-c", "import time; time.sleep(1.0)"],
        timeout_seconds=30.0,
        max_stdout_bytes=1024,
    )
    record = monitor.records[-1]
    assert record.child_token_elevated is False and "child_token_elevated" not in record.violations


# -- tracing failures prevent execution; nothing is leaked --------------------------------------------------------------


@windows_only
def test_a_trace_that_cannot_start_launches_nothing_and_leaves_no_session(tmp_path: Path) -> None:
    backend = etw_tests.FakeBackend()
    backend.fail_start_at = 1  # the OS refuses the second session (for example, access denied)
    monitor = etw_host_monitor(
        OwnershipPolicy(),
        tmp_path / "ev",
        capture=etw_tests.capture(tmp_path, backend),
        self_elevated=lambda: False,
    )
    marker = tmp_path / "launched.txt"
    outcome = monitor.runner()(
        [PYTHON, "-I", "-c", f"open({str(marker)!r}, 'w').write('x')"],
        timeout_seconds=30.0,
        max_stdout_bytes=1024,
    )
    assert outcome.launch_error and not marker.exists()
    assert set(backend.started) <= set(backend.stopped), "a half-started window is rolled back"
    # the OS tool's own message is kept next to the verdict, so a denied provider can be told from a missing right
    assert monitor.records[-1].provider_errors, monitor.records[-1].as_json()
    assert all(m.startswith("EtwError:") for m in monitor.records[-1].provider_errors.values())
    assert monitor.records[-1].violations == [
        "provider_failed:connections",
        "provider_failed:files",
    ] or any(v.startswith("provider_failed") for v in monitor.records[-1].violations)


def test_the_account_without_trace_rights_makes_every_channel_unavailable(tmp_path: Path) -> None:
    backend = etw_tests.FakeBackend()
    monitor = etw_host_monitor(
        OwnershipPolicy(),
        tmp_path / "ev",
        capture=etw_tests.capture(tmp_path, backend, elevated=False),
        self_elevated=lambda: False,
    )
    problems = monitor.provider_problems()
    assert any(p.startswith("connections: no lifetime_complete provider") for p in problems)
    with pytest.raises(EtwError, match="trace-control rights"):
        monitor.providers[0].begin()
    assert backend.started == []


def test_close_reports_and_records_leaked_sessions(tmp_path: Path) -> None:
    backend = etw_tests.FakeBackend()
    monitor = etw_host_monitor(
        OwnershipPolicy(),
        tmp_path / "ev",
        capture=etw_tests.capture(tmp_path, backend),
        self_elevated=lambda: False,
    )
    where = tmp_path / "evidence"
    where.mkdir()
    assert monitor.close_and_report(where) == []
    assert (
        json.loads((where / "trace-teardown.json").read_text())["trace_sessions_left_running"] == []
    )
    backend.live = ["StableNewAi113-aaaaaaaaaaaa"]
    other = tmp_path / "evidence2"
    other.mkdir()
    assert monitor.close_and_report(other) == ["StableNewAi113-aaaaaaaaaaaa"]
    assert json.loads((other / "trace-teardown.json").read_text())["trace_sessions_left_running"]


def test_an_unreadable_session_list_is_a_finding_not_a_pass(tmp_path: Path) -> None:
    backend = etw_tests.FakeBackend()

    def broken() -> list[str]:
        raise EtwError("logman query failed")

    backend.live_sessions = broken  # type: ignore[method-assign]
    monitor = etw_host_monitor(
        OwnershipPolicy(),
        tmp_path / "ev",
        capture=etw_tests.capture(tmp_path, backend),
        self_elevated=lambda: False,
    )
    assert monitor.leaked_traces() == ["session list unreadable"]


# -- D12a attestation and the resource gate ----------------------------------------------------------------------------


def test_d12a_refuses_without_an_operator_attestation(tmp_path: Path) -> None:
    from tests.tools import test_ai114_d12a as d12a_tests

    archive, intent = d12a_tests._archive(tmp_path)
    with pytest.raises(d12a.D12aRefused, match="attestation"):
        d12a.run_d12a(
            archive=archive,
            passive_manifest=d12a_tests._manifest(tmp_path, archive),
            evidence_root=tmp_path / "run",
            monitor=d12a_tests.FakeMonitor([]),  # type: ignore[arg-type]
            authorization_text="owner",
            attestation="  ",
            intent=intent,
            passive_manifest_sha256=None,
        )


REGISTRY = load_model_registry(plan_module.REGISTRY_PATH)
Q5 = "qwen3.5-9b-q5_k_m-unsloth"


def _mem(available: float, commit: float):
    return lambda: HostMemory(available_gib=available, commit_headroom_gib=commit)


def test_the_9b_q5_requirement_is_model_size_plus_four_gib_in_both_measures() -> None:
    report, problems = physical.resource_check(_mem(11.0, 11.0), REGISTRY, [Q5])
    assert round(report["per_arm_requirement_gib"][Q5], 2) == 10.13 and problems == []
    assert report["warnings"], "11 GiB is under the preferred 12 GiB"
    _, low_ram = physical.resource_check(_mem(10.0, 30.0), REGISTRY, [Q5])
    _, low_commit = physical.resource_check(_mem(30.0, 10.0), REGISTRY, [Q5])
    assert len(low_ram) == 1 and "available RAM" in low_ram[0]
    assert len(low_commit) == 1 and "commit headroom" in low_commit[0]


def test_twelve_gib_available_meets_the_preferred_level_without_a_warning() -> None:
    report, problems = physical.resource_check(_mem(12.5, 20.0), REGISTRY, [Q5])
    assert problems == [] and report["warnings"] == []


def test_unreadable_memory_refuses_and_baseline_only_sessions_need_nothing() -> None:
    _, problems = physical.resource_check(lambda: None, REGISTRY, [Q5])
    assert problems == ["memory could not be read"]
    _, none_needed = physical.resource_check(_mem(1.0, 1.0), REGISTRY, ["B0_identity"])
    assert none_needed == []
