"""PR-DEVEX-CI-110: previous-head evidence reuse is a pure, conservative, repository-owned policy."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "ci"))

import previous_evidence as pe  # noqa: E402


def run(
    name: str,
    conclusion: str | None,
    *,
    status: str = "completed",
    id: int = 1,
    app: str = "github-actions",
) -> dict:  # noqa: A002
    return {
        "id": id,
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "app": {"slug": app},
    }


GREEN = [
    run("required", "success", id=10),
    run("full-suite", "success", id=12),
    run("windows", "success", id=13),
]


def decide(runs: list[dict], *, ancestor: bool = True) -> pe.Decision:
    return pe.evaluate(runs, base_is_ancestor=ancestor)


def test_all_selected_checks_green_is_eligible() -> None:
    assert decide(GREEN).green
    assert decide(
        [run("required", "success"), run("full-suite", "skipped"), run("windows", "skipped")]
    ).green


@pytest.mark.parametrize(
    "conclusion",
    [
        "failure",
        "cancelled",
        "timed_out",
        "action_required",
        "neutral",
        "stale",
        "startup_failure",
        None,
    ],
)
def test_a_completed_but_not_successful_census_blocks_reuse(conclusion: str | None) -> None:
    """The historical bug: full-suite was status=completed, conclusion=failure and still counted as green."""

    runs = [run("required", "success"), run("full-suite", conclusion)]
    decision = decide(runs)
    assert not decision.green and "full-suite" in decision.reason


@pytest.mark.parametrize("status", ["queued", "in_progress", "waiting", "pending"])
def test_in_flight_jobs_cannot_be_reused(status: str) -> None:
    for name in ("required", "full-suite", "windows"):
        runs = [
            run(n, "success" if n != name else None, status=status if n == name else "completed")
            for n in ("required", "full-suite", "windows")
        ]
        assert not decide(runs).green, name


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "timed_out", "skipped", None])
def test_a_required_check_that_is_not_success_blocks_reuse(conclusion: str | None) -> None:
    assert not decide([run("required", conclusion), run("full-suite", "skipped")]).green


def test_missing_checks_block_reuse() -> None:
    assert not decide([]).green
    assert not decide(
        [run("required", "success")]
    ).green  # no full-suite record at all (e.g. a pre-CI-110 head)
    assert not decide([run("required", "success"), run("full-suite", "success")]).green


def test_the_latest_github_actions_check_run_wins_not_the_first_match() -> None:
    old_failure_new_success = [
        run("required", "failure", id=1),
        run("required", "success", id=9),
        run("full-suite", "skipped"),
        run("windows", "success"),
    ]
    assert decide(old_failure_new_success).green
    old_success_new_failure = [
        run("required", "success", id=1),
        run("required", "failure", id=9),
        run("full-suite", "skipped"),
        run("windows", "success"),
    ]
    assert not decide(old_success_new_failure).green
    rerun = [
        *GREEN,
        run("full-suite", "failure", id=99),
    ]  # a later failing rerun supersedes the earlier success
    assert not decide(rerun).green


def test_only_github_actions_check_runs_count() -> None:
    forged = [
        run("required", "success", app="some-other-app"),
        run("full-suite", "skipped"),
        run("windows", "success"),
    ]
    assert not decide(forged).green
    assert decide(
        [*forged, run("required", "success", id=5)]
    ).green  # the Actions-owned run is what counts


def test_a_base_that_is_not_an_ancestor_of_the_previous_head_disables_reuse() -> None:
    decision = decide(GREEN, ancestor=False)
    assert not decision.green and "unvalidated" in decision.reason


def test_decide_fails_closed_on_any_error_or_missing_input() -> None:
    def boom(_repo: str, _sha: str) -> list[dict]:
        raise subprocess.CalledProcessError(1, "gh")

    assert not pe.decide("o/r", "b" * 40, "a" * 40, fetch=boom, ancestor=lambda *_: True).green
    assert not pe.decide("", "b", "a", fetch=lambda *_: GREEN, ancestor=lambda *_: True).green
    assert pe.decide(
        "o/r", "b" * 40, "a" * 40, fetch=lambda *_: GREEN, ancestor=lambda *_: True
    ).green
    fetched: list[str] = []
    not_ancestor = pe.decide(
        "o/r",
        "b",
        "a",
        fetch=lambda r, s: fetched.append(s) or GREEN,
        ancestor=lambda *_: False,
        docs_only=lambda *_: False,
    )
    assert (
        not not_ancestor.green and fetched == []
    )  # no API call is made when reuse is already impossible


def test_ancestry_is_decided_by_real_git_history(tmp_path: Path) -> None:
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=tmp_path, capture_output=True, text=True, check=True
        ).stdout.strip()

    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    (tmp_path / "f").write_text("1\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    old_base = git("rev-parse", "HEAD")
    git("checkout", "-q", "-b", "feature")
    (tmp_path / "g").write_text("x\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "feature work")
    feature_head = git("rev-parse", "HEAD")
    git("checkout", "-q", "main")
    (tmp_path / "h").write_text("main moved\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "main advances")
    new_base = git("rev-parse", "HEAD")
    assert pe.base_is_ancestor(
        old_base, feature_head, tmp_path
    )  # the validated head contains the old base
    assert not pe.base_is_ancestor(
        new_base, feature_head, tmp_path
    )  # main advanced: reuse must be refused
    assert not pe.base_is_ancestor(
        new_base, "0" * 40, tmp_path
    )  # an unknown previous head never reuses


def test_the_workflow_uses_the_helper_instead_of_untested_jq_policy() -> None:
    workflow = (Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    assert "tools/ci/previous_evidence.py" in workflow and "jq " not in workflow
    assert "--before" in workflow and "--previous-green" in workflow


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "timed_out", "neutral", None])
def test_windows_evidence_must_be_green(conclusion) -> None:
    assert not decide([*GREEN, run("windows", conclusion, id=99)]).green


def test_success_conclusion_on_an_incomplete_record_is_not_evidence() -> None:
    for name in ("required", "full-suite", "windows"):
        assert not decide([*GREEN, run(name, "success", status="in_progress", id=99)]).green


def test_real_docs_only_base_conflict_and_repeated_docs_followups_reuse_evidence(
    tmp_path: Path,
) -> None:
    import validation_plan as vp

    def git(*args, check=True):
        return subprocess.run(
            ["git", *args], cwd=tmp_path, capture_output=True, text=True, check=check
        ).stdout.strip()

    git("init", "-q", "-b", "main")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "test")
    (tmp_path / "STATUS.md").write_text("base\n")
    git("add", "STATUS.md")
    git("commit", "-qm", "base")
    git("checkout", "-qb", "feature")
    (tmp_path / "feature.py").write_text("result = 1\n")
    (tmp_path / "STATUS.md").write_text("feature documentation\n")
    git("add", "feature.py", "STATUS.md")
    git("commit", "-qm", "validated feature")
    validated = git("rev-parse", "HEAD")
    git("checkout", "-q", "main")
    (tmp_path / "STATUS.md").write_text("main documentation\n")
    git("commit", "-qam", "docs on main")
    base = git("rev-parse", "HEAD")
    assert not pe.base_is_ancestor(base, validated, tmp_path)
    assert pe.base_advance_is_docs_only(base, validated, tmp_path)
    git("checkout", "-q", "feature")
    git("merge", "--no-commit", "main", check=False)
    (tmp_path / "STATUS.md").write_text("both accepted documentation changes\n")
    git("add", "STATUS.md")
    git("commit", "-qm", "resolve docs only")
    head = git("rev-parse", "HEAD")
    delta = vp.changed_files_direct(validated, head, tmp_path)
    assert delta == ["STATUS.md"]
    assert pe.evaluate(GREEN, base_is_ancestor=False, base_docs_only=True).green
    assert vp.apply_evidence_reuse(
        vp.classify(["feature.py"]), delta, previous_green=True
    ).cheap_path
    (tmp_path / "STATUS.md").write_text("another documentation correction\n")
    git("commit", "-qam", "docs followup")
    assert vp.classify(vp.changed_files_direct(head, "HEAD", tmp_path)).docs_only
    assert pe.evaluate(
        [run("required", "success"), run("full-suite", "skipped"), run("windows", "skipped")],
        base_is_ancestor=True,
    ).green
    git("checkout", "-q", "main")
    (tmp_path / "other.py").write_text("changed = True\n")
    git("add", "other.py")
    git("commit", "-qm", "executable base advance")
    assert not pe.base_advance_is_docs_only("HEAD", validated, tmp_path)
    with pytest.raises(subprocess.CalledProcessError):
        pe.base_advance_is_docs_only("0" * 40, validated, tmp_path)
