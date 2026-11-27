"""Update the live checkout to an approved ``origin/main`` commit and restart (LAUNCH-UPDATE-1).

Design and owner decisions: ``docs/work_packages/LAUNCH-UPDATE_remote_restart.md``. This module holds the pieces that
do not need the running application:

* :func:`preflight` decides, read-only apart from ``git fetch``, whether the checkout may be fast-forwarded: branch
  ``main`` tracking ``origin/main``, the expected ``origin`` URL, no staged or modified tracked files, ``origin/main``
  equal to the commit the requester was shown and a descendant of ``HEAD``, the target commit signed by GitHub
  (SAFE-UPDATE, :func:`github_signature_check`), and the target's pinned constraints still satisfied by the current
  ``.venv`` (nothing is ever installed).
* :class:`LiveUpdateStore` keeps the intent, the updater's result, the started marker, the last receipt and the
  owner's switch as small JSON files under ``%LOCALAPPDATA%\\StableNew\\live-update``, outside the checkout, so an
  update can never change them.
* :func:`launch_updater_process` starts ``scripts/update_and_restart.ps1`` (copied next to the state first, so the
  old, already-trusted version runs) as a detached process that outlives the app.

Every Git call is a fixed argument list (no shell); a requested SHA is validated as 40 lowercase hex characters before
it reaches Git, and no ref name, path, remote or option ever comes from a request.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.utils.atomic_io import atomic_write_json, atomic_write_text

# Reason codes (receipt to the desktop now, to the phone in LAUNCH-UPDATE-2).
INVALID_REQUEST = "invalid_request"
REMOTE_UPDATE_DISABLED = "remote_update_disabled"
UPDATE_IN_PROGRESS = "update_in_progress"
RATE_LIMITED = "rate_limited"
WRONG_BRANCH = "wrong_branch"
WRONG_UPSTREAM = "wrong_upstream"
ORIGIN_MISMATCH = "origin_mismatch"
DIRTY_CHECKOUT = "dirty_checkout"
FETCH_FAILED = "fetch_failed"
TARGET_MOVED = "target_moved"
ALREADY_CURRENT = "already_current"
NOT_FAST_FORWARD = "not_fast_forward"
NOT_GITHUB_SIGNED = "not_github_signed"
GITHUB_UNAVAILABLE = "github_unavailable"
ENVIRONMENT_DRIFT = "environment_drift"
BUSY_TIMEOUT = "busy_timeout"
UPDATER_FAILED = "updater_failed"
GIT_FAILED = "git_failed"
QUEUE_UNAVAILABLE = "queue_unavailable"
UPDATER_LOST = "updater_lost"

REASON_TEXT = {
    INVALID_REQUEST: "The request did not name a valid commit.",
    REMOTE_UPDATE_DISABLED: "Remote update is switched off on this PC.",
    UPDATE_IN_PROGRESS: "An update is already in progress.",
    RATE_LIMITED: "An update ran less than 10 minutes ago.",
    WRONG_BRANCH: "The checkout is not on branch main.",
    WRONG_UPSTREAM: "Local main does not track origin/main.",
    ORIGIN_MISMATCH: "The origin remote is not the expected repository.",
    DIRTY_CHECKOUT: "The checkout has uncommitted changes to tracked files.",
    FETCH_FAILED: "origin could not be fetched.",
    TARGET_MOVED: "origin/main moved after the update was requested.",
    ALREADY_CURRENT: "Already up to date.",
    NOT_FAST_FORWARD: "origin/main is not a fast-forward of local main.",
    NOT_GITHUB_SIGNED: (
        "The newest commit on origin/main is not a merge GitHub signed, so it was not installed. "
        "Merge the change through a pull request on GitHub and check again, "
        "or review the commit and update by hand at the desk."
    ),
    GITHUB_UNAVAILABLE: (
        "GitHub could not be asked whether it signed the new commit, so nothing was changed. "
        "Check this PC's internet connection and try again in a few minutes."
    ),
    ENVIRONMENT_DRIFT: "The update needs packages this environment does not have; nothing was installed.",
    BUSY_TIMEOUT: "The running job did not finish within the wait limit; the queue continues.",
    UPDATER_FAILED: "The updater could not be started.",
    GIT_FAILED: "Git failed.",
    QUEUE_UNAVAILABLE: "The job queue is not reachable, so the running job cannot be waited for.",
    "old_app_did_not_exit": "StableNew did not exit, so nothing was changed.",
    "checkout_changed": "The checkout changed after the check; it was left as it was.",
    "merge_failed": "The fast-forward failed; the checkout was left as it was.",
    "rolled_back": "The new version did not start; local main was moved back and the previous version restarted.",
    UPDATER_LOST: "The updater stopped without a result; check the checkout at the desk.",
    "rollback_failed": "The new version did not start and the rollback failed; fix it at the desk.",
}

EXPECTED_ORIGIN = "https://github.com/destroyer42/StableNew2.git"
#: GitHub's record of one commit of the expected repository (public; read without credentials).
GITHUB_COMMITS_API = "https://api.github.com/repos/destroyer42/StableNew2/commits"
#: The account GitHub commits as when it merges a pull request; it signs those commits with its own key.
GITHUB_SIGNER = "web-flow"
CONSTRAINTS_PATH = "constraints/windows-py314-cu130.txt"
REPO_ROOT = Path(__file__).resolve().parents[2]
UPDATER_SCRIPT = REPO_ROOT / "scripts" / "update_and_restart.ps1"
STATE_DIR_ENV = "STABLENEW_LIVE_UPDATE_DIR"

_SHA = re.compile(r"[0-9a-f]{40}")
_GIT_TIMEOUT = 120.0
_ENV_CHECK_TIMEOUT = 300.0
_JSON_LIMIT = 64 * 1024
_GITHUB_TIMEOUT = 20.0
_GITHUB_LIMIT = 4 * 1024 * 1024


@dataclass(frozen=True)
class GitResult:
    code: int
    out: str
    err: str


GitRunner = Callable[[Sequence[str]], GitResult]


@dataclass(frozen=True)
class Preflight:
    ok: bool
    reason: str
    old_sha: str
    target_sha: str
    detail: str = ""
    commits_ahead: int = 0


@dataclass(frozen=True)
class UpdaterLaunch:
    repo_root: Path
    state_dir: Path
    old_pid: int
    old_sha: str
    target_sha: str


def valid_sha(value: object) -> bool:
    return isinstance(value, str) and _SHA.fullmatch(value) is not None


def same_origin(configured: str, expected: str) -> bool:
    def norm(url: str) -> str:
        text = url.strip().rstrip("/").lower()
        return text[:-4] if text.endswith(".git") else text

    return bool(configured.strip()) and norm(configured) == norm(expected)


def subprocess_git(repo: Path, *, timeout: float = _GIT_TIMEOUT) -> GitRunner:
    """A runner for ``git -C <repo> <args>``: argument list, no shell, no prompt, bounded time."""

    executable = shutil.which("git") or "git"
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}

    def run(args: Sequence[str]) -> GitResult:
        try:
            completed = subprocess.run(
                [executable, "-C", str(repo), *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return GitResult(-1, "", str(error))
        return GitResult(completed.returncode, completed.stdout.strip(), completed.stderr.strip())

    return run


def read_target_file(git: GitRunner, sha: str, path: str) -> str | None:
    """A tracked file's text at ``sha`` without checking it out; ``None`` when it does not exist there."""

    if not valid_sha(sha):
        return None
    result = git(["show", f"{sha}:{path}"])
    if result.code != 0:
        return None
    return result.out + "\n" if result.out and not result.out.endswith("\n") else result.out


def _run_bounded(argv: Sequence[str], timeout: float) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return -1, str(error)
    return completed.returncode, (completed.stdout + completed.stderr).strip()


def environment_check(
    repo_root: Path,
    *,
    python: Path,
    read_file: Callable[[str, str], str | None],
    run: Callable[[Sequence[str], float], tuple[int, str]] = _run_bounded,
) -> Callable[[str], tuple[bool, str]]:
    """The launcher's own read-only check (interpreter policy + exact pins), against the target's constraints."""

    checker = repo_root / "tools" / "runtime" / "check_launch_environment.py"

    def check(sha: str) -> tuple[bool, str]:
        text = read_file(sha, CONSTRAINTS_PATH)
        if text is None:
            return False, f"{CONSTRAINTS_PATH} does not exist in the target commit"
        with tempfile.TemporaryDirectory(prefix="stablenew-live-update-") as folder:
            constraints = Path(folder) / "constraints.txt"
            atomic_write_text(constraints, text)
            code, output = run(
                [str(python), str(checker), "--constraints", str(constraints)], _ENV_CHECK_TIMEOUT
            )
        lines = [line for line in output.splitlines() if line.strip()]
        return code == 0, "\n".join(lines[-8:])

    return check


def _github_json(url: str) -> tuple[int, Any]:
    """One anonymous GET of a fixed ``https://api.github.com`` URL: the status and the decoded body.

    A refused status is returned with no body. A network failure, a cut-off response or an undecodable body raises
    ``OSError``, ``HTTPException`` or ``ValueError``; the caller reports each as ``github_unavailable``.
    """

    request = urllib.request.Request(  # noqa: S310 - the URL is a module constant plus a validated SHA
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "StableNew-live-update"},
    )
    try:
        with urllib.request.urlopen(  # noqa: S310
            request, timeout=_GITHUB_TIMEOUT, context=ssl.create_default_context()
        ) as response:
            if not str(response.geturl()).startswith("https://api.github.com/"):
                raise OSError("GitHub redirected the request to another host")
            return int(response.status), json.loads(response.read(_GITHUB_LIMIT))
    except urllib.error.HTTPError as error:
        return int(error.code), None


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def github_signature_check(
    *,
    fetch_json: Callable[[str], tuple[int, Any]] | None = None,
    api: str = GITHUB_COMMITS_API,
) -> Callable[[str], tuple[str, str]]:
    """A check that GitHub signed a commit: ``("", "")`` when it did, else a reason code and a short detail.

    The same rule as the gateway deployer (``services/deploy/stablenew_deploy.py`` ``verify_target``): GitHub reports
    ``verification.verified`` true and the committer is ``web-flow``, which is what a pull request merged on GitHub
    produces. The deployer's other two conditions, on ``main`` and forward only, are already established here by Git
    (the target is the fetched ``origin/main`` and a descendant of ``HEAD``).

    ``not_github_signed``: GitHub answered and the commit is unknown to it, unsigned, or committed by someone else.
    ``github_unavailable``: no usable answer (no network, a timeout, a rate limit, a server error). Both refuse.
    """

    def check(sha: str) -> tuple[str, str]:
        if not valid_sha(sha):
            return NOT_GITHUB_SIGNED, "not a commit id"
        fetch = fetch_json or _github_json
        try:
            status, body = fetch(f"{api}/{sha}")
        except (OSError, ValueError, http.client.HTTPException) as error:
            return GITHUB_UNAVAILABLE, f"GitHub did not answer: {error}"[:300]
        if status in (404, 422):
            return NOT_GITHUB_SIGNED, f"GitHub does not know commit {sha[:12]} (HTTP {status})."
        if status != 200 or not isinstance(body, dict):
            return GITHUB_UNAVAILABLE, f"GitHub answered HTTP {status}."
        if body.get("sha") != sha:
            return NOT_GITHUB_SIGNED, f"GitHub answered for a different commit than {sha[:12]}."
        commit = _mapping(body.get("commit"))
        verification = _mapping(commit.get("verification"))
        committer = _mapping(body.get("committer"))
        verified = verification.get("verified") is True
        login = re.sub(r"[^A-Za-z0-9-]", "", str(committer.get("login") or ""))[:40]
        if not verified or login != GITHUB_SIGNER:
            signed = "signature verified" if verified else "no verified signature"
            return (
                NOT_GITHUB_SIGNED,
                f"Commit {sha[:12]}: {signed}, committed by {login or 'an unknown account'}.",
            )
        return "", ""

    return check


def preflight(
    git: GitRunner,
    *,
    expected_sha: str | None,
    expected_origin: str,
    env_check: Callable[[str], tuple[bool, str]],
    signature_check: Callable[[str], tuple[str, str]],
) -> Preflight:
    """Whether the checkout may be fast-forwarded to ``expected_sha`` (or to the fetched ``origin/main``).

    ``signature_check`` (:func:`github_signature_check` in production) is asked only about a target that already
    passed every Git check, and before the slower environment check. It has no default: a caller cannot leave the
    signature unchecked by omission. A check that raises is a refusal (``github_unavailable``).
    """

    if expected_sha is not None and not valid_sha(expected_sha):
        return Preflight(False, INVALID_REQUEST, "", "")

    def refuse(reason: str, old: str = "", target: str = "", detail: str = "") -> Preflight:
        return Preflight(False, reason, old, target, detail)

    branch = git(["rev-parse", "--abbrev-ref", "HEAD"])
    if branch.code != 0:
        return refuse(GIT_FAILED, detail=branch.err)
    if branch.out != "main":
        return refuse(WRONG_BRANCH, detail=branch.out)
    upstream = git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
    if upstream.code != 0 or upstream.out != "origin/main":
        return refuse(WRONG_UPSTREAM, detail=upstream.out or upstream.err)
    origin = git(["remote", "get-url", "origin"])
    if origin.code != 0 or not same_origin(origin.out, expected_origin):
        return refuse(ORIGIN_MISMATCH, detail=origin.out)
    status = git(["status", "--porcelain", "--untracked-files=no"])
    if status.code != 0:
        return refuse(GIT_FAILED, detail=status.err)
    if status.out:
        return refuse(DIRTY_CHECKOUT, detail=status.out[:500])
    head = git(["rev-parse", "HEAD"])
    if head.code != 0 or not valid_sha(head.out):
        return refuse(GIT_FAILED, detail=head.err)
    old = head.out
    fetched = git(["fetch", "--no-tags", "--quiet", "origin", "main"])
    if fetched.code != 0:
        return refuse(FETCH_FAILED, old, detail=fetched.err[:500])
    remote = git(["rev-parse", "refs/remotes/origin/main"])
    if remote.code != 0 or not valid_sha(remote.out):
        return refuse(FETCH_FAILED, old, detail=remote.err)
    target = remote.out
    if expected_sha is not None and target != expected_sha:
        return refuse(TARGET_MOVED, old, target, f"origin/main is {target}, not {expected_sha}")
    if target == old:
        return refuse(ALREADY_CURRENT, old, target)
    if git(["merge-base", "--is-ancestor", old, target]).code != 0:
        return refuse(NOT_FAST_FORWARD, old, target)
    count = git(["rev-list", "--count", f"{old}..{target}"])
    ahead = int(count.out) if count.code == 0 and count.out.isdigit() else 0
    try:
        unsigned, why = signature_check(target)
    except Exception as error:  # noqa: BLE001 - an unanswered signature question never lets an update through
        unsigned, why = GITHUB_UNAVAILABLE, f"The signature check failed: {error}"[:300]
    if unsigned:
        return Preflight(False, unsigned, old, target, why, ahead)
    ok, detail = env_check(target)
    if not ok:
        return Preflight(False, ENVIRONMENT_DRIFT, old, target, detail, ahead)
    return Preflight(True, "", old, target, "", ahead)


# -- state --------------------------------------------------------------------------------------------------------


def default_state_dir() -> Path:
    override = os.environ.get(STATE_DIR_ENV)
    if override:
        return Path(override)
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    if not local.is_absolute():
        raise OSError("Windows local application data is unavailable")
    return local / "StableNew" / "live-update"


class LiveUpdateStore:
    """Small JSON files outside the checkout: intent, result, started marker, last receipt, settings."""

    NAMES = frozenset(
        {"intent.json", "result.json", "started.json", "last_result.json", "settings.json"}
    )

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    def _path(self, name: str) -> Path:
        if name not in self.NAMES:
            raise ValueError(name)
        return self.directory / name

    def read(self, name: str) -> dict[str, Any] | None:
        path = self._path(name)
        try:
            if path.stat().st_size > _JSON_LIMIT:
                return None
            # utf-8-sig: Windows PowerShell 5.1 writes a byte order mark.
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return None
        return value if isinstance(value, dict) else None

    def write(self, name: str, payload: dict[str, Any]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self._path(name), payload)

    def remove(self, name: str) -> None:
        try:
            self._path(name).unlink()
        except FileNotFoundError:
            pass


# -- updater ------------------------------------------------------------------------------------------------------


def _powershell() -> str:
    system_root = os.environ.get("SystemRoot") or r"C:\Windows"
    candidate = Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return str(candidate) if candidate.is_file() else "powershell.exe"


def updater_command(launch: UpdaterLaunch, *, powershell: str, script: Path) -> list[str]:
    for sha in (launch.old_sha, launch.target_sha):
        if not valid_sha(sha):
            raise ValueError("invalid commit")
    return [
        powershell,
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-WindowStyle",
        "Hidden",
        "-File",
        str(script),
        "-RepoRoot",
        str(launch.repo_root),
        "-StateDir",
        str(launch.state_dir),
        "-OldPid",
        str(int(launch.old_pid)),
        "-OldSha",
        launch.old_sha,
        "-TargetSha",
        launch.target_sha,
    ]


def launch_updater_process(launch: UpdaterLaunch) -> None:
    """Start the updater detached from this process; it waits for this process to exit before changing anything."""

    if sys.platform != "win32":
        raise OSError("the live updater runs on Windows only")
    launch.state_dir.mkdir(parents=True, exist_ok=True)
    script = launch.state_dir / "update_and_restart.ps1"
    shutil.copyfile(UPDATER_SCRIPT, script)
    argv = updater_command(launch, powershell=_powershell(), script=script)
    # CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS (by value: the names exist only on Windows builds of Python).
    flags = 0x00000200 | 0x00000008
    breakaway = (
        0x01000000  # CREATE_BREAKAWAY_FROM_JOB: survive a job object that closes with this process
    )
    try:
        subprocess.Popen(
            argv, creationflags=flags | breakaway, close_fds=True, cwd=str(launch.state_dir)
        )
    except OSError:
        subprocess.Popen(argv, creationflags=flags, close_fds=True, cwd=str(launch.state_dir))
