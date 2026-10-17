"""PR-DEVEX-CI-160: the repository-owned validation policy (docs-only vs full census) and the workflow that consumes it."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "ci"))

import validation_plan as vp  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


# --- classifier -------------------------------------------------------------------------------------------------


def test_docs_only_diff_is_docs_only_and_schedules_no_census() -> None:
    plan = vp.classify(["docs/Subsystems/Image/PR-X.md", "STATUS.md", "docs/StableNew Roadmap v2.6.md", ".github/pull_request_template.md"])
    assert plan.docs_only and plan.cheap_path and not plan.full_census and plan.full_census_reasons == ()


@pytest.mark.parametrize(
    "path",
    [
        "src/pipeline/executor.py",
        "tests/pipeline/test_pipeline_runner.py",
        "tools/ci/validation_plan.py",
        ".github/workflows/ci.yml",
        "pyproject.toml",
        "requirements.txt",
        "constraints/windows-py314-cu130.txt",
        "scripts/bootstrap_windows.ps1",
        "config/managed_forge_runtime.json",
        "src/prompting/notes.md",  # a .md under src/ is data consumed by code, never documentation
        "tools/ci/notes.txt",
    ],
)
def test_executable_or_configuration_files_are_never_docs_only_and_always_run_the_census(path: str) -> None:
    plan = vp.classify([path])
    assert not plan.docs_only and plan.full_census and plan.full_census_reasons == (vp.CENSUS_REASON,)


def test_executable_source_plus_docs_stays_executable() -> None:
    plan = vp.classify(["docs/x.md", "src/queue/job_queue.py"])
    assert not plan.docs_only and plan.full_census


def test_an_empty_change_set_is_docs_only() -> None:
    assert vp.classify([]).docs_only


def test_the_plan_has_no_lane_routing_left_to_rot() -> None:
    source = (ROOT / "tools" / "ci" / "validation_plan.py").read_text(encoding="utf-8")
    for removed in ("LANE_RULES", "DOMAIN_TARGETS", "affected_targets", "run_affected"):
        assert removed not in source


# --- CLI ----------------------------------------------------------------------------------------------------------


def _run_cli(tmp_path: Path, *args: str) -> dict[str, str]:
    out = tmp_path / "out.txt"
    script = ROOT / "tools" / "ci" / "validation_plan.py"
    subprocess.run([sys.executable, str(script), *args, "--github-output", str(out)], check=True, capture_output=True)
    return dict(line.split("=", 1) for line in out.read_text(encoding="utf-8").splitlines() if "=" in line)


def test_the_plan_cli_writes_github_outputs_for_the_workflow(tmp_path: Path) -> None:
    values = _run_cli(tmp_path, "--files", "src/queue/job_queue.py")
    assert values == {"docs_only": "false", "cheap_path": "false", "reuse_previous_evidence": "false", "full_census": "true"}


@pytest.mark.parametrize("event", ["schedule", "workflow_dispatch", "push"])
def test_periodic_manual_and_post_merge_events_are_always_a_full_census(tmp_path: Path, event: str) -> None:
    values = _run_cli(tmp_path, "--event", event, "--files", "docs/x.md")
    assert values["full_census"] == "true" and values["cheap_path"] == "false"


# --- the workflow consumes the plan and keeps its operational contracts ---------------------------------------------


def test_the_workflow_consumes_the_repository_owned_plan_rather_than_embedding_policy() -> None:
    assert "tools/ci/validation_plan.py" in WORKFLOW
    for output in ("docs_only", "cheap_path", "full_census"):
        assert f"steps.plan.outputs.{output}" in WORKFLOW
    assert "paths-filter" not in WORKFLOW and "dorny/" not in WORKFLOW  # no third-party path-filter action


def test_docs_only_runs_no_python_environment_or_tests() -> None:
    required = WORKFLOW[WORKFLOW.index("  required:") : WORKFLOW.index("  full-suite-shard:")]
    for marker in ("Set up Python 3.14", "Install pip tools", "Lint (Ruff)", "Run mypy smoke gate", "Run required positive-list gate"):
        step = required[required.index(marker) - 200 : required.index(marker) + 120]
        assert "steps.plan.outputs.cheap_path != 'true'" in step, marker
    cheap = required[required.index("Cheap documentation checks") : required.index("Set up Python 3.14")]
    assert "git diff --check" in cheap and "python3 tools/ci/check_repository_completeness.py" in cheap


def test_the_census_is_the_blocking_merge_gate_and_waits_for_the_required_gate() -> None:
    full = WORKFLOW[WORKFLOW.index("  full-suite-shard:") : WORKFLOW.index("\n  # Windows platform contract")]
    assert "continue-on-error" not in WORKFLOW  # nothing is informational any more
    assert "affected:" not in WORKFLOW
    assert full.count("needs: ") == 2 and full.count("needs.required.outputs.full_census == 'true'") == 2


def test_every_job_has_a_timeout_so_a_hang_cannot_hold_a_runner_for_hours() -> None:
    jobs = WORKFLOW[WORKFLOW.index("\njobs:") :]
    assert jobs.count("timeout-minutes:") == 4  # required, full-suite-shard, full-suite, windows


def test_third_party_actions_are_pinned_to_full_commit_shas() -> None:
    workflows = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    assert workflows
    for workflow in workflows:
        for ref in re.findall(r"uses: (\S+)", workflow.read_text(encoding="utf-8-sig")):
            assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", ref), f"{workflow.name}: {ref}"


def test_no_workflow_runs_fork_code_from_a_comment_trigger() -> None:
    """issue_comment/pull_request_target workflows run with base-repository secrets and tokens; PR code must never run there."""

    for workflow in (ROOT / ".github" / "workflows").glob("*.yml"):
        text = workflow.read_text(encoding="utf-8-sig")
        assert "issue_comment" not in text and "pull_request_target" not in text, workflow.name


def test_main_has_a_periodic_census_post_merge_runs_manual_dispatch_and_one_workflow_per_pr_head() -> None:
    triggers = WORKFLOW[WORKFLOW.index("\non:") : WORKFLOW.index("\nconcurrency:")]
    assert "cron:" in triggers and "1,3,5" in triggers  # Monday/Wednesday/Friday
    assert "workflow_dispatch:" in triggers
    assert "push:\n    branches: [ main ]" in triggers  # a commit that bypasses a PR is still tested; other pushes are not


def test_superseded_pull_request_heads_are_cancelled_but_main_runs_are_not() -> None:
    concurrency = WORKFLOW[WORKFLOW.index("\nconcurrency:") : WORKFLOW.index("\njobs:")]
    assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in concurrency
    assert "github.event.pull_request.number" in concurrency


def test_the_required_check_identity_is_preserved_and_never_masked() -> None:
    assert "\n  required:\n" in WORKFLOW
    assert "\n  full-suite:\n" in WORKFLOW  # the census verdict is the second branch-protection identity
    required = WORKFLOW[WORKFLOW.index("  required:") : WORKFLOW.index("  full-suite-shard:")]
    assert "continue-on-error" not in required


def test_the_plan_artifact_stays_outside_the_checkout_so_the_clean_tree_check_holds() -> None:
    assert '"$RUNNER_TEMP/plan.json"' in WORKFLOW and "runner.temp" in WORKFLOW


# --- docs-only follow-ups reuse green evidence instead of re-earning it ---------------------------------------------


def _executable_plan() -> vp.ValidationPlan:
    return vp.classify([".github/workflows/ci.yml", "tools/ci/validation_plan.py"])


def test_a_docs_only_delta_over_green_evidence_takes_the_cheap_path_without_downgrading_the_classification() -> None:
    plan = vp.apply_evidence_reuse(_executable_plan(), ["docs/Subsystems/Testing/PR-X.md", "STATUS.md"], previous_green=True)
    assert plan.reuse_previous_evidence and plan.cheap_path
    assert not plan.docs_only and plan.full_census  # the base-to-head classification is unchanged


@pytest.mark.parametrize(
    ("delta", "green"),
    [
        (["docs/x.md"], False),  # previous head not green (failed, in flight or never validated): full validation
        (["src/video/svd_native.py"], True),  # the delta is executable
        (["docs/x.md", "tools/ci/validation_plan.py"], True),  # a mixed delta is executable
        ([], True),
    ],
)
def test_evidence_is_never_reused_unless_the_delta_is_docs_only_over_green_evidence(delta: list[str], green: bool) -> None:
    plan = vp.apply_evidence_reuse(_executable_plan(), delta, previous_green=green)
    assert not plan.reuse_previous_evidence and not plan.cheap_path


def test_a_pure_docs_pr_needs_no_reuse_and_the_workflow_reads_the_previous_head_checks() -> None:
    docs = vp.classify(["docs/x.md"])
    assert vp.apply_evidence_reuse(docs, ["docs/x.md"], previous_green=True) is docs
    assert "github.event.before" in WORKFLOW and "--previous-green" in WORKFLOW
    assert "tools/ci/previous_evidence.py" in WORKFLOW  # the policy is a tested helper, not jq in YAML
