"""Formatting and blind/silent-exception ratchets (audit P1-5): existing debt may shrink, never grow."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ci"))

import run_ruff_ratchets as ratchets  # noqa: E402


def test_parse_unformatted_reads_ruff_output_and_normalizes_windows_paths() -> None:
    output = "Would reformat: tools\\runtime\\a.py\nWould reformat: src/b.py\n2 files would be reformatted, 9 already formatted\n"
    assert ratchets.parse_unformatted(output) == ["src/b.py", "tools/runtime/a.py"]


def test_parse_rule_counts_counts_only_the_ratcheted_rules_per_file() -> None:
    raw = json.dumps(
        [
            {"code": "BLE001", "filename": str(ROOT / "src" / "a.py")},
            {"code": "BLE001", "filename": str(ROOT / "src" / "a.py")},
            {"code": "S110", "filename": str(ROOT / "src" / "a.py")},
            {"code": "E501", "filename": str(ROOT / "src" / "a.py")},
            {"code": "S112", "filename": str(ROOT / "src" / "b.py")},
        ]
    )
    assert ratchets.parse_rule_counts(raw) == {
        "src/a.py": {"BLE001": 2, "S110": 1},
        "src/b.py": {"S112": 1},
    }


def test_a_newly_unformatted_file_is_a_format_regression_and_a_formatted_one_must_leave_the_baseline() -> (
    None
):
    problems = ratchets.compare_format(["src/new.py", "src/old.py"], ["src/old.py", "src/fixed.py"])
    assert any(p.startswith("FORMAT REGRESSION: src/new.py") for p in problems)
    assert any(p.startswith("FORMAT IMPROVED: src/fixed.py") for p in problems)
    assert not any("src/old.py" in p for p in problems)


def test_more_findings_than_the_baseline_is_a_regression_per_file_and_rule() -> None:
    problems = ratchets.compare_rules(
        {"src/a.py": {"BLE001": 3, "S110": 1}}, {"src/a.py": {"BLE001": 2, "S110": 1}}
    )
    assert problems and problems[0].startswith("BLE001 REGRESSION: src/a.py") and len(problems) == 1


def test_a_new_swallowed_failure_in_a_previously_clean_file_is_a_regression() -> None:
    assert ratchets.compare_rules({"src/clean.py": {"S110": 1}}, {})[0].startswith(
        "S110 REGRESSION: src/clean.py"
    )


def test_an_improvement_is_not_offset_against_a_regression_and_must_be_locked_in() -> None:
    problems = ratchets.compare_rules(
        {"src/a.py": {"BLE001": 1}, "src/b.py": {"BLE001": 5}},
        {"src/a.py": {"BLE001": 4}, "src/b.py": {"BLE001": 4}},
    )
    assert any(p.startswith("BLE001 IMPROVED: src/a.py") and "--update" in p for p in problems)
    assert any(p.startswith("BLE001 REGRESSION: src/b.py") for p in problems)


def test_equal_state_passes() -> None:
    assert (
        ratchets.compare_format(["a.py"], ["a.py"]) == []
        and ratchets.compare_rules({"a": {"S110": 2}}, {"a": {"S110": 2}}) == []
    )


def test_the_checked_in_baseline_is_well_formed_and_refers_to_real_files() -> None:
    files, counts = ratchets.load_baseline()
    assert files and all((ROOT / path).is_file() for path in files)
    assert counts and all(path.startswith("src/") and (ROOT / path).is_file() for path in counts)
    assert all(n > 0 for per in counts.values() for n in per.values())
    data = json.loads(ratchets.BASELINE_PATH.read_text(encoding="utf-8"))
    assert data["format"]["total"] == len(files)
    assert data["rules"]["totals"] == {
        rule: sum(per.get(rule, 0) for per in counts.values()) for rule in ratchets.RULES
    }


def test_the_ratchets_are_wired_into_the_local_gate_and_the_required_ci_job() -> None:
    assert "run_ruff_ratchets.py" in (ROOT / "tools" / "ci" / "run_pr_gate.py").read_text(
        encoding="utf-8"
    )
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    required = workflow[workflow.index("  required:") : workflow.index("  full-suite-shard:")]
    assert "python tools/ci/run_ruff_ratchets.py" in required and "cheap_path != 'true'" in required


def test_end_to_end_a_new_unformatted_module_that_swallows_an_exception_fails_the_real_gate() -> (
    None
):
    """Negative case against real ruff: a fresh, unformatted src module with `except Exception: pass` is reported."""

    probe = ROOT / "src" / "_p1_5_probe_swallow.py"
    probe.write_text(
        "def f( x ):\n    try:\n        return x()\n    except Exception:\n        pass\n",
        encoding="utf-8",
    )
    try:
        files, counts = ratchets.collect()
        base_files, base_counts = ratchets.load_baseline()
        problems = ratchets.compare_format(files, base_files) + ratchets.compare_rules(
            counts, base_counts
        )
        joined = "\n".join(problems)
        assert "FORMAT REGRESSION: src/_p1_5_probe_swallow.py" in joined
        assert "BLE001 REGRESSION: src/_p1_5_probe_swallow.py" in joined
        assert "S110 REGRESSION: src/_p1_5_probe_swallow.py" in joined
    finally:
        probe.unlink()
