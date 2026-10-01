from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_ci_workflow_uses_named_required_smoke_script() -> None:
    workflow = _read(".github/workflows/ci.yml")
    assert "python tools/ci/check_repository_completeness.py" in workflow
    assert "python tools/ci/check_controller_surface.py" in workflow
    assert "ruff check ." in workflow
    assert "run_ruff_baseline.py" not in workflow
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


def test_ruff_gate_is_version_pinned_and_raw_zero() -> None:
    pyproject = _read("pyproject.toml")
    runner = _read("tools/ci/run_pr_gate.py")

    assert '"ruff==0.14.9"' in pyproject
    assert '("Ruff", ("ruff", "check", "."))' in runner
    assert not (ROOT / "tools/ci/run_ruff_baseline.py").exists()
    assert not (ROOT / "tools/ci/ruff_baseline.json").exists()


def test_legacy_journey_lane_is_retired_and_workflows_are_intentional() -> None:
    workflows = {path.name for path in (ROOT / ".github/workflows").glob("*.yml")}

    assert not (ROOT / "tests/journeys").exists()
    assert "journey-tests.yml" not in workflows
    assert "journeys_shutdown.yml" not in workflows
    assert not (ROOT / "scripts/run_journey_tests.ps1").exists()

    shutdown = _read(".github/workflows/shutdown_leak_manual.yml")
    assert "workflow_dispatch" in shutdown
    assert "schedule:" not in shutdown
    assert "STABLENEW_RUN_SHUTDOWN_LEAK_TEST" in shutdown
    assert "tests/system/test_shutdown_no_leaks.py" in shutdown


def test_full_suite_lane_is_informational_and_not_fail_fast() -> None:
    workflow = _read(".github/workflows/ci.yml")
    full_suite = workflow[workflow.index("  full-suite:") :]

    assert "continue-on-error: true" in full_suite
    assert "--maxfail" not in full_suite
    assert "pytest-timeout" in full_suite
    assert "--timeout" in full_suite


def test_shutdown_leak_process_test_is_explicit_opt_in() -> None:
    source = _read("tests/system/test_shutdown_no_leaks.py")

    assert "STABLENEW_RUN_SHUTDOWN_LEAK_TEST" in source
    assert "skipif" in source


def test_ci_docs_point_to_named_required_smoke_script() -> None:
    coding = _read("docs/StableNew_Coding_and_Testing_v2.6.md")
    agents = _read("AGENTS.md")
    assert "python tools/ci/run_pr_gate.py" in coding
    assert "python tools/ci/run_pr_gate.py" in agents
    assert "GitHub required CI" in coding


def test_local_pr_gate_delegates_to_each_required_authority() -> None:
    runner = _read("tools/ci/run_pr_gate.py")

    for script in (
        "check_repository_completeness.py",
        "check_controller_surface.py",
        "run_mypy_smoke.py",
        "run_collection_gate.py",
        "run_required_smoke.py",
    ):
        assert script in runner
    assert '("Ruff", ("ruff", "check", "."))' in runner
