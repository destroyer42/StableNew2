"""Deterministic coverage for the PR-IMG-110R qualification tooling (no GPU, no torch)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tools.qualification.img110r import common, orchestrate
from tools.qualification.img110r import verdict as v
from tools.qualification.img110r.caption import (
    FIXED_CAPTION,
    caption_json,
    caption_sha256,
    shape_problems,
)
from tools.qualification.img110r.common import RunRecord, classify_failure

REPO_ROOT = Path(__file__).resolve().parents[2]


def _record(**overrides) -> RunRecord:
    record = RunRecord(
        run_id="L1-x-r1",
        runtime="official-staged",
        family="official",
        level=1,
        width=512,
        height=512,
        preset="V4_TURBO_12",
        steps=12,
        success=True,
        stage="complete",
        output={"valid": True},
        timing={"generate_total_s": 60.0},
    )
    for key, value in overrides.items():
        setattr(record, key, value)
    return record


def test_fixed_caption_is_valid_structured_json_and_stable() -> None:
    assert shape_problems(FIXED_CAPTION) == []
    assert json.loads(caption_json()) == FIXED_CAPTION
    assert ": " not in caption_json()  # compact separators, as the official guide prescribes
    assert caption_sha256() == caption_sha256()
    broken = json.loads(caption_json())
    broken["style_description"]["color_palette"] = ["#2f5d8a"]
    assert any("uppercase" in p for p in shape_problems(broken))
    reordered = {k: FIXED_CAPTION[k] for k in reversed(list(FIXED_CAPTION))}
    assert shape_problems(reordered)


def test_presets_match_the_documented_official_values_and_diffusers_order() -> None:
    assert {k: (s, len(g), mu, std) for k, (s, g, mu, std) in common.PRESETS.items()} == {
        "V4_QUALITY_48": (48, 48, 0.0, 1.5),
        "V4_DEFAULT_20": (20, 20, 0.0, 1.75),
        "V4_TURBO_12": (12, 12, 0.5, 1.75),
    }
    turbo = common.diffusers_guidance("V4_TURBO_12")
    assert turbo[:11] == [7.0] * 11 and turbo[11] == 3.0  # first step first; polish step last
    assert common.PRESETS["V4_TURBO_12"][1][0] == 3.0  # official order: index 0 is the last step
    assert [level.pixels for level in common.LEVELS.values()] == [262144, 786432, 1048576, 1048576]


def test_gpu_query_rows_parse() -> None:
    sample = common.parse_gpu_line("11690, 12282, 71, 268.4, 2535, 100, 0x0000000000000004")
    assert (sample.vram_used_mib, sample.vram_total_mib, sample.temp_c) == (11690, 12282, 71)
    assert sample.throttle == 4 and sample.util_pct == 100


def test_run_record_round_trips(tmp_path: Path) -> None:
    record = _record(fault_events=[{"provider": "nvlddmkm", "id": 153}])
    path = tmp_path / "r.json"
    record.write(path)
    assert RunRecord.read(path) == record


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, "success"),
        (
            {
                "success": False,
                "exception_type": "OutOfMemoryError",
                "exception": "CUDA out of memory",
            },
            "resource_exhaustion",
        ),
        (
            {
                "success": False,
                "exception_type": "RuntimeError",
                "exception": "CUBLAS_STATUS_NOT_SUPPORTED",
            },
            "dtype_kernel_driver",
        ),
        (
            {
                "success": False,
                "exception_type": "AcceleratorError",
                "exception": "CUDA error: illegal memory access",
            },
            "dtype_kernel_driver",
        ),
        (
            {
                "success": False,
                "exception_type": "RuntimeError",
                "exception": "unexpected keys after load",
            },
            "acquisition_schema",
        ),
        (
            {"success": False, "timed_out": True, "stage": "loading", "exception_type": "Timeout"},
            "no_progress_timeout",
        ),
        (
            {
                "success": False,
                "timed_out": True,
                "stage": "denoising",
                "exception_type": "Timeout",
            },
            "performance_only",
        ),
        ({"success": False, "stage": "started"}, "machine_fault"),
        (
            {"success": False, "exception_type": "ValueError", "exception": "something odd"},
            "unclassified",
        ),
    ],
)
def test_failures_are_classified_by_root_cause_class(overrides: dict, expected: str) -> None:
    assert classify_failure(_record(**overrides)) == expected


def test_only_cuda_faults_poison_the_context_not_plain_oom() -> None:
    assert common.is_context_poisoning("RuntimeError", "CUDA error: an illegal memory access")
    assert not common.is_context_poisoning(
        "OutOfMemoryError", "CUDA out of memory. Tried to allocate"
    )


def _fail(family: str, level: int, klass: str, stage: str = "denoising") -> RunRecord:
    return _record(
        family=family,
        runtime=f"{family}-x",
        level=level,
        success=False,
        output={},
        stage=stage,
        classification=klass,
    )


def test_verdict_practical_requires_a_large_fast_reproduced_success() -> None:
    big = {
        "runtime": "official-as-shipped",
        "level": 2,
        "width": 768,
        "height": 1024,
        "timing": {"generate_total_s": 120.0},
        "classification": "success",
    }
    once = [_record(**big)]
    assert v.decide(once).model_on_hardware == v.PASS_CONSTRAINED
    twice = [_record(**big), _record(run_id="L2-x-r2", **big)]
    assert v.decide(twice).model_on_hardware == v.PASS_PRACTICAL
    slow = {**big, "timing": {"generate_total_s": 900.0}}
    assert (
        v.decide([_record(**slow), _record(run_id="r2", **slow)]).model_on_hardware
        == v.PASS_CONSTRAINED
    )


def test_success_that_needs_an_explicit_residency_policy_is_constrained_not_practical() -> None:
    staged = {
        "runtime": "official-staged-swap",
        "level": 2,
        "width": 768,
        "height": 1024,
        "timing": {"generate_total_s": 60.0},
        "classification": "success",
    }
    records = [_record(**staged), _record(run_id="L2-x-r2", **staged)]
    verdict = v.decide(records)
    assert verdict.model_on_hardware == v.PASS_CONSTRAINED
    assert "explicit residency policy" in verdict.reasons[-1]


def test_verdict_separates_model_on_hardware_from_the_diffusers_path() -> None:
    records = [_record(classification="success"), _fail("diffusers", 1, "dtype_kernel_driver")]
    verdict = v.decide(records)
    assert verdict.model_on_hardware == v.PASS_CONSTRAINED
    assert verdict.diffusers_path == v.SOFTWARE_NO_GO


def test_hardware_no_go_needs_both_families_and_reproduced_exhaustion() -> None:
    one_family = [_fail("official", 1, "resource_exhaustion")] * 2
    assert v.decide(one_family).model_on_hardware == v.INCONCLUSIVE
    both = one_family + [_fail("diffusers", 1, "resource_exhaustion")] * 2
    assert v.decide(both).model_on_hardware == v.HARDWARE_NO_GO
    single = [
        _fail("official", 1, "resource_exhaustion"),
        _fail("diffusers", 1, "resource_exhaustion"),
    ]
    assert v.decide(single).model_on_hardware == v.INCONCLUSIVE


def test_driver_stack_no_go_needs_repeated_official_path_faults() -> None:
    faults = [_fail("official", 1, "dtype_kernel_driver")] * 2
    assert v.decide(faults).model_on_hardware == v.DRIVER_NO_GO
    assert v.decide(faults[:1]).model_on_hardware == v.INCONCLUSIVE


def test_preflight_refuses_unfinished_or_poisoned_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        orchestrate, "query_gpu", lambda: common.parse_gpu_line("900, 12282, 40, 30.0, 210, 0, 0x1")
    )
    monkeypatch.setattr(orchestrate, "_boot_time", lambda: 1000.0)
    assert orchestrate.preflight(tmp_path, acknowledge_crash=False)["vram_total_mib"] == 12282
    orchestrate._save_state(tmp_path, {"in_flight": "L1-x-r1", "boot_time": 1000.0})
    with pytest.raises(SystemExit, match="never finished"):
        orchestrate.preflight(tmp_path, acknowledge_crash=False)
    orchestrate._save_state(tmp_path, {"reboot_required": True, "boot_time": 1000.0})
    with pytest.raises(SystemExit, match="reboot"):
        orchestrate.preflight(tmp_path, acknowledge_crash=False)
    monkeypatch.setattr(orchestrate, "_boot_time", lambda: 2000.0)  # machine rebooted since
    assert orchestrate.preflight(tmp_path, acknowledge_crash=False)


def test_runtimes_map_to_the_right_environment_and_run_ids_increment(tmp_path: Path) -> None:
    assert orchestrate.RUNTIMES["official-staged"]["env"] == "venv-ref"
    assert orchestrate.RUNTIMES["official-staged-swap"]["args"] == ["--mode", "staged_swap"]
    assert orchestrate.RUNTIMES["diffusers-cpu-offload"]["env"] == "venv-dfz"
    assert orchestrate._next_run_id(tmp_path, "official-staged", 2, "") == "L2-official-staged-r1"
    (tmp_path / "L2-official-staged-r1.json").write_text("{}", encoding="utf-8")
    assert orchestrate._next_run_id(tmp_path, "official-staged", 2, "") == "L2-official-staged-r2"


def test_qualification_code_never_reaches_production_source() -> None:
    """No production Diffusers/Ideogram backend: ``src/`` must not know these tools or models."""

    pattern = re.compile(r"ideogram4|Ideogram4Pipeline|img110r|ideogram-4", re.IGNORECASE)
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in (REPO_ROOT / "src").rglob("*.py")
        if pattern.search(path.read_text(encoding="utf-8", errors="ignore"))
    ]
    assert offenders == []
