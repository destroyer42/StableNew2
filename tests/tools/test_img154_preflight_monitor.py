"""PR-IMG-MODELS-154A T07-T15: fail-closed preflight and the deterministic monitor state machine (fake samples, fake clock)."""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from tools.qualification.img154 import manifest as mf
from tools.qualification.img154 import monitor as mon
from tools.qualification.img154 import preflight as pf
from tools.qualification.img154.core import GIB, MIB, Finding, Observation

NOW = 5000.0


def obs(name, value, units="bytes", *, age=0.0, status="ok", t=None):
    return Observation(
        name,
        value,
        units,
        "test fake",
        NOW - age if t is None else t,
        "2026-01-01T00:00:00+00:00",
        status,
    )


def good_observations(**overrides):
    values = {
        "commit_headroom_bytes": 40 * GIB,
        "commit_limit_bytes": 49.8 * GIB,
        "ram_available_bytes": 25 * GIB,
        "pagefile_volume_free_bytes": 100 * GIB,
        "vram_used_bytes": 2.3 * GIB,
        "vram_total_bytes": 12 * GIB,
        "vram_quiescent_baseline_bytes": 2.2 * GIB,
        "evidence_volume_free_bytes": 50 * GIB,
    }
    values.update(overrides)
    return {name: obs(name, value) for name, value in values.items()}


COVERAGE = dict.fromkeys(pf.ESSENTIAL_TELEMETRY, "available")
FAULTS = dict.fromkeys(
    ("system_log", "application_log", "wer_reports", "live_kernel", "whea"), "complete"
)


def good_inputs(**overrides) -> pf.PreflightInputs:
    base = {
        "manifest_digest": mf.build_manifest().digest(),
        "sections": {key: [] for key in pf.SECTION_REASON},
        "observations": good_observations(),
        "telemetry_coverage": dict(COVERAGE),
        "fault_baseline_coverage": dict(FAULTS),
        "residual_gpu_risk_accepted": None,
        "evidence_dir_valid": True,
        "ledger_state": "none",
    }
    base.update(overrides)
    return pf.PreflightInputs(**base)


def evaluate(inputs, *, now=NOW):
    return pf.evaluate_preflight(inputs, now_mono_s=now, now_utc="2026-01-01T00:00:00+00:00")


# --- decision vocabulary -------------------------------------------------------------------------------------------------


def test_numeric_baseline_remains_inconclusive_with_decisions_pending():
    result = evaluate(good_inputs())
    assert result.decision == pf.INCONCLUSIVE
    assert "VRAM_BASELINE_UNVERIFIED" in result.reason_codes
    assert "RESIDUAL_GPU_RISK_ACCEPTANCE" in result.pending_owner_decisions
    assert "PHASE_B_PHYSICAL_QUALIFICATION_AUTHORIZATION" in result.pending_owner_decisions


def test_decision_vocabulary_never_says_go_safe_qualified_or_ready():
    for decision in pf.ALL_DECISIONS:
        assert not (set(decision.split("_")) & pf.FORBIDDEN_DECISION_WORDS), decision
    assert pf.PREPARED == "PREPARED_FOR_OWNER_REVIEW"


def test_nothing_assessed_is_not_assessed():
    assert evaluate(None).decision == pf.NOT_ASSESSED
    assert evaluate(pf.PreflightInputs()).decision == pf.NOT_ASSESSED


def test_unassessed_sections_are_inconclusive_not_a_pass():
    sections = {key: [] for key in pf.SECTION_REASON}
    sections["isolation"] = None
    result = evaluate(good_inputs(sections=sections))
    assert result.decision == pf.INCONCLUSIVE
    assert "ISOLATION_NOT_ASSESSED" in result.reason_codes


# --- T07 -----------------------------------------------------------------------------------------------------------------


def _reading(value, *, units="bytes", status="ok", mono=NOW):
    return Observation("commit_headroom_bytes", value, units, "test fake", mono, None, status)


@pytest.mark.parametrize(
    "bad",
    [
        _reading(None),
        _reading(float("nan")),
        _reading(float("inf")),
        _reading(-1),
        _reading(True),
        _reading("40"),
        _reading(40 * GIB, mono=NOW - 3600),  # stale
        _reading(40 * GIB, mono=NOW + 600),  # from the future
        _reading(40 * GIB, mono=None),  # no timestamp at all
        _reading(40 * GIB, units="gib"),
        _reading(40 * GIB, status="error"),
        _reading(40 * GIB, status="stale"),
    ],
)
def test_t07_unusable_telemetry_can_never_pass(bad):
    observations = good_observations()
    observations["commit_headroom_bytes"] = bad
    result = evaluate(good_inputs(observations=observations))
    assert result.decision != pf.PREPARED
    assert any(code.startswith("COMMIT_HEADROOM_") for code in result.reason_codes)


def test_t07_missing_observation_and_missing_coverage_are_inconclusive():
    observations = good_observations()
    del observations["ram_available_bytes"]
    assert evaluate(good_inputs(observations=observations)).decision == pf.INCONCLUSIVE
    broken = dict(COVERAGE, gpu_temperature_c="unavailable")
    result = evaluate(good_inputs(telemetry_coverage=broken))
    assert result.decision == pf.INCONCLUSIVE
    assert "TELEMETRY_FIELD_UNAVAILABLE" in result.reason_codes
    assert evaluate(good_inputs(telemetry_coverage=None)).decision == pf.INCONCLUSIVE


# --- T08 -----------------------------------------------------------------------------------------------------------------


def test_t08_actual_commit_headroom_is_used_not_a_theoretical_ceiling():
    # the theoretical ceiling (RAM + pagefile - reserve) would be ~45.8 GiB; only the real reading may decide
    observations = good_observations(
        commit_headroom_bytes=16.1 * GIB, commit_limit_bytes=49.8 * GIB
    )
    result = evaluate(good_inputs(observations=observations))
    assert result.decision == pf.REFUSED_RESOURCE_THRESHOLD
    assert "COMMIT_HEADROOM_BELOW_THRESHOLD" in result.reason_codes
    assert result.measurements["commit_headroom_gib"] == 16.1


def test_t08_commit_limit_below_threshold_is_unreachable_and_policy_is_not_lowered():
    observations = good_observations(commit_headroom_bytes=30 * GIB, commit_limit_bytes=36 * GIB)
    result = evaluate(good_inputs(observations=observations))
    assert result.decision == pf.REFUSED_RESOURCE_THRESHOLD
    assert "COMMIT_THRESHOLD_UNREACHABLE" in result.reason_codes
    assert pf.PreflightPolicy().commit_headroom.limit == 37 * GIB  # unchanged by the host


def test_t08_headroom_above_limit_is_an_inconsistent_reading():
    observations = good_observations(commit_headroom_bytes=60 * GIB, commit_limit_bytes=49.8 * GIB)
    result = evaluate(good_inputs(observations=observations))
    assert "COMMIT_READING_INCONSISTENT" in result.reason_codes
    assert result.decision != pf.PREPARED


# --- T09 -----------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "limit"),
    [
        ("commit_headroom_bytes", 37 * GIB),
        ("ram_available_bytes", 20 * GIB),
        ("pagefile_volume_free_bytes", 30 * GIB),
    ],
)
def test_t09_minimums_pass_at_exact_equality_and_fail_one_byte_below(name, limit):
    at_limit = evaluate(good_inputs(observations=good_observations(**{name: limit})))
    assert at_limit.decision == pf.INCONCLUSIVE
    assert not any(code.endswith("BELOW_THRESHOLD") for code in at_limit.reason_codes)
    below = evaluate(good_inputs(observations=good_observations(**{name: limit - 1})))
    assert below.decision == pf.REFUSED_RESOURCE_THRESHOLD


def test_t09_vram_maximum_comparator_edges_do_not_validate_a_baseline():
    threshold = pf.PreflightPolicy().vram_over_baseline
    assert threshold.passes(512 * MIB)
    assert not threshold.passes(512 * MIB + 1)
    result = evaluate(good_inputs())
    assert result.decision == pf.INCONCLUSIVE
    assert "VRAM_BASELINE_UNVERIFIED" in result.reason_codes
    assert "vram_over_baseline_mib" not in result.measurements


def test_t09_vram_without_a_measured_baseline_is_inconclusive_never_assumed():
    observations = good_observations()
    del observations["vram_quiescent_baseline_bytes"]
    result = evaluate(good_inputs(observations=observations))
    assert result.decision == pf.INCONCLUSIVE
    assert "VRAM_BASELINE_MISSING" in result.reason_codes


def test_t09_no_threshold_is_claimed_proven():
    policy = pf.PreflightPolicy().as_dict()
    assert policy["all_thresholds_proven"] is False
    assert {t["status"] for t in policy["thresholds"]} <= {pf.PROVISIONAL, pf.BASELINE_RELATIVE}
    assert all(t["source"] and t["sensitivity"] for t in policy["thresholds"])


def test_t09_launch_headroom_leaves_room_above_the_simulated_commit_stop():
    policy = pf.PreflightPolicy()
    stop = mon.MonitorConfig().commit_headroom_floor_bytes
    high_analogue = 30.7 * GIB  # PR-IMG-MODELS-153 ratio analogue of the Forge-tree private commit
    assert (
        policy.commit_headroom.limit - high_analogue > stop
    )  # a launch at the minimum would not start at the stop line


def test_preflight_assessment_goes_stale_and_binds_to_the_manifest():
    # Synthetic PREPARED result tests freshness only; numeric baseline cannot produce it.
    result = replace(evaluate(good_inputs()), decision=pf.PREPARED)
    assert result.is_current(now_mono_s=NOW + 10, max_age_s=30)
    assert not result.is_current(now_mono_s=NOW + 31, max_age_s=30)
    other = mf.QualificationManifest(forge_pin="f" * 40)
    assert not result.is_current(now_mono_s=NOW + 1, max_age_s=30, manifest=other)


# --- hard prerequisites --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("section", "code", "decision"),
    [
        ("assets", "ASSET_SHA256_MISMATCH", pf.REFUSED_ASSET_IDENTITY),
        ("served", "SERVED_PATH_MISMATCH", pf.REFUSED_ASSET_IDENTITY),
        ("pin", "PIN_MARKER_MISMATCH", pf.REFUSED_RUNTIME_PIN),
        ("intent", "INTENT_DRIFT", pf.REFUSED_INTENT_DRIFT),
        ("isolation", "ISOLATION_INSIDE_RESERVED", pf.REFUSED_ISOLATION),
        ("endpoint", "RUNTIME_PORT_OCCUPIED", pf.REFUSED_RUNTIME_CONFLICT),
        ("processes", "RUNTIME_CONFLICT_FOREIGN_OWNER", pf.REFUSED_RUNTIME_CONFLICT),
    ],
)
def test_hard_prerequisites_refuse(section, code, decision):
    sections = {key: [] for key in pf.SECTION_REASON}
    sections[section] = [Finding(code, "refuse", "")]
    result = evaluate(good_inputs(sections=sections))
    assert result.decision == decision
    assert code in result.reason_codes


def test_prior_dispatch_declined_risk_and_bad_evidence_path_refuse():
    assert evaluate(good_inputs(ledger_state="ambiguous")).decision == pf.REFUSED_PRIOR_DISPATCH
    assert evaluate(good_inputs(ledger_state="dispatched")).decision == pf.REFUSED_PRIOR_DISPATCH
    assert evaluate(good_inputs(ledger_state="unknown")).decision == pf.INCONCLUSIVE
    assert (
        evaluate(good_inputs(residual_gpu_risk_accepted=False)).decision
        == pf.REFUSED_RISK_NOT_ACCEPTED
    )
    assert evaluate(good_inputs(evidence_dir_valid=False)).decision == pf.REFUSED_EVIDENCE_PATH
    accepted = evaluate(good_inputs(residual_gpu_risk_accepted=True))
    assert accepted.decision == pf.INCONCLUSIVE
    assert "RESIDUAL_GPU_RISK_ACCEPTANCE" not in accepted.pending_owner_decisions


def test_changed_manifest_digest_refuses():
    result = evaluate(good_inputs(manifest_digest="0" * 64))
    assert result.decision == pf.REFUSED_INTENT_DRIFT
    assert "MANIFEST_DIGEST_MISMATCH" in result.reason_codes


def test_refusal_precedence_names_identity_before_resources_and_reports_every_code():
    sections = {key: [] for key in pf.SECTION_REASON}
    sections["assets"] = [Finding("ASSET_SIZE_MISMATCH", "refuse", "")]
    observations = good_observations(ram_available_bytes=1 * GIB)
    result = evaluate(good_inputs(sections=sections, observations=observations))
    assert result.decision == pf.REFUSED_ASSET_IDENTITY
    assert {"ASSET_SIZE_MISMATCH", "RAM_AVAILABLE_BELOW_THRESHOLD"} <= set(result.reason_codes)


def test_incomplete_fault_baseline_is_inconclusive_and_bounded_lookback_is_accepted():
    partial = dict(FAULTS, wer_reports="inaccessible")
    result = evaluate(good_inputs(fault_baseline_coverage=partial))
    assert result.decision == pf.INCONCLUSIVE
    bounded = dict(FAULTS, system_log="bounded_lookback")
    assert (
        "FAULT_BASELINE_INCOMPLETE"
        not in evaluate(good_inputs(fault_baseline_coverage=bounded)).reason_codes
    )
    assert evaluate(good_inputs(fault_baseline_coverage=None)).decision == pf.INCONCLUSIVE


# --- monitor -------------------------------------------------------------------------------------------------------------


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


def sample(seq, t, **kw):
    values = {
        "seq": seq,
        "mono_s": t,
        "utc": "2026-01-01T00:00:00+00:00",
        "ram_available_bytes": 12 * GIB,
        "commit_headroom_bytes": 20 * GIB,
        "vram_used_bytes": 5 * GIB,
        "vram_total_bytes": 12 * GIB,
        "shared_vram_bytes": 0.5 * GIB,
        "gpu_temperature_c": 55.0,
        "gpu_device_present": True,
    }
    values.update(kw)
    return mon.Sample(**values)


def machine(config=None):
    clock = Clock()
    monitor = mon.SafetyMonitor(
        config or mon.MonitorConfig(shared_baseline_bytes=0.5 * GIB), clock=clock
    )
    monitor.begin_observation()
    return monitor, clock


def feed(monitor, clock, seq, offset, **kw):
    clock.now = 1000.0 + offset
    return monitor.ingest(sample(seq, 1000.0 + offset, **kw))


def test_nominal_samples_request_nothing():
    monitor, clock = machine()
    decisions = [feed(monitor, clock, i, i) for i in range(1, 31)]
    assert {d.action for d in decisions} == {mon.NONE}
    assert monitor.latched_action == mon.NONE


# --- T10 -----------------------------------------------------------------------------------------------------------------


def test_t10_ram_below_one_gib_for_exactly_ten_seconds_does_not_stop():
    monitor, clock = machine()
    low = {"ram_available_bytes": 0.9 * GIB}
    actions = [
        feed(monitor, clock, i, i, **low).action for i in range(1, 12)
    ]  # violation spans t=1..11 (10.0 s)
    assert mon.REQUEST_OWNER_STOP not in actions
    assert actions[-1] == mon.WARN


def test_t10_ram_below_one_gib_for_over_ten_seconds_requests_stop():
    monitor, clock = machine()
    low = {"ram_available_bytes": 0.9 * GIB}
    actions = [feed(monitor, clock, i, i, **low).action for i in range(1, 13)]  # 10.0 s then 11.0 s
    assert actions[:11].count(mon.REQUEST_OWNER_STOP) == 0
    assert actions[11] == mon.REQUEST_OWNER_STOP
    assert monitor.first_trigger == "RAM_AVAILABLE_BELOW_FLOOR"


def test_t10_one_recovered_sample_resets_the_hold_and_exact_floor_is_not_a_violation():
    monitor, clock = machine()
    for i in range(1, 9):
        feed(monitor, clock, i, i, ram_available_bytes=0.5 * GIB)
    feed(monitor, clock, 9, 9, ram_available_bytes=1 * GIB)  # exactly the floor: not below it
    actions = [
        feed(monitor, clock, i, i, ram_available_bytes=0.5 * GIB).action for i in range(10, 18)
    ]
    assert mon.REQUEST_OWNER_STOP not in actions  # the clock restarted at the recovered sample


# --- T11 -----------------------------------------------------------------------------------------------------------------


def test_t11_commit_headroom_below_four_gib_requests_stop_after_debounce():
    monitor, clock = machine()
    first = feed(monitor, clock, 1, 1, commit_headroom_bytes=3.9 * GIB)
    assert first.action == mon.WARN  # one sample is debounced
    second = feed(monitor, clock, 2, 2, commit_headroom_bytes=3.9 * GIB)
    assert second.action == mon.REQUEST_OWNER_STOP
    assert "COMMIT_HEADROOM_BELOW_FLOOR" in second.codes


def test_t11_exactly_four_gib_is_not_below_the_floor():
    monitor, clock = machine()
    actions = [
        feed(monitor, clock, i, i, commit_headroom_bytes=4 * GIB).action for i in range(1, 5)
    ]
    assert mon.REQUEST_OWNER_STOP not in actions


def test_t09_flapping_never_reaches_the_debounce_but_warns_each_time():
    monitor, clock = machine()
    actions = []
    for i in range(1, 11):
        low = i % 2 == 1
        actions.append(
            feed(monitor, clock, i, i, commit_headroom_bytes=(3 if low else 20) * GIB).action
        )
    assert mon.REQUEST_OWNER_STOP not in actions
    assert actions[0] == mon.WARN
    assert monitor.latched_action == mon.WARN


# --- T12 -----------------------------------------------------------------------------------------------------------------


def test_t12_vram_at_95_percent_shared_growth_and_temperature_edges():
    cases = (
        # 95/100 is exactly the 0.95 ratio; 94.9/100 is inside
        (
            {"vram_used_bytes": 95.0, "vram_total_bytes": 100.0},
            {"vram_used_bytes": 94.9, "vram_total_bytes": 100.0},
        ),
        # baseline 0.5 GiB: growth must be strictly more than 1 GiB
        ({"shared_vram_bytes": 1.5 * GIB + 1}, {"shared_vram_bytes": 1.5 * GIB}),
        ({"gpu_temperature_c": 80.0}, {"gpu_temperature_c": 79.9}),
    )
    for at_edge, inside in cases:
        stop, clock = machine()
        actions = [feed(stop, clock, i, i, **at_edge).action for i in (1, 2)]
        assert actions[-1] == mon.REQUEST_OWNER_STOP, at_edge
        calm, clock = machine()
        actions = [feed(calm, clock, i, i, **inside).action for i in (1, 2)]
        assert mon.REQUEST_OWNER_STOP not in actions, inside


def test_t12_shared_rule_without_a_measured_baseline_is_unobservable_not_assumed():
    monitor, clock = machine(mon.MonitorConfig())  # no shared baseline
    decision = feed(monitor, clock, 1, 1, shared_vram_bytes=50 * GIB)
    assert "SHARED_BASELINE_MISSING" in decision.codes
    assert decision.action == mon.WARN


# --- T13 -----------------------------------------------------------------------------------------------------------------


def test_t13_gpu_fault_event_takes_precedence_over_a_resource_stop():
    monitor, clock = machine()
    feed(monitor, clock, 1, 1, commit_headroom_bytes=3 * GIB)
    decision = feed(monitor, clock, 2, 2, commit_headroom_bytes=3 * GIB, fault_events=("nvlddmkm",))
    assert decision.action == mon.CANNOT_VERIFY_SAFE_STATE
    assert decision.codes[0] == "GPU_FAULT_EVENT:nvlddmkm"
    assert "COMMIT_HEADROOM_BELOW_FLOOR" in decision.codes
    # a later clean sample never lowers a latched finding
    later = feed(monitor, clock, 3, 3)
    assert later.action == mon.NONE
    assert later.latched_action == mon.CANNOT_VERIFY_SAFE_STATE


def test_t13_lost_device_gap_staleness_and_prolonged_incomplete_samples():
    lost, clock = machine()
    assert feed(lost, clock, 1, 1, gpu_device_present=False).codes[0] == "GPU_DEVICE_LOST"

    gap, clock = machine()
    feed(gap, clock, 1, 1)
    assert "TELEMETRY_GAP" in feed(gap, clock, 2, 9).codes

    stale, clock = machine()
    clock.now = 1100.0
    assert "TELEMETRY_STALE" in stale.ingest(sample(1, 1000.0)).codes

    incomplete, clock = machine()
    decisions = [feed(incomplete, clock, i, i, gpu_temperature_c=None) for i in (1, 2, 3)]
    assert decisions[0].action == mon.WARN
    assert decisions[1].action == mon.WARN
    assert decisions[2].action == mon.CANNOT_VERIFY_SAFE_STATE
    assert "TELEMETRY_LOST" in decisions[2].codes


def test_t13_tick_detects_silence_against_the_injected_clock():
    monitor, clock = machine()
    clock.now = 1002.0
    assert monitor.tick().action == mon.NONE
    clock.now = 1004.0
    assert monitor.tick().codes == ("TELEMETRY_NEVER_RECEIVED",)
    fresh, clock = machine()
    feed(fresh, clock, 1, 1)
    clock.now = 1000.0 + 1 + 3.5
    decision = fresh.tick()
    assert decision.action == mon.CANNOT_VERIFY_SAFE_STATE
    assert decision.codes == ("TELEMETRY_STALE",)


def test_non_monotonic_or_duplicate_samples_are_a_harness_fault_not_a_finding():
    monitor, clock = machine()
    feed(monitor, clock, 1, 5)
    assert feed(monitor, clock, 1, 6).codes == ("SAMPLE_SEQUENCE_INVALID",)
    clock.now = 1010.0
    assert monitor.ingest(sample(2, 1004.0)).codes == ("SAMPLE_TIME_NOT_MONOTONIC",)
    clock.now = 1010.0
    assert monitor.ingest(sample(3, 2000.0)).codes == ("SAMPLE_FROM_FUTURE",)
    assert monitor.latched_action == mon.HARNESS_FAULT


def test_invalid_numbers_are_missing_not_zero():
    monitor, clock = machine()
    for seq, bad in enumerate((math.nan, math.inf, -5.0, True, "12"), start=1):
        decision = feed(monitor, clock, seq, seq, ram_available_bytes=bad)
        assert "SAMPLE_INCOMPLETE" in decision.codes or "TELEMETRY_LOST" in decision.codes


def test_reset_clears_latched_state_and_events():
    monitor, clock = machine()
    feed(monitor, clock, 1, 1, fault_events=("WHEA",))
    assert monitor.latched_action == mon.CANNOT_VERIFY_SAFE_STATE
    monitor.reset()
    assert monitor.latched_action == mon.NONE
    assert monitor.events == []


# --- T14 / T15 -----------------------------------------------------------------------------------------------------------


def test_t14_unobservable_stage_is_unknown_not_inferred():
    monitor, clock = machine()
    decision = feed(monitor, clock, 1, 1, stage="unknown", stage_source="inferred")
    assert decision.stage == "unknown"
    assert decision.stage_source == "unknown"
    for stage in ("encoder_load", "transformer_load", "vae_decode"):
        assert mon.STAGE_OBSERVABILITY[stage].startswith("not_observable")
    assert "unproven" in mon.STAGE_OBSERVABILITY["denoise"]


def test_t14_invalid_stage_names_are_flagged_and_collapse_to_unknown():
    monitor, clock = machine()
    decision = feed(monitor, clock, 1, 1, stage="layer_17_attention", stage_source="forge_api")
    assert "STAGE_VALUE_INVALID" in decision.codes
    assert decision.stage == "unknown"


def test_t15_stage_sources_stay_distinguishable():
    monitor, clock = machine()
    feed(monitor, clock, 1, 1, stage="preflight", stage_source="operator")
    feed(monitor, clock, 2, 2, stage="managed_start", stage_source="manager")
    feed(monitor, clock, 3, 3, stage="denoise", stage_source="forge_api")
    feed(monitor, clock, 4, 4, stage="denoise", stage_source="inferred")
    stages = [(e["stage"], e["stage_source"]) for e in monitor.events if e.get("event") == "stage"]
    assert stages == [
        ("preflight", "operator"),
        ("managed_start", "manager"),
        ("denoise", "forge_api"),
        ("denoise", "inferred"),
    ]


def test_stall_rule_is_inactive_without_an_evidenced_deadline_and_active_with_one():
    inactive, clock = machine()
    for i in range(1, 40):
        feed(inactive, clock, i, i, stage="denoise", stage_source="forge_api")
    assert inactive.latched_action == mon.NONE
    assert mon.RULE_CLASSIFICATION["stage_stall"]["status"] == "unconfigured"

    config = mon.MonitorConfig(shared_baseline_bytes=0.5 * GIB, stall_deadlines_s={"denoise": 20.0})
    active, clock = machine(config)
    actions = [
        feed(active, clock, i, i, stage="denoise", stage_source="forge_api").action
        for i in range(1, 25)
    ]
    assert actions[-1] == mon.REQUEST_OWNER_STOP


def test_no_rule_is_called_enforceable_and_the_policy_is_self_consistent():
    assert all(rule["enforceable"] is False for rule in mon.RULE_CLASSIFICATION.values())
    assert mon.policy_findings(mon.MonitorConfig()) == []
    bad = mon.MonitorConfig(temperature_warn_c=85.0)
    assert [f.code for f in mon.policy_findings(bad)] == ["WARN_NOT_BELOW_STOP_TEMPERATURE"]
    assert (
        "Pages Input/sec" in mon.WINDOWS_COUNTERS["hard_fault_pages"]
    )  # hard-fault page reads, not total page faults
