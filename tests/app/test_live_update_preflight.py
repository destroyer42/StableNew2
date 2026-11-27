"""LAUNCH-UPDATE-1: the read-only preflight that decides whether the live checkout may be fast-forwarded.

Real Git against disposable repositories (``tests/helpers/live_update_repos.py``). The environment check is a fake;
its real command line is covered separately.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from src.app import live_update as lu
from tests.helpers.live_update_repos import git, make_repos

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")

FILES = {"src/main.py": "print('v1')\n", "constraints/windows-py314-cu130.txt": "pkg==1.0\n"}


@pytest.fixture
def repos(tmp_path):
    return make_repos(tmp_path, FILES)


def _env_ok(_sha: str) -> tuple[bool, str]:
    return True, ""


def _signed(_sha: str) -> tuple[str, str]:
    return "", ""


def check(repos, expected_sha=None, *, env=_env_ok, origin=None, signature=_signed):
    return lu.preflight(
        lu.subprocess_git(repos.live),
        expected_sha=expected_sha,
        expected_origin=origin if origin is not None else str(repos.origin),
        env_check=env,
        signature_check=signature,
    )


def test_a_clean_fast_forward_to_the_shown_sha_passes(repos):
    old = repos.head
    new = repos.merge_upstream({"src/main.py": "print('v2')\n"})

    result = check(repos, new)

    assert result.ok and result.reason == ""
    assert (result.old_sha, result.target_sha, result.commits_ahead) == (old, new, 1)
    assert repos.head == old  # the preflight never moves HEAD or the tree
    assert (repos.live / "src/main.py").read_text(encoding="utf-8") == "print('v1')\n"


def test_without_an_expected_sha_the_fetched_origin_main_is_the_target(repos):
    new = repos.merge_upstream({"a.txt": "a\n"})

    assert check(repos).target_sha == new


def test_already_current(repos):
    assert check(repos).reason == lu.ALREADY_CURRENT


@pytest.mark.parametrize(
    "sha", ["", "abc", "G" * 40, "A" * 40, "a" * 39, "a" * 40 + "\n", "main", "HEAD~1"]
)
def test_a_malformed_expected_sha_is_refused_before_any_git_call(repos, sha):
    calls = []

    def recording(args):
        calls.append(args)
        return lu.GitResult(0, "", "")

    result = lu.preflight(
        recording,
        expected_sha=sha,
        expected_origin=str(repos.origin),
        env_check=_env_ok,
        signature_check=_signed,
    )

    assert result.reason == lu.INVALID_REQUEST and calls == []


def test_target_moved_when_origin_main_is_not_the_shown_sha(repos):
    shown = repos.merge_upstream({"a.txt": "a\n"})
    repos.merge_upstream({"b.txt": "b\n"})

    assert check(repos, shown).reason == lu.TARGET_MOVED


def test_wrong_branch(repos):
    git(repos.live, "switch", "-q", "-c", "feature")
    repos.merge_upstream({"a.txt": "a\n"})

    assert check(repos).reason == lu.WRONG_BRANCH


def test_wrong_upstream(repos):
    git(repos.live, "branch", "-q", "--unset-upstream")

    assert check(repos).reason == lu.WRONG_UPSTREAM


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("https://github.com/owner/Repo.git", "https://github.com/owner/repo"),
        ("https://github.com/owner/repo/", "https://github.com/owner/repo.git"),
    ],
)
def test_origin_url_comparison_ignores_case_and_git_suffix(configured, expected):
    assert lu.same_origin(configured, expected)
    assert not lu.same_origin(configured, "https://github.com/someone-else/repo")


def test_origin_mismatch(repos):
    assert (
        check(repos, origin="https://github.com/someone-else/repo.git").reason == lu.ORIGIN_MISMATCH
    )


def test_dirty_tracked_file_is_refused_but_untracked_files_are_allowed(repos):
    repos.merge_upstream({"a.txt": "a\n"})
    (repos.live / "notes-untracked.txt").write_text("mine\n", encoding="utf-8")
    assert check(repos).ok

    (repos.live / "src/main.py").write_text("print('local edit')\n", encoding="utf-8")
    assert check(repos).reason == lu.DIRTY_CHECKOUT


def test_staged_change_is_refused(repos):
    (repos.live / "new.txt").write_text("x\n", encoding="utf-8")
    git(repos.live, "add", "new.txt")

    assert check(repos).reason == lu.DIRTY_CHECKOUT


def test_not_fast_forward_when_local_main_has_its_own_commit(repos):
    (repos.live / "local.txt").write_text("x\n", encoding="utf-8")
    git(repos.live, "add", "local.txt")
    git(
        repos.live,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.invalid",
        "commit",
        "-q",
        "-m",
        "local",
    )
    repos.merge_upstream({"a.txt": "a\n"})

    assert check(repos).reason == lu.NOT_FAST_FORWARD


def test_fetch_failure(repos, tmp_path):
    repos.origin.rename(tmp_path / "origin moved away.git")

    assert check(repos).reason == lu.FETCH_FAILED


def test_environment_drift_reports_the_checker_detail(repos):
    new = repos.merge_upstream({"constraints/windows-py314-cu130.txt": "pkg==2.0\n"})
    seen = []

    def drifted(sha):
        seen.append(sha)
        return False, "pkg: installed 1.0, pinned 2.0"

    result = check(repos, new, env=drifted)

    assert result.reason == lu.ENVIRONMENT_DRIFT and "pinned 2.0" in result.detail
    assert seen == [new]


def test_target_constraints_are_read_from_the_target_commit_without_checkout(repos, tmp_path):
    new = repos.merge_upstream({"constraints/windows-py314-cu130.txt": "pkg==2.0\n"})
    git(repos.live, "fetch", "-q", "origin", "main")

    text = lu.read_target_file(lu.subprocess_git(repos.live), new, lu.CONSTRAINTS_PATH)

    assert text == "pkg==2.0\n"
    assert (repos.live / lu.CONSTRAINTS_PATH).read_text(encoding="utf-8") == "pkg==1.0\n"


def test_environment_check_command_uses_the_target_constraints(tmp_path):
    calls = []

    def runner(argv, timeout):
        calls.append(argv)
        constraints = Path(argv[argv.index("--constraints") + 1])
        assert constraints.read_text(encoding="utf-8") == "pkg==2.0\n"
        return 1, "pkg: drift"

    def reader(sha, path):
        assert path == lu.CONSTRAINTS_PATH
        return "pkg==2.0\n"

    env_check = lu.environment_check(
        Path("C:/repo"),
        python=Path("C:/repo/.venv/Scripts/python.exe"),
        read_file=reader,
        run=runner,
    )

    assert env_check("a" * 40) == (False, "pkg: drift")
    assert calls[0][0] == str(Path("C:/repo/.venv/Scripts/python.exe"))
    assert calls[0][1] == str(Path("C:/repo") / "tools" / "runtime" / "check_launch_environment.py")


def test_environment_check_refuses_a_target_without_the_constraints_file(tmp_path):
    env_check = lu.environment_check(
        Path("C:/repo"),
        python=Path("python"),
        read_file=lambda sha, path: None,
        run=lambda a, t: (0, ""),
    )

    ok, detail = env_check("a" * 40)

    assert not ok and lu.CONSTRAINTS_PATH in detail


# -- SAFE-UPDATE: the target must be a commit GitHub signed -------------------------------------------------------


@pytest.mark.parametrize("reason", ["not_github_signed", "github_unavailable"])
def test_a_target_github_did_not_vouch_for_is_refused_before_anything_changes(repos, reason):
    old = repos.head
    new = repos.merge_upstream({"src/main.py": "print('v2')\n"})
    asked, env_calls = [], []

    def signature(sha):
        asked.append(sha)
        return reason, "why"

    result = check(repos, new, env=lambda sha: env_calls.append(sha), signature=signature)

    assert (result.ok, result.reason, result.detail) == (False, reason, "why")
    assert (result.old_sha, result.target_sha, result.commits_ahead) == (old, new, 1)
    assert asked == [new] and env_calls == []
    assert repos.head == old
    assert (repos.live / "src/main.py").read_text(encoding="utf-8") == "print('v1')\n"


def test_a_signature_check_that_raises_is_a_refusal(repos):
    repos.merge_upstream({"a.txt": "a\n"})

    def broken(_sha):
        raise RuntimeError("boom")

    result = check(repos, signature=broken)

    assert (result.ok, result.reason) == (False, lu.GITHUB_UNAVAILABLE)


def test_github_is_not_asked_about_a_target_git_already_refuses(repos):
    asked = []

    def signature(sha):
        asked.append(sha)
        return "", ""

    assert check(repos, signature=signature).reason == lu.ALREADY_CURRENT
    shown = repos.merge_upstream({"a.txt": "a\n"})
    repos.merge_upstream({"b.txt": "b\n"})
    assert check(repos, shown, signature=signature).reason == lu.TARGET_MOVED
    (repos.live / "src/main.py").write_text("print('local edit')\n", encoding="utf-8")
    assert check(repos, signature=signature).reason == lu.DIRTY_CHECKOUT
    assert asked == []


def test_the_signature_refusals_say_what_to_do():
    assert "pull request" in lu.REASON_TEXT[lu.NOT_GITHUB_SIGNED]
    assert "try again" in lu.REASON_TEXT[lu.GITHUB_UNAVAILABLE]
