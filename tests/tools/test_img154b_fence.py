"""PR-IMG-MODELS-154B T09-T16: the atomic cross-process claim, ordered stages, interruption and no-replay behavior.

Temporary directories only. Concurrency is exercised with REAL separate interpreter processes, not threads.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import time
from dataclasses import replace
from pathlib import Path

import pytest

from tools.qualification.img154 import evidence as ev
from tools.qualification.img154 import manifest as mf
from tools.qualification.img154b import fence as fn

REPO_ROOT = Path(__file__).resolve().parents[2]


def make_fence(tmp_path: Path, **kwargs) -> fn.CaseFence:
    manifest = kwargs.pop("manifest", mf.build_manifest())
    return fn.CaseFence(manifest, tmp_path / "records", sync=lambda fd: None, **kwargs)


def drive_to(fence: fn.CaseFence, stage: str) -> None:
    fence.claim(provenance={"test": True})
    for name in ev.LEDGER_STAGES[1:]:
        if name == stage:
            return
        fence.record_stage(name)


# --- T09: claim ----------------------------------------------------------------------------------------------------------


def test_t09_a_case_can_be_claimed_exactly_once_and_the_claim_is_durable(tmp_path):
    syncs = []
    fence = fn.CaseFence(mf.build_manifest(), tmp_path / "records", sync=syncs.append)
    assert fence.state().status == "none"
    assert fence.state().preflight_state() == "none"
    fence.claim(provenance={"authorization": "a" * 64})
    assert len(syncs) == 1  # the claim is fsynced before anything may start
    state = fence.state()
    assert state.status == "open" and state.stages == ("claimed",) and state.ambiguous
    assert state.preflight_state() == "ambiguous"
    with pytest.raises(fn.FenceRefusal) as raised:
        fence.claim()
    assert raised.value.code == fn.STAGE_REFUSED
    again = make_fence(tmp_path)
    with pytest.raises(fn.FenceRefusal) as raised:
        again.claim()
    assert raised.value.code == fn.CASE_ALREADY_CLAIMED


def test_t09_identity_is_independent_of_policy_wording_revision_and_workspace(tmp_path):
    base = mf.build_manifest()
    variants = [
        replace(base, policy_revision="another-policy-revision"),
        replace(
            base,
            stop_policy_revision="x",
            evidence_contract_revision="y",
            operator_preflight_revision="z",
        ),
        replace(base, intent=replace(base.intent, prompt="a different wording")),
        replace(base, forge_pin="0" * 40),
    ]
    first = fn.CaseFence(
        base, tmp_path / "records", workspace_root=tmp_path / "workspace-1", sync=lambda fd: None
    )
    first.claim()
    for variant in variants:
        assert variant.attempt_identity() == base.attempt_identity()
        other = fn.CaseFence(
            variant,
            tmp_path / "records",
            workspace_root=tmp_path / "other-workspace",
            sync=lambda fd: None,
        )
        assert other.path == first.path
        assert other.state().consumed
        with pytest.raises(fn.FenceRefusal) as raised:
            other.claim()
        assert raised.value.code == fn.CASE_ALREADY_CLAIMED
    # only a distinct owner-authorized case has a distinct record
    distinct = fn.CaseFence(
        replace(base, case_id="owner-authorized-case-2"), tmp_path / "records", sync=lambda fd: None
    )
    assert distinct.state().status == "none" and distinct.path != first.path


def test_t09_the_record_location_cannot_be_inside_the_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    with pytest.raises(fn.FenceRefusal) as raised:
        fn.CaseFence(
            mf.build_manifest(), workspace / "evidence" / "records", workspace_root=workspace
        )
    assert raised.value.code == fn.RECORD_LOCATION_REFUSED
    with pytest.raises(fn.FenceRefusal):
        fn.CaseFence(mf.build_manifest(), workspace, workspace_root=workspace)
    fn.CaseFence(
        mf.build_manifest(), tmp_path / "records", workspace_root=workspace
    )  # a sibling is fine


def test_t09_the_stable_location_never_depends_on_a_workspace_or_import_time_state():
    root = fn.stable_record_root({"LOCALAPPDATA": "C:/Users/someone/AppData/Local"})
    assert root.parts[-3:] == fn.RECORD_ROOT_PARTS
    assert fn.stable_record_root({"LOCALAPPDATA": "D:/other"}) != root


# --- T10: real concurrency -----------------------------------------------------------------------------------------------

WORKER = textwrap.dedent(
    """
    import sys, time
    from pathlib import Path
    sys.path.insert(0, {repo!r})
    from tools.qualification.img154 import manifest as mf
    from tools.qualification.img154b import fence as fn

    records, workspace, go = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    fence = fn.CaseFence(mf.build_manifest(), records, workspace_root=workspace, sync=lambda fd: None)
    deadline = time.time() + 30
    while not go.exists() and time.time() < deadline:
        time.sleep(0.001)
    try:
        fence.claim(provenance={{"workspace": workspace.name}})
        print("CLAIMED")
    except fn.FenceRefusal as exc:
        print("REFUSED:" + exc.code)
    """
).format(repo=str(REPO_ROOT))


def test_t10_concurrent_processes_with_different_workspaces_claim_the_case_exactly_once(tmp_path):
    records, go = tmp_path / "records", tmp_path / "go"
    workers = [
        subprocess.Popen(  # noqa: S603
            [
                sys.executable,
                "-c",
                WORKER,
                str(records),
                str(tmp_path / f"workspace-{index}"),
                str(go),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for index in range(6)
    ]
    time.sleep(1.0)  # let every interpreter reach the barrier
    go.write_text("go", encoding="utf-8")
    results = []
    for worker in workers:
        out, err = worker.communicate(timeout=60)
        assert worker.returncode == 0, err
        results.append(out.strip())
    assert results.count("CLAIMED") == 1, results
    assert results.count("REFUSED:CASE_ALREADY_CLAIMED") == 5, results
    path = fn.case_record_path(records, mf.build_manifest())
    recorded, torn, corrupt = ev.read_jsonl(path)
    assert (torn, corrupt, len(recorded)) == (False, 0, 1)
    assert recorded[0]["kind"] == "attempt"
    assert sorted(p.name for p in records.iterdir()) == [path.name]


# --- T11: ordered stages -------------------------------------------------------------------------------------------------


def test_t11_stages_are_recorded_in_exactly_the_documented_order(tmp_path):
    assert ev.LEDGER_STAGES == (
        "claimed",
        "managed_start_attempted",
        "startup_observed",
        "selection_attempted",
        "selection_confirmed",
        "generation_dispatched",
        "terminal_evidence",
    )
    fence = make_fence(tmp_path)
    fence.claim()
    for stage in ev.LEDGER_STAGES[1:-1]:
        fence.record_stage(stage, detail=stage)
    assert fence.state().stages == ev.LEDGER_STAGES[:-1]
    fence.finish("AMBIGUOUS_DISPATCH", note="x")
    state = fence.state()
    assert state.status == "terminal" and state.stages == ev.LEDGER_STAGES
    assert state.preflight_state() == "dispatched"


def test_t11_skipping_repeating_or_reordering_a_stage_is_refused_and_writes_nothing(tmp_path):
    fence = make_fence(tmp_path)
    fence.claim()
    for bad in (
        "startup_observed",
        "selection_attempted",
        "generation_dispatched",
        "claimed",
        "nonsense",
    ):
        with pytest.raises(fn.FenceRefusal) as raised:
            fence.record_stage(bad)
        assert raised.value.code == fn.STAGE_REFUSED
    fence.record_stage("managed_start_attempted")
    with pytest.raises(fn.FenceRefusal):
        fence.record_stage("managed_start_attempted")  # a repeat
    assert fence.state().stages == ("claimed", "managed_start_attempted")


def test_t11_a_second_dispatch_stage_is_impossible(tmp_path):
    fence = make_fence(tmp_path)
    drive_to(fence, "generation_dispatched")
    fence.record_stage("generation_dispatched")
    with pytest.raises(fn.FenceRefusal):
        fence.record_stage("generation_dispatched")
    with pytest.raises(fn.FenceRefusal):
        fence.record_stage("selection_confirmed")


def test_t11_terminal_evidence_may_end_the_case_at_any_stage_and_nothing_follows_it(tmp_path):
    for index, _stage in enumerate(ev.LEDGER_STAGES[:-1]):
        fence = fn.CaseFence(
            mf.build_manifest(), tmp_path / f"records-{index}", sync=lambda fd: None
        )
        fence.claim()
        for name in ev.LEDGER_STAGES[1 : index + 1]:
            fence.record_stage(name)
        fence.finish("PREFLIGHT_REFUSED" if index == 0 else "LOADER_FAILED")
        assert fence.state().status == "terminal"
        with pytest.raises(fn.FenceRefusal):
            fence.record_stage("managed_start_attempted")
        with pytest.raises(fn.FenceRefusal):
            fence.finish("again")
        with pytest.raises(fn.FenceRefusal):
            fn.CaseFence(mf.build_manifest(), tmp_path / f"records-{index}").claim()


def test_t11_a_stage_needs_the_claim_and_the_claimants_token(tmp_path):
    fence = make_fence(tmp_path)
    with pytest.raises(fn.FenceRefusal) as raised:
        fence.record_stage("managed_start_attempted")
    assert raised.value.code == fn.NOT_CLAIMED
    fence.claim()
    restarted = make_fence(tmp_path)  # a restart is not the claimant and can never become it
    with pytest.raises(fn.FenceRefusal) as raised:
        restarted.record_stage("managed_start_attempted")
    assert raised.value.code == fn.NOT_CLAIMED
    with pytest.raises(fn.FenceRefusal):
        restarted.claim()


# --- T12: interruption and no replay -------------------------------------------------------------------------------------


@pytest.mark.parametrize("stage", ev.LEDGER_STAGES[:-1])
def test_t12_an_interruption_after_any_stage_is_ambiguous_and_never_retried(tmp_path, stage):
    fence = make_fence(tmp_path)
    fence.claim()
    for name in ev.LEDGER_STAGES[1:]:
        if ev.LEDGER_STAGES.index(name) > ev.LEDGER_STAGES.index(stage):
            break
        fence.record_stage(name)
    del fence  # the process "dies" here: no finish, no cleanup
    restarted = make_fence(tmp_path)
    state = restarted.state()
    assert state.status == "open" and state.ambiguous
    assert state.stages[-1] == stage
    assert state.preflight_state() == "ambiguous"
    with pytest.raises(fn.FenceRefusal) as raised:
        restarted.claim()
    assert raised.value.code == fn.CASE_ALREADY_CLAIMED
    assert restarted.state().stages[-1] == stage  # the refusal changed nothing


def test_t12_the_dispatch_record_precedes_the_send_so_a_crash_after_it_is_ambiguous_not_clean(
    tmp_path,
):
    fence = make_fence(tmp_path)
    drive_to(fence, "generation_dispatched")
    fence.record_stage("generation_dispatched", endpoint="/sdapi/v1/txt2img")
    # crash "between the record and the response": the ledger says dispatched, with no terminal record
    state = make_fence(tmp_path).state()
    assert state.stages[-1] == "generation_dispatched" and state.status == "open"


def test_t12_a_failed_durable_write_refuses_the_stage_so_the_action_must_not_happen(tmp_path):
    calls = {"n": 0}

    def flaky_sync(fd):
        calls["n"] += 1
        if calls["n"] == 3:  # claim (1), managed_start_attempted (2), startup_observed (3) fails
            raise OSError("disk full")

    fence = fn.CaseFence(mf.build_manifest(), tmp_path / "records", sync=flaky_sync)
    fence.claim()
    fence.record_stage("managed_start_attempted")
    with pytest.raises(fn.FenceRefusal):
        fence.record_stage("startup_observed")
    # nothing is replayed: the stage is not silently retried and the case stays consumed
    with pytest.raises(fn.FenceRefusal):
        make_fence(tmp_path).claim()


def test_t12_an_interrupted_claim_write_leaves_a_consumed_unknown_record(tmp_path):
    def fail(fd):
        raise OSError("power lost")

    fence = fn.CaseFence(mf.build_manifest(), tmp_path / "records", sync=fail)
    with pytest.raises(fn.FenceRefusal):
        fence.claim()
    path = fn.case_record_path(tmp_path / "records", mf.build_manifest())
    path.write_bytes(b"")  # the worst case: created but empty
    state = make_fence(tmp_path).state()
    assert state.consumed and state.status == "unknown"
    with pytest.raises(fn.FenceRefusal):
        make_fence(tmp_path).claim()


def test_t12_a_torn_tail_a_corrupt_line_and_a_missing_prefix_are_unknown_and_refuse_everything(
    tmp_path,
):
    fence = make_fence(tmp_path)
    drive_to(fence, "generation_dispatched")
    path = fence.path
    intact = path.read_bytes()
    for damaged in (
        intact + b'{"kind":"stage","stage":"generation_disp',  # torn tail
        intact + b"not json\n",
        b"\n".join(intact.splitlines()[1:]) + b"\n",  # the claim record is gone
    ):
        path.write_bytes(damaged)
        state = make_fence(tmp_path).state()
        assert state.status == "unknown" and state.consumed and state.ambiguous
        assert state.preflight_state() == "unknown"
        with pytest.raises(fn.FenceRefusal):
            make_fence(tmp_path).claim()
        with pytest.raises(fn.FenceRefusal):
            fence.record_stage("generation_dispatched")


def test_t12_a_deleted_record_cannot_be_reclaimed_by_the_claimant_it_loses_ownership(tmp_path):
    fence = make_fence(tmp_path)
    fence.claim()
    fence.path.unlink()
    with pytest.raises(fn.FenceRefusal) as raised:
        fence.record_stage("managed_start_attempted")
    assert raised.value.code == fn.OWNERSHIP_LOST
    with pytest.raises(fn.FenceRefusal) as raised:
        fence.record_stage("terminal_evidence")
    assert raised.value.code == fn.OWNERSHIP_LOST


def test_t12_a_record_replaced_by_another_claimant_is_ownership_lost(tmp_path):
    ours = make_fence(tmp_path)
    ours.claim()
    stolen = ours.path.read_text(encoding="utf-8").splitlines()
    record = json.loads(stolen[0])
    record["claimant"]["token"] = "f" * 32
    ours.path.write_text(
        json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    with pytest.raises(fn.FenceRefusal) as raised:
        ours.record_stage("managed_start_attempted")
    assert raised.value.code == fn.OWNERSHIP_LOST


def test_t12_an_unusable_record_location_is_inaccessible_not_clear(tmp_path):
    blocker = tmp_path / "records"
    blocker.write_text("a file where the record directory should be", encoding="utf-8")
    fence = fn.CaseFence(mf.build_manifest(), blocker, sync=lambda fd: None)
    state = fence.state()
    assert state.status == "unknown" and state.code == "inaccessible"
    with pytest.raises(fn.FenceRefusal) as raised:
        fence.claim()
    assert raised.value.code == fn.RECORD_INACCESSIBLE


def test_t12_a_misfiled_record_is_unknown(tmp_path):
    other = replace(mf.build_manifest(), case_id="somebody-elses-case")
    elsewhere = fn.CaseFence(other, tmp_path / "records", sync=lambda fd: None)
    elsewhere.claim()
    ours = mf.build_manifest()
    fn.case_record_path(tmp_path / "records", ours).write_bytes(elsewhere.path.read_bytes())
    state = fn.CaseFence(ours, tmp_path / "records").state()
    assert (state.status, state.code) == ("unknown", "misfiled")


# --- T13: workspace ledger and the 154A ledger semantics -----------------------------------------------------------------


def test_t13_the_workspace_ledger_is_read_as_an_additional_authority(tmp_path):
    path = tmp_path / "evidence" / "dispatch-ledger.jsonl"
    assert fn.workspace_ledger_state(path, mf.build_manifest()) == "none"
    ev.DispatchLedger(ev.FileLedgerStore(path)).record_attempt(mf.build_manifest())
    assert fn.workspace_ledger_state(path, mf.build_manifest()) == "ambiguous"
    path.write_bytes(b"")  # an empty ledger file is never clean
    assert fn.workspace_ledger_state(path, mf.build_manifest()) == "unknown"


def test_t13_the_154a_ledger_stays_valid_for_a_ledger_with_stage_records(tmp_path):
    fence = make_fence(tmp_path)
    drive_to(fence, "generation_dispatched")
    plain = ev.DispatchLedger(ev.FileLedgerStore(fence.path))
    assert plain.state(mf.build_manifest()) == "ambiguous"
    assert plain.stage_history(mf.build_manifest()) == ev.LEDGER_STAGES[:5]
    fence.finish("INSTRUMENTATION_GAP")
    assert plain.state(mf.build_manifest()) == "completed"


def test_t10_the_atomic_claim_itself_refuses_even_when_the_precheck_was_stale(tmp_path):
    """The exclusive create is the gate: a claimant that saw 'none' before another process claimed is still refused."""

    winner = make_fence(tmp_path)
    loser = make_fence(tmp_path)
    loser._ledger.state = lambda manifest: "none"  # its pre-check ran before the winner's claim
    winner.claim(provenance={"who": "winner"})
    before = winner.path.read_bytes()
    with pytest.raises(fn.FenceRefusal) as raised:
        loser.claim(provenance={"who": "loser"})
    assert raised.value.code == fn.CASE_ALREADY_CLAIMED
    assert (
        winner.path.read_bytes() == before
    )  # the winner's record was neither replaced nor truncated
    winner.record_stage("managed_start_attempted")  # the winner still owns the case
    with pytest.raises(fn.FenceRefusal):
        loser.record_stage("managed_start_attempted")
