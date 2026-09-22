"""PR-VID-150 qualification harness: case planning, seed/prompt preservation, no accidental retry,
stop-on-failure and evidence serialization (no GPU, no Comfy, no queue)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from tools.qualification.vid150 import run as harness


def _args(case: str, source: str = "s.png", seed: int = 1733123036) -> argparse.Namespace:
    return argparse.Namespace(source=source, case=case, seed=seed, dry=False)


def test_exactly_three_cases_only_the_prompt_differs() -> None:
    assert set(harness.CASES) == {"A", "B", "C"}
    assert all(isinstance(prompt, str) and prompt for prompt in harness.CASES.values())
    forms = {case: harness.form_data_for(case, 1733123036) for case in harness.CASES}
    constant_keys = {"workflow_id", "workflow_version", "negative_prompt", "seed", "experimental_opt_in"}
    for key in constant_keys:
        assert len({forms[case][key] for case in forms}) == 1, key
    assert len({forms[case]["prompt"] for case in forms}) == 3


def test_form_data_freezes_the_requested_seed_as_a_string() -> None:
    form = harness.form_data_for("B", 1733123036)
    assert form["seed"] == "1733123036"
    assert form["prompt"] == harness.CASES["B"]


def test_form_data_rejects_an_unknown_case() -> None:
    with pytest.raises(ValueError, match="unknown case"):
        harness.form_data_for("D", 1733123036)


def test_case_reports_dir_is_distinct_per_case() -> None:
    dirs = {case: harness.case_reports_dir(case) for case in harness.CASES}
    assert len(set(dirs.values())) == 3
    assert all(d.parent == harness.REPORTS_ROOT for d in dirs.values())


def test_main_stops_before_building_anything_when_an_external_comfy_is_serving(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    built: list[str] = []
    monkeypatch.setattr(harness, "preflight", lambda: {"endpoint_state": "healthy"})
    monkeypatch.setattr(harness, "run_case", lambda *_a: built.append("ran") or 0)
    assert harness.main(["s.png", "--case", "A"]) == 3
    assert built == []  # no stack, no launch, nothing stopped
    assert "never adopts or restarts" in capsys.readouterr().out


def test_dry_run_never_calls_run_case(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[str] = []
    monkeypatch.setattr(harness, "preflight", lambda: {"endpoint_state": "free"})
    monkeypatch.setattr(harness, "run_case", lambda *_a: built.append("ran") or 0)
    assert harness.main(["s.png", "--case", "B", "--dry"]) == 0
    assert built == []


def test_run_case_calls_the_stack_exactly_once_and_never_retries_a_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(harness, "REPORTS_ROOT", tmp_path / "reports")
    monkeypatch.setattr(harness, "preflight", lambda: {"endpoint_state": "free"})
    monkeypatch.setattr(harness, "_teardown", lambda _stack: (False, []))
    calls: list[str] = []

    def failing_run_case(stack, args, evidence, workspace, reports):
        calls.append(args.case)
        evidence["status"] = "failed"
        return 1

    monkeypatch.setattr(harness, "_run_case", failing_run_case)
    assert harness.run_case(_args("C")) == 1
    assert calls == ["C"]  # exactly one attempt; no loop, no automatic retry

    evidence_path = harness.case_reports_dir("C") / "evidence.json"
    data = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert data["status"] == "failed"


def test_run_case_writes_partial_evidence_and_still_tears_down_on_exception(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(harness, "REPORTS_ROOT", tmp_path / "reports")
    monkeypatch.setattr(harness, "preflight", lambda: {"endpoint_state": "free"})
    teardown_calls: list[int] = []

    def teardown(_stack):
        teardown_calls.append(1)
        return False, []

    monkeypatch.setattr(harness, "_teardown", teardown)

    def aborting_run_case(stack, args, evidence, workspace, reports):
        evidence["job_id"] = "in-flight"
        raise RuntimeError("GPU lost")

    monkeypatch.setattr(harness, "_run_case", aborting_run_case)
    with pytest.raises(RuntimeError, match="GPU lost"):
        harness.run_case(_args("A"))

    assert teardown_calls == [1]
    data = json.loads((harness.case_reports_dir("A") / "evidence.json").read_text(encoding="utf-8"))
    assert data["job_id"] == "in-flight"
    assert "GPU lost" in data["aborted"]
