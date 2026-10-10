"""PR-IMG-MODELS-154A T16-T21 and the mutation probes: ledger, durable evidence, fault classification, probes with fakes,
operator packet validity, the no-execution source guard and the highest-risk gate mutants.

Synthetic data and fakes only; no host counter, process, GPU or model is touched except the explicitly opt-in smoke.
"""

from __future__ import annotations

import ast
import importlib
import json
import os
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.qualification.img154 import evidence as ev
from tools.qualification.img154 import isolation as iso
from tools.qualification.img154 import manifest as mf
from tools.qualification.img154 import preflight as pf
from tools.qualification.img154 import probes
from tools.qualification.img154 import report as rep
from tools.qualification.img154.core import GIB, MIB, Observation

PACKAGE = Path(mf.__file__).parent
MODULES = ("core", "manifest", "isolation", "preflight", "monitor", "evidence", "probes", "report")


# --- T16 -----------------------------------------------------------------------------------------------------------------


def test_t16_ledger_allows_exactly_one_attempt_and_never_a_replay():
    ledger = ev.DispatchLedger(ev.MemoryLedgerStore())
    digest = mf.build_manifest().digest()
    request = mf.build_manifest().request_digest()
    assert ledger.state(digest) == "none"
    ledger.record_attempt(digest, request)
    assert ledger.state(digest) == "ambiguous"
    assert ledger.preflight_state(digest) == "ambiguous"
    with pytest.raises(ev.LedgerRefusal):
        ledger.record_attempt(digest, request)  # an ambiguous attempt is never replayed
    ledger.record_outcome(digest, "loader_failed")
    assert ledger.state(digest) == "completed"
    assert ledger.preflight_state(digest) == "dispatched"
    with pytest.raises(ev.LedgerRefusal):
        ledger.record_attempt(digest, request)  # not even after a recorded failure: no retry
    with pytest.raises(ev.LedgerRefusal):
        ledger.record_outcome(digest, "again")


def test_t16_unreadable_ledger_is_unknown_and_refuses_attempts():
    ledger = ev.DispatchLedger(ev.MemoryLedgerStore(fail_reads=True))
    digest = "d" * 64
    assert ledger.state(digest) == "unknown"
    assert ledger.preflight_state(digest) == "unknown"
    with pytest.raises(ev.LedgerRefusal):
        ledger.record_attempt(digest, "r" * 64)
    with pytest.raises(ev.LedgerRefusal):
        ledger.record_outcome(digest, "x")


def test_t16_a_full_ledger_refuses_and_never_rotates_away_history(tmp_path):
    path = tmp_path / "ledger.jsonl"
    writer = ev.DurableJsonlWriter(
        path, max_bytes=1024, rotate=False, sync=lambda fd: None, redact=False
    )
    written = 0
    with pytest.raises(OSError):
        for index in range(100):
            writer.append({"kind": "attempt", "manifest_digest": f"{index:064d}"})
            written += 1
    assert written > 0
    assert [p.name for p in tmp_path.iterdir()] == ["ledger.jsonl"]  # nothing rotated or deleted
    kept, torn, corrupt = ev.read_jsonl(path)
    assert (len(kept), torn, corrupt) == (written, False, 0)
    assert ev.FileLedgerStore(tmp_path / "other.jsonl")._writer.rotate is False


def test_t17_records_cannot_spoof_reserved_keys_and_sequence_survives_a_restart(tmp_path):
    path = tmp_path / "s.jsonl"
    first = ev.DurableJsonlWriter(path, sync=lambda fd: None)
    first.append({"kind": "a", "seq": 999, "schema": "forged"})
    first.append({"kind": "b"})
    second = ev.DurableJsonlWriter(path, sync=lambda fd: None)  # a restarted process
    second.append({"kind": "c"})
    records, _, _ = ev.read_jsonl(path)
    assert [r["seq"] for r in records] == [1, 2, 3]
    assert {r["schema"] for r in records} == {ev.EVIDENCE_SCHEMA}


def test_t16_ledgers_are_per_manifest_and_a_changed_manifest_is_a_new_case():
    ledger = ev.DispatchLedger(ev.MemoryLedgerStore())
    ledger.record_attempt("a" * 64, "r" * 64)
    assert ledger.state("b" * 64) == "none"


def test_t16_file_ledger_is_durable_and_a_torn_tail_is_ambiguous(tmp_path):
    path = tmp_path / "evidence" / "dispatch-ledger.jsonl"
    syncs = []
    store = ev.FileLedgerStore(path, sync=syncs.append)
    ledger = ev.DispatchLedger(store)
    ledger.record_attempt("a" * 64, "r" * 64)
    assert len(syncs) == 1  # fsync before the attempt may proceed
    assert ev.DispatchLedger(ev.FileLedgerStore(path)).state("a" * 64) == "ambiguous"
    with path.open("ab") as stream:
        stream.write(b'{"kind":"outcome","manifest_di')  # a crash mid-write
    assert ev.DispatchLedger(ev.FileLedgerStore(path)).state("a" * 64) == "unknown"


# --- T17 -----------------------------------------------------------------------------------------------------------------


def test_t17_every_record_is_flushed_and_synced_and_survives_without_close(tmp_path):
    synced = []
    writer = ev.DurableJsonlWriter(tmp_path / "samples.jsonl", sync=synced.append)
    for index in range(5):
        writer.append({"kind": "sample", "n": index})
    assert len(synced) == 5
    # read back through a separate handle with the writer still live: nothing relied on a finally/close
    records, torn, corrupt = ev.read_jsonl(tmp_path / "samples.jsonl")
    assert [r["n"] for r in records] == [0, 1, 2, 3, 4]
    assert [r["seq"] for r in records] == [1, 2, 3, 4, 5]
    assert (torn, corrupt) == (False, 0)


def test_t17_torn_final_line_and_corrupt_lines_are_reported_not_hidden(tmp_path):
    path = tmp_path / "e.jsonl"
    path.write_bytes(b'{"a":1}\nnot json\n{"b":2}\n{"c":')
    records, torn, corrupt = ev.read_jsonl(path)
    assert [list(r) for r in records] == [["a"], ["b"]]
    assert torn is True
    assert corrupt == 1


def test_t17_stream_is_bounded_by_rotation_and_reports_dropped_files(tmp_path):
    writer = ev.DurableJsonlWriter(
        tmp_path / "s.jsonl", max_bytes=1024, max_files=2, sync=lambda fd: None
    )
    for index in range(80):
        writer.append({"kind": "sample", "n": index, "pad": "x" * 60})
    files = sorted(p.name for p in tmp_path.iterdir())
    assert files == ["s.jsonl", "s.jsonl.1"]
    assert all(p.stat().st_size <= 1024 + 200 for p in tmp_path.iterdir())
    assert writer.dropped_files > 0
    kept = [r["seq"] for name in files for r in ev.read_jsonl(tmp_path / name)[0]]
    gaps = ev.sequence_gaps(kept)
    assert gaps == [] or gaps[0][0] > 0  # a dropped range is detectable from the sequence numbers
    assert (
        min(kept) > 1
    )  # older records were dropped, and the stream says so rather than pretending


def test_t17_oversize_record_is_replaced_by_a_digest_stub(tmp_path):
    writer = ev.DurableJsonlWriter(tmp_path / "s.jsonl", max_bytes=2048, sync=lambda fd: None)
    writer.append({"kind": "blob", "data": "z" * 5000})
    (record,) = ev.read_jsonl(tmp_path / "s.jsonl")[0]
    assert record["truncated"] is True
    assert re.fullmatch(r"[0-9a-f]{64}", record["sha256"])
    assert writer.truncated_records == 1


def test_t17_redaction_removes_prompts_profile_paths_and_hardware_identifiers(tmp_path):
    secret_prompt = "a very particular private prompt about my neighbour"
    record = {
        "prompt": secret_prompt,
        "negative_prompt": "ugly",
        "note": "loaded from C:\\Users\\alexdoe\\models\\x.safetensors and /home/alice/cache",
        "serial_number": "ABC123",
        "gpu": {"uuid": "GPU-1234", "name": "RTX 4070 Ti"},
        "text": "SerialNumber: 99887766 and mac aa:bb:cc:dd:ee:ff",
    }
    writer = ev.DurableJsonlWriter(tmp_path / "s.jsonl", sync=lambda fd: None)
    writer.append(record)
    raw = (tmp_path / "s.jsonl").read_text(encoding="utf-8")
    for leaked in (
        secret_prompt,
        "rob",
        "alice",
        "ABC123",
        "GPU-1234",
        "99887766",
        "aa:bb:cc:dd:ee:ff",
    ):
        assert leaked not in raw, leaked
    (stored,) = ev.read_jsonl(tmp_path / "s.jsonl")[0]
    assert stored["prompt"]["chars"] == len(secret_prompt)
    assert stored["gpu"]["name"] == "RTX 4070 Ti"  # the model name is not an identifier


# --- T18 -----------------------------------------------------------------------------------------------------------------


def snapshot(boot="boot-1", **coverage):
    sources = {}
    for name in ev.FAULT_SOURCES:
        state = coverage.get(name, ev.COMPLETE)
        ids = frozenset({"1", "2"}) if state != ev.INACCESSIBLE else frozenset()
        sources[name] = ev.FaultSourceSnapshot(name, state, ids)
    return ev.FaultSnapshot("2026-01-01T00:00:00+00:00", boot, sources)


def test_t18_complete_unchanged_evidence_is_the_only_no_new_events_outcome():
    result = ev.classify_faults(snapshot(), snapshot(), seconds_after_run=600)
    assert (
        result.status == ev.NO_NEW_EVENTS_COMPLETE_COVERAGE
    )  # the strongest statement; never "no faults"


@pytest.mark.parametrize(
    "after",
    [
        snapshot(wer_reports=ev.INACCESSIBLE),  # access denied
        snapshot(live_kernel=ev.NOT_COLLECTED),
        snapshot(whea=ev.PARTIAL),
    ],
)
def test_t18_missing_or_inaccessible_evidence_is_unknown_never_clean(after):
    result = ev.classify_faults(snapshot(), after, seconds_after_run=600)
    assert result.status == ev.UNKNOWN_COVERAGE_GAP
    assert result.gaps


def test_t18_delayed_evidence_and_missing_snapshots_are_unknown():
    assert (
        ev.classify_faults(snapshot(), snapshot(), seconds_after_run=5).status
        == ev.UNKNOWN_COVERAGE_GAP
    )
    assert (
        ev.classify_faults(snapshot(), snapshot(), seconds_after_run=None).status
        == ev.UNKNOWN_COVERAGE_GAP
    )
    assert (
        ev.classify_faults(None, snapshot(), seconds_after_run=600).status
        == ev.UNKNOWN_COVERAGE_GAP
    )
    assert (
        ev.classify_faults(snapshot(), None, seconds_after_run=600).status
        == ev.UNKNOWN_COVERAGE_GAP
    )
    assert ev.classify_faults(
        snapshot(boot=None), snapshot(boot=None), seconds_after_run=600
    ).status == (ev.UNKNOWN_COVERAGE_GAP)


def test_t18_new_records_and_a_changed_boot_are_findings():
    after = snapshot()
    sources = dict(after.sources)
    sources["whea"] = ev.FaultSourceSnapshot("whea", ev.COMPLETE, frozenset({"1", "2", "3"}))
    grown = ev.FaultSnapshot(after.taken_utc, after.boot_id, sources)
    found = ev.classify_faults(snapshot(), grown, seconds_after_run=600)
    assert found.status == ev.NEW_EVENTS
    assert found.new_records == {"whea": ("3",)}
    rebooted = ev.classify_faults(snapshot(), snapshot(boot="boot-2"), seconds_after_run=600)
    assert rebooted.status == ev.BOOT_CHANGED
    assert rebooted.boot_changed is True


def test_t18_bounded_lookback_requires_overlap_to_prove_continuity():
    def bounded(ids):
        return ev.FaultSnapshot(
            "t",
            "b",
            {n: ev.FaultSourceSnapshot(n, ev.BOUNDED, frozenset(ids)) for n in ev.FAULT_SOURCES},
        )

    overlapping = ev.classify_faults(
        bounded({"1", "2"}), bounded({"2", "3"}), seconds_after_run=600
    )
    assert overlapping.status == ev.NEW_EVENTS  # continuity proven, and 3 is new
    disjoint = ev.classify_faults(bounded({"1", "2"}), bounded({"8", "9"}), seconds_after_run=600)
    assert (
        disjoint.status == ev.NEW_EVENTS
    )  # records were seen; the finding is never downgraded to "unknown"
    assert any(
        "lookback_continuity_unproven" in gap for gap in disjoint.gaps
    )  # and the missing range is named
    unchanged = ev.classify_faults(bounded({"1", "2"}), bounded({"1", "2"}), seconds_after_run=600)
    assert unchanged.status == ev.NO_NEW_EVENTS_COMPLETE_COVERAGE


def test_t18_probe_failures_become_inaccessible_not_empty():
    def failing(argv):
        return None

    def denied(directory):
        raise PermissionError("denied")

    clocks = probes.Clocks(mono=lambda: 1.0, utc=lambda: "2026-01-01T00:00:00+00:00")
    shot = probes.collect_fault_snapshot(clocks, failing, wer_listing=denied)
    assert {s.coverage for s in shot.sources.values()} == {ev.INACCESSIBLE}
    assert shot.boot_id is None
    # an empty, successful query is complete coverage (distinguishable from a failure)
    ok = probes.collect_fault_snapshot(clocks, lambda argv: "[]", wer_listing=lambda d: [])
    assert {s.coverage for s in ok.sources.values()} == {ev.COMPLETE}


def test_t18_result_classification_never_declares_a_pass():
    refused = ev.classify_non_pass(ev.ResultFacts(preflight_prepared=False, dispatched=False))
    assert refused == (ev.PREFLIGHT_REFUSED, ())
    ambiguous = ev.classify_non_pass(
        ev.ResultFacts(
            True, True, outcome_recorded=False, fault_status=ev.NEW_EVENTS, telemetry_complete=True
        )
    )
    assert ambiguous[0] == ev.SYSTEM_OR_GPU_FAULT
    assert ev.AMBIGUOUS_DISPATCH in ambiguous[1]
    gap = ev.classify_non_pass(
        ev.ResultFacts(True, True, outcome_recorded=True, telemetry_complete=False)
    )
    assert gap[0] == ev.INSTRUMENTATION_GAP
    clean = ev.classify_non_pass(
        ev.ResultFacts(
            True,
            True,
            outcome_recorded=True,
            fault_status=ev.NO_NEW_EVENTS_COMPLETE_COVERAGE,
            telemetry_complete=True,
            output_valid=True,
        )
    )
    assert clean == (
        None,
        (),
    )  # no failure class applies; this package never declares TECHNICAL_PASS_CONSTRAINED
    assert ev.TECHNICAL_PASS_CONSTRAINED in ev.PHASE_A_UNREACHABLE_RESULT_CLASSES
    returned = {
        ev.classify_non_pass(f)[0]
        for f in (
            ev.ResultFacts(False, False),
            ev.ResultFacts(
                True,
                True,
                loader_failed=True,
                outcome_recorded=True,
                telemetry_complete=True,
                fault_status=ev.NO_NEW_EVENTS_COMPLETE_COVERAGE,
            ),
            ev.ResultFacts(
                True,
                True,
                stop_requested=True,
                outcome_recorded=True,
                telemetry_complete=True,
                fault_status=ev.NO_NEW_EVENTS_COMPLETE_COVERAGE,
            ),
            ev.ResultFacts(
                True,
                True,
                output_valid=False,
                outcome_recorded=True,
                telemetry_complete=True,
                fault_status=ev.NO_NEW_EVENTS_COMPLETE_COVERAGE,
            ),
        )
    }
    assert ev.TECHNICAL_PASS_CONSTRAINED not in returned


def test_evidence_bundle_gaps_are_named():
    gaps = ev.evidence_gaps({"manifest": {"x": 1}, "ledger": [{"k": 1}]})
    assert {g.detail.split("'")[1] for g in gaps} == set(ev.REQUIRED_EVIDENCE_ITEMS) - {
        "manifest",
        "ledger",
    }


# --- T19 -----------------------------------------------------------------------------------------------------------------

NOW = 5000.0


def prepared_result():
    inputs = pf.PreflightInputs(
        manifest_digest=mf.build_manifest().digest(),
        sections={key: [] for key in pf.SECTION_REASON},
        observations={
            name: Observation(name, value, "bytes", "fake", NOW, None)
            for name, value in {
                "commit_headroom_bytes": 40 * GIB,
                "commit_limit_bytes": 49 * GIB,
                "ram_available_bytes": 25 * GIB,
                "pagefile_volume_free_bytes": 90 * GIB,
                "vram_used_bytes": 2 * GIB,
                "vram_total_bytes": 12 * GIB,
                "vram_quiescent_baseline_bytes": 2 * GIB,
                "evidence_volume_free_bytes": 9 * GIB,
            }.items()
        },
        telemetry_coverage=dict.fromkeys(pf.ESSENTIAL_TELEMETRY, "available"),
        fault_baseline_coverage=dict.fromkeys(ev.FAULT_SOURCES, "complete"),
        evidence_dir_valid=True,
        ledger_state="none",
    )
    return pf.evaluate_preflight(inputs, now_mono_s=NOW, now_utc="2026-01-01T00:00:00+00:00")


def test_t19_packet_is_valid_only_for_the_prepared_assessment_of_this_manifest():
    result = prepared_result()
    assert result.decision == pf.PREPARED
    packet = rep.build_packet(
        preflight=result, mode="live_read_only", generated_utc="2026-01-01T00:00:00+00:00"
    )
    assert packet["disposition"] == "PREPARED_FOR_OWNER_REVIEW"
    assessed = datetime(2026, 1, 1, tzinfo=UTC)
    assert rep.packet_is_current(packet, now_utc=assessed + timedelta(seconds=30)) == (True, [])
    changed = mf.QualificationManifest(forge_pin="e" * 40)
    ok, problems = rep.packet_is_current(
        packet, manifest=changed, now_utc=assessed + timedelta(seconds=30)
    )
    assert not ok
    assert "manifest digest differs from the packet" in problems


def test_t19_changed_record_and_stale_assessment_invalidate_the_packet():
    result = prepared_result()
    packet = rep.build_packet(preflight=result, mode="live_read_only")
    tampered = json.loads(json.dumps(packet))
    tampered["manifest_digest"] = "0" * 64
    assessed = datetime(2026, 1, 1, tzinfo=UTC)
    assert rep.packet_is_current(tampered, now_utc=assessed)[0] is False
    # a stale, future-dated or untimed assessment invalidates an otherwise identical packet
    stale_ok, stale_problems = rep.packet_is_current(packet, now_utc=assessed + timedelta(hours=1))
    assert not stale_ok
    assert "preflight assessment is stale" in stale_problems
    assert not rep.packet_is_current(packet, now_utc=assessed - timedelta(seconds=60))[0]
    untimed = json.loads(json.dumps(packet))
    untimed["preflight"]["assessed_utc"] = None
    assert (
        "preflight assessment has no usable timestamp"
        in rep.packet_is_current(untimed, now_utc=assessed)[1]
    )
    assert not result.is_current(now_mono_s=NOW + 3600, max_age_s=60)
    refused = pf.evaluate_preflight(
        pf.PreflightInputs(manifest_digest="0" * 64, sections={"assets": []}), now_mono_s=NOW
    )
    refused_packet = rep.build_packet(preflight=refused, mode="live_read_only")
    assert refused_packet["disposition"] == "REFUSED"
    assert rep.packet_is_current(refused_packet, now_utc=assessed)[0] is False


def test_packet_is_redacted_bounded_and_never_a_safety_claim():
    packet = rep.build_packet(preflight=prepared_result(), mode="live_read_only")
    text = json.dumps(packet)
    assert mf.FrozenIntent().prompt not in text
    assert re.search(r"[A-Za-z]:\\\\Users\\\\", text) is None
    assert packet["meaning"].startswith("Preparation evidence only")
    assert packet["disposition"] in {"REFUSED", "HOLD", "PREPARED_FOR_OWNER_REVIEW"}
    assert len(rep.render_text(packet).splitlines()) < 80
    assert packet["execution_boundary"]["launch"] == "absent"


def test_dry_run_packet_reads_no_host_state_and_is_a_hold(monkeypatch, tmp_path, capsys):
    def boom(*a, **k):
        raise AssertionError("dry-run must not probe the host")

    monkeypatch.setattr(rep, "collect_live_observations", boom)
    out = tmp_path / "packet.json"
    assert rep.main(["dry-run", "--out", str(out)]) == 0
    packet = json.loads(out.read_text(encoding="utf-8"))
    assert packet["mode"] == "offline_dry_run"
    assert packet["disposition"] == "HOLD"
    assert packet["phase_a_classification"] == rep.PHASE_A_HOLD
    assert all(item["ok"] for item in packet["stop_rules"]["monitor_dry_run"])
    assert "PR-IMG-MODELS-154A" in capsys.readouterr().out


def test_report_output_never_overwrites_a_file_that_is_not_a_previous_packet(tmp_path, capsys):
    target = tmp_path / "notes.json"
    target.write_text('{"keep": "me"}', encoding="utf-8")
    assert rep.main(["dry-run", "--out", str(target)]) == 2
    assert json.loads(target.read_text(encoding="utf-8")) == {"keep": "me"}
    precious = tmp_path / "script.py"
    precious.write_text("print(1)", encoding="utf-8")
    assert rep.main(["dry-run", "--out", str(precious)]) == 2
    assert precious.read_text(encoding="utf-8") == "print(1)"
    again = tmp_path / "packet.json"
    assert rep.main(["dry-run", "--out", str(again)]) == 0
    assert rep.main(["dry-run", "--out", str(again)]) == 0  # a previous packet may be replaced
    capsys.readouterr()


def test_dry_run_monitor_scenarios_all_reproduce():
    results = rep.dry_run_scenarios()
    assert len(results) >= 10
    assert all(item["ok"] for item in results), [i for i in results if not i["ok"]]


# --- T20 -----------------------------------------------------------------------------------------------------------------


def fake_runner(argv):
    table = probes.ALLOW_LISTED_COMMANDS
    if tuple(argv) == table["pagefile"]:
        return '{"Name":"C:\\\\pagefile.sys","AllocatedBaseSize":18432,"CurrentUsage":100,"PeakUsage":500}'
    if tuple(argv) == table["gpu_shared_memory"]:
        return "123456\n"
    if tuple(argv) == table["hard_fault_pages"]:
        return "17.5\n"
    if tuple(argv) == table["boot_identity"]:
        return "2026-01-01T00:00:00.0000000Z\n"
    if tuple(argv)[-1].startswith("try {"):
        return '[{"RecordId":1,"Id":41},{"RecordId":2,"Id":141}]'
    raise AssertionError(argv)


def fake_clocks():
    ticks = iter(range(1000, 2000))
    return probes.Clocks(mono=lambda: float(next(ticks)), utc=lambda: "2026-01-01T00:00:00+00:00")


COMMIT = SimpleNamespace(
    commit_headroom_gb=20.0,
    commit_limit_gb=49.8,
    commit_total_gb=29.8,
    physical_available_gb=12.0,
    physical_total_gb=31.8,
)
GPU = {
    "devices": [
        {
            "memory_used_mb": 2300.0,
            "memory_total_mb": 12282.0,
            "temperature_c": 38.0,
            "utilization_gpu_pct": 3.0,
            "power_draw_w": 30.0,
        }
    ]
}


def collect(**overrides):
    kwargs = {
        "clocks": fake_clocks(),
        "runner": fake_runner,
        "memory_reader": lambda: COMMIT,
        "gpu_snapshot": lambda: GPU,
        "port_connect": lambda host, port: False,
        "process_memory_reader": lambda pid: object(),
        "process_iterator": lambda: [],
        "listeners": lambda: {},
        "wer_listing": lambda directory: ["Kernel_141_abc"],
        "disk_free": lambda root: 200 * GIB,
    }
    kwargs.update(overrides)
    return probes.collect_live_observations(**kwargs)


def test_t20_modules_import_and_probes_run_with_fake_providers_on_any_platform():
    for name in MODULES:
        importlib.import_module(f"tools.qualification.img154.{name}")
    result = collect()
    obs = result.observations
    assert obs["commit_headroom_bytes"].value == pytest.approx(20 * GIB)
    assert obs["ram_available_bytes"].value == pytest.approx(12 * GIB)
    assert obs["ram_total_bytes"].value == pytest.approx(31.8 * GIB)
    assert obs["pagefile_allocated_bytes"].value == 18432 * MIB
    assert obs["pagefile_volume_free_bytes"].value == 200 * GIB
    assert obs["vram_used_bytes"].value == pytest.approx(2300 * MIB)
    assert obs["gpu_temperature_c"].units == "celsius"
    assert obs["shared_vram_bytes"].value == 123456
    assert obs["hard_fault_pages_input_per_s"].value == 17.5
    assert set(result.telemetry_coverage.values()) == {"available"}
    assert result.port.state == "free"
    assert result.processes == []
    assert result.fault_snapshot.sources["live_kernel"].record_ids == frozenset({"Kernel_141_abc"})
    assert result.gaps == []


def test_t20_every_failed_provider_is_a_visible_non_ok_observation_never_zero():
    def broken_memory():
        raise OSError("GetPerformanceInfo failed")

    result = collect(
        runner=lambda argv: None,
        memory_reader=broken_memory,
        gpu_snapshot=lambda: None,
        disk_free=lambda root: (_ for _ in ()).throw(OSError("no disk")),
        port_connect=lambda host, port: (_ for _ in ()).throw(OSError("blocked")),
    )
    for name in (
        "commit_headroom_bytes",
        "ram_available_bytes",
        "vram_used_bytes",
        "shared_vram_bytes",
    ):
        item = result.observations[name]
        assert item.status != "ok"
        assert item.value is None
    assert result.port.state == "unverifiable"
    assert result.telemetry_coverage["commit_headroom_bytes"] == "unavailable"
    assert result.telemetry_coverage["gpu_device_present"] == "unavailable"
    assert any("commit_headroom_bytes" in gap for gap in result.gaps)
    # failed observations cannot satisfy the evaluator
    inputs = pf.PreflightInputs(
        manifest_digest=mf.build_manifest().digest(),
        sections={key: [] for key in pf.SECTION_REASON},
        observations=result.observations,
        telemetry_coverage=result.telemetry_coverage,
    )
    assert pf.evaluate_preflight(inputs, now_mono_s=1500.0).decision != pf.PREPARED


def test_t20_process_tree_capability_requires_a_working_reader_not_an_import():
    assert collect().telemetry_coverage["forge_process_tree"] == "available"

    def cannot_open(pid):
        return None

    def broken(pid):
        raise AttributeError("no windll")

    for reader in (cannot_open, broken):
        result = collect(process_memory_reader=reader)
        assert result.telemetry_coverage["forge_process_tree"] == "unavailable"
        assert any("forge_process_tree" in gap for gap in result.gaps)


def test_t20_only_an_active_refusal_proves_a_free_port():
    assert probes.probe_port(connect=lambda h, p: True).state == "occupied"
    assert probes.probe_port(connect=lambda h, p: False).state == "free"
    assert (
        probes.probe_port(connect=lambda h, p: None).state == "unverifiable"
    )  # a timeout proves nothing


def test_t20_powershell_is_resolved_to_an_absolute_path_never_from_cwd_or_path(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = list(argv)
        return SimpleNamespace(stdout="ok", returncode=0)

    monkeypatch.setattr(probes.subprocess, "run", fake_run)
    monkeypatch.setattr(probes.os.path, "isfile", lambda path: True)
    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    command = probes.ALLOW_LISTED_COMMANDS["boot_identity"]
    assert probes.run_allow_listed(command) == "ok"
    assert seen["argv"][0].lower().endswith(r"windowspowershell\v1.0\powershell.exe")
    assert seen["argv"][0].lower().startswith("c:")
    assert seen["argv"][1:] == list(command[1:])
    monkeypatch.setattr(probes.os.path, "isfile", lambda path: False)
    assert (
        probes.run_allow_listed(command) is None
    )  # missing interpreter: failed, never a PATH lookup


def test_t20_allow_list_refuses_anything_else():
    with pytest.raises(PermissionError):
        probes.run_allow_listed(("powershell", "-Command", "Stop-Process -Id 1"))
    with pytest.raises(PermissionError):
        probes.run_allow_listed(("taskkill", "/F", "/PID", "1"))


def test_t20_own_process_chain_is_never_reported_as_a_competing_runtime():
    me = SimpleNamespace(
        pid=os.getpid(), name="python.exe", cmdline=("python", "stable-diffusion-webui")
    )
    other = SimpleNamespace(
        pid=999_999, name="python.exe", cmdline=("python", "launch.py", "forge")
    )
    seen = probes.probe_processes(lambda: [me, other], lambda: {})
    assert [p.pid for p in seen] == [999_999]


@pytest.mark.skipif(
    sys.platform != "win32" or os.environ.get("STABLENEW_IMG154_LIVE_SMOKE") != "1",
    reason="opt-in Windows read-only counter smoke (set STABLENEW_IMG154_LIVE_SMOKE=1)",
)
def test_t20_windows_read_only_counter_smoke():
    items = {o.name: o for o in probes.probe_system_memory(probes.Clocks())}
    assert items["commit_headroom_bytes"].status == "ok"
    assert 0 < items["commit_headroom_bytes"].value <= items["commit_limit_bytes"].value


# --- T21 -----------------------------------------------------------------------------------------------------------------

FORBIDDEN_IMPORTS = {
    "requests",
    "urllib.request",
    "http.client",
    "httpx",
    "aiohttp",
    "websocket",
    "websockets",
    "ctypes.windll",
    "winreg",
    "multiprocessing",
    "asyncio",
    "signal",
    "pynvml",
    "torch",
    "cuda",
}
FORBIDDEN_PREFIXES = (
    "src.api",
    "src.pipeline",
    "src.controller",
    "src.gui",
    "src.queue",
    "tools.qualification.img115",
)
FORBIDDEN_CALLS = {
    "os.kill",
    "os.killpg",
    "os.system",
    "os.startfile",
    "os.popen",
    "os.link",
    "os.symlink",
    "os.chmod",
    "os.rename",
    "os.makedirs",
    "os.mkdir",
    "os.truncate",
    "subprocess.Popen",
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
    "shutil.copy",
    "shutil.copy2",
    "shutil.copyfile",
    "shutil.copytree",
    "shutil.move",
    "shutil.rmtree",
    "socket.create_connection",
}
FORBIDDEN_METHODS = {
    "terminate",
    "kill",
    "send_signal",
    "post",
    "put",
    "patch",
    "urlopen",
    "write_bytes",
    "hardlink_to",
    "symlink_to",
    "rmdir",
    "chmod",
    "touch",
}
FORBIDDEN_NAME_PREFIXES = (
    "launch",
    "terminate",
    "kill",
    "post_",
    "generate",
    "set_model",
    "select_model",
    "start_forge",
    "stop_",
    "cancel",
    "interrupt",
    "dispatch",
    "send_",
)
FORBIDDEN_STRINGS = (
    "taskkill",
    "Stop-Process",
    "Start-Process",
    "Restart-",
    "Set-ItemProperty",
    "Remove-Item",
    "New-Item",
    "Invoke-WebRequest",
    "Invoke-RestMethod",
    "Invoke-Expression",
    "bcdedit",
    "wmic",
    "netsh",
    "reg add",
    "powercfg",
    "pnputil",
    "nvidia-smi -",
    "sdapi",
    "/options",
    "WebUIProcessManager",
    "OwnedForge",
)


def _trees():
    for name in MODULES:
        path = PACKAGE / f"{name}.py"
        yield name, ast.parse(path.read_text(encoding="utf-8"))


def _dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def test_t21_no_network_process_control_or_filesystem_mutation_code_exists():
    problems = []
    for name, tree in _trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported = [node.module or ""]
            else:
                imported = []
            for module in imported:
                if module in FORBIDDEN_IMPORTS or module.startswith(FORBIDDEN_PREFIXES):
                    problems.append(f"{name}: import {module}")
            if isinstance(node, ast.Call):
                called = _dotted(node.func)
                if called in FORBIDDEN_CALLS:
                    problems.append(f"{name}: call {called}")
                if isinstance(node.func, ast.Attribute) and node.func.attr in FORBIDDEN_METHODS:
                    problems.append(f"{name}: method .{node.func.attr}()")
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith(
                FORBIDDEN_NAME_PREFIXES
            ):
                problems.append(f"{name}: function {node.name}")
    assert problems == []


def test_t21_subprocess_exists_only_in_the_probe_module_and_only_as_run():
    users = []
    for name, tree in _trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(a.name == "subprocess" for a in node.names):
                users.append(name)
            if isinstance(node, ast.Call) and _dotted(node.func).startswith("subprocess."):
                assert _dotted(node.func) == "subprocess.run", (name, _dotted(node.func))
    assert users == ["probes"]


def test_t21_no_forbidden_command_text_and_every_allow_listed_query_is_a_read():
    for name in MODULES:
        text = (PACKAGE / f"{name}.py").read_text(encoding="utf-8")
        for needle in FORBIDDEN_STRINGS:
            if needle in {"WebUIProcessManager", "OwnedForge"}:
                # these names may be MENTIONED in prose, never imported or called
                assert f"import {needle}" not in text and f"{needle}(" not in text, (name, needle)
                continue
            assert needle not in text, (name, needle)
    cmdlet = re.compile(
        r"\b(Set|Remove|Stop|Start|New|Clear|Invoke|Restart|Add|Enable|Disable|Out|Write)-[A-Za-z]+"
    )
    for key, argv in probes.ALLOW_LISTED_COMMANDS.items():
        assert argv[0] in {"powershell", "nvidia-smi"}, key
        assert cmdlet.search(" ".join(argv)) is None, key
        assert " ".join(argv).count("Get-") >= 1 or argv[0] == "nvidia-smi", key


def test_t21_cli_exposes_only_read_only_subcommands_and_no_execution_flags():
    import argparse

    parser = rep.build_parser()
    subparsers = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    assert set(subparsers.choices) == {"manifest", "dry-run", "read-only-probe"}
    flags = {
        opt for p in subparsers.choices.values() for a in p._actions for opt in a.option_strings
    }
    assert not {
        f
        for f in flags
        if re.search(r"launch|run|start|stop|kill|generate|post|select|set-model|force", f)
    }


def test_t21_manifest_command_prints_json_without_touching_the_host(capsys):
    assert rep.main(["manifest"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "PROPOSED_NOT_APPLIED"
    assert data["request_digest"] == mf.build_manifest().request_digest()


# --- mutation probes -----------------------------------------------------------------------------------------------------
#
# Each regression below must pass against the real code and FAIL against its mutant: that shows the regression actually
# guards the gate it names rather than passing vacuously.


def _good_inputs(**overrides):
    base = {
        "manifest_digest": mf.build_manifest().digest(),
        "sections": {key: [] for key in pf.SECTION_REASON},
        "observations": {
            name: Observation(name, value, "bytes", "fake", NOW, None)
            for name, value in {
                "commit_headroom_bytes": 40 * GIB,
                "commit_limit_bytes": 49 * GIB,
                "ram_available_bytes": 25 * GIB,
                "pagefile_volume_free_bytes": 90 * GIB,
                "vram_used_bytes": 2 * GIB,
                "vram_total_bytes": 12 * GIB,
                "vram_quiescent_baseline_bytes": 2 * GIB,
                "evidence_volume_free_bytes": 9 * GIB,
            }.items()
        },
        "telemetry_coverage": dict.fromkeys(pf.ESSENTIAL_TELEMETRY, "available"),
        "fault_baseline_coverage": dict.fromkeys(ev.FAULT_SOURCES, "complete"),
        "evidence_dir_valid": True,
        "ledger_state": "none",
    }
    base.update(overrides)
    return pf.PreflightInputs(**base)


def reg_commit_comparison():
    good = _good_inputs()
    observations = dict(good.observations)
    observations["commit_headroom_bytes"] = Observation(
        "commit_headroom_bytes", 3 * GIB, "bytes", "fake", NOW, None
    )
    refused = pf.evaluate_preflight(_good_inputs(observations=observations), now_mono_s=NOW)
    assert refused.decision == pf.REFUSED_RESOURCE_THRESHOLD
    assert "COMMIT_HEADROOM_BELOW_THRESHOLD" in refused.reason_codes
    accepted = pf.evaluate_preflight(good, now_mono_s=NOW)
    assert accepted.decision == pf.PREPARED
    assert "COMMIT_HEADROOM_BELOW_THRESHOLD" not in accepted.reason_codes


def reg_stale_sensor_is_not_evidence():
    observations = dict(_good_inputs().observations)
    observations["ram_available_bytes"] = Observation(
        "ram_available_bytes", 25 * GIB, "bytes", "fake", NOW - 10_000, None
    )
    result = pf.evaluate_preflight(_good_inputs(observations=observations), now_mono_s=NOW)
    assert result.decision == pf.INCONCLUSIVE
    assert "RAM_AVAILABLE_STALE" in result.reason_codes


def reg_wrong_sha_is_refused():
    wrong = {
        r: mf.FileMeasurement(s.filename, s.size_bytes, s.sha256)
        for r, s in mf.FROZEN_ASSETS.items()
    }
    wrong["vae"] = mf.FileMeasurement(
        mf.FROZEN_ASSETS["vae"].filename, mf.FROZEN_ASSETS["vae"].size_bytes, "9" * 64
    )
    assert {f.code for f in mf.verify_assets(wrong)} == {"ASSET_SHA256_MISMATCH"}


def reg_same_name_other_path_is_refused():
    root = "C:/qual/forge-data/models"
    items = {
        r: mf.FileMeasurement(
            s.filename, s.size_bytes, s.sha256, f"{root}/{s.models_subdir}/{s.filename}"
        )
        for r, s in mf.FROZEN_ASSETS.items()
    }
    spec = mf.FROZEN_ASSETS["vae"]
    items["vae"] = mf.FileMeasurement(
        spec.filename, spec.size_bytes, spec.sha256, "D:/downloads/" + spec.filename
    )
    assert "SERVED_PATH_MISMATCH" in {
        f.code for f in mf.verify_served_files(items, models_root=root)
    }


def reg_foreign_runtime_is_refused():
    forge = iso.ProcessObservation(
        1, "python.exe", ("python", "launch.py", "--api"), (7871,), "external"
    )
    assert {f.code for f in iso.validate_process_conflicts([forge])} >= {
        "RUNTIME_CONFLICT_FOREIGN_OWNER"
    }


def reg_missing_event_log_is_not_clean():
    before = snapshot()
    after = snapshot(wer_reports=ev.INACCESSIBLE)
    assert (
        ev.classify_faults(before, after, seconds_after_run=600).status == ev.UNKNOWN_COVERAGE_GAP
    )


def reg_ambiguous_attempt_is_never_retried():
    ledger = ev.DispatchLedger(ev.MemoryLedgerStore())
    ledger.record_attempt("a" * 64, "r" * 64)
    with pytest.raises(ev.LedgerRefusal):
        ledger.record_attempt("a" * 64, "r" * 64)


def _mutant_inverted_commit(monkeypatch):
    original = pf.Threshold.passes
    monkeypatch.setattr(pf.Threshold, "passes", lambda self, value: not original(self, value))


def _mutant_ignore_staleness(monkeypatch):
    def number(self, *, units, now_mono_s, max_age_s, allow_negative=False):
        if self.status != "ok" or self.units != units or not isinstance(self.value, int | float):
            return None, "invalid"
        return float(self.value), None

    monkeypatch.setattr(Observation, "number", number)


def _mutant_accept_wrong_sha(monkeypatch):
    original = mf.verify_assets

    def lenient(measured, manifest=None):
        plan = manifest or mf.build_manifest()
        fixed = {
            role: (
                mf.FileMeasurement(item.name, item.size_bytes, plan.assets[role].sha256, item.path)
                if item is not None and role in plan.assets
                else item
            )
            for role, item in measured.items()
        }
        return original(fixed, manifest)

    monkeypatch.setattr(mf, "verify_assets", lenient)


def _mutant_ignore_served_path(monkeypatch):
    monkeypatch.setattr(
        mf,
        "verify_served_files",
        lambda served, *, models_root, manifest=None: mf.verify_assets(served, manifest),
    )


def _mutant_skip_foreign_conflict(monkeypatch):
    monkeypatch.setattr(iso, "looks_like_runtime", lambda process: False)


def _mutant_missing_log_is_clean(monkeypatch):
    original = ev.classify_faults

    def optimistic(before, after, *, seconds_after_run=None):
        if after is not None:
            fixed = {
                name: ev.FaultSourceSnapshot(name, ev.COMPLETE, s.record_ids)
                for name, s in after.sources.items()
            }
            after = ev.FaultSnapshot(after.taken_utc, after.boot_id, fixed)
        return original(before, after, seconds_after_run=seconds_after_run)

    monkeypatch.setattr(ev, "classify_faults", optimistic)


def _mutant_retry_ambiguous(monkeypatch):
    original = ev.DispatchLedger.state
    monkeypatch.setattr(
        ev.DispatchLedger,
        "state",
        lambda self, digest: "none"
        if original(self, digest) == "ambiguous"
        else original(self, digest),
    )


MUTANTS = [
    ("inverted commit comparison", reg_commit_comparison, _mutant_inverted_commit),
    ("ignoring a stale sensor", reg_stale_sensor_is_not_evidence, _mutant_ignore_staleness),
    ("accepting a wrong SHA", reg_wrong_sha_is_refused, _mutant_accept_wrong_sha),
    (
        "allowing a same-name different-path file",
        reg_same_name_other_path_is_refused,
        _mutant_ignore_served_path,
    ),
    (
        "skipping the foreign-process conflict",
        reg_foreign_runtime_is_refused,
        _mutant_skip_foreign_conflict,
    ),
    (
        "treating a missing event log as clean",
        reg_missing_event_log_is_not_clean,
        _mutant_missing_log_is_clean,
    ),
    (
        "retrying an ambiguous ledger entry",
        reg_ambiguous_attempt_is_never_retried,
        _mutant_retry_ambiguous,
    ),
]


@pytest.mark.parametrize(("label", "regression", "mutate"), MUTANTS, ids=[m[0] for m in MUTANTS])
def test_mutation_probe_regression_passes_on_real_code_and_fails_on_the_mutant(
    label, regression, mutate, monkeypatch
):
    regression()  # the unmutated implementation satisfies the regression
    mutate(monkeypatch)
    with pytest.raises((AssertionError, pytest.fail.Exception)):
        regression()
