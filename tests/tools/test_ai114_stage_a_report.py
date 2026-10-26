"""PR-AI-QUAL-114 Stage A report: verdict rules and sample attribution on SYNTHETIC records (no model output exists here)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.qualification.ai111 import plan as plan_module  # noqa: E402
from tools.qualification.ai111 import stage_a_report as report  # noqa: E402
from tools.qualification.ai111.baselines import ARMS  # noqa: E402
from tools.qualification.ai111.corpus import corpus_digest  # noqa: E402
from tools.qualification.ai111.scoring import summarize_arm  # noqa: E402

PLAN = plan_module.frozen_plan()
CASES = report.rederive_cases(PLAN)
BY_ID = {c.case_id: c for c in CASES}
MODELS = [m["model_id"] for m in PLAN["models"]]
D12A = {
    "verdict": "PASS",
    "members": {"llama-cli.exe": {"verdict": "PASS", "sha256": "c" * 64}},
    "archive_sha256": PLAN["runtime_intent"]["sha256"],
}


def _row(
    case, arm: str, index: int, *, outcome: str = "suggestion", reason: str = "", ms: int = 8000
):
    produced = ARMS["B1_engine"](case)
    if (
        case.canary and arm in MODELS
    ):  # a well-behaved model does not carry an injected instruction through
        produced = {
            k: v.replace(case.canary, "") if isinstance(v, str) else v for k, v in produced.items()
        }
    expects = case.expected_outcome
    return {
        "case_id": case.case_id,
        "arm": arm,
        "outcome": expects or outcome,
        "reason": reason,
        "elapsed_ms": ms,
        "positive": produced.get("positive"),
        "negative": produced.get("negative"),
        "choice": case.oracle or produced.get("choice"),
        "details": {
            "child_observed": True,
            "priority_verified": True,
            "observed_priority_class": 0x4000,
            "peak_tree_private_gib": 6.5,
            "peak_tree_working_set_gib": 6.0,
            "tree_cpu_seconds": 40.0,
            "max_tree_processes": 1,
            "egress_connections": 0,
        },
        "started_utc": f"2026-10-25T12:{index:02d}:00+00:00",
        "ended_utc": f"2026-10-25T12:{index:02d}:30+00:00",
        "arm_request_index": index + 1,
        "phase": "cold" if index == 0 else "warm",
    }


def _evidence(tmp_path: Path, *, probes: bool = True, mutate=None, abort: str = "") -> Path:
    evidence = tmp_path / "physical-A"
    evidence.mkdir()
    rows: list[dict[str, Any]] = []
    for arm in plan_module.BASELINE_ARMS:
        rows += [{**_row(c, arm, i), "elapsed_ms": 0, "details": {}} for i, c in enumerate(CASES)]
    for arm in MODELS:
        rows += [_row(c, arm, i % 50) for i, c in enumerate(CASES)]
    if mutate:
        rows = mutate(rows)
    (evidence / "records.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )
    summaries = {}
    for arm in {r["arm"] for r in rows}:
        summaries[arm] = summarize_arm(BY_ID, [r for r in rows if r["arm"] == arm])
    (evidence / "summary.json").write_text(json.dumps(summaries), encoding="utf-8")
    (evidence / "execution-manifest.json").write_text(
        json.dumps(
            {
                "plan_sha256": plan_module.digest(PLAN),
                "corpus_sha256": corpus_digest(CASES),
                "run_id": "test",
                "executable": "llama-cli.exe",
                "executed_sha": "x",
                "source_dirty": False,
            }
        ),
        encoding="utf-8",
    )
    (evidence / "result.json").write_text(
        json.dumps(
            {
                "teardown_verified": True,
                "abort_reason": abort,
                "monitoring": {
                    "violations": [],
                    "channel_coverage": {
                        "connections": ["lifetime_complete"],
                        "files": ["lifetime_complete"],
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    (evidence / "telemetry.jsonl").write_text(
        json.dumps(
            {"utc": "2026-10-25T12:00:10+00:00", "available_gib": 9.5, "commit_headroom_gib": 20.0}
        )
        + "\n",
        encoding="utf-8",
    )
    if probes:
        (evidence / "lifecycle-probes.jsonl").write_text(
            "\n".join(
                json.dumps(
                    {
                        "arm": arm,
                        "probe": kind,
                        "stopped_as_intended": True,
                        "teardown_verified": True,
                        "ownership_violations": [],
                    }
                )
                for arm in MODELS
                for kind in ("timeout", "cancel")
            )
            + "\n",
            encoding="utf-8",
        )
    (evidence / "arm-integrity.jsonl").write_text(
        "\n".join(
            json.dumps({"arm": arm, "phase": phase, "problems": []})
            for arm in MODELS
            for phase in ("before", "after")
        )
        + "\n",
        encoding="utf-8",
    )
    return evidence


def test_the_stage_a_case_list_is_rederived_and_matches_the_recorded_digest(tmp_path: Path) -> None:
    result = report.build_report(_evidence(tmp_path), D12A)
    assert result["attribution_problems"] == []
    assert len(CASES) == 30 and set(result["models"]) == set(MODELS)


def test_a_clean_fast_model_advances_only_with_every_axis_passing(tmp_path: Path) -> None:
    result = report.build_report(_evidence(tmp_path), D12A)
    for arm in MODELS:
        judgement = result["models"][arm]["judgement"]
        assert judgement["recommendation"] == "ADVANCE", judgement
        assert (
            judgement["compatibility"],
            judgement["execution_integrity"],
            judgement["security_monitoring"],
        ) == ("PASS", "PASS", "PASS")


def test_missing_lifecycle_probes_or_d12a_cannot_yield_advance(tmp_path: Path) -> None:
    no_probes = report.build_report(_evidence(_mk(tmp_path / "a"), probes=False), D12A)
    assert all(
        m["judgement"]["recommendation"] == "INCONCLUSIVE" for m in no_probes["models"].values()
    )
    no_d12a = report.build_report(_evidence(_mk(tmp_path / "b")), None)
    assert all(
        m["judgement"]["recommendation"] == "INCONCLUSIVE" for m in no_d12a["models"].values()
    )


def _mk(path: Path) -> Path:
    path.mkdir()
    return path


def test_slow_model_is_inconclusive_with_the_missed_threshold_listed(tmp_path: Path) -> None:
    def slow(rows):
        return [{**r, "elapsed_ms": 45000} if r["arm"] == MODELS[2] else r for r in rows]

    result = report.build_report(_evidence(tmp_path, mutate=slow), D12A)
    judgement = result["models"][MODELS[2]]["judgement"]
    assert judgement["recommendation"] == "INCONCLUSIVE"
    assert any("median latency" in m for m in judgement["measured_thresholds_missed"])
    assert result["models"][MODELS[0]]["judgement"]["recommendation"] == "ADVANCE"


def test_a_protected_token_change_is_a_hard_reject(tmp_path: Path) -> None:
    def break_tokens(rows):
        out = []
        changed = False
        for r in rows:
            case = BY_ID[r["case_id"]]
            if (
                not changed
                and r["arm"] == MODELS[0]
                and case.kind == "prompt_rewrite"
                and "<" in case.positive
                and r["outcome"] == "suggestion"
            ):
                r = {**r, "positive": (r["positive"] or "").replace("<", "(").replace(">", ")")}
                changed = True
            out.append(r)
        assert changed
        return out

    result = report.build_report(_evidence(tmp_path, mutate=break_tokens), D12A)
    judgement = result["models"][MODELS[0]]["judgement"]
    assert judgement["recommendation"] == "REJECT"
    assert "accepted_protected_token_changes" in judgement["hard_gates_failed"]


def test_a_model_whose_child_never_runs_is_rejected_but_a_host_stop_is_not(tmp_path: Path) -> None:
    def exits(rows):
        return [
            {**r, "outcome": "unavailable", "reason": "child_exit_nonzero", "positive": None}
            if r["arm"] == MODELS[1]
            else r
            for r in rows
        ]

    def starved(rows):
        return [
            {**r, "outcome": "resource_insufficient", "reason": "memory_guard", "positive": None}
            if r["arm"] == MODELS[1]
            else r
            for r in rows
        ]

    broken = report.build_report(_evidence(_mk(tmp_path / "a"), mutate=exits), D12A)
    assert broken["models"][MODELS[1]]["judgement"]["recommendation"] == "REJECT"
    assert broken["models"][MODELS[1]]["judgement"]["compatibility"] == "FAIL"
    host = report.build_report(_evidence(_mk(tmp_path / "b"), mutate=starved), D12A)
    assert host["models"][MODELS[1]]["judgement"]["recommendation"] == "INCONCLUSIVE"


def test_a_d12a_record_for_another_executable_cannot_support_a_recommendation(
    tmp_path: Path,
) -> None:
    covered = D12A
    evidence = _evidence(tmp_path)
    manifest = json.loads((evidence / "execution-manifest.json").read_text())
    manifest["executable"] = "llama-completion.exe"
    (evidence / "execution-manifest.json").write_text(json.dumps(manifest))
    result = report.build_report(evidence, covered)
    assert result["attribution_problems"] and result["binary_compatibility"] == "NOT TESTED"
    assert all(
        m["judgement"]["recommendation"] == "INCONCLUSIVE" for m in result["models"].values()
    )
    assert "Attribution problems" in report.render_markdown(result)
    manifest["executable"] = "llama-cli.exe"
    (evidence / "execution-manifest.json").write_text(json.dumps(manifest))
    assert report.build_report(evidence, covered)["attribution_problems"] == []


def test_records_for_other_cases_or_a_different_corpus_are_an_attribution_problem(
    tmp_path: Path,
) -> None:
    evidence = _evidence(tmp_path)
    manifest = json.loads((evidence / "execution-manifest.json").read_text())
    manifest["corpus_sha256"] = "0" * 64
    (evidence / "execution-manifest.json").write_text(json.dumps(manifest))
    assert report.build_report(evidence, D12A)["attribution_problems"]


def test_an_arm_that_never_ran_is_inconclusive_not_absent(tmp_path: Path) -> None:
    def drop(rows):
        return [r for r in rows if r["arm"] != MODELS[3]]

    result = report.build_report(_evidence(tmp_path, mutate=drop), D12A)
    assert result["models"][MODELS[3]]["judgement"]["recommendation"] == "INCONCLUSIVE"
    assert result["models"][MODELS[3]]["metrics"] is None


def test_the_markdown_states_the_limits_and_never_the_word_qualified(tmp_path: Path) -> None:
    text = report.render_markdown(report.build_report(_evidence(tmp_path), D12A))
    assert "Limits of this evidence" in text and "operator-attested" in text
    assert "qualified=true" not in text and "promot" not in text.lower()


@pytest.mark.parametrize("value", [None, 0.0, 12.345])
def test_number_formatting_never_raises(value) -> None:
    assert isinstance(report._fmt(value), str)


def test_compatibility_is_judged_per_executable_never_from_the_other_members_verdict(
    tmp_path: Path,
) -> None:
    evidence = _evidence(tmp_path)
    manifest = json.loads((evidence / "execution-manifest.json").read_text())
    two = {
        "verdict": "FAIL",
        "archive_sha256": PLAN["runtime_intent"]["sha256"],
        "members": {
            "llama-cli.exe": {"verdict": "FAIL", "sha256": "c" * 64},
            "llama-completion.exe": {"verdict": "PASS", "sha256": "d" * 64},
        },
    }
    manifest["executable"] = "llama-completion.exe"
    (evidence / "execution-manifest.json").write_text(json.dumps(manifest))
    assert report.build_report(evidence, two)["binary_compatibility"] == "PASS"
    manifest["executable"] = "llama-cli.exe"
    (evidence / "execution-manifest.json").write_text(json.dumps(manifest))
    assert report.build_report(evidence, two)["binary_compatibility"] == "FAIL"
