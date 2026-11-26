"""LAUNCH-UPDATE-1: ``scripts/update_and_restart.ps1`` against disposable repositories (Windows).

The live checkout is a clone of a temporary bare ``origin``; its ``scripts/launch_stablenew.ps1`` is a stub that writes
the started marker the real app writes and exits with the code stored in the commit. The "old app" is a short-lived
Python process the test owns. No real checkout, launcher or StableNew process is involved.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.helpers.live_update_repos import git, make_repos

ROOT = Path(__file__).resolve().parents[2]
UPDATER = ROOT / "scripts" / "update_and_restart.ps1"
POWERSHELL = shutil.which("powershell.exe") if sys.platform == "win32" else None
windows_only = pytest.mark.skipif(
    POWERSHELL is None or shutil.which("git") is None, reason="Windows PowerShell updater behavior"
)

STUB_LAUNCHER = r"""
$state = $env:STABLENEW_LIVE_UPDATE_DIR
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$code = [int](Get-Content -LiteralPath (Join-Path $root "exit_code.txt") -Raw)
$head = (& git -C $root rev-parse HEAD).Trim()
Add-Content -LiteralPath (Join-Path $state "launches.log") -Value $head
if ($code -eq 0) {
    $intent = Get-Content -LiteralPath (Join-Path $state "intent.json") -Raw | ConvertFrom-Json
    @{ update_id = $intent.update_id; head_sha = $head; pid = $PID } | ConvertTo-Json -Compress |
        Set-Content -LiteralPath (Join-Path $state "started.json") -Encoding UTF8
}
exit $code
"""

FILES = {
    "src/main.py": "print('v1')\n",
    "scripts/launch_stablenew.ps1": STUB_LAUNCHER,
    "exit_code.txt": "0\n",
}


@pytest.fixture
def repos(tmp_path):
    return make_repos(tmp_path, FILES)


@pytest.fixture
def state(tmp_path):
    path = tmp_path / "live update state"
    path.mkdir()
    return path


def _old_app(seconds: float) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", f"import time; time.sleep({seconds})"])


def _write_intent(state: Path, old: str, new: str, update_id: str = "u-test-1") -> None:
    intent = {"update_id": update_id, "old_sha": old, "target_sha": new, "record_id": "r1"}
    (state / "intent.json").write_text(json.dumps(intent), encoding="utf-8")


def run_updater(repos, state, old_pid, old, new, *, exit_wait=20, health=30):
    assert POWERSHELL is not None
    env = {**os.environ, "STABLENEW_LIVE_UPDATE_DIR": str(state), "GIT_CONFIG_NOSYSTEM": "1"}
    completed = subprocess.run(
        [
            POWERSHELL,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(UPDATER),
            "-RepoRoot",
            str(repos.live),
            "-StateDir",
            str(state),
            "-OldPid",
            str(old_pid),
            "-OldSha",
            old,
            "-TargetSha",
            new,
            "-ExitWaitSeconds",
            str(exit_wait),
            "-HealthSeconds",
            str(health),
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=180,
    )
    result_path = state / "result.json"
    assert result_path.exists(), completed.stdout + completed.stderr
    return json.loads(result_path.read_text(encoding="utf-8-sig")), completed


def launches(state: Path) -> list[str]:
    path = state / "launches.log"
    if not path.exists():
        return []
    return [
        line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()
    ]


# --- Static contract ----------------------------------------------------------------------------


def _code(path: Path) -> str:
    text = re.sub(r"<#.*?#>", "", path.read_text(encoding="utf-8"), flags=re.DOTALL)
    return "\n".join(
        line for line in text.splitlines() if line.strip() and not line.strip().startswith("#")
    )


def test_updater_never_kills_installs_or_touches_origin() -> None:
    code = _code(UPDATER).lower()

    for forbidden in (
        "stop-process",
        "taskkill",
        ".kill(",
        "pip",
        "bootstrap",
        "git push",
        "push",
        "--force",
        "reset --hard",
        "clean -",
        "invoke-expression",
        "iex ",
        "remove-item",
    ):
        assert forbidden not in code, forbidden
    assert '"merge", "--ff-only"' in code
    assert '"reset", "--keep"' in code
    assert "launch_stablenew.ps1" in code


def test_updater_validates_both_shas_before_any_git_call() -> None:
    code = _code(UPDATER)

    assert "function Invoke-Git" in code
    assert code.index("^[0-9a-f]{40}$") < code.index("Invoke-Git @(")


# --- Behavior (Windows) -------------------------------------------------------------------------


@windows_only
def test_fast_forward_then_relaunch_reports_old_and_new_sha(repos, state):
    old = repos.head
    new = repos.merge_upstream({"src/main.py": "print('v2')\n"})
    git(repos.live, "fetch", "-q", "origin", "main")
    (repos.live / "data").mkdir()
    (repos.live / "data" / "history.db").write_bytes(b"owner state")
    (repos.live / "my-notes.txt").write_text("untracked\n", encoding="utf-8")
    _write_intent(state, old, new)
    app = _old_app(1)

    result, run = run_updater(repos, state, app.pid, old, new)

    assert result["status"] == "applied", run.stdout + run.stderr
    assert (result["old_sha"], result["new_sha"], result["health"]) == (old, new, "confirmed")
    assert result["update_id"] == "u-test-1"
    assert repos.head == new
    assert (repos.live / "src/main.py").read_text(encoding="utf-8") == "print('v2')\n"
    assert (repos.live / "data" / "history.db").read_bytes() == b"owner state"
    assert (repos.live / "my-notes.txt").read_text(encoding="utf-8") == "untracked\n"
    assert launches(state) == [new]
    assert git(repos.live, "rev-parse", "origin/main") == new  # origin untouched
    assert git(repos.origin, "rev-parse", "main") == new


@windows_only
def test_a_failed_start_rolls_local_main_back_and_relaunches_the_old_code(repos, state):
    old = repos.head
    new = repos.merge_upstream({"exit_code.txt": "11\n"}, message="breaks the launch")
    git(repos.live, "fetch", "-q", "origin", "main")
    _write_intent(state, old, new)

    result, run = run_updater(repos, state, _old_app(0.5).pid, old, new)

    assert (result["status"], result["reason"]) == ("refused", "rolled_back"), (
        run.stdout + run.stderr
    )
    assert result["old_sha"] == old and result["new_sha"] == old
    assert "11" in result["detail"]
    assert repos.head == old
    assert launches(state) == [new, old]
    assert git(repos.origin, "rev-parse", "main") == new  # origin untouched


@windows_only
def test_target_moved_after_the_old_app_exited_relaunches_unchanged(repos, state):
    old = repos.head
    shown = repos.merge_upstream({"a.txt": "a\n"})
    repos.merge_upstream({"b.txt": "b\n"})
    git(repos.live, "fetch", "-q", "origin", "main")
    _write_intent(state, old, shown)

    result, _run = run_updater(repos, state, _old_app(0.5).pid, old, shown)

    assert (result["status"], result["reason"]) == ("refused", "target_moved")
    assert repos.head == old
    assert launches(state) == [old]  # the owner's app is never left stopped


@windows_only
def test_a_tracked_edit_made_after_the_preflight_is_refused(repos, state):
    old = repos.head
    new = repos.merge_upstream({"a.txt": "a\n"})
    git(repos.live, "fetch", "-q", "origin", "main")
    (repos.live / "src/main.py").write_text("print('edited meanwhile')\n", encoding="utf-8")
    _write_intent(state, old, new)

    result, _run = run_updater(repos, state, _old_app(0.5).pid, old, new)

    assert (result["status"], result["reason"]) == ("refused", "checkout_changed")
    assert repos.head == old
    assert (repos.live / "src/main.py").read_text(encoding="utf-8") == "print('edited meanwhile')\n"
    assert launches(state) == [old]


@windows_only
def test_head_moved_since_the_preflight_is_refused(repos, state):
    old = repos.head
    new = repos.merge_upstream({"a.txt": "a\n"})
    git(repos.live, "fetch", "-q", "origin", "main")
    git(repos.live, "merge", "-q", "--ff-only", new)  # someone updated at the desk meanwhile
    _write_intent(state, old, new)

    result, _run = run_updater(repos, state, _old_app(0.5).pid, old, new)

    assert (result["status"], result["reason"]) == ("refused", "checkout_changed")
    assert launches(state) == [new]


@windows_only
def test_old_app_that_does_not_exit_is_left_alone(repos, state):
    old = repos.head
    new = repos.merge_upstream({"a.txt": "a\n"})
    git(repos.live, "fetch", "-q", "origin", "main")
    _write_intent(state, old, new)
    app = _old_app(60)
    try:
        started = time.monotonic()
        result, _run = run_updater(repos, state, app.pid, old, new, exit_wait=2)

        assert (result["status"], result["reason"]) == ("refused", "old_app_did_not_exit")
        assert time.monotonic() - started < 60
        assert app.poll() is None  # never killed
        assert repos.head == old
        assert launches(state) == []  # the old app is still the running instance
    finally:
        app.kill()
        app.wait(timeout=10)


@windows_only
def test_malformed_sha_is_refused_without_touching_the_checkout(repos, state):
    old = repos.head
    _write_intent(state, old, "main")

    result, _run = run_updater(repos, state, _old_app(0.2).pid, old, "main")

    assert (result["status"], result["reason"]) == ("refused", "invalid_request")
    assert repos.head == old
    assert launches(state) == [old]  # relaunched unchanged
