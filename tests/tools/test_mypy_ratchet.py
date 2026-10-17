"""The whole-application mypy ratchet (audit P1-4): existing debt may shrink, never grow; clean files stay clean."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ci"))

import run_mypy_ratchet as ratchet  # noqa: E402

SAMPLE = """\
src\\utils\\a.py:4: error: Function is missing a type annotation  [no-untyped-def]
src/utils/a.py:9:5: error: Call to untyped function "f" in typed context  [no-untyped-call]
src/pipeline/b.py:1: error: Cannot find implementation or library stub for module named "torch"  [import-not-found]
src/pipeline/b.py:2: error: Skipping analyzing "yaml": module is installed, but missing library stubs  [import-untyped]
src/pipeline/b.py:3: note: See https://mypy.readthedocs.io for more info
tests/x.py:1: error: Function is missing a type annotation  [no-untyped-def]
src/pipeline/c.py:7: error: Incompatible types in assignment  [assignment]
"""


def test_parse_counts_counts_only_src_errors_and_ignores_environment_dependent_import_errors() -> None:
    assert ratchet.parse_counts(SAMPLE) == {"src/pipeline/c.py": 1, "src/utils/a.py": 2}  # backslashes normalized


def test_a_new_error_in_a_clean_file_is_a_regression() -> None:
    problems = ratchet.compare({"src/new.py": 1}, {})
    assert len(problems) == 1 and problems[0].startswith("REGRESSION: src/new.py") and "no mypy errors" in problems[0]


def test_more_errors_than_the_baseline_is_a_regression_even_when_other_files_improved() -> None:
    problems = ratchet.compare({"src/a.py": 3, "src/b.py": 0}, {"src/a.py": 2, "src/b.py": 5})
    assert any(p.startswith("REGRESSION: src/a.py") for p in problems)
    assert any(p.startswith("IMPROVED: src/b.py") for p in problems)  # an improvement is never offset against a regression


def test_an_improvement_must_be_locked_in_by_lowering_the_baseline() -> None:
    problems = ratchet.compare({"src/a.py": 1}, {"src/a.py": 2})
    assert len(problems) == 1 and "--update" in problems[0]


def test_equal_counts_pass() -> None:
    assert ratchet.compare({"src/a.py": 2}, {"src/a.py": 2}) == []
    assert ratchet.compare({}, {}) == []


def test_the_checked_in_baseline_is_well_formed_and_refers_to_real_files() -> None:
    baseline = ratchet.load_baseline()
    assert baseline and all(path.startswith("src/") and (ROOT / path).is_file() for path in baseline)
    assert all(count > 0 for count in baseline.values())  # a clean file must not be listed
    import json

    data = json.loads(ratchet.BASELINE_PATH.read_text(encoding="utf-8"))
    assert data["total"] == sum(baseline.values())


def test_the_ratchet_is_wired_into_the_local_gate_and_the_required_ci_job() -> None:
    gate = (ROOT / "tools" / "ci" / "run_pr_gate.py").read_text(encoding="utf-8")
    assert "run_mypy_ratchet.py" in gate
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    required = workflow[workflow.index("  required:") : workflow.index("  full-suite-shard:")]
    assert "python tools/ci/run_mypy_ratchet.py" in required and "cheap_path != 'true'" in required


def test_end_to_end_a_new_untyped_function_in_a_clean_file_fails_the_real_gate() -> None:
    """Negative case against the real mypy run: a freshly added, untyped module must be reported."""

    probe = ROOT / "src" / "_p1_4_probe_untyped.py"
    probe.write_text("def untyped(x):\n    return x\n", encoding="utf-8")
    try:
        counts = ratchet.parse_counts(ratchet.run_mypy())
        assert counts.get("src/_p1_4_probe_untyped.py", 0) >= 1
        problems = ratchet.compare(counts, ratchet.load_baseline())
        assert any(p.startswith("REGRESSION: src/_p1_4_probe_untyped.py") for p in problems)
    finally:
        probe.unlink()
