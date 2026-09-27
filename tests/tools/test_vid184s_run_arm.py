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


def test_no_repeat_attempt_after_a_matched_state_gate_miss(_tmp_root: Path) -> None:
    """A gate miss writes arm_record.json without SUBMITTED.marker (no submission occurred);
    that must still block a repeat attempt at the same arm."""
    _write_record(_tmp_root, "B1", outcome="COMPLETED", peaks={"commit_peak_percent": 50})
    (_tmp_root / "reference_state.json").write_text("{}")
    assert not (_tmp_root / "A" / "SUBMITTED.marker").exists()
    _write_record(_tmp_root, "A", matched_state_gate_not_met=True)
    fails = run_arm.sequence_failures("A")
    assert any("A" in f and "no repeat attempt is authorized" in f for f in fails)


def test_lock_frozen_bands_writes_once_and_flags_mismatch(_tmp_root: Path) -> None:
    assert run_arm.lock_frozen_bands() is None
    saved = json.loads((_tmp_root / "frozen_bands.json").read_text())
    assert saved == run_arm.frozen_bands()
    # Second call with unchanged constants: still no mismatch, file untouched.
    assert run_arm.lock_frozen_bands() is None

    tampered = {**saved, "commit_percent_points": 999.0}
    (_tmp_root / "frozen_bands.json").write_text(json.dumps(tampered))
    mismatch = run_arm.lock_frozen_bands()
    assert mismatch is not None and "differs" in mismatch
    # Must not silently overwrite the tampered/mismatched file with the current constants.
    assert json.loads((_tmp_root / "frozen_bands.json").read_text()) == tampered


def test_events_since_drops_pre_submit_events_keeps_unparseable() -> None:
    submit = 1790504626.0  # seconds
    before = {"TimeCreated": "/Date(1790504620000)/", "Id": 1, "ProviderName": "Boot"}
    after = {"TimeCreated": "/Date(1790504630000)/", "Id": 41, "ProviderName": "Kernel-Power"}
    unparseable = {"TimeCreated": "not-a-date", "Id": 6008, "ProviderName": "EventLog"}
    kept = run_arm._events_since([before, after, unparseable], submit)
    assert kept == [after, unparseable]

    # Singleton PowerShell object (bare dict) is normalized before filtering, not dropped.
    assert run_arm._events_since(after, submit) == [after]
    assert run_arm._events_since(before, submit) == []


def test_classify_events_whea_is_severe() -> None:
    events = [{"Id": 17, "ProviderName": "Microsoft-Windows-WHEA-Logger"}]
    assert run_arm._classify_events(events) == (True, False)


def test_classify_events_nvlddmkm_provider_is_gpu_lost() -> None:
    events = [{"Id": 14, "ProviderName": "nvlddmkm"}]
    assert run_arm._classify_events(events) == (False, True)


def test_classify_events_driver_tdr_4101_is_gpu_lost() -> None:
    events = [{"Id": 4101, "ProviderName": "Display"}]
    assert run_arm._classify_events(events) == (False, True)


def test_classify_events_unexpected_shutdown_41_and_6008_are_severe() -> None:
    assert run_arm._classify_events([{"Id": 41, "ProviderName": "Microsoft-Windows-Kernel-Power"}]) == (
        True, False,
    )  # fmt: skip
    assert run_arm._classify_events([{"Id": 6008, "ProviderName": "EventLog"}]) == (True, False)


def test_classify_events_generic_informational_ids_are_noise() -> None:
    events = [
        {"Id": 1, "ProviderName": "Microsoft-Windows-IsolatedUserMode"},
        {"Id": 153, "ProviderName": "Disk"},
        {"Id": 157, "ProviderName": "Disk"},
    ]
    assert run_arm._classify_events(events) == (False, False)


def test_build_record_uses_event_classification_for_severe_and_gpu_lost() -> None:
    gate = {"boot_time": "t", "minutes_since_boot": 1.0}
    tdr = run_arm.build_record(
        "A", gate,
        {"outcome": "COMPLETED", "gpu_query_failed": False, "final_log": {},
         "events_since_submit": [{"Id": 4101, "ProviderName": "Display"}]},
    )  # fmt: skip
    assert tdr["gpu_lost"] is True
    assert tdr["severe_system_fault"] is False

    reboot = run_arm.build_record(
        "A", gate,
        {"outcome": "PROCESS_EXITED", "gpu_query_failed": False, "final_log": {},
         "events_since_submit": [{"Id": 41, "ProviderName": "Microsoft-Windows-Kernel-Power"}]},
    )  # fmt: skip
    assert reboot["severe_system_fault"] is True


def test_build_record_survives_a_singleton_powershell_event_object() -> None:
    """ConvertTo-Json emits a bare object, not a one-element array, for exactly one match --
    build_record must not raise when events_since_submit is that bare dict."""
    gate = {"boot_time": "t", "minutes_since_boot": 1.0}
    singleton = run_arm.build_record(
        "A", gate,
        {"outcome": "COMPLETED", "events_since_submit": {"TimeCreated": "x", "Id": 1,
                                                           "ProviderName": "Microsoft-Windows-Kernel-Power"}},
    )  # fmt: skip
    assert singleton["severe_system_fault"] is False

    whea_singleton = run_arm.build_record(
        "A", gate,
        {"outcome": "COMPLETED", "events_since_submit": {"TimeCreated": "x", "Id": 1,
                                                           "ProviderName": "Microsoft-Windows-WHEA-Logger"}},
    )  # fmt: skip
    assert whea_singleton["severe_system_fault"] is True
