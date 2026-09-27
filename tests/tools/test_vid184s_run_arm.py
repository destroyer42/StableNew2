"""PR-VID-184S: sequencing/safety-protocol and GPU-loss-vs-clean-failure regression tests for
``run_arm.py`` (no GPU; pure functions against a temp evidence root)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.qualification.vid184s import run_arm


@pytest.fixture(autouse=True)
def _tmp_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(run_arm, "ROOT", tmp_path)
    return tmp_path


def _write_record(root: Path, arm: str, **fields: object) -> None:
    d = root / arm
    d.mkdir(parents=True, exist_ok=True)
    (d / "arm_record.json").write_text(json.dumps(fields))


def test_a_requires_b1_completed(_tmp_root: Path) -> None:
    fails = run_arm.sequence_failures("A")
    assert "B1 has not been run: order is B1 -> A -> B2" in fails
    _write_record(_tmp_root, "B1", outcome="EXECUTION_ERROR", gpu_lost=False)
    (_tmp_root / "reference_state.json").write_text("{}")
    fails = run_arm.sequence_failures("A")
    assert any("B1" in f and "stop before A" in f for f in fails)


def test_a_gpu_loss_or_clean_fail_does_not_block_b2(_tmp_root: Path) -> None:
    _write_record(_tmp_root, "B1", outcome="COMPLETED", peaks={"commit_peak_percent": 50})
    (_tmp_root / "reference_state.json").write_text("{}")
    for status_kwargs in (
        {"outcome": "PROCESS_EXITED", "gpu_lost": True},
        {"outcome": "EXECUTION_ERROR"},
    ):
        _write_record(_tmp_root, "A", **status_kwargs)
        assert run_arm.sequence_failures("B2") == []


def test_a_severe_fault_blocks_b2(_tmp_root: Path) -> None:
    _write_record(_tmp_root, "B1", outcome="COMPLETED", peaks={"commit_peak_percent": 50})
    (_tmp_root / "reference_state.json").write_text("{}")
    _write_record(_tmp_root, "A", outcome="PROCESS_EXITED", severe_system_fault=True)
    fails = run_arm.sequence_failures("B2")
    assert any("A" in f and "stop before B2" in f for f in fails)


def test_matched_state_gate_miss_blocks_next_arm(_tmp_root: Path) -> None:
    _write_record(_tmp_root, "B1", outcome="COMPLETED", peaks={"commit_peak_percent": 50})
    (_tmp_root / "reference_state.json").write_text("{}")
    _write_record(_tmp_root, "A", matched_state_gate_not_met=True)
    fails = run_arm.sequence_failures("B2")
    assert any("A" in f and "stop before B2" in f for f in fails)


def test_no_retry_after_submission(_tmp_root: Path) -> None:
    (_tmp_root / "B1").mkdir(parents=True)
    (_tmp_root / "B1" / "SUBMITTED.marker").write_text("1")
    assert "B1 already submitted: no retry is authorized" in run_arm.sequence_failures("B1")


def test_build_record_distinguishes_clean_failure_from_gpu_loss() -> None:
    gate = {"boot_time": "t", "minutes_since_boot": 1.0}
    clean = run_arm.build_record(
        "A", gate,
        {"outcome": "EXECUTION_ERROR", "gpu_query_failed": False,
         "final_log": {"cuda_error": 1, "hostbuffer_error": 1, "gpu_lost": 0}},
    )  # fmt: skip
    assert clean["gpu_lost"] is False

    real_loss_via_query = run_arm.build_record(
        "A", gate, {"outcome": "PROCESS_EXITED", "gpu_query_failed": True, "final_log": {}}
    )
    assert real_loss_via_query["gpu_lost"] is True

    real_loss_via_signature = run_arm.build_record(
        "A", gate,
        {"outcome": "PROCESS_EXITED", "gpu_query_failed": False, "final_log": {"gpu_lost": 1}},
    )  # fmt: skip
    assert real_loss_via_signature["gpu_lost"] is True
