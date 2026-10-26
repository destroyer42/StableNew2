"""PR-AI-QUAL-114E: the Stage A report refuses retrospective findings until the stopped capture's analysis supports them."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tests.tools.test_ai114_stage_a_report import D12A, MODELS, _evidence  # noqa: E402
from tools.qualification.ai111 import stage_a_report as report  # noqa: E402

CAPTURE_ID = "20261025T190000Z-0a1b2c3d"


def _retrospective(tmp_path: Path, **monitoring: Any) -> Path:
    evidence = _evidence(tmp_path)
    result = json.loads((evidence / "result.json").read_text(encoding="utf-8"))
    result["monitoring"] = {
        "violations": [],
        "channel_coverage": {
            "connections": ["retrospective_capture"],
            "files": ["retrospective_capture"],
        },
        "mode": "retrospective_capture",
        "capture_id": CAPTURE_ID,
        "capture_analysis_required": True,
        **monitoring,
    }
    (evidence / "result.json").write_text(json.dumps(result), encoding="utf-8")
    return evidence


def _analysis(**override: Any) -> dict[str, Any]:
    return {
        "capture_id": CAPTURE_ID,
        "kind": "qualification_capture",
        "verdict": "PASS",
        "requests": [{"number": 2, "canary": False, "violations": []}],
        **override,
    }


def _recommendations(result: dict[str, Any]) -> set[str]:
    return {m["judgement"]["recommendation"] for m in result["models"].values()}


def test_a_retrospective_session_without_a_capture_analysis_cannot_advance(tmp_path: Path) -> None:
    result = report.build_report(_retrospective(tmp_path), D12A)
    assert _recommendations(result) == {"INCONCLUSIVE"}
    assert result["session"]["channels_lifetime_complete"] is False
    assert "no capture analysis was supplied" in json.dumps(result)


def test_a_passing_analysis_of_the_sessions_own_capture_allows_advance(tmp_path: Path) -> None:
    result = report.build_report(_retrospective(tmp_path), D12A, None, _analysis())
    assert _recommendations(result) == {"ADVANCE"}
    assert result["session"]["capture_analysis_verdict"] == "PASS"


@pytest.mark.parametrize(
    "analysis",
    [
        _analysis(capture_id="20250101T000000Z-ffffffff"),
        _analysis(kind="canary_capture"),
        _analysis(verdict="INCONCLUSIVE"),
    ],
)
def test_an_analysis_of_another_capture_kind_or_an_inconclusive_one_is_not_enough(
    tmp_path: Path, analysis: dict[str, Any]
) -> None:
    result = report.build_report(_retrospective(tmp_path), D12A, None, analysis)
    assert "ADVANCE" not in _recommendations(result)


def test_a_violation_found_only_in_the_capture_blocks_the_recommendation(tmp_path: Path) -> None:
    analysis = _analysis(
        verdict="FAIL",
        requests=[{"number": 2, "canary": False, "violations": ["egress_attempt_observed"]}],
    )
    result = report.build_report(_retrospective(tmp_path), D12A, None, analysis)
    assert "egress_attempt_observed" in result["session"]["violations"]
    assert "ADVANCE" not in _recommendations(result)


def test_a_canary_requests_findings_are_not_charged_to_the_model(tmp_path: Path) -> None:
    analysis = _analysis(
        requests=[
            {"number": 1, "canary": True, "violations": ["egress_attempt_observed"]},
            {"number": 2, "canary": False, "violations": []},
        ]
    )
    result = report.build_report(_retrospective(tmp_path), D12A, None, analysis)
    assert result["session"]["violations"] == []
    assert _recommendations(result) == {"ADVANCE"}


def test_a_retrospective_d12a_run_needs_its_own_passing_analysis(tmp_path: Path) -> None:
    d12a = {
        **D12A,
        "monitoring": {"mode": "retrospective_capture", "capture_id": "20261025T180000Z-deadbeef"},
    }
    evidence = _retrospective(tmp_path)
    without = report.build_report(evidence, d12a, None, _analysis())
    assert without["binary_compatibility"] == "NOT TESTED"
    other = {
        "capture_id": "20261025T180000Z-deadbeef",
        "kind": "qualification_capture",
        "verdict": "PASS",
    }
    assert (
        report.build_report(evidence, d12a, None, _analysis(), other)["binary_compatibility"]
        == "PASS"
    )
    failed = {**other, "verdict": "INCONCLUSIVE"}
    assert (
        report.build_report(evidence, d12a, None, _analysis(), failed)["binary_compatibility"]
        == "NOT TESTED"
    )


def test_the_limits_section_states_that_findings_are_retrospective(tmp_path: Path) -> None:
    text = report.render_markdown(
        report.build_report(_retrospective(tmp_path), D12A, None, _analysis())
    )
    assert "retrospective" in text and "outbound firewall" in text


def test_the_models_are_the_frozen_plans(tmp_path: Path) -> None:
    result = report.build_report(_retrospective(tmp_path), D12A, None, _analysis())
    assert set(result["models"]) == set(MODELS)
