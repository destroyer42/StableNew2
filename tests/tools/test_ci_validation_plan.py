"""PR-DEVEX-CI-110: the repository-owned validation policy (classifier) and the workflow that consumes it."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "ci"))

import validation_plan as vp  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def covered(target: str, targets: tuple[str, ...]) -> bool:
    return any(target == t or target.startswith(t.rstrip("/") + "/") for t in targets)


# --- classifier acceptance ------------------------------------------------------------------------------------


def test_docs_only_diff_is_docs_only_with_no_tests_scheduled() -> None:
    plan = vp.classify(["docs/Subsystems/Image/PR-X.md", "STATUS.md", "docs/StableNew Roadmap v2.6.md", ".github/pull_request_template.md"])
    assert plan.docs_only and plan.lanes == (vp.LANE_DOCS_ONLY,)
    assert not plan.full_census and not plan.run_affected and plan.affected_targets == () and plan.changed_tests == ()


def test_executable_or_configuration_text_is_never_docs_only() -> None:
    for path in ("src/notes.md", "tests/data/readme.txt", "presets/global_positive.txt", "docs/tool.json", "docs/script.py",
                 ".github/workflows/ci.yml", "scripts/run.ps1", "config/managed_forge_runtime.json", ".gitignore", "tools/x.md.py"):
        assert not vp.classify([path]).docs_only, path


def test_image_source_and_image_test_route_to_image_and_the_changed_test_runs() -> None:
    plan = vp.classify(["src/image_backends/forge_webui_backend.py", "tests/image_backends/test_forge_klein_profile.py"])
    assert vp.LANE_IMAGE in plan.lanes and not plan.docs_only and not plan.full_census
    assert "tests/image_backends/test_forge_klein_profile.py" in plan.changed_tests
    assert covered("tests/image_backends/test_forge_klein_profile.py", plan.affected_targets)


def test_image_and_runtime_sources_do_not_drag_in_the_whole_core_lane() -> None:
    """Proportionate routing: the contract gate protects the boundary; core runs only when core source changes."""

    for path in ("src/image_backends/forge_webui_backend.py", "src/api/forge_client.py", "src/api/webui_process_manager.py"):
        plan = vp.classify([path])
        assert vp.LANE_CORE not in plan.lanes and not plan.full_census, path
        assert not covered("tests/controller", plan.affected_targets), path
    runtime = vp.classify(["src/api/webui_process_manager.py"])
    assert runtime.lanes == (vp.LANE_RUNTIME,) and covered("tests/services/test_runtime_transition_service.py", runtime.affected_targets)


def test_video_source_routes_to_video() -> None:
    plan = vp.classify(["src/video/svd_native.py"])
    assert plan.lanes == (vp.LANE_VIDEO,) and covered("tests/video", plan.affected_targets)


def test_gui_source_routes_to_gui() -> None:
    plan = vp.classify(["src/gui/views/review_tab_frame_v2.py"])
    assert plan.lanes == (vp.LANE_GUI,) and covered("tests/gui_v2", plan.affected_targets)


@pytest.mark.parametrize("path", ["src/queue/job_repository.py", "src/pipeline/njr_core_v26.py", "src/history/job_history_store.py"])
def test_queue_njr_compiler_runner_source_routes_to_core(path: str) -> None:
    plan = vp.classify([path])
    assert vp.LANE_CORE in plan.lanes and covered("tests/queue", plan.affected_targets) and not plan.full_census


def test_qualification_harness_only_routes_to_qualification_tools() -> None:
    plan = vp.classify(["tools/qualification/img115/run.py", "tools/acceptance/img_116_klein_acceptance.py"])
    assert plan.lanes == (vp.LANE_QUALIFICATION,) and covered("tests/tools", plan.affected_targets)


@pytest.mark.parametrize(
    "path",
    ["pyproject.toml", "requirements.txt", "requirements-svd.txt", "constraints/forge-windows-py313-cu130-neo-d70373eb.txt",
     "pytest.ini", ".github/workflows/ci.yml", "tools/ci/validation_plan.py", "tools/ci/run_required_smoke.py",
     "tests/conftest.py", "tests/helpers/njr_factory.py", "tests/helpers/fake_webui_transport.py", "tests/fixtures/anything.py"],
)
def test_global_dependency_pytest_ci_policy_and_shared_test_infrastructure_require_the_full_census(path: str) -> None:
    plan = vp.classify([path])
    assert plan.full_census and vp.LANE_FULL_CENSUS in plan.lanes and plan.full_census_reasons
    assert not plan.docs_only


def test_ci_framework_and_policy_changes_also_activate_the_ci_authority_lane() -> None:
    for path in (".github/workflows/ci.yml", "tools/ci/validation_plan.py", "pyproject.toml", "tests/conftest.py"):
        assert vp.LANE_CI_AUTHORITY in vp.classify([path]).lanes, path


@pytest.mark.parametrize("path", ["mystery/thing.py", "main.py", "newtool/run.sh", "somefile.cfg", "docs/tool.json"])
def test_unknown_ownership_is_never_assumed_core_only_it_requires_the_full_census(path: str) -> None:
    plan = vp.classify([path])
    assert not plan.docs_only and plan.full_census and vp.LANE_FULL_CENSUS in plan.lanes
    assert plan.escalations and "unknown" in plan.escalations[0] and plan.full_census_reasons
    assert plan.affected_targets == () and not plan.run_affected  # the census subsumes the lanes


@pytest.mark.parametrize("path", [".gitignore", ".editorconfig", "presets/global_negative.txt", "packs/anything.json", "config/other.json", "data/x.json"])
def test_known_data_and_repo_meta_trees_are_owned_not_unknown(path: str) -> None:
    plan = vp.classify([path])
    assert not plan.full_census and not plan.escalations and vp.LANE_CORE in plan.lanes and plan.run_affected


def test_mixed_changes_are_additive_not_dominated_by_one_lane() -> None:
    plan = vp.classify(["src/image_backends/forge_webui_backend.py", "src/gui/klein_panel_projection.py"])
    assert {vp.LANE_IMAGE, vp.LANE_GUI} <= set(plan.lanes)
    assert covered("tests/image_backends", plan.affected_targets) and covered("tests/gui_v2", plan.affected_targets)


def test_executable_source_plus_docs_stays_executable() -> None:
    plan = vp.classify(["src/video/svd_native.py", "docs/Subsystems/Video/x.md", "STATUS.md"])
    assert not plan.docs_only and vp.LANE_VIDEO in plan.lanes


def test_a_later_docs_commit_cannot_downgrade_the_base_to_head_classification(tmp_path: Path) -> None:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, text=True, check=True).stdout.strip()

    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    (tmp_path / "README.md").write_text("base\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    base = git("rev-parse", "HEAD")
    git("checkout", "-q", "-b", "feature")
    (tmp_path / "src" / "queue").mkdir(parents=True)
    (tmp_path / "src" / "queue" / "q.py").write_text("x = 1\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "executable change")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "note.md").write_text("docs only\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "docs correction on top")
    changed = vp.changed_files_between(base, "HEAD", root=tmp_path)
    assert set(changed) == {"src/queue/q.py", "docs/note.md"}
    assert not vp.classify(changed).docs_only  # the whole base-to-head set decides, not the last commit
    assert vp.classify(vp.changed_files_between("HEAD~1", "HEAD", root=tmp_path)).docs_only  # last commit alone would lie


def test_every_directly_changed_executable_test_is_guaranteed_to_run() -> None:
    candidates = [
        "tests/utils/test_thread_registry.py",  # backbone
        "tests/photo_optimize/" + next((ROOT / "tests" / "photo_optimize").glob("test_*.py")).name,  # domain-only area
        "tests/mocks/" + next((ROOT / "tests" / "mocks").glob("test_*.py")).name,  # shared infrastructure area
        "tests/unit/" + next((ROOT / "tests" / "unit").glob("test_*.py")).name,
        "tests/learning_v2/" + next((ROOT / "tests" / "learning_v2").glob("test_*.py")).name,
    ]
    for path in candidates:
        assert (ROOT / path).exists(), path
        plan = vp.classify([path])
        assert path in plan.changed_tests, path
        # either it runs in a bounded lane/target set or the full census runs everything
        assert plan.full_census or covered(path, plan.affected_targets), path


def test_full_census_suppresses_the_duplicate_affected_lanes() -> None:
    plan = vp.classify(["src/image_backends/forge_webui_backend.py", "pyproject.toml"])
    assert plan.full_census and plan.affected_targets == () and not plan.run_affected
    forced = vp.classify(["src/video/svd_native.py"], force_full="label 'full-census'")
    assert forced.full_census and forced.affected_targets == () and not forced.run_affected


# --- cross-domain source -> test ownership (the lane of a source is not where all its tests live) -----------------------


def _routed(plan: vp.ValidationPlan, test_path: str) -> bool:
    return plan.full_census or covered(test_path, plan.affected_targets)


def test_learning_gui_sources_activate_the_learning_domain_tests_besides_gui() -> None:
    for source in ("src/gui/controllers/learning_controller.py", "src/gui/learning_state.py", "src/gui/views/learning_review_panel.py",
                   "src/gui_v2/adapters/learning_adapter_v2.py"):
        plan = vp.classify([source])
        assert vp.LANE_GUI in plan.lanes and not plan.full_census, source
        for test in ("tests/learning_v2", "tests/learning", "tests/controller/test_learning_controller_njr.py",
                     "tests/integration/test_learning_review_recommendation_e2e.py"):
            assert _routed(plan, test), (source, test)


def test_prompt_workspace_and_pack_model_state_sources_activate_state_and_promptpack_tests_besides_gui() -> None:
    for source in ("src/gui/models/prompt_pack_model.py", "src/gui/models/prompt_metadata.py", "src/gui/prompt_workspace_state.py"):
        plan = vp.classify([source])
        assert vp.LANE_GUI in plan.lanes and not plan.full_census, source
        for test in ("tests/state/test_prompt_workspace_state.py", "tests/promptpacks/test_storage.py", "tests/test_json_unification.py"):
            assert _routed(plan, test), (source, test)


def test_central_gui_state_and_panels_reach_their_core_runtime_image_and_video_owners() -> None:
    state = vp.classify(["src/gui/app_state_v2.py"])
    assert {vp.LANE_GUI, vp.LANE_CORE} <= set(state.lanes) and _routed(state, "tests/queue")
    assert _routed(vp.classify(["src/gui/panels_v2/running_job_panel_v2.py"]), "tests/integration/test_job_timing_e2e.py")
    assert _routed(vp.classify(["src/gui/preview_panel_v2.py"]), "tests/controller/test_pack_draft_to_normalized_preview_v2.py")
    assert vp.LANE_RUNTIME in vp.classify(["src/gui/api_status_panel.py"]).lanes
    assert vp.LANE_IMAGE in vp.classify(["src/gui/dropdown_loader_v2.py"]).lanes
    assert vp.LANE_VIDEO in vp.classify(["src/gui/views/movie_clips_tab_frame_v2.py"]).lanes
    assert _routed(vp.classify(["src/gui/stage_cards_v2/adetailer_stage_card_v2.py"]), "tests/test_pr_008.py")


def _direct_importers(sources: list[str]) -> dict[str, set[str]]:
    """Re-derive the evidence: which test files import each source module directly (static AST scan)."""

    import ast

    wanted = {s: s[: -len(".py")].replace("/", ".") for s in sources}
    found: dict[str, set[str]] = {s: set() for s in sources}
    for path in sorted((ROOT / "tests").rglob("test_*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith(("tests/legacy", "tests/quarantine", "tests/gui_v1_legacy", "tests/scripts")):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("src"):
                names = [node.module, *(f"{node.module}.{alias.name}" for alias in node.names)]
            elif isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            for source, dotted in wanted.items():
                if dotted in names:
                    found[source].add(rel)
    return found


def test_every_test_that_directly_imports_a_cross_domain_gui_source_is_routed_to_it() -> None:
    """Strengthened ownership proof: not 'some lane owns the file' but 'the changed source runs the tests that import it'."""

    sources = [
        "src/gui/controllers/learning_controller.py", "src/gui/learning_state.py", "src/gui/models/prompt_pack_model.py",
        "src/gui/prompt_workspace_state.py", "src/gui/models/prompt_metadata.py", "src/gui/app_state_projection_sink.py",
        "src/gui/panels_v2/running_job_panel_v2.py", "src/gui/preview_panel_v2.py", "src/gui/sidebar_panel_v2.py",
        "src/gui/job_history_panel_v2.py", "src/gui/views/learning_review_panel.py", "src/gui/views/movie_clips_tab_frame_v2.py",
        "src/gui/api_status_panel.py", "src/gui/dropdown_loader_v2.py", "src/gui_v2/adapters/learning_adapter_v2.py",
    ]
    live = [s for s in sources if (ROOT / s).exists()]
    importers = _direct_importers(live)
    missing: dict[str, list[str]] = {}
    for source, tests in importers.items():
        plan = vp.classify([source])
        gaps = sorted(t for t in tests if not _routed(plan, t))
        if gaps:
            missing[source] = gaps[:5]
    assert not missing, f"changed source would not run the tests that import it: {missing}"


def test_a_bounded_executable_pr_does_not_run_the_full_census_but_runs_its_lanes() -> None:
    plan = vp.classify(["src/image_backends/forge_webui_backend.py"])
    assert not plan.full_census and plan.run_affected and plan.affected_targets
    assert len(plan.affected_targets) < 200  # a lane selection, never the whole tree


# --- escape hatches and periodic evidence ----------------------------------------------------------------------


def test_full_census_can_be_requested_without_editing_workflow_yaml() -> None:
    assert vp.full_census_request("pull_request", [], "ordinary change") == ""
    assert vp.full_census_request("pull_request", ["bug", "Full-Census"], "") != ""
    assert vp.full_census_request("pull_request", [], "risky\n\n[full-census]") != ""
    assert vp.full_census_request("workflow_dispatch", [], "") != ""
    assert vp.full_census_request("schedule", [], "") != ""


def test_the_plan_cli_writes_github_outputs_for_the_workflow(tmp_path: Path) -> None:
    out = tmp_path / "gh_output"
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "ci" / "validation_plan.py"), "--files", "src/video/svd_native.py", "--github-output", str(out)],
        capture_output=True, text=True, check=True,
    )
    text = out.read_text(encoding="utf-8")
    assert "docs_only=false" in text and "full_census=false" in text and "run_affected=true" in text
    import re

    block = re.search(r"targets<<(TARGETS_[0-9a-f]{32})\n(.*?)\n\1\n", text, re.S)
    assert "lanes=video" in text and block and "tests/video" in block.group(2)  # random delimiter: no path can end the block
    assert '"docs_only": false' in result.stdout


# --- policy self-consistency ----------------------------------------------------------------------------------


def test_every_lane_target_pattern_matches_something_so_routing_cannot_silently_rot() -> None:
    for lane, patterns in vp.LANE_TARGETS.items():
        for pattern in patterns:
            assert vp.expand_targets([pattern]), f"{lane}: {pattern} matches nothing"
    for pattern, targets in vp.DOMAIN_TARGETS:
        for target in targets:
            assert vp.expand_targets([target]), f"domain {pattern}: {target} matches nothing"


def test_every_collected_test_file_is_owned_by_a_lane_a_domain_target_or_the_census_only_set() -> None:
    owned = set()
    for patterns in vp.LANE_TARGETS.values():
        owned.update(vp.expand_targets(patterns))
    for _pattern, targets in vp.DOMAIN_TARGETS:
        owned.update(vp.expand_targets(targets))
    ignored = ("tests/gui_v1_legacy", "tests/legacy", "tests/quarantine", "tests/scripts", "tests/__pycache__")
    unowned = []
    for path in sorted((ROOT / "tests").rglob("test_*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith(ignored) or rel.startswith(vp.FULL_CENSUS_ONLY_AREAS):
            continue
        if not covered(rel, tuple(owned)):
            unowned.append(rel)
    assert not unowned, f"test files with no lane ownership (a PR touching them would never run them via a lane): {unowned[:10]}"


# --- the workflow consumes the plan and keeps its operational contracts ----------------------------------------


def test_the_workflow_consumes_the_repository_owned_plan_rather_than_embedding_policy() -> None:
    assert "tools/ci/validation_plan.py" in WORKFLOW
    for output in ("docs_only", "cheap_path", "full_census", "run_affected", "targets"):
        assert f"steps.plan.outputs.{output}" in WORKFLOW
    assert "paths-filter" not in WORKFLOW and "dorny/" not in WORKFLOW  # no third-party path-filter action


def test_docs_only_runs_no_python_environment_or_tests() -> None:
    required = WORKFLOW[WORKFLOW.index("  required:"):WORKFLOW.index("  affected:")]
    for marker in ("Set up Python 3.14", "Install pip tools", "Lint (Ruff)", "Run mypy smoke gate", "Run required positive-list gate"):
        step = required[required.index(marker) - 200: required.index(marker) + 120]
        assert "steps.plan.outputs.cheap_path != 'true'" in step, marker
    cheap = required[required.index("Cheap documentation checks"):required.index("Set up Python 3.14")]
    assert "git diff --check" in cheap and "python3 tools/ci/check_repository_completeness.py" in cheap


def test_expensive_work_waits_for_the_required_gate_and_the_census_does_not_duplicate_the_lanes() -> None:
    affected = WORKFLOW[WORKFLOW.index("  affected:"):WORKFLOW.index("  full-suite-shard:")]
    full = WORKFLOW[WORKFLOW.index("  full-suite-shard:"):]  # the shard jobs plus the aggregate verdict
    assert "needs: required" in affected and "needs.required.outputs.run_affected == 'true'" in affected
    assert "needs: required" in full and "needs.required.outputs.full_census == 'true'" in full
    assert full.count("needs.required.outputs.full_census == 'true'") == 2  # shards and aggregate both wait for it
    assert "full_census" not in affected and "run_affected" not in full


def test_main_has_a_periodic_census_and_manual_dispatch_and_one_workflow_per_pr_head() -> None:
    triggers = WORKFLOW[WORKFLOW.index("\non:"):WORKFLOW.index("\nconcurrency:")]
    assert "cron:" in triggers and "1,3,5" in triggers  # Monday/Wednesday/Friday
    assert "workflow_dispatch:" in triggers and "push:" not in triggers


def test_superseded_pull_request_heads_are_still_cancelled() -> None:
    concurrency = WORKFLOW[WORKFLOW.index("\nconcurrency:"):WORKFLOW.index("\njobs:")]
    assert "cancel-in-progress: true" in concurrency and "github.event.pull_request.number" in concurrency


def test_the_required_check_identity_is_preserved() -> None:
    assert "\n  required:\n" in WORKFLOW
    required = WORKFLOW[WORKFLOW.index("  required:"):WORKFLOW.index("  affected:")]
    assert "continue-on-error" not in required  # the required gate is never masked


def test_the_plan_artifact_stays_outside_the_checkout_so_the_clean_tree_check_holds() -> None:
    assert '"$RUNNER_TEMP/plan.json"' in WORKFLOW and "runner.temp" in WORKFLOW


# --- docs-only follow-ups reuse green evidence instead of re-earning it ---------------------------------------------


def _executable_plan() -> vp.ValidationPlan:
    return vp.classify([".github/workflows/ci.yml", "tools/ci/validation_plan.py"])  # a full-census CI-authority change


def test_a_docs_only_delta_over_green_evidence_takes_the_cheap_path_without_downgrading_the_classification() -> None:
    plan = vp.apply_evidence_reuse(_executable_plan(), ["docs/Subsystems/Testing/PR-X.md", "STATUS.md"], previous_green=True)
    assert plan.reuse_previous_evidence and plan.cheap_path and not plan.run_affected
    assert not plan.docs_only and plan.full_census  # the base-to-head classification is unchanged


@pytest.mark.parametrize(
    ("delta", "green", "forced"),
    [
        (["docs/x.md"], False, ""),  # previous head not green (failed, in flight or never validated): full routing
        (["src/video/svd_native.py"], True, ""),  # the delta is executable
        (["docs/x.md", "tools/ci/validation_plan.py"], True, ""),  # a mixed delta is executable
        (["docs/x.md"], True, "label 'full-census'"),  # an explicit census request always wins
        ([], True, ""),
    ],
)
def test_evidence_is_never_reused_unless_the_delta_is_docs_only_over_green_evidence(delta: list[str], green: bool, forced: str) -> None:
    plan = vp.apply_evidence_reuse(_executable_plan(), delta, previous_green=green, forced_full=forced)
    assert not plan.reuse_previous_evidence and not plan.cheap_path


def test_a_pure_docs_pr_needs_no_reuse_and_the_workflow_reads_the_previous_head_checks() -> None:
    docs = vp.classify(["docs/x.md"])
    assert vp.apply_evidence_reuse(docs, ["docs/x.md"], previous_green=True) is docs
    assert "github.event.before" in WORKFLOW and "--previous-green" in WORKFLOW
    assert "tools/ci/previous_evidence.py" in WORKFLOW  # the policy is a tested helper, not jq in YAML
