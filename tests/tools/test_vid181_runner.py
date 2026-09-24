"""PR-VID-181 Animate runner: only A/B runnable, frozen control hashes enforced before anything
starts, frozen 480x832 spec identical to PR-VID-175/180 (pose_video present, face_video absent),
A/B differ only by pose asset, exactly one submission, no retry, external-Comfy refusal,
owner-only teardown, evidence persistence on abort (no GPU, no real Comfy)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tools.qualification.vid170.graph import CharacterizationSpec, build_characterization_graph
from tools.qualification.vid181 import run as harness


def test_only_a_and_b_are_runnable_and_case_c_is_rejected() -> None:
    assert harness.CASES == ["A", "B"]
    with pytest.raises(SystemExit):
        harness.main(["ref.png", "--case", "C"])
    with pytest.raises(ValueError, match="unknown case"):
        harness.verify_control("C")


def test_frozen_control_hashes_are_pinned() -> None:
    assert harness.CONTROLS["A"]["sha256"].startswith("96705f92")
    assert harness.CONTROLS["B"]["sha256"].startswith("b685a39d")
    assert harness.case_reports_dir("A") != harness.case_reports_dir("B")


def test_verify_control_refuses_a_hash_mismatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = {"A": {"workspace": "a.mp4", "staged": str(tmp_path / "staged_a.mp4"), "sha256": "0" * 64}}
    monkeypatch.setattr(harness, "CONTROLS", fake)
    (tmp_path / "a.mp4").write_bytes(b"not the frozen control")
    with pytest.raises(RuntimeError, match="hash mismatch"):
        harness.verify_control("A", workspace=tmp_path)


def test_verify_control_stages_and_accepts_the_exact_frozen_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    payload = b"frozen control bytes"
    import hashlib

    fake = {
        "B": {
            "workspace": "b.mp4",
            "staged": str(tmp_path / "staged" / "b.mp4"),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    }
    monkeypatch.setattr(harness, "CONTROLS", fake)
    (tmp_path / "b.mp4").write_bytes(payload)
    staged = harness.verify_control("B", workspace=tmp_path)
    assert staged.read_bytes() == payload


def test_verify_control_reports_a_missing_frozen_control(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = {"A": {"workspace": "missing.mp4", "staged": str(tmp_path / "s.mp4"), "sha256": "0" * 64}}
    monkeypatch.setattr(harness, "CONTROLS", fake)
    with pytest.raises(RuntimeError, match="frozen control missing"):
        harness.verify_control("A", workspace=tmp_path)


def test_spec_is_the_frozen_animate_configuration_without_face_video() -> None:
    spec_a = CharacterizationSpec(
        reference_image="ref.png", pose_video_file="a.mp4", width=harness.WIDTH, height=harness.HEIGHT
    )
    spec_b = CharacterizationSpec(
        reference_image="ref.png", pose_video_file="b.mp4", width=harness.WIDTH, height=harness.HEIGHT
    )
    assert (spec_a.width, spec_a.height, spec_a.length, spec_a.fps) == (480, 832, 13, 8.0)
    assert (spec_a.steps, spec_a.cfg, spec_a.shift) == (20, 1.0, 5.0)
    assert (spec_a.sampler, spec_a.scheduler, spec_a.seed) == ("uni_pc", "simple", 1733123036)
    graph_a, graph_b = build_characterization_graph(spec_a), build_characterization_graph(spec_b)
    for node_id in graph_a:
        a_in, b_in = dict(graph_a[node_id]["inputs"]), dict(graph_b[node_id]["inputs"])
        a_in.pop("file", None)
        b_in.pop("file", None)
        assert a_in == b_in, node_id
    animate = next(n["inputs"] for n in graph_a.values() if n["class_type"] == "WanAnimateToVideo")
    assert animate["pose_video"] == ["17", 0] and "face_video" not in animate


def test_main_stops_when_an_external_comfy_is_serving(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ran: list[str] = []
    monkeypatch.setattr(harness, "preflight", lambda: {"endpoint_state": "healthy"})
    monkeypatch.setattr(harness, "run_case", lambda *_a: ran.append("x") or 0)
    assert harness.main(["ref.png", "--case", "A"]) == 3
    assert ran == [] and "never adopts or restarts" in capsys.readouterr().out


def test_run_case_submits_once_never_retries_and_persists_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(harness, "REPORTS_ROOT", tmp_path / "reports")
    monkeypatch.setattr(harness, "preflight", lambda: {"endpoint_state": "free"})
    monkeypatch.setattr(harness, "_teardown", lambda _s: (False, []))
    calls: list[str] = []

    def failing(stack, args, evidence, reports):
        calls.append("attempt")
        evidence["status"] = "dependency_blocked"
        return 1

    monkeypatch.setattr(harness, "_run_case", failing)
    assert harness.run_case(argparse.Namespace(reference_image="r.png", case="A")) == 1
    assert calls == ["attempt"]
    data = json.loads((tmp_path / "reports" / "run_a" / "evidence.json").read_text(encoding="utf-8"))
    assert data["status"] == "dependency_blocked"


def test_run_case_tears_down_and_keeps_partial_evidence_on_exception(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(harness, "REPORTS_ROOT", tmp_path / "reports")
    monkeypatch.setattr(harness, "preflight", lambda: {"endpoint_state": "free"})
    torn: list[int] = []
    monkeypatch.setattr(harness, "_teardown", lambda _s: torn.append(1) or (False, []))

    def aborting(stack, args, evidence, reports):
        evidence["prompt_id"] = "in-flight"
        raise RuntimeError("GPU lost")

    monkeypatch.setattr(harness, "_run_case", aborting)
    with pytest.raises(RuntimeError, match="GPU lost"):
        harness.run_case(argparse.Namespace(reference_image="r.png", case="B"))
    assert torn == [1]
    data = json.loads((tmp_path / "reports" / "run_b" / "evidence.json").read_text(encoding="utf-8"))
    assert data["prompt_id"] == "in-flight" and "GPU lost" in data["aborted"]


def test_teardown_is_owner_only() -> None:
    owned = SimpleNamespace(owns_process=True, stop=Mock())
    assert harness._teardown(harness._Stack(manager=owned)) == (True, [])
    owned.stop.assert_called_once()
    external = SimpleNamespace(owns_process=False, stop=Mock())
    assert harness._teardown(harness._Stack(manager=external)) == (False, [])
    external.stop.assert_not_called()


def test_commit_aware_thresholds_are_unchanged() -> None:
    from tools.qualification.vid160c.telemetry import (
        COMMIT_HEADROOM_ABORT_GB,
        COMMIT_PERCENT_ABORT,
        CONSECUTIVE_SAMPLES,
        EMERGENCY_RAM_GB,
    )

    assert (COMMIT_PERCENT_ABORT, COMMIT_HEADROOM_ABORT_GB) == (97.0, 1.0)
    assert (EMERGENCY_RAM_GB, CONSECUTIVE_SAMPLES) == (0.25, 2)
