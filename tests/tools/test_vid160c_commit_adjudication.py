"""PR-VID-160C commit-aware adjudication: Windows commit-metric conversion, EX2->EX fallback,
owned-process sampling, the revised two-sample stop rule (commit%, commit-headroom, emergency
physical-RAM floor), the original 0.77 GB-alone-does-not-trigger regression, exactly-one-additional
-submission, no retry, evidence persistence, and owner-only teardown (no GPU, no real Comfy,
no Windows API calls beyond what ctypes structs decode from synthetic bytes)."""

from __future__ import annotations

import argparse
import ctypes
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tools.qualification.vid160c import adjudicate as harness
from tools.qualification.vid160c import win_memory
from tools.qualification.vid160c.telemetry import (
    COMMIT_HEADROOM_ABORT_GB,
    COMMIT_PERCENT_ABORT,
    CONSECUTIVE_SAMPLES,
    EMERGENCY_RAM_GB,
    WARN_RAM_GB,
    CommitAwarePeaks,
    CommitAwareResourceSampler,
)

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only ctypes structures")


# --- Windows commit-metric conversion -------------------------------------------------------------


def test_read_system_commit_converts_pages_to_gb_and_derives_headroom_and_percent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = 4096
    gb_pages = (1024**3) // page

    def fake_get_performance_info(buf_ptr, cb):
        info = ctypes.cast(buf_ptr, ctypes.POINTER(win_memory._PERFORMANCE_INFORMATION)).contents
        info.CommitTotal = 16 * gb_pages
        info.CommitLimit = 64 * gb_pages
        info.CommitPeak = 20 * gb_pages
        info.PhysicalTotal = 32 * gb_pages
        info.PhysicalAvailable = 8 * gb_pages
        info.PageSize = page
        return 1

    monkeypatch.setattr(
        win_memory.ctypes.windll.psapi, "GetPerformanceInfo", fake_get_performance_info
    )

    commit = win_memory.read_system_commit()

    assert commit.commit_total_gb == pytest.approx(16.0, abs=0.01)
    assert commit.commit_limit_gb == pytest.approx(64.0, abs=0.01)
    assert commit.commit_peak_gb == pytest.approx(20.0, abs=0.01)
    assert commit.commit_headroom_gb == pytest.approx(48.0, abs=0.01)  # limit - total
    assert commit.commit_percent == pytest.approx(25.0, abs=0.1)  # 16/64 * 100
    assert commit.physical_total_gb == pytest.approx(32.0, abs=0.01)
    assert commit.physical_available_gb == pytest.approx(8.0, abs=0.01)


def test_read_system_commit_raises_oserror_on_api_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        win_memory.ctypes.windll.psapi, "GetPerformanceInfo", lambda buf_ptr, cb: 0
    )
    with pytest.raises(OSError, match="GetPerformanceInfo failed"):
        win_memory.read_system_commit()


# --- EX2 -> EX fallback ---------------------------------------------------------------------------


def test_read_process_memory_uses_ex2_fields_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gb = 1024**3
    monkeypatch.setattr(win_memory.ctypes.windll.kernel32, "OpenProcess", lambda *a: 12345)
    monkeypatch.setattr(win_memory.ctypes.windll.kernel32, "CloseHandle", lambda h: 1)

    def fake_get_process_memory_info(handle, buf_ptr, cb):
        if cb == ctypes.sizeof(win_memory._PROCESS_MEMORY_COUNTERS_EX2):
            counters = ctypes.cast(
                buf_ptr, ctypes.POINTER(win_memory._PROCESS_MEMORY_COUNTERS_EX2)
            ).contents
            counters.WorkingSetSize = 2 * gb
            counters.PeakWorkingSetSize = 3 * gb
            counters.PrivateUsage = 4 * gb
            counters.PagefileUsage = 4 * gb
            counters.PeakPagefileUsage = 5 * gb
            counters.PrivateWorkingSetSize = int(1.5 * gb)
            counters.SharedCommitUsage = int(0.5 * gb)
            return 1
        return 0  # EX2 unsupported in this fake -- forces the caller to detect via cb size

    monkeypatch.setattr(
        win_memory.ctypes.windll.psapi, "GetProcessMemoryInfo", fake_get_process_memory_info
    )

    mem = win_memory.read_process_memory(999)

    assert mem is not None
    assert mem.working_set_gb == pytest.approx(2.0, abs=0.01)
    assert mem.private_usage_gb == pytest.approx(4.0, abs=0.01)
    assert mem.private_working_set_gb == pytest.approx(1.5, abs=0.01)
    assert mem.shared_commit_gb == pytest.approx(0.5, abs=0.01)


def test_read_process_memory_falls_back_to_ex_when_ex2_call_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gb = 1024**3
    monkeypatch.setattr(win_memory.ctypes.windll.kernel32, "OpenProcess", lambda *a: 12345)
    monkeypatch.setattr(win_memory.ctypes.windll.kernel32, "CloseHandle", lambda h: 1)

    def fake_get_process_memory_info(handle, buf_ptr, cb):
        if cb == ctypes.sizeof(win_memory._PROCESS_MEMORY_COUNTERS_EX2):
            return 0  # EX2 fails entirely (older OS/Python combination)
        counters = ctypes.cast(
            buf_ptr, ctypes.POINTER(win_memory._PROCESS_MEMORY_COUNTERS_EX)
        ).contents
        counters.WorkingSetSize = 2 * gb
        counters.PeakWorkingSetSize = 3 * gb
        counters.PrivateUsage = 4 * gb
        counters.PagefileUsage = 4 * gb
        counters.PeakPagefileUsage = 5 * gb
        return 1

    monkeypatch.setattr(
        win_memory.ctypes.windll.psapi, "GetProcessMemoryInfo", fake_get_process_memory_info
    )

    mem = win_memory.read_process_memory(999)

    assert mem is not None
    assert mem.working_set_gb == pytest.approx(2.0, abs=0.01)
    assert mem.private_working_set_gb is None  # EX2-only field absent on fallback
    assert mem.shared_commit_gb is None


def test_read_process_memory_returns_none_when_process_cannot_be_opened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(win_memory.ctypes.windll.kernel32, "OpenProcess", lambda *a: 0)
    assert win_memory.read_process_memory(999999) is None


# --- revised stop rule: helper to drive the sampler without threads/real APIs --------------------


def _sampler_with_fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    ram_series: list[float],
    commit_series: list[tuple[float, float]] | None = None,  # (commit_total_gb, commit_limit_gb)
) -> CommitAwareResourceSampler:
    sampler = CommitAwareResourceSampler.__new__(CommitAwareResourceSampler)
    sampler.peaks = CommitAwarePeaks()
    sampler._lock = threading.Lock()
    sampler._log = None
    sampler._t0 = 0.0
    sampler._comfy_pid = None

    import tools.qualification.vid160c.telemetry as telemetry_mod

    monkeypatch.setattr(telemetry_mod, "_gpu_sample", lambda: (1000, 50, 100.0, 10))

    ram_iter = iter(ram_series)
    commit_iter = iter(commit_series or [])

    fake_psutil = SimpleNamespace(
        virtual_memory=lambda: SimpleNamespace(available=next(ram_iter) * 1e9),
        swap_memory=lambda: SimpleNamespace(used=0, percent=1.0),
    )
    import sys as _sys

    monkeypatch.setitem(_sys.modules, "psutil", fake_psutil)

    def fake_commit():
        total, limit = next(commit_iter)
        headroom = limit - total
        percent = (total / limit * 100.0) if limit else 0.0
        return SimpleNamespace(
            commit_total_gb=total,
            commit_limit_gb=limit,
            commit_peak_gb=total,
            commit_headroom_gb=headroom,
            commit_percent=percent,
            physical_total_gb=32.0,
            physical_available_gb=0.0,
        )

    if commit_series:
        monkeypatch.setattr(telemetry_mod, "read_system_commit", fake_commit)
    else:
        monkeypatch.setattr(
            telemetry_mod, "read_system_commit", lambda: (_ for _ in ()).throw(OSError())
        )
    return sampler


def test_low_physical_ram_alone_does_not_trigger_the_new_guard_when_commit_headroom_is_healthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression for the exact PR-VID-160C first-run reading: 0.77 GB available physical RAM,
    but commit headroom stays far above the abort floor -- must NOT abort."""

    sampler = _sampler_with_fakes(
        monkeypatch,
        ram_series=[0.98, 0.77, 0.77],
        commit_series=[(16.0, 64.0), (16.5, 64.0), (16.5, 64.0)],  # ~48 GB headroom throughout
    )
    for _ in range(3):
        sampler._sample()
    assert sampler.abort_reason() == ""
    assert sampler.peaks.warn_ram_low_seen is True  # still recorded as a warning
    assert sampler.peaks.ram_available_min_gb == pytest.approx(0.77, abs=0.01)


def test_commit_percent_at_or_above_97_for_two_consecutive_samples_triggers_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sampler = _sampler_with_fakes(
        monkeypatch,
        ram_series=[10.0, 10.0],
        commit_series=[(62.5, 64.0), (63.0, 64.0)],  # 97.66%, 98.44%
    )
    sampler._sample()
    assert sampler.abort_reason() == ""
    sampler._sample()
    reason = sampler.abort_reason()
    assert "system commit" in reason and "97" in reason


def test_commit_headroom_below_1gb_for_two_consecutive_samples_triggers_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Isolate the headroom-only branch: for a commit limit >= ~33 GB, headroom < 1 GB always also
    # implies commit% >= 97% (they become mathematically coupled), so a small synthetic limit is
    # used here specifically to exercise the headroom rule without the percent rule also firing.
    sampler = _sampler_with_fakes(
        monkeypatch,
        ram_series=[10.0, 10.0],
        commit_series=[(19.2, 20.0), (19.25, 20.0)],  # 0.8, 0.75 GB headroom; 96.0%, 96.25%
    )
    sampler._sample()
    sampler._sample()
    reason = sampler.abort_reason()
    assert "commit headroom" in reason


def test_emergency_physical_ram_floor_triggers_independent_of_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sampler = _sampler_with_fakes(
        monkeypatch,
        ram_series=[0.2, 0.1],  # below EMERGENCY_RAM_GB
        commit_series=[(5.0, 64.0), (5.0, 64.0)],  # huge healthy commit headroom
    )
    sampler._sample()
    sampler._sample()
    reason = sampler.abort_reason()
    assert "emergency floor" in reason


def test_frozen_thresholds_match_the_documented_revised_rule() -> None:
    assert WARN_RAM_GB == 1.0  # the original threshold, now a warning only
    assert EMERGENCY_RAM_GB == 0.25
    assert COMMIT_PERCENT_ABORT == 97.0
    assert COMMIT_HEADROOM_ABORT_GB == 1.0
    assert CONSECUTIVE_SAMPLES == 2


# --- exactly-one-additional-submission / no retry / evidence / teardown --------------------------


def test_main_stops_before_building_anything_when_an_external_comfy_is_serving(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    built: list[str] = []
    monkeypatch.setattr(harness, "preflight", lambda: {"endpoint_state": "healthy"})
    monkeypatch.setattr(harness, "run_adjudication", lambda *_a: built.append("ran") or 0)
    assert harness.main(["ref.png", "pose.mp4"]) == 3
    assert built == []
    assert "never adopts or restarts" in capsys.readouterr().out


def test_dry_run_never_calls_run_adjudication(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[str] = []
    monkeypatch.setattr(harness, "preflight", lambda: {"endpoint_state": "free"})
    monkeypatch.setattr(harness, "run_adjudication", lambda *_a: built.append("ran") or 0)
    assert harness.main(["ref.png", "pose.mp4", "--dry"]) == 0
    assert built == []


def test_run_adjudication_calls_the_stack_exactly_once_and_never_retries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(harness, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(harness, "preflight", lambda: {"endpoint_state": "free"})
    monkeypatch.setattr(harness, "_teardown", lambda _stack: (False, []))
    calls: list[str] = []

    def failing_run(stack, args, evidence):
        calls.append("attempt")
        evidence["status"] = "dependency_blocked"
        return 1

    monkeypatch.setattr(harness, "_run_adjudication", failing_run)
    assert (
        harness.run_adjudication(argparse.Namespace(reference_image="ref.png", pose_video="p.mp4"))
        == 1
    )
    assert calls == ["attempt"]
    data = json.loads((tmp_path / "reports" / "evidence.json").read_text(encoding="utf-8"))
    assert data["status"] == "dependency_blocked"


def test_run_adjudication_writes_partial_evidence_and_tears_down_on_exception(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(harness, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(harness, "preflight", lambda: {"endpoint_state": "free"})
    teardown_calls: list[int] = []

    def teardown(_stack):
        teardown_calls.append(1)
        return False, []

    monkeypatch.setattr(harness, "_teardown", teardown)

    def aborting_run(stack, args, evidence):
        evidence["prompt_id"] = "in-flight"
        raise RuntimeError("GPU lost")

    monkeypatch.setattr(harness, "_run_adjudication", aborting_run)
    with pytest.raises(RuntimeError, match="GPU lost"):
        harness.run_adjudication(argparse.Namespace(reference_image="ref.png", pose_video="p.mp4"))
    assert teardown_calls == [1]
    data = json.loads((tmp_path / "reports" / "evidence.json").read_text(encoding="utf-8"))
    assert data["prompt_id"] == "in-flight"
    assert "GPU lost" in data["aborted"]


def test_teardown_stops_only_a_process_this_run_owns() -> None:
    owned_manager = SimpleNamespace(owns_process=True, stop=Mock())
    stack = harness._Stack(manager=owned_manager)
    owned, errors = harness._teardown(stack)
    assert owned is True and errors == []
    owned_manager.stop.assert_called_once()
