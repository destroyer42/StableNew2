"""PR-IMG-MODELS-154B T23-T27: validated quiescent baselines in the 154A preflight evaluator (synthetic data only).

The 154A thresholds are untouched; these tests prove only that the baseline-relative rule becomes assessable through an
independently validated window, and that every missing proof keeps the decision away from ``PREPARED_FOR_OWNER_REVIEW``.
"""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from tools.qualification.img154 import manifest as mf
from tools.qualification.img154 import preflight as pf
from tools.qualification.img154.core import GIB, MIB, Observation

NOW = 5000.0
DEVICE = "gpu-device-digest-a"
BOOT = "2026-01-01T00:00:00+00:00"


def obs(name, value, units="bytes", *, age=0.0):
    return Observation(
        name, value, units, "test fake", NOW - age, "2026-01-01T00:00:00+00:00", "ok"
    )


def observations(**overrides):
    values = {
        "commit_headroom_bytes": 40 * GIB,
        "commit_limit_bytes": 49.8 * GIB,
        "ram_available_bytes": 25 * GIB,
        "pagefile_volume_free_bytes": 100 * GIB,
        "vram_used_bytes": 2.3 * GIB,
        "vram_total_bytes": 12 * GIB,
        "evidence_volume_free_bytes": 50 * GIB,
    }
    values.update(overrides)
    return {name: obs(name, value) for name, value in values.items()}


def window(
    count=25, *, used=2.2 * GIB, shared=0.3 * GIB, util=2.0, end=NOW - 5.0, spacing=1.0, **overrides
):
    samples = tuple(
        pf.BaselineSample(end - (count - 1 - index) * spacing, used, shared, util)
        for index in range(count)
    )
    values = {
        "samples": samples,
        "device_id": DEVICE,
        "boot_id": BOOT,
        "acquired_by": pf.BASELINE_PROVIDER,
        "competing_runtime_free": True,
    }
    values.update(overrides)
    return pf.QuiescentBaselineEvidence(**values)


def inputs(**overrides) -> pf.PreflightInputs:
    base = {
        "manifest_digest": mf.build_manifest().digest(),
        "sections": {key: [] for key in pf.SECTION_REASON},
        "observations": observations(),
        "telemetry_coverage": dict.fromkeys(pf.ESSENTIAL_TELEMETRY, "available"),
        "fault_baseline_coverage": dict.fromkeys(
            ("system_log", "application_log", "wer_reports", "live_kernel", "whea"), "complete"
        ),
        "residual_gpu_risk_accepted": True,
        "evidence_dir_valid": True,
        "ledger_state": "none",
        "quiescent_baseline": window(),
        "launch_device_id": DEVICE,
        "launch_boot_id": BOOT,
    }
    base.update(overrides)
    return pf.PreflightInputs(**base)


def evaluate(value, *, now=NOW):
    return pf.evaluate_preflight(value, now_mono_s=now, now_utc="2026-01-01T00:00:10+00:00")


def test_t23_a_validated_window_makes_the_baseline_rule_assessable_and_everything_good_is_prepared():
    result = evaluate(inputs())
    assert result.decision == pf.PREPARED, result.reason_codes
    assert result.measurements["vram_over_baseline_mib"] == round((2.3 * GIB - 2.2 * GIB) / MIB)
    assert result.measurements["vram_quiescent_baseline_mib"] == round(2.2 * GIB / MIB)
    # the harness never decides for the owner
    assert "PHASE_B_PHYSICAL_QUALIFICATION_AUTHORIZATION" in result.pending_owner_decisions


def test_t23_without_a_window_the_numeric_observation_alone_still_never_validates_a_baseline():
    values = observations(vram_quiescent_baseline_bytes=2.2 * GIB)
    result = evaluate(inputs(observations=values, quiescent_baseline=None))
    assert result.decision == pf.INCONCLUSIVE
    assert "VRAM_BASELINE_UNVERIFIED" in result.reason_codes
    assert "vram_over_baseline_mib" not in result.measurements


def test_t24_the_512_mib_margin_is_inclusive_and_unchanged():
    base = 2.2 * GIB
    at_margin = evaluate(inputs(observations=observations(vram_used_bytes=base + 512 * MIB)))
    assert at_margin.decision == pf.PREPARED
    over = evaluate(inputs(observations=observations(vram_used_bytes=base + 512 * MIB + 1)))
    assert over.decision == pf.REFUSED_RESOURCE_THRESHOLD
    assert "VRAM_OVER_QUIESCENT_BASELINE" in over.reason_codes
    below = evaluate(inputs(observations=observations(vram_used_bytes=1.0 * GIB)))
    assert below.decision == pf.PREPARED  # lower than the baseline is not a violation
    assert pf.PreflightPolicy().vram_over_baseline.limit == 512 * MIB


@pytest.mark.parametrize(
    "changes,code,decision",
    [
        ({"acquired_by": "operator"}, "BASELINE_PROVENANCE_UNVERIFIED", pf.INCONCLUSIVE),
        ({"device_id": None}, "BASELINE_DEVICE_UNKNOWN", pf.INCONCLUSIVE),
        ({"device_id": "another-gpu"}, "BASELINE_DEVICE_MISMATCH", pf.REFUSED_RESOURCE_THRESHOLD),
        ({"boot_id": None}, "BASELINE_BOOT_UNKNOWN", pf.INCONCLUSIVE),
        (
            {"boot_id": "2025-12-31T00:00:00+00:00"},
            "BASELINE_BOOT_MISMATCH",
            pf.REFUSED_RESOURCE_THRESHOLD,
        ),
        ({"competing_runtime_free": None}, "BASELINE_COMPETING_RUNTIME_UNKNOWN", pf.INCONCLUSIVE),
        (
            {"competing_runtime_free": False},
            "BASELINE_COMPETING_RUNTIME",
            pf.REFUSED_RESOURCE_THRESHOLD,
        ),
    ],
)
def test_t25_provenance_device_boot_and_runtime_presence_must_all_be_proven(
    changes, code, decision
):
    result = evaluate(inputs(quiescent_baseline=window(**changes)))
    assert result.decision == decision
    assert code in result.reason_codes
    assert "vram_over_baseline_mib" not in result.measurements


def test_t25_the_launch_reading_must_carry_the_same_device_and_boot_identity():
    assert "BASELINE_DEVICE_UNKNOWN" in evaluate(inputs(launch_device_id=None)).reason_codes
    assert "BASELINE_DEVICE_MISMATCH" in evaluate(inputs(launch_device_id="other")).reason_codes
    assert "BASELINE_BOOT_UNKNOWN" in evaluate(inputs(launch_boot_id=None)).reason_codes
    assert "BASELINE_BOOT_MISMATCH" in evaluate(inputs(launch_boot_id="rebooted")).reason_codes


@pytest.mark.parametrize(
    "baseline,code",
    [
        (window(count=5), "BASELINE_TOO_FEW_SAMPLES"),
        (
            window(count=25, spacing=0.5),
            "BASELINE_WINDOW_TOO_SHORT",
        ),  # 12 s of window, 20 s required
        (window(end=NOW - 3600.0), "BASELINE_STALE"),
        (window(end=NOW + 30.0), "BASELINE_STALE"),
        (window(util=60.0), "BASELINE_NOT_QUIESCENT"),
    ],
)
def test_t26_density_freshness_and_quiet_are_required(baseline, code):
    result = evaluate(inputs(quiescent_baseline=baseline))
    assert result.decision != pf.PREPARED
    assert code in result.reason_codes
    assert "vram_over_baseline_mib" not in result.measurements


def test_t26_unstable_vram_shared_memory_gaps_and_invalid_readings_do_not_validate():
    jumpy = list(window().samples)
    jumpy[10] = replace(jumpy[10], vram_used_bytes=jumpy[10].vram_used_bytes + 200 * MIB)
    assert (
        "BASELINE_NOT_QUIESCENT"
        in evaluate(inputs(quiescent_baseline=window(samples=tuple(jumpy)))).reason_codes
    )

    shared = list(window().samples)
    shared[3] = replace(shared[3], shared_vram_bytes=shared[3].shared_vram_bytes + 300 * MIB)
    assert (
        "BASELINE_NOT_QUIESCENT"
        in evaluate(inputs(quiescent_baseline=window(samples=tuple(shared)))).reason_codes
    )

    gap = list(window().samples)
    gap = gap[:12] + [replace(s, mono_s=s.mono_s + 6.0) for s in gap[12:]]
    assert (
        "BASELINE_GAP"
        in evaluate(inputs(quiescent_baseline=window(samples=tuple(gap)))).reason_codes
    )

    for bad in (None, math.nan, -1.0, True):
        samples = list(window().samples)
        samples[4] = replace(samples[4], vram_used_bytes=bad)
        result = evaluate(inputs(quiescent_baseline=window(samples=tuple(samples))))
        assert result.decision != pf.PREPARED, bad
        assert "BASELINE_VRAM_INCOMPLETE" in result.reason_codes

    reversed_times = tuple(reversed(window().samples))
    assert (
        "BASELINE_SAMPLE_ORDER_INVALID"
        in evaluate(inputs(quiescent_baseline=window(samples=reversed_times))).reason_codes
    )


def test_t27_validation_is_pure_and_reports_its_provisional_policy():
    validated, findings = pf.validate_quiescent_baseline(
        window(), now_mono_s=NOW, launch_device_id=DEVICE, launch_boot_id=BOOT
    )
    assert findings == [] and validated is not None
    assert validated.as_dict()["bound_to_device_and_boot"] is True
    none, findings = pf.validate_quiescent_baseline(
        None, now_mono_s=NOW, launch_device_id=DEVICE, launch_boot_id=BOOT
    )
    assert none is None and findings[0].code == "VRAM_BASELINE_UNVERIFIED"
    _, clock = pf.validate_quiescent_baseline(
        window(), now_mono_s=float("nan"), launch_device_id=DEVICE, launch_boot_id=BOOT
    )
    assert "BASELINE_CLOCK_INVALID" in {f.code for f in clock}
    assert pf.PreflightPolicy().as_dict()["baseline_validation"]["status"] == "provisional"
