from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_ci_workflow_uses_named_required_smoke_script() -> None:
    workflow = _read(".github/workflows/ci.yml")
    assert "python tools/ci/check_repository_completeness.py" in workflow
    assert "python tools/ci/run_ruff_baseline.py" in workflow
    assert "python tools/ci/run_collection_gate.py" in workflow
    assert "python tools/ci/run_required_smoke.py" in workflow
    assert "python tools/ci/run_mypy_smoke.py" in workflow
    assert "ruff==0.14.9" in workflow
    assert "ruff check src" not in workflow
    assert "git diff --exit-code" in workflow


def test_pytest_has_one_strict_configuration_authority() -> None:
    pytest_ini = ROOT / "pytest.ini"
    pyproject = _read("pyproject.toml")

    assert not pytest_ini.exists()
    assert "[tool.pytest.ini_options]" in pyproject
    assert '"--strict-config"' in pyproject
    assert '"--strict-markers"' in pyproject
    assert '"--import-mode=importlib"' in pyproject
    for excluded in (
        "tests/gui",
        "tests/gui_v1_legacy",
        "tests/legacy",
        "tests/quarantine",
        "tests/scripts",
    ):
        assert f'"--ignore={excluded}"' in pyproject


def test_required_smoke_is_a_positive_architecture_current_list() -> None:
    runner = _read("tools/ci/run_required_smoke.py")

    assert "REQUIRED_SMOKE_TARGETS" in runner
    assert "tests/system/test_repository_completeness_v2.py" in runner
    assert "tests/system/test_architecture_enforcement_v2.py" in runner
    assert "tests/controller/test_core_run_path_v2.py" in runner
    assert "TestQueuedModeExecution" in runner
    assert "TestQueueErrorHandling" in runner
    assert '"tests/",' not in runner
    assert "tests/compat" not in runner
    assert "TestLegacyDirectNormalization" not in runner
    assert "TestDirectQueueParity" not in runner


def test_ruff_gate_is_version_pinned_and_non_increasing() -> None:
    pyproject = _read("pyproject.toml")
    runner = _read("tools/ci/run_ruff_baseline.py")
    baseline = _read("tools/ci/ruff_baseline.json")

    assert '"ruff==0.14.9"' in pyproject
    assert '"ruff_version": "0.14.9"' in baseline
    assert '"total": 2208' in baseline
    assert "count > allowed.get(key, 0)" in runner
    assert "actual_version != expected_version" in runner


def test_journeys_require_explicit_real_backend_opt_in() -> None:
    conftest = _read("tests/journeys/conftest.py")

    assert "STABLENEW_REAL_BACKEND_TESTS" in conftest
    assert 'os.getenv("CI"' not in conftest
    assert "if not real_backend_enabled():" in conftest


def test_ci_docs_point_to_named_required_smoke_script() -> None:
    coding = _read("docs/StableNew_Coding_and_Testing_v2.6.md")
    assert "tools/ci/run_ruff_baseline.py" in coding
    assert "tools/ci/run_collection_gate.py" in coding
    assert "tools/ci/run_required_smoke.py" in coding
    assert "tools/ci/run_mypy_smoke.py" in coding
