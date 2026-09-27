"""PR-VID-184S: deterministic arm-manifest, matched-state gate and classification tests (no GPU)."""

from __future__ import annotations

from typing import Any

import pytest

from tools.qualification.vid184s import arms


def _arm(outcome: str = "COMPLETED", *, commit_peak: float = 57.0, **kw: Any) -> dict[str, Any]:
    return {"outcome": outcome, "peaks": {"commit_peak_percent": commit_peak}, **kw}


def test_b1_and_b2_are_execution_equivalent() -> None:
    assert arms.execution_equivalent(arms.arm_manifest("B1"), arms.arm_manifest("B2"))
    assert arms.launch_args("B1") == arms.launch_args("B2")


def test_a_differs_from_b_only_by_pinned_state_and_identity() -> None:
    from tools.qualification.vid184r import arm_manifest as base

    a, b = arms.arm_manifest("A"), arms.arm_manifest("B1")
    assert set(base.diff_manifests(a, b)) <= arms.ALLOWED_DIFF_KEYS
    assert base.launch_arg_difference(a, b) == [arms.PINNED_FLAG]


def test_no_hidden_flags_and_unknown_arm() -> None:
    for arm in arms.ARMS:
        assert arms.hidden_flag_check(arm) == []
    with pytest.raises(ValueError):
        arms.launch_args("C")


def test_frozen_bands_are_the_registered_values() -> None:
    assert arms.BAND_COMMIT_PERCENT_POINTS == 3.0
    assert arms.BAND_PHYSICAL_AVAILABLE_GB == 1.5
    assert arms.BAND_FREE_VRAM_MIB == 512.0
    assert arms.MAX_MINUTES_SINCE_BOOT == 60.0
    assert arms.PRESSURE_COMMIT_PEAK_DELTA_POINTS == 10.0


REF = {"commit_percent": 30.0, "physical_available_gb": 18.0, "free_vram_mib": 11000.0}


def test_matched_state_within_bands() -> None:
    cur = {"commit_percent": 32.9, "physical_available_gb": 16.6, "free_vram_mib": 10600.0}
    assert arms.matched_state_check(REF, cur)["matched"] is True


@pytest.mark.parametrize(
    "cur",
    [
        {"commit_percent": 33.1, "physical_available_gb": 18.0, "free_vram_mib": 11000.0},
        {"commit_percent": 30.0, "physical_available_gb": 16.4, "free_vram_mib": 11000.0},
        {"commit_percent": 30.0, "physical_available_gb": 18.0, "free_vram_mib": 10400.0},
        {"commit_percent": 30.0, "physical_available_gb": 18.0, "free_vram_mib": None},
    ],
)
def test_matched_state_out_of_band(cur: dict[str, Any]) -> None:
    res = arms.matched_state_check(REF, cur)
    assert res["matched"] is False
    assert any(not r["within"] for r in res["rows"].values())


def test_matched_state_records_absolute_and_delta() -> None:
    row = arms.matched_state_check(REF, {**REF, "commit_percent": 31.0})["rows"]["commit_percent"]
    assert (row["reference"], row["current"], row["delta"]) == (30.0, 31.0, 1.0)


def test_b1_failure_stops_before_a() -> None:
    for bad in (_arm("EXECUTION_ERROR"), _arm("PROCESS_EXITED", gpu_lost=True)):
        res = arms.classify({"B1": bad, "A": None, "B2": None})
        assert res["labels"] == ["DISABLE_PINNED_MEMORY_REPRODUCIBILITY_NOT_CONFIRMED"]
        assert res["stopped_early"]


def test_strong_reproduction() -> None:
    res = arms.classify({"B1": _arm(), "A": _arm("PROCESS_EXITED", gpu_lost=True), "B2": _arm()})
    assert "PINNED_MEMORY_EFFECT_REPRODUCED_UNDER_MATCHED_STATE" in res["labels"]
    assert "WAN_ANIMATE_2_LOCAL_EXECUTION_REPRODUCIBLE_WITH_PINNED_MEMORY_DISABLED" in res["labels"]


def test_all_complete_not_reproduced_and_pressure_recorded_separately() -> None:
    res = arms.classify({"B1": _arm(commit_peak=57), "A": _arm(commit_peak=80), "B2": _arm()})
    assert "ORIGINAL_PINNED_MEMORY_FAILURE_NOT_REPRODUCED_UNDER_MATCHED_STATE" in res["labels"]
    assert "PINNED_MEMORY_RESOURCE_PRESSURE_EFFECT_REPRODUCED" in res["labels"]
    assert "PINNED_MEMORY_EFFECT_REPRODUCED_UNDER_MATCHED_STATE" not in res["labels"]
    low = arms.classify({"B1": _arm(commit_peak=57), "A": _arm(commit_peak=60), "B2": _arm()})
    assert "PINNED_MEMORY_RESOURCE_PRESSURE_EFFECT_REPRODUCED" not in low["labels"]


def test_a_clean_failure_is_state_association() -> None:
    res = arms.classify({"B1": _arm(), "A": _arm("EXECUTION_ERROR"), "B2": _arm()})
    assert "PINNED_MEMORY_STATE_ASSOCIATED_WITH_MATERIAL_RUNTIME_DIFFERENCE" in res["labels"]


def test_b2_failure_is_unresolved() -> None:
    res = arms.classify({"B1": _arm(), "A": _arm(), "B2": _arm("EXECUTION_ERROR")})
    assert res["labels"] == ["RUN_TO_RUN_REPRODUCIBILITY_UNRESOLVED"]


def test_severe_a_and_matched_state_stop() -> None:
    sev = arms.classify(
        {"B1": _arm(), "A": _arm("PROCESS_EXITED", severe_system_fault=True), "B2": None}
    )
    assert sev["stopped_early"] and "DIAG_GPU_BOUNDARY" in sev["labels"][0]
    gate = arms.classify({"B1": _arm(), "A": {"matched_state_gate_not_met": True}, "B2": None})
    assert gate["labels"] == ["MATCHED_STATE_GATE_NOT_MET"]


def test_incomplete_has_no_labels() -> None:
    assert arms.classify({"B1": _arm(), "A": None, "B2": None})["labels"] == []


def test_gpu_lost_overrides_a_completed_outcome() -> None:
    """A transient nvidia-smi failure during monitoring, recorded as gpu_lost, must be classified
    GPU_LOSS even if Comfy's own status later reports outcome COMPLETED."""
    compromised = _arm("COMPLETED", gpu_lost=True)
    assert arms.arm_status(compromised) == "GPU_LOSS"
    res = arms.classify({"B1": _arm(), "A": compromised, "B2": _arm()})
    assert "PINNED_MEMORY_EFFECT_REPRODUCED_UNDER_MATCHED_STATE" in res["labels"]


def test_analyze_log_pinned_and_errors() -> None:
    on = arms.analyze_log("Enabled pinned memory 13010.0\n 9/10 [02:10<00:14, 14.5s/it]\n")
    assert on["enabled_pinned_memory_value"] == "13010.0" and on["last_step_seen"] == 9
    off = arms.analyze_log("10/10 [02:26<00:00, 14.6s/it]\nPrompt executed in 163.99 seconds\n")
    assert off["enabled_pinned_memory_line"] is None
    assert off["prompt_executed_seconds"] == 163.99
    assert off["hostbuffer_error"] == off["cuda_error"] == off["traceback"] == 0
    bad = arms.analyze_log("Traceback (most recent call last)\nHostBuffer failed\nCUDA error: x\n")
    assert bad["traceback"] == bad["hostbuffer_error"] == bad["cuda_error"] == 1
