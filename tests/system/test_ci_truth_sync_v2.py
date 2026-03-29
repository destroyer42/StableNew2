from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_ci_workflow_uses_named_required_smoke_script() -> None:
    workflow = _read(".github/workflows/ci.yml")
    assert "python tools/ci/run_required_smoke.py" in workflow
    assert "python tools/ci/run_mypy_smoke.py" in workflow


def test_ci_docs_point_to_named_required_smoke_script() -> None:
    manifest = _read("tests/TEST_SURFACE_MANIFEST.md")
    coding = _read("docs/StableNew_Coding_and_Testing_v2.6.md")
    assert "tools/ci/run_required_smoke.py" in manifest
    assert "tools/ci/run_required_smoke.py" in coding
    assert "tools/ci/run_mypy_smoke.py" in coding


def test_ci_issue_template_matches_current_gate_shape() -> None:
    issue = _read(".github/ISSUE_TEMPLATE/14_s3_c_ci_pipeline.md")
    assert "required smoke gate" in issue
    assert "mypy smoke gate" in issue
    assert "black" not in issue.lower()
    assert "pre-commit" not in issue.lower()
