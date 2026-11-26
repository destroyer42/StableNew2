"""Disposable Git repositories for LAUNCH-UPDATE tests: a bare ``origin`` and a ``live`` clone on ``main``.

Nothing here touches a real checkout. Every repository lives under the test's ``tmp_path``.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

_IDENTITY = ("-c", "user.name=LAUNCH-UPDATE test", "-c", "user.email=launch-update@example.invalid")
_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1"}


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *_IDENTITY, *args],
        capture_output=True,
        text=True,
        env=_ENV,
        timeout=60,
        check=True,
    )
    return result.stdout.strip()


@dataclass
class Repos:
    origin: Path
    live: Path
    upstream: Path  # a second clone that plays "a PR merged to main"

    @property
    def head(self) -> str:
        return git(self.live, "rev-parse", "HEAD")

    def merge_upstream(self, files: dict[str, str], message: str = "merged PR") -> str:
        """Commit ``files`` in the upstream clone and push to origin/main; returns the new SHA."""

        for name, text in files.items():
            path = self.upstream / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
            git(self.upstream, "add", name)
        git(self.upstream, "commit", "-q", "-m", message)
        git(self.upstream, "push", "-q", "origin", "main")
        return git(self.upstream, "rev-parse", "HEAD")


def make_repos(tmp_path: Path, files: dict[str, str]) -> Repos:
    seed = tmp_path / "seed"
    seed.mkdir()
    git(seed, "init", "-q", "--initial-branch=main")
    for name, text in files.items():
        path = seed / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    (seed / ".gitignore").write_text("data/\n*.log\n", encoding="utf-8", newline="\n")
    git(seed, "add", "-A")
    git(seed, "commit", "-q", "-m", "initial")
    origin = tmp_path / "origin.git"
    subprocess.run(
        ["git", "clone", "-q", "--bare", str(seed), str(origin)], check=True, env=_ENV, timeout=60
    )
    live = tmp_path / "live checkout (test)"
    upstream = tmp_path / "upstream"
    for clone in (live, upstream):
        subprocess.run(
            ["git", "clone", "-q", str(origin), str(clone)], check=True, env=_ENV, timeout=60
        )
    return Repos(origin=origin, live=live, upstream=upstream)
