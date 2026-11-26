"""PR-VID-MOTION-430 Workstream E: the Fun Control qualification harness can plan the 1.1.0 trial without changing the old plan.

Every executor here is a fake.  No Comfy, model, GPU, download or network is involved and no ledger is touched.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from tools.qualification.fun354 import harness, q0
from tools.qualification.fun354 import physical as phys
from tools.qualification.fun354.__main__ import main as cli_main
from tools.qualification.fun354.harness import Authorization, CaseObservation, run_qualification
from tools.qualification.fun354.inputs import rebuild_plan
from tools.qualification.fun354.plan import (
    EXPECTED_STATUS,
    TELEMETRY,
    TRIAL_TELEMETRY,
    TRIAL_VERSION,
    WORKFLOW_VERSION,
    PlanError,
    build_plan,
    fun_control_spec,
)
from tools.qualification.vid110 import monitor as vid110_monitor
from tools.qualification.vid160c import telemetry as vid160c_telemetry

#: Digests recorded from the 1.0.0 plan builder before this package; they must never move.
EMPTY_1_0_0_DIGEST = "23c2ae3f46536b7de504ee716c1b250934aac3fed8563659f9d934ac46c00cf5"
PINNED_1_0_0_DIGEST = "23ffdaa01862d9c2773ce16b847b2b73ed91b4e0a9d15c2936e4beba6a299ebb"
HOST = q0.HostFacts(32768, 20000, 49152, 50 * 1024**3)


def _pinned(version: str = WORKFLOW_VERSION):
    return build_plan(
        driving_clip_sha256="a" * 64,
        driving_clip_size=10,
        reference_sha256="b" * 64,
        reference_size=5,
        workflow_version=version,
    )


def test_the_1_0_0_plan_and_its_digest_are_exactly_what_they_were():
    assert build_plan().digest == EMPTY_1_0_0_DIGEST
    plan = _pinned()
    assert plan.digest == PINNED_1_0_0_DIGEST
    assert plan.resource_policy is None and "candidate" not in plan.to_record()
    assert plan.telemetry == TELEMETRY and plan.workflow_version == "1.0.0"


def test_a_trial_plan_pins_the_exact_candidate_graph_model_and_resource_policy():
    plan = _pinned(TRIAL_VERSION)
    record = plan.to_record()
    published = _pinned()
    assert plan.digest != published.digest
    assert record["workflow"]["version"] == "1.1.0"
    # the identical graph and weights: only the policy and the plan differ
    assert plan.graph_sha256 == published.graph_sha256 and plan.assets == published.assets
    candidate = record["candidate"]
    assert candidate["resource_policy"]["qualification_status"] == "trial_unqualified"
    assert candidate["resource_policy"]["min_available_to_comfy_vram_mib"] == 10000
    assert len(candidate["resource_policy_sha256"]) == 64
    assert "does not change" in candidate["policy_status"]
    text = json.dumps(candidate)
    assert "not a qualification of 1.1.0" in text and "4K drivers failed" in text
    assert record["physical_execution"] == "NOT AUTHORIZED"
    assert plan.telemetry == TRIAL_TELEMETRY
    assert {"gpu_temperature_peak_c", "gpu_vram_headroom_min_mib"} <= set(plan.telemetry)


def test_stop_conditions_are_not_weakened_for_the_trial():
    assert _pinned(TRIAL_VERSION).stops == _pinned().stops


def test_only_known_versions_with_their_declared_policy_can_be_planned():
    with pytest.raises(PlanError, match="No qualification plan"):
        build_plan(workflow_version="9.9.9")
    assert EXPECTED_STATUS == {"1.0.0": "not_qualified", "1.1.0": "trial_unqualified"}
    assert fun_control_spec(TRIAL_VERSION).workflow_version == TRIAL_VERSION


def test_q0_reports_the_trial_policy_as_unchanged_and_still_unqualified():
    plan = _pinned(TRIAL_VERSION)
    report = q0.run_q0(plan, folders=None, host=HOST, inputs={}, runtime_commit=plan.runtime_commit)
    catalog = next(c for c in report.checks if c.check_id == "catalog_identity")
    assert catalog.status == "PASS" and "resource policy unchanged" in catalog.detail
    assert "still not qualified" in catalog.detail
    assert report.status != "ready"  # no weights or inputs were given: nothing here is a go-ahead


def test_a_plan_with_a_different_resource_policy_is_blocked_by_q0():
    plan = _pinned(TRIAL_VERSION)
    stale = replace(
        plan, resource_policy={**plan.resource_policy, "min_available_to_comfy_vram_mib": 9000}
    )
    report = q0.run_q0(
        stale, folders=None, host=HOST, inputs={}, runtime_commit=plan.runtime_commit
    )
    catalog = next(c for c in report.checks if c.check_id == "catalog_identity")
    assert catalog.status == "BLOCKED" and "mint a new plan" in catalog.detail
    assert stale.digest != plan.digest


def test_the_cli_proposes_a_trial_plan_without_running_anything(tmp_path, capsys, monkeypatch):
    clip = tmp_path / "drive.mp4"
    ref = tmp_path / "ref.png"
    clip.write_bytes(b"clip")
    ref.write_bytes(b"ref")
    out = tmp_path / "plan.json"
    monkeypatch.setattr("tools.qualification.fun354.__main__._outside_repo", lambda p: Path(p))
    assert (
        cli_main(
            [
                "propose",
                "--workflow-version",
                "1.1.0",
                "--out",
                str(out),
                "--driving-clip",
                str(clip),
                "--reference",
                str(ref),
            ]
        )
        == 0
    )
    stored = json.loads(out.read_text(encoding="utf-8"))
    assert stored["workflow"]["version"] == "1.1.0" and stored["candidate"]
    assert rebuild_plan(stored).digest == stored["digest"]
    assert "NOT AUTHORIZED" in capsys.readouterr().out


def test_an_authorization_for_one_plan_cannot_run_another():
    trial, published = _pinned(TRIAL_VERSION), _pinned()
    auth = Authorization(plan_digest=published.digest, authorized_by="owner")
    ready = q0.Q0Report(plan_digest=trial.digest, checks=(), host=None)
    outcome = run_qualification(trial, ready, _NeverRuns(), auth)
    assert outcome.verdict == harness.NOT_RUN and not outcome.observations


class _NeverRuns:
    def run_case(self, plan, phase, case):  # pragma: no cover - must not be reached
        raise AssertionError("an executor was reached without a matching authorization")


# ----------------------------------------------------------------------------------------------- telemetry


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("83.9", 83.9),
        ("71", 71.0),
        (" 40.0 ", 40.0),
        ("[N/A]", None),
        ("", None),
        ("hot", None),
        ("-5", None),
        ("nan", None),
        ("inf", None),
    ],
)
def test_gpu_numbers_keep_decimals_and_never_crash_on_driver_noise(text, expected):
    assert phys.parse_gpu_number(text) == expected


def test_the_guard_records_peak_temperature_and_minimum_vram_headroom():
    guard = phys.StopGuard()
    for elapsed, used, temp in ((0.0, 2000.0, 55.5), (1.0, 11800.0, 83.9), (2.0, 9000.0, None)):
        assert guard.observe(phys.Sample(elapsed, 0.5, 20000.0, used, 12282.0, temp)) == ""
    assert guard.peak_temperature_c == 83.9
    assert guard.min_headroom_mib == 12282.0 - 11800.0
    assert guard.peak_vram_mib == 11800.0
    quiet = phys.StopGuard()
    quiet.observe(phys.Sample(0.0, 0.5, 20000.0, 100.0, 12282.0))
    assert quiet.peak_temperature_c is None  # absent is not zero


def test_the_older_qualification_monitors_accept_decimal_temperatures():
    sample = vid110_monitor.parse_gpu_line(
        "11690, 83.9, 268.4, 2535, 10501, 100, 0x0000000000000004"
    )
    assert sample.temp_c == 83.9 and sample.vram_mib == 11690
    peaks = vid110_monitor.ResourcePeaks()
    peaks.temp_peak_c = max(peaks.temp_peak_c, sample.temp_c)
    assert peaks.temp_peak_c == 83.9


def test_the_vid160c_sampler_survives_a_decimal_temperature(monkeypatch):
    monkeypatch.setattr(
        vid160c_telemetry.subprocess,
        "check_output",
        lambda *a, **k: "11690, 83.9, 268.40, 100\n",
    )
    assert vid160c_telemetry._gpu_sample() == (11690, 83.9, 268.4, 100)


def test_missing_temperature_makes_a_trial_case_telemetry_incomplete_but_never_a_stop(tmp_path):
    plan = _pinned(TRIAL_VERSION)
    assert "gpu_temperature_peak_c" in plan.telemetry
    observation = CaseObservation("Q1", "c", True, 17, 17)
    assert observation.peak_gpu_temperature_c is None and observation.min_vram_headroom_mib is None
    assert "gpu_temperature_peak_c" not in _pinned().telemetry
