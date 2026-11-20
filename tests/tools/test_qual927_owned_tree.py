"""QUAL-927: bounded teardown verification and owned worker-tree memory, against scripted fake process tables.

No real process, runtime, model, GPU or network is touched: every observation comes from ``FakeTable`` and every wait
advances a fake clock.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

from tools.qualification import owned_tree as ot


@dataclass(frozen=True)
class Mem:
    working_set_gb: float
    private_usage_gb: float


class FakeTable:
    """A scripted process table. ``exit_after[pid] = n`` removes ``pid`` once ``n`` waits have elapsed.

    It also carries the signalling methods a careless verifier might reach for; calling any of them fails the test.
    """

    def __init__(
        self,
        processes: dict[int, float],
        *,
        children: dict[int, list[int]] | None = None,
        listeners: dict[int, list[int]] | None = None,
        memory: dict[int, Mem | None] | None = None,
        exit_after: dict[int, int] | None = None,
    ) -> None:
        self.processes = dict(processes)  # pid -> creation time
        self.kids = {k: list(v) for k, v in (children or {}).items()}
        self.listeners = {k: list(v) for k, v in (listeners or {}).items()}
        self.mem = dict(memory or {})
        self.exit_after = dict(exit_after or {})
        self.waits = 0
        self.now = 0.0
        self.calls: list[tuple[str, int]] = []

    # clock and wait -------------------------------------------------------------------------------------------------
    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds
        self.waits += 1
        for pid, n in list(self.exit_after.items()):
            if self.waits >= n:
                self.processes.pop(pid, None)
                for port, pids in self.listeners.items():
                    self.listeners[port] = [p for p in pids if p != pid]

    # observation ----------------------------------------------------------------------------------------------------
    def exists(self, pid: int) -> bool:
        self.calls.append(("exists", pid))
        return pid in self.processes

    def create_time(self, pid: int) -> float | None:
        self.calls.append(("create_time", pid))
        return self.processes.get(pid)

    def children(self, pid: int) -> list[int]:
        self.calls.append(("children", pid))
        out: list[int] = []
        stack = list(self.kids.get(pid, ()))
        while stack:
            child = stack.pop(0)
            if child in self.processes:
                out.append(child)
                stack.extend(self.kids.get(child, ()))
        return out

    def listening_pids(self, port: int) -> list[int]:
        self.calls.append(("listening", port))
        return list(self.listeners.get(port, ()))

    def memory(self, pid: int) -> Mem | None:
        self.calls.append(("memory", pid))
        return self.mem.get(pid) if pid in self.processes else None

    # authority this module must never use ---------------------------------------------------------------------------
    def kill(self, pid: int) -> None:  # pragma: no cover - reaching it is the failure
        raise AssertionError(f"kill({pid}) called")

    def terminate(self, pid: int) -> None:  # pragma: no cover - reaching it is the failure
        raise AssertionError(f"terminate({pid}) called")


def verify(table: FakeTable, owned, ports=(), *, deadline=10.0, poll=0.5):
    return ot.verify_teardown(
        owned,
        ports,
        deadline_seconds=deadline,
        poll_seconds=poll,
        table=table,
        clock=table.clock,
        sleep=table.sleep,
    )


# --- bounded teardown wait -------------------------------------------------------------------------------------------


def test_pids_that_exit_after_n_polls_are_verified_clean_with_every_observation_timestamped() -> (
    None
):
    table = FakeTable(
        {100: 1.0, 101: 2.0},
        listeners={7886: [101]},
        exit_after={100: 2, 101: 3},
    )
    owned = [ot.OwnedProcess(100, 1.0), ot.OwnedProcess(101, 2.0)]
    result = verify(table, owned, (7886,))

    assert result.verified is True and result.outcome == ot.TEARDOWN_VERIFIED
    assert result.survivors == () and result.held_ports == {}
    assert len(result.observations) == 4  # polls 0..3: the tree needed three waits to go away
    assert [o["alive_pids"] for o in result.observations] == [[100, 101], [100, 101], [101], []]
    assert result.observations[0]["listeners"] == {"7886": [101]}
    assert all("t" in o and "utc" in o for o in result.observations)
    assert (
        result.elapsed_seconds == pytest.approx(1.5)
        and result.elapsed_seconds <= result.deadline_seconds
    )
    record = result.as_dict()
    assert record["deadline_seconds"] == 10.0 and record["poll_seconds"] == 0.5
    assert record["verified"] is True and record["owned"] == [
        {"pid": 100, "create_time": 1.0},
        {"pid": 101, "create_time": 2.0},
    ]


def test_pids_that_outlive_the_deadline_stay_unverified_and_the_survivors_are_named() -> None:
    table = FakeTable({100: 1.0, 101: 2.0, 102: 3.0}, exit_after={100: 1})
    owned = [ot.OwnedProcess(p, c) for p, c in ((100, 1.0), (101, 2.0), (102, 3.0))]
    result = verify(table, owned, deadline=2.0)

    assert result.verified is False and result.outcome == ot.TEARDOWN_SURVIVORS
    assert result.survivors == (101, 102)
    assert result.elapsed_seconds == pytest.approx(
        2.0
    )  # the wait is bounded by the deadline, no further
    assert result.observations[-1]["alive_pids"] == [101, 102]
    assert len(result.observations) == 5  # 0.0, 0.5, 1.0, 1.5, 2.0
    assert "101" in result.detail and "102" in result.detail
    assert result.as_dict()["survivors"] == [101, 102]


def test_a_port_still_held_keeps_teardown_unverified_and_a_foreign_listener_is_only_named() -> None:
    table = FakeTable({100: 1.0, 555: 9.0}, listeners={8197: [555]}, exit_after={100: 1})
    result = verify(table, [ot.OwnedProcess(100, 1.0)], (8197,), deadline=1.0)

    assert result.verified is False and result.survivors == ()
    assert result.held_ports == {8197: (555,)} and result.foreign_listeners == (555,)
    # the unowned listener was observed through the port listing only: never queried, read or signalled
    assert not [c for c in table.calls if c[1] == 555]


def test_a_reused_pid_is_not_a_survivor_and_the_unrelated_process_is_never_touched() -> None:
    table = FakeTable({100: 99.0})  # pid 100 now belongs to an unrelated process created later
    result = verify(table, [ot.OwnedProcess(100, 1.0)])

    assert result.verified is True and result.survivors == ()
    assert result.observations[0]["reused_pids"] == [100]
    assert {name for name, _ in table.calls} <= {"exists", "create_time"}


def test_an_unknown_creation_time_is_a_survivor_conservatively() -> None:
    table = FakeTable({100: 5.0})
    result = verify(table, [ot.OwnedProcess(100, None)], deadline=0.5)
    assert result.verified is False and result.survivors == (100,)


def test_nothing_recorded_is_never_a_clean_teardown() -> None:
    table = FakeTable({})
    result = verify(table, [], (8197,))
    assert result.verified is False and result.outcome == ot.TEARDOWN_NOTHING_RECORDED
    assert len(result.observations) == 1 and table.waits == 0


def test_a_zero_deadline_is_a_single_observation_and_bad_bounds_are_refused() -> None:
    table = FakeTable({100: 1.0}, exit_after={100: 1})
    single = verify(table, [ot.OwnedProcess(100, 1.0)], deadline=0.0)
    assert single.verified is False and len(single.observations) == 1 and table.waits == 0
    for deadline, poll in ((-1.0, 0.5), (float("inf"), 0.5), (1.0, 0.0), (1.0, float("nan"))):
        with pytest.raises(ValueError):
            verify(FakeTable({}), [ot.OwnedProcess(1, 1.0)], deadline=deadline, poll=poll)


def test_duplicate_records_merge_and_a_known_creation_time_wins() -> None:
    merged = ot.merge_owned(
        [ot.OwnedProcess(7, None), ot.OwnedProcess(7, 3.0), ot.OwnedProcess(8, None)],
        [ot.OwnedProcess(8, None)],
    )
    assert merged == (ot.OwnedProcess(7, 3.0), ot.OwnedProcess(8, None))


# --- owned worker-tree memory ----------------------------------------------------------------------------------------


def comfy_like_table() -> FakeTable:
    # 10 is the 4.7 MB launcher stub; 11 is the real worker; 12 a helper child of the worker; 999 is not ours.
    return FakeTable(
        {10: 1.0, 11: 2.0, 12: 3.0, 999: 4.0},
        children={10: [11], 11: [12]},
        memory={
            10: Mem(0.0044, 0.0009),
            11: Mem(8.0, 12.0),
            12: Mem(0.5, 0.25),
            999: Mem(30.0, 30.0),
        },
    )


def test_tree_sampling_sums_the_children_and_records_the_peak_and_pid_set_per_sample() -> None:
    table = comfy_like_table()
    sampler = ot.OwnedTreeSampler(lambda: 10, table=table, memory=table.memory, clock=table.clock)

    first = sampler.sample(host={"available_gb": 16.0, "commit_used_gb": 22.5})
    assert first["pids"] == [10, 11, 12]
    assert first["tree_working_set_gib"] == pytest.approx(8.5044)
    assert first["tree_private_gib"] == pytest.approx(12.2509)
    assert first["processes"]["11"] == {"working_set_gib": 8.0, "private_gib": 12.0}
    assert (
        first["host"] == {"available_gb": 16.0, "commit_used_gb": 22.5}
        and first["complete"] is True
    )

    table.mem[11] = Mem(10.0, 15.0)
    table.now = 1.0
    second = sampler.sample()
    table.processes.pop(12)
    table.mem[11] = Mem(4.0, 6.0)
    third = sampler.sample()

    assert second["tree_private_gib"] == pytest.approx(15.2509)
    assert third["pids"] == [10, 11]
    assert sampler.peaks["tree_working_set_gib"] == pytest.approx(10.5044)
    assert sampler.peaks["tree_private_gib"] == pytest.approx(15.2509)
    assert sampler.peaks["max_process_count"] == 3 and sampler.samples == 3
    assert sampler.recorded == (
        ot.OwnedProcess(10, 1.0),
        ot.OwnedProcess(11, 2.0),
        ot.OwnedProcess(12, 3.0),
    )


def test_an_unowned_pid_is_never_sampled_recorded_or_signalled() -> None:
    table = comfy_like_table()
    sampler = ot.OwnedTreeSampler(lambda: 10, table=table, memory=table.memory, clock=table.clock)
    sampler.sample()
    assert 999 not in [p.pid for p in sampler.recorded]
    assert not [c for c in table.calls if c[1] == 999]
    result = verify(table, sampler.recorded, deadline=0.0)
    assert 999 not in result.survivors and not [c for c in table.calls if c[1] == 999]


def test_a_child_that_exits_between_listing_and_reading_leaves_a_lower_bound() -> None:
    table = comfy_like_table()
    table.mem[12] = None  # listed, but gone before its counters were read
    sampler = ot.OwnedTreeSampler(lambda: 10, table=table, memory=table.memory, clock=table.clock)
    sample = sampler.sample()
    assert sample["unreadable_pids"] == [12] and sample["complete"] is False
    assert sample["tree_private_gib"] == pytest.approx(12.0009)
    assert sample["readable_pids"] == [10, 11]


def test_the_harness_root_itself_can_be_excluded_and_a_missing_root_records_nothing() -> None:
    table = comfy_like_table()
    children_only = ot.OwnedTreeSampler(
        lambda: 10, include_root=False, table=table, memory=table.memory, clock=table.clock
    )
    assert children_only.sample()["pids"] == [11, 12]
    nobody = ot.OwnedTreeSampler(lambda: None, table=table, memory=table.memory, clock=table.clock)
    empty = nobody.sample()
    assert empty["pids"] == [] and empty["root_pid"] is None and nobody.recorded == ()


def test_a_reused_pid_in_a_later_sample_is_recorded_as_a_distinct_process() -> None:
    table = FakeTable(
        {10: 1.0, 11: 2.0}, children={10: [11]}, memory={10: Mem(1, 1), 11: Mem(1, 1)}
    )
    sampler = ot.OwnedTreeSampler(lambda: 10, table=table, memory=table.memory, clock=table.clock)
    sampler.sample()
    table.processes[11] = 7.0  # 11 exited and a new owned child received the same pid
    sampler.sample()
    assert (
        ot.OwnedProcess(11, 2.0) in sampler.recorded
        and ot.OwnedProcess(11, 7.0) in sampler.recorded
    )


@pytest.mark.parametrize("pid", [None, 0, -4, True])
def test_the_real_table_never_reads_a_missing_pid_as_this_process(pid) -> None:
    # psutil.Process(None) is the calling process; a missing manager PID must never turn the harness into "owned".
    table = ot.PsutilProcessTable()
    assert table.exists(pid) is False
    assert table.create_time(pid) is None and table.children(pid) == []


# --- no signal or kill authority -------------------------------------------------------------------------------------


def test_the_shared_module_has_no_signal_kill_or_adoption_authority() -> None:
    source = Path(ot.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not called & {
        "kill",
        "terminate",
        "send_signal",
        "killpg",
        "TerminateProcess",
        "TerminateJobObject",
        "suspend",
        "resume",
        "Popen",
        "run",
    }
    code = source.replace(ast.get_docstring(tree, clean=False) or "", "")
    for needle in ("taskkill", "Stop-Process", "os.kill", ".kill(", ".terminate(", "subprocess"):
        assert needle not in code


def test_importing_the_module_is_pure() -> None:
    import subprocess
    import sys

    probe = (
        "import sys; import tools.qualification.owned_tree; "
        "print('psutil' in sys.modules, 'tools.qualification.vid160c.win_memory' in sys.modules)"
    )
    out = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=True,
        cwd=Path(__file__).resolve().parents[2],
    ).stdout.split()
    assert out == ["False", "False"]
