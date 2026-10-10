"""S1-S8 safety regressions; synthetic inputs only, never physical qualification."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from tools.qualification.img154 import evidence as ev
from tools.qualification.img154 import manifest as mf
from tools.qualification.img154 import monitor as mon
from tools.qualification.img154 import preflight as pf
from tools.qualification.img154 import probes
from tools.qualification.img154 import report as rep
from tools.qualification.img154.core import GIB, Observation


def sample(seq, **values):
    return rep._sample(seq, float(seq), **values)


@pytest.mark.parametrize(
    "field,low",
    [
        ("ram_available_bytes", 0.5 * GIB),
        ("commit_headroom_bytes", 3 * GIB),
        ("vram_used_bytes", 11.5 * GIB),
        ("gpu_temperature_c", 85),
        ("shared_vram_bytes", 2 * GIB),
    ],
)
def test_s1_alternating_missing_and_violation_cannot_warn_forever(field, low):
    clock = rep.FakeClock(0)
    monitor = mon.SafetyMonitor(mon.MonitorConfig(shared_baseline_bytes=0.5 * GIB), clock=clock)
    monitor.begin_observation()
    decisions = []
    for seq in range(1, 42):
        clock.now = seq
        decisions.append(monitor.ingest(sample(seq, **{field: low if seq % 2 else None})))
    assert monitor.latched_action == mon.CANNOT_VERIFY_SAFE_STATE
    assert any("UNKNOWN_DATA" in code for d in decisions for code in d.codes)
    assert not any(d.action == mon.REQUEST_OWNER_STOP for d in decisions)
    assert monitor.observed_violations[field] > 0


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf"), True, "1", -1])
@pytest.mark.parametrize("target", ["observed", "clock", "limit"])
def test_s2_nonfinite_or_invalid_freshness_never_passes(bad, target):
    observed, now, limit = 1.0, 2.0, 30.0
    if target == "observed":
        observed = bad
    elif target == "clock":
        now = bad
    else:
        limit = bad
    obs = Observation("ram", 20 * GIB, "bytes", "fake", observed)
    assert obs.number(units="bytes", now_mono_s=now, max_age_s=limit)[0] is None


def test_s7_guidance_and_frozen_settings_survive_redaction():
    frozen = {
        "guidance_scale": 0.0,
        "cfg_scale": 1.0,
        "sampler_name": "Euler",
        "scheduler": "Beta",
        "shift": 9.0,
    }
    assert ev.redact_value(frozen) == frozen


@pytest.mark.parametrize(
    "path",
    [
        r"C:\Users\First Last\private folder\secret.txt",
        "/home/First Last/private folder/secret.txt",
    ],
)
def test_s7_personal_paths_with_spaces_do_not_leak(path):
    text = str(ev.redact_value({"path": path, "detail": "reading " + path}))
    assert "First" not in text and "Last" not in text and "secret.txt" not in text


def inputs():
    values = {
        "commit_headroom_bytes": 40 * GIB,
        "commit_limit_bytes": 50 * GIB,
        "ram_available_bytes": 25 * GIB,
        "pagefile_volume_free_bytes": 90 * GIB,
        "vram_used_bytes": 10 * GIB,
        "vram_total_bytes": 12 * GIB,
        "vram_quiescent_baseline_bytes": 11 * GIB,
        "evidence_volume_free_bytes": 10 * GIB,
    }
    return pf.PreflightInputs(
        manifest_digest=mf.build_manifest().digest(),
        sections={key: [] for key in pf.SECTION_REASON},
        observations={k: Observation(k, v, "bytes", "operator", 100.0) for k, v in values.items()},
        telemetry_coverage=dict.fromkeys(pf.ESSENTIAL_TELEMETRY, "available"),
        fault_baseline_coverage=dict.fromkeys(ev.FAULT_SOURCES, "complete"),
        evidence_dir_valid=True,
        ledger_state="none",
    )


@pytest.mark.parametrize(
    "source,timestamp",
    [
        ("operator", 100.0),
        ("", 100.0),
        ("wrong_device", 100.0),
        ("wrong_boot", 100.0),
        ("operator", 0.0),
    ],
)
def test_s3_unverified_baseline_never_satisfies_threshold(source, timestamp):
    data = inputs()
    readings = dict(data.observations)
    readings["vram_quiescent_baseline_bytes"] = Observation(
        "vram_quiescent_baseline_bytes", 11 * GIB, "bytes", source, timestamp
    )
    result = pf.evaluate_preflight(replace(data, observations=readings), now_mono_s=100.0)
    assert result.decision == pf.INCONCLUSIVE
    assert "vram_over_baseline_mib" not in result.measurements


@pytest.mark.parametrize("close", [False, True])
def test_s8_policy_revision_cannot_reopen_same_attempt(close):
    plan = mf.build_manifest()
    revised = replace(plan, policy_revision="revised", stop_policy_revision="revised")
    ledger = ev.DispatchLedger(ev.MemoryLedgerStore())
    ledger.record_attempt(plan)
    if close:
        ledger.record_outcome(plan, "completed")
    assert ledger.state(revised) in {"ambiguous", "completed"}
    with pytest.raises(ev.LedgerRefusal):
        ledger.record_attempt(revised)
    distinct = replace(revised, case_id="owner-authorized-distinct-case")
    ledger.record_attempt(distinct)
    assert ledger.state(distinct) == "ambiguous"


def test_s4_slow_hash_precedes_resource_observations(monkeypatch, tmp_path, capsys):
    clock = rep.FakeClock(100.0)
    monkeypatch.setattr(
        rep, "Clocks", lambda: probes.Clocks(mono=clock, utc=lambda: "2026-01-01T00:00:00+00:00")
    )
    order = []

    def measure(*args, **kwargs):
        order.append("hash")
        clock.advance(90.0)
        return {}

    def collect(*args, **kwargs):
        order.append("probe")
        return probes.ProbeResult(
            observations={
                "ram_available_bytes": Observation(
                    "ram_available_bytes", 25 * GIB, "bytes", "fake", clock()
                )
            }
        )

    monkeypatch.setattr(rep, "_measure_assets", measure)
    monkeypatch.setattr(rep, "collect_live_observations", collect)
    monkeypatch.setattr(
        rep, "collect_code_revision", lambda: {"state": "unverifiable"}, raising=False
    )
    out = tmp_path / "packet.json"
    assert (
        rep.main(["read-only-probe", "--hash", "--models-root", str(tmp_path), "--out", str(out)])
        != 0
    )
    assert order == ["hash", "probe"]
    capsys.readouterr()


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0, True])
def test_s2_packet_age_limit_is_valid(bad):
    result = replace(
        pf.evaluate_preflight(inputs(), now_mono_s=100.0, now_utc="2026-01-01T00:00:00+00:00"),
        decision=pf.PREPARED,
    )
    packet = rep.build_packet(preflight=result)
    assert not rep.packet_is_current(
        packet, now_utc=datetime(2026, 1, 1, tzinfo=UTC), max_age_s=bad
    )[0]


def test_s5_packet_preserves_fault_coverage_continuity_and_revision():
    snapshot = ev.FaultSnapshot(
        "2026-01-01T00:00:00+00:00",
        "boot",
        {"system_log": ev.FaultSourceSnapshot("system_log", ev.BOUNDED, frozenset({"42"}))},
    )
    probe = probes.ProbeResult(
        fault_snapshot=snapshot, environment={"code_revision": {"sha": "a" * 40, "state": "dirty"}}
    )
    packet = rep.build_packet(probe=probe)
    assert packet["fault_evidence"]["sources"]["system_log"]["coverage"] == ev.BOUNDED
    assert packet["fault_evidence"]["sources"]["system_log"]["continuity"] == "not_compared"
    assert packet["code_revision"]["state"] == "dirty"


def test_s1_confirmed_recovery_resets_pending_unknown_but_not_latch():
    clock = rep.FakeClock(0)
    monitor = mon.SafetyMonitor(clock=clock)
    monitor.begin_observation()
    for seq, ram in enumerate([0.5 * GIB, None, 12 * GIB, 0.5 * GIB], 1):
        clock.now = seq
        monitor.ingest(sample(seq, ram_available_bytes=ram))
    assert monitor.latched_action == mon.WARN
    assert monitor.observed_violations["ram_available_bytes"] == 2
    for seq in range(5, 18):
        clock.now = seq
        monitor.ingest(sample(seq, ram_available_bytes=0.5 * GIB))
    assert monitor.latched_action == mon.REQUEST_OWNER_STOP
    clock.now = 18
    monitor.ingest(sample(18))
    assert monitor.latched_action == mon.REQUEST_OWNER_STOP


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0])
def test_s2_monitor_invalid_clock_is_harness_fault(bad):
    monitor = mon.SafetyMonitor(clock=lambda: bad)
    monitor.begin_observation()
    assert monitor.ingest(sample(1)).action == mon.HARNESS_FAULT
    assert monitor.tick().action == mon.HARNESS_FAULT


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0])
def test_s2_nonfinite_settle_never_means_complete_coverage(bad):
    snap = ev.FaultSnapshot(
        "2026-01-01T00:00:00+00:00",
        "boot",
        {name: ev.FaultSourceSnapshot(name, ev.COMPLETE) for name in ev.FAULT_SOURCES},
    )
    assert ev.classify_faults(snap, snap, seconds_after_run=bad).status == ev.UNKNOWN_COVERAGE_GAP


@pytest.mark.parametrize(
    "record",
    [
        {},
        {"kind": "attempt", "manifest_digest": "a" * 64},
        {"kind": "outcome", "attempt_identity": "a" * 64, "outcome": "done"},
    ],
)
def test_s8_corrupt_or_legacy_history_fails_closed(record):
    store = ev.MemoryLedgerStore()
    store.records.append(record)
    ledger = ev.DispatchLedger(store)
    assert ledger.state(mf.build_manifest()) == "unknown"
    with pytest.raises(ev.LedgerRefusal):
        ledger.record_attempt(mf.build_manifest())


def test_s8_changed_request_same_case_also_cannot_replay():
    plan = mf.build_manifest()
    ledger = ev.DispatchLedger(ev.MemoryLedgerStore())
    ledger.record_attempt(plan)
    changed = replace(plan, intent=replace(plan.intent, seed=123))
    with pytest.raises(ev.LedgerRefusal):
        ledger.record_attempt(changed)


def test_s1_lost_samples_and_gaps_latch_without_a_physical_violation_claim():
    clock = rep.FakeClock(0)
    monitor = mon.SafetyMonitor(clock=clock)
    monitor.begin_observation()
    for seq in range(1, 4):
        clock.now = seq
        decision = monitor.ingest(sample(seq, ram_available_bytes=None))
    assert "TELEMETRY_LOST" in decision.codes
    clock.now = 10
    decision = monitor.ingest(sample(10))
    assert "TELEMETRY_GAP" in decision.codes
    assert monitor.latched_action == mon.CANNOT_VERIFY_SAFE_STATE
    assert not monitor.observed_violations


@pytest.mark.parametrize("state", ["REFUSED_RESOURCE_THRESHOLD", "INCONCLUSIVE"])
def test_disposition_is_separate_from_implementation_pass(state):
    result = replace(pf.evaluate_preflight(inputs(), now_mono_s=100.0), decision=state)
    packet = rep.build_packet(preflight=result)
    assert packet["phase_a_classification"] == rep.PHASE_A_PASS
    assert packet["disposition"] in {"REFUSED", "HOLD"}
    assert packet["physical_qualification_acceptable"] is False


@pytest.mark.parametrize("utc", ["nan", "infinity", "2026-01-01", "", float("nan")])
def test_s2_invalid_wall_timestamp_cannot_be_fresh(utc):
    obs = Observation("ram", 20 * GIB, "bytes", "fake", 1.0, utc)
    assert obs.number(units="bytes", now_mono_s=2.0, max_age_s=30.0)[0] is None


def test_s3_cli_assertion_is_not_restamped(monkeypatch, tmp_path):
    args = rep._parse(["read-only-probe", "--vram-baseline-mib", "12000"])
    data = rep._read_only_inputs(
        args,
        mf.build_manifest(),
        probes.ProbeResult(),
        probes.Clocks(mono=lambda: 100.0, utc=lambda: "2026-01-01T00:00:00+00:00"),
    )
    baseline = data.observations["vram_quiescent_baseline_bytes"]
    assert baseline.status != "ok" and baseline.observed_mono_s is None


def test_s5_code_revision_clean_dirty_and_unverifiable_with_fake_git(monkeypatch):
    root = probes.Path(probes.__file__).resolve().parents[3]
    monkeypatch.setattr(probes.shutil, "which", lambda name: "C:/trusted/git.exe")
    state = {"status": ""}

    def run(argv, **kwargs):
        from types import SimpleNamespace

        return SimpleNamespace(
            returncode=0,
            stdout=str(root) + "\n" + "a" * 40 if "rev-parse" in argv else state["status"],
        )

    monkeypatch.setattr(probes.subprocess, "run", run)
    assert probes.collect_code_revision()["state"] == "clean"
    state["status"] = " M tools/qualification/img154/core.py"
    dirty = probes.collect_code_revision()
    assert dirty["state"] == "dirty" and dirty["source_sha256"]
    monkeypatch.setattr(probes.shutil, "which", lambda name: None)
    unknown = probes.collect_code_revision()
    assert unknown["state"] == "unverifiable" and unknown["sha"] is None


@pytest.mark.parametrize(
    "before_time,after_time",
    [
        ("nan", "2026-01-01T00:02:00+00:00"),
        ("2026-01-01T00:02:00+00:00", "2026-01-01T00:00:00+00:00"),
        ("2026-01-01T00:00:00", "2026-01-01T00:02:00+00:00"),
    ],
)
def test_s2_invalid_or_reversed_fault_timestamps_never_prove_complete(before_time, after_time):
    sources = {name: ev.FaultSourceSnapshot(name, ev.COMPLETE) for name in ev.FAULT_SOURCES}
    before = ev.FaultSnapshot(before_time, "boot", sources)
    after = ev.FaultSnapshot(after_time, "boot", sources)
    assert (
        ev.classify_faults(before, after, seconds_after_run=120.0).status == ev.UNKNOWN_COVERAGE_GAP
    )


def test_s1_skipped_sequences_do_not_prove_contiguous_physical_violation():
    clock = rep.FakeClock(0)
    monitor = mon.SafetyMonitor(clock=clock)
    monitor.begin_observation()
    decisions = []
    for seq in range(1, 42, 2):
        clock.now = seq
        decisions.append(monitor.ingest(sample(seq, commit_headroom_bytes=3 * GIB)))
    assert not any("COMMIT_HEADROOM_BELOW_FLOOR" in d.codes for d in decisions)
    assert monitor.latched_action == mon.CANNOT_VERIFY_SAFE_STATE
    assert monitor.observed_violations["commit_headroom_bytes"] == 21


@pytest.mark.parametrize("added", [False, True])
def test_s5_disappeared_complete_coverage_records_cannot_prove_continuity(added):
    sources = {
        name: ev.FaultSourceSnapshot(name, ev.COMPLETE, frozenset({"42"}))
        for name in ev.FAULT_SOURCES
    }
    before = ev.FaultSnapshot("2026-01-01T00:00:00+00:00", "boot", sources)
    after = replace(
        before,
        sources={
            **sources,
            "system_log": ev.FaultSourceSnapshot(
                "system_log", ev.COMPLETE, frozenset({"43"}) if added else frozenset()
            ),
        },
    )
    result = ev.classify_faults(before, after, seconds_after_run=120.0)
    assert result.status == (ev.NEW_EVENTS if added else ev.UNKNOWN_COVERAGE_GAP)
    assert "system_log:records_disappeared" in result.gaps


@pytest.mark.parametrize("coverage", [{}, {"system_log": "complete"}])
def test_s5_missing_required_baseline_sources_are_explicit(coverage):
    result = pf.evaluate_preflight(
        replace(inputs(), fault_baseline_coverage=coverage), now_mono_s=100.0
    )
    assert "FAULT_BASELINE_INCOMPLETE" in result.reason_codes
    assert any("not_collected" in item.detail for item in result.findings)


def test_s8_deleted_prior_case_records_leave_a_fail_closed_sequence_gap(tmp_path):
    path = tmp_path / "ledger.jsonl"
    store = ev.FileLedgerStore(path)
    ledger = ev.DispatchLedger(store)
    plan = mf.build_manifest()
    ledger.record_attempt(plan)
    ledger.record_outcome(plan, "done")
    ledger.record_attempt(replace(plan, case_id="owner-case-two"))
    lines = path.read_bytes().splitlines(keepends=True)
    path.write_bytes(lines[-1])  # simulate corrupted/deleted earlier durable history
    assert ledger.state(plan) == "unknown"
    with pytest.raises(ev.LedgerRefusal):
        ledger.record_attempt(plan)
