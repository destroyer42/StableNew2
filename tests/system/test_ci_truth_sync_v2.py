from __future__ import annotations

import re
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


def test_affected_ci_bounds_wall_time_and_uses_thread_test_timeout() -> None:
    affected = _ci_section("  affected:", "  full-suite-shard:")
    match = re.search(r"^    timeout-minutes: (\d+)$", affected, flags=re.MULTILINE)
    assert match is not None
    assert 5 < int(match.group(1)) <= 30
    assert "--timeout=300" in affected
    assert "--timeout-method=thread" in affected


def test_pytest_has_one_strict_configuration_authority() -> None:
    pytest_ini = ROOT / "pytest.ini"
    pyproject = _read("pyproject.toml")

    assert not pytest_ini.exists()
    assert "[tool.pytest.ini_options]" in pyproject
    assert '"--strict-config"' in pyproject
    assert '"--strict-markers"' in pyproject
    assert '"--import-mode=importlib"' in pyproject
    for excluded in (
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
    full_suite = workflow[workflow.index("  full-suite-shard:") :]
    shards = _census_shards_module()

    assert full_suite.count("continue-on-error: true") == 2  # the shard job and the aggregate verdict
    assert "--maxfail" not in full_suite and "--maxfail" not in " ".join(shards.PYTEST_ARGS)
    assert "pytest-timeout" in full_suite
    assert "--timeout=300" in shards.PYTEST_ARGS


def _ci_section(start: str, end: str | None = None) -> str:
    workflow = _read(".github/workflows/ci.yml")
    begin = workflow.index(start)
    return workflow[begin : workflow.index(end, begin) if end else None]


def test_ci_is_python_312_only_with_no_version_matrix() -> None:
    workflow = _read(".github/workflows/ci.yml")

    # The only matrix is the census shard index (PR-DEVEX-CENSUS-140); there is never an interpreter matrix.
    assert workflow.count("matrix:") == 1 and "shard: [0, 1, 2]" in workflow
    assert "python-version: [" not in workflow
    assert "3.11" not in workflow
    assert "3.12" not in workflow and "3.13" not in workflow
    assert workflow.count('python-version: "3.14"') == 4  # required + affected + full-suite-shard + full-suite


def test_census_shard_count_is_consistent_between_the_matrix_and_every_command() -> None:
    section = _ci_section("  full-suite-shard:")

    assert "shard: [0, 1, 2]" in section
    assert "--shards 3" in section
    assert "--shards 3" in _ci_section("  full-suite:")
    assert "census_shards.py run-shard" in section and "census_shards.py verify" in _ci_section("  full-suite:")


def test_ci_runs_once_per_pull_request_head_including_stacked_prs() -> None:
    triggers = _ci_section("\non:", "\nconcurrency:")

    assert "pull_request:" in triggers
    assert 'branches: [ "**" ]' in triggers  # stacked PRs may target a feature branch
    assert "workflow_dispatch:" in triggers
    assert "push:" not in triggers  # a branch push plus its PR would duplicate every run


def test_superseded_ci_runs_are_cancelled_per_pull_request() -> None:
    concurrency = _ci_section("\nconcurrency:", "\njobs:")

    assert "cancel-in-progress: true" in concurrency
    assert "github.event.pull_request.number" in concurrency


def test_ci_has_one_required_job_one_affected_lane_job_and_one_full_suite_job() -> None:
    jobs = _ci_section("\njobs:")

    assert re.findall(r"^  ([a-z][a-z-]*):\s*$", jobs, flags=re.MULTILINE) == [
        "required",
        "affected",
        "full-suite-shard",
        "full-suite",
    ]
    required = _ci_section("  required:", "  affected:")
    assert "continue-on-error" not in required  # the required gate is never masked


def test_full_suite_reports_a_quiet_summary_with_failure_diagnostics() -> None:
    flags = list(_census_shards_module().PYTEST_ARGS)  # the one place the census pytest flags live

    assert "-q" in flags  # concise green result
    assert not {"-v", "-vv", "-vvv", "--verbose"} & set(flags)  # no per-test success logging
    assert "-rfE" in flags  # failures and errors stay summarized
    assert "--tb=short" in flags
    assert "--timeout=300" in flags
    assert "junit_duration_report=total" in flags
    source = _read("tools/ci/census_shards.py")
    assert "/dev/null" not in source and "capture_output" not in source  # no hidden diagnostics


def test_pytest_gates_share_one_quiet_runner_authority() -> None:
    collection = _read("tools/ci/run_collection_gate.py")
    smoke = _read("tools/ci/run_required_smoke.py")

    assert "capture_output=True" in collection
    assert "from run_collection_gate import" in smoke and "run_pytest_gate" in smoke
    assert "subprocess" not in smoke  # smoke must not grow a second pytest runner


def test_python_314_is_the_sole_runtime_contract_across_current_authorities() -> None:
    pyproject = _read("pyproject.toml")
    pre_commit = _read(".pre-commit-config.yaml")
    bootstrap = _read("scripts/bootstrap_windows.ps1")
    readiness = _read("src/services/operator_readiness_service.py")

    assert 'requires-python = ">=3.14,<3.15"' in pyproject
    assert 'python_version = "3.14"' in pyproject
    assert 'target-version = "py314"' in pyproject
    assert "target-version = ['py314']" in pyproject
    assert "py311" not in pyproject and "py312" not in pyproject
    assert "python3.11" not in pre_commit and "python3.12" not in pre_commit
    assert "'^3\\.14\\.'" in bootstrap  # rejects every other minor, including 3.11 and 3.13+
    assert 'foreach ($requested in @("3.14"))' in bootstrap
    assert "Py_GIL_DISABLED" in bootstrap  # the free-threaded build is rejected
    assert "_jit" in bootstrap and "PYTHON_JIT" in bootstrap  # an enabled JIT is rejected
    assert "3.11" not in bootstrap and "3.12" not in bootstrap
    assert "SUPPORTED_PYTHON_MINOR = (3, 14)" in readiness
    for workflow in (ROOT / ".github/workflows").glob("*.yml"):
        text = workflow.read_text(encoding="utf-8")
        assert "3.11" not in text and "3.12" not in text, workflow.name


def _census_shards_module():
    import importlib.util
    import sys

    tools_ci = str(ROOT / "tools" / "ci")
    if tools_ci not in sys.path:
        sys.path.insert(0, tools_ci)
    spec = importlib.util.spec_from_file_location("census_shards_authority", ROOT / "tools" / "ci" / "census_shards.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _truth_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("ci_truth_authority", ROOT / "tools" / "ci" / "ci_truth.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_testing_authority_defines_the_three_validation_levels() -> None:
    """The rules live in tools/ci/ci_truth.py (stdlib, also run by the docs-only cheap path); pytest binds to the same authority."""

    problems = _truth_module().docs_truth_problems(ROOT)
    assert [p for p in problems if "Level" in p or "Python 3." in p] == []
    coding = _read("docs/StableNew_Coding_and_Testing_v2.6.md")
    for heading in ("Level 1", "Level 2", "Level 3"):
        assert heading in coding


def test_shutdown_leak_process_test_is_explicit_opt_in() -> None:
    source = _read("tests/system/test_shutdown_no_leaks.py")

    assert "STABLENEW_RUN_SHUTDOWN_LEAK_TEST" in source
    assert "skipif" in source


def test_ci_docs_point_to_named_required_smoke_script() -> None:
    assert _truth_module().docs_truth_problems(ROOT) == []
    assert "python tools/ci/run_pr_gate.py" in _read("AGENTS.md")


def test_the_cheap_docs_path_enforces_the_same_truth_without_the_application_environment() -> None:
    workflow = _read(".github/workflows/ci.yml")
    cheap = workflow[workflow.index("Cheap documentation checks") : workflow.index("Set up Python 3.14")]
    assert "python3 tools/ci/ci_truth.py" in cheap
    source = _read("tools/ci/ci_truth.py")
    assert "pytest" not in source.replace("pytest truth tests", "") and "import yaml" not in source  # stdlib only


def test_a_docs_edit_that_violates_current_ci_truth_is_detected(tmp_path: Path) -> None:
    import shutil

    for rel in ("docs/StableNew_Coding_and_Testing_v2.6.md", "AGENTS.md", "STATUS.md", "docs/CODEX_MAP.md"):
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, target)
    truth = _truth_module()
    assert truth.docs_truth_problems(tmp_path) == []
    coding = tmp_path / "docs/StableNew_Coding_and_Testing_v2.6.md"
    coding.write_text(coding.read_text(encoding="utf-8").replace("python tools/ci/run_pr_gate.py", "run the gate"), encoding="utf-8")
    assert any("run_pr_gate" in p for p in truth.docs_truth_problems(tmp_path))
    status = tmp_path / "STATUS.md"
    status.write_text(status.read_text(encoding="utf-8") + "\n(one required gate, one informational full-suite job)\n", encoding="utf-8")
    assert any("pre-CI-110" in p for p in truth.docs_truth_problems(tmp_path))
    result = __import__("subprocess").run([__import__("sys").executable, str(ROOT / "tools" / "ci" / "ci_truth.py")], capture_output=True, text=True)
    assert result.returncode == 0  # the real repository currently satisfies its own truth


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
