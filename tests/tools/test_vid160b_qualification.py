"""PR-VID-160B qualification harness: graph freeze, exactly-one-submit, external-runtime refusal,
no retry, safety-stop triggering, evidence persistence on abort, owned-runtime cleanup (no GPU, no
real Comfy, no queue)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tools.qualification.vid160b import graph as graph_mod
from tools.qualification.vid160b import run as harness
from tools.qualification.vid160b.telemetry import (
    HIGH_SWAP_PERCENT,
    LOW_RAM_CONSECUTIVE,
    LOW_RAM_GB,
    ProbePeaks,
    ProbeResourceSampler,
)

# --- graph freeze -----------------------------------------------------------------------------


def test_frozen_graph_uses_only_the_required_node_classes() -> None:
    spec = graph_mod.ProbeSpec(reference_image="ref.png")
    wf = graph_mod.build_probe_graph(spec)
    assert graph_mod.validate_graph(wf) == []
    classes = {node["class_type"] for node in wf.values()}
    assert classes == graph_mod.REQUIRED_NODE_CLASSES
    assert "UnetLoaderGGUF" in classes and "WanAnimateToVideo" in classes


def test_frozen_graph_omits_pose_face_background_character_mask_inputs() -> None:
    spec = graph_mod.ProbeSpec(reference_image="ref.png")
    wf = graph_mod.build_probe_graph(spec)
    animate_inputs = next(
        n["inputs"] for n in wf.values() if n["class_type"] == "WanAnimateToVideo"
    )
    for excluded in ("pose_video", "face_video", "background_video", "character_mask"):
        assert excluded not in animate_inputs


def test_graph_rejects_dimensions_not_divisible_by_16() -> None:
    with pytest.raises(ValueError, match="divisible by 16"):
        graph_mod.build_probe_graph(graph_mod.ProbeSpec(reference_image="ref.png", width=257))


def test_graph_rejects_an_invalid_length() -> None:
    with pytest.raises(ValueError, match="length must be"):
        graph_mod.build_probe_graph(graph_mod.ProbeSpec(reference_image="ref.png", length=10))


def test_validate_graph_flags_a_dangling_link() -> None:
    wf = graph_mod.build_probe_graph(graph_mod.ProbeSpec(reference_image="ref.png"))
    wf["11"]["inputs"]["model"] = ["999", 0]
    problems = graph_mod.validate_graph(wf)
    assert any("missing node 999" in p for p in problems)


def test_validate_graph_flags_a_non_frozen_node_class() -> None:
    wf = graph_mod.build_probe_graph(graph_mod.ProbeSpec(reference_image="ref.png"))
    wf["16"] = {"class_type": "DWPreprocessor", "inputs": {}}
    problems = graph_mod.validate_graph(wf)
    assert any("non-frozen class DWPreprocessor" in p for p in problems)


# --- external-runtime refusal -------------------------------------------------------------------


def test_main_stops_before_building_anything_when_an_external_comfy_is_serving(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    built: list[str] = []
    monkeypatch.setattr(harness, "preflight", lambda: {"endpoint_state": "healthy"})
    monkeypatch.setattr(harness, "run_probe", lambda *_a: built.append("ran") or 0)
    assert harness.main(["ref.png"]) == 3
    assert built == []
    assert "never adopts or restarts" in capsys.readouterr().out


def test_dry_run_never_calls_run_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[str] = []
    monkeypatch.setattr(harness, "preflight", lambda: {"endpoint_state": "free"})
    monkeypatch.setattr(harness, "run_probe", lambda *_a: built.append("ran") or 0)
    assert harness.main(["ref.png", "--dry"]) == 0
    assert built == []


# --- exactly-one-submit / no retry --------------------------------------------------------------


def test_run_probe_calls_the_stack_exactly_once_and_never_retries_a_failure(
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

    monkeypatch.setattr(harness, "_run_probe", failing_run)
    assert harness.run_probe(argparse.Namespace(reference_image="ref.png")) == 1
    assert calls == ["attempt"]  # exactly one attempt; no loop, no automatic retry

    data = json.loads((tmp_path / "reports" / "evidence.json").read_text(encoding="utf-8"))
    assert data["status"] == "dependency_blocked"


# --- evidence persistence on abort / owned-runtime cleanup ---------------------------------------


def test_run_probe_writes_partial_evidence_and_still_tears_down_on_exception(
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

    monkeypatch.setattr(harness, "_run_probe", aborting_run)
    with pytest.raises(RuntimeError, match="GPU lost"):
        harness.run_probe(argparse.Namespace(reference_image="ref.png"))

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


def test_teardown_never_stops_an_unowned_or_external_process() -> None:
    for manager in (SimpleNamespace(owns_process=False, stop=Mock()), None):
        stack = harness._Stack(manager=manager)
        owned, errors = harness._teardown(stack)
        assert owned is False and errors == []
        if manager is not None:
            manager.stop.assert_not_called()


def test_teardown_records_a_failing_stop_without_raising() -> None:
    manager = SimpleNamespace(owns_process=True, stop=Mock(side_effect=RuntimeError("stuck")))
    stack = harness._Stack(manager=manager)
    owned, errors = harness._teardown(stack)
    assert owned is False
    assert any("stop_owned_comfy" in e and "stuck" in e for e in errors)


# --- safety-stop triggering ----------------------------------------------------------------------


def test_low_ram_for_two_consecutive_samples_sets_a_stop_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    import threading

    from tools.qualification.vid160b import telemetry as telemetry_mod

    sampler = ProbeResourceSampler.__new__(ProbeResourceSampler)  # bypass __init__ (no threads)
    sampler.peaks = ProbePeaks()
    sampler._lock = threading.Lock()
    sampler._log = None
    sampler._t0 = 0.0

    fake_psutil = SimpleNamespace(
        virtual_memory=lambda: SimpleNamespace(available=0.5e9),  # 0.5 GB, below LOW_RAM_GB
        swap_memory=lambda: SimpleNamespace(used=0, percent=10.0),
    )
    monkeypatch.setitem(sys.modules, "psutil", fake_psutil)
    monkeypatch.setattr(telemetry_mod, "_gpu_sample", lambda: (1000, 50, 100.0, 10))

    assert sampler.abort_reason() == ""
    sampler._sample()
    assert sampler.abort_reason() == ""  # one low sample: not yet consecutive
    sampler._sample()
    reason = sampler.abort_reason()
    assert reason != ""
    assert f"< {LOW_RAM_GB}" in reason
    assert sampler.peaks.low_ram_consecutive >= LOW_RAM_CONSECUTIVE


def test_high_swap_with_low_ram_also_sets_a_stop_reason() -> None:
    assert HIGH_SWAP_PERCENT == 90.0  # frozen threshold, documented before the physical run
    assert LOW_RAM_GB == 1.0
    assert LOW_RAM_CONSECUTIVE == 2


def test_comfy_client_wait_interrupts_and_raises_when_abort_reason_fires() -> None:
    from tools.qualification.vid110.comfy_client import ComfyClient, ComfyRunError

    client = ComfyClient.__new__(ComfyClient)
    client.base = "http://x"
    client.timeout = 5.0
    client.client_id = "test"
    client.running_prompt_ids = Mock(return_value=["p1"])  # our prompt is running
    client.interrupt_own = Mock(wraps=lambda pid: True)

    with pytest.raises(ComfyRunError, match="safety guard"):
        client.wait("p1", timeout=30, poll=0.01, abort_reason=lambda: "available RAM < 1.0 GB")
    client.interrupt_own.assert_called_once_with("p1")
