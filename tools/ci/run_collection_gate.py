"""Run pytest collection in an isolated directory and detect repo pollution."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYTEST_CONFIG = ROOT / "pyproject.toml"

# These ignored runtime paths caused real pollution during the PR-MVP-010 audit.
# They need explicit fingerprints because Git status intentionally hides them.
GUARDED_RUNTIME_PATHS = (
    "data/webui_cache.json",
    "output",
    "runs",
    "temp",
    "tmp",
    "manifests",
    "logs",
    "test_output",
    "tmp_prompt_pack_probe",
    "tmp_prompt_pack_probe2",
    "tmp_prompt_pack_probe3",
    "tmp_prompt_pack_probe4",
    "tmp_prompt_pack_probe5",
)

DEFAULT_COLLECTION_EXCLUDES = (
    "tests/gui",
    "tests/gui_v1_legacy",
    "tests/legacy",
    "tests/quarantine",
    "tests/scripts",
)


@dataclass(frozen=True)
class RepositorySnapshot:
    """Content identity for tracked, visible-untracked, and guarded files."""

    files: tuple[tuple[str, str], ...]
    guarded: tuple[tuple[str, str], ...]


def _git_paths(*args: str) -> tuple[str, ...]:
    result = subprocess.run(
        ["git", *args, "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return tuple(
        os.fsdecode(raw_path)
        for raw_path in result.stdout.split(b"\0")
        if raw_path
    )


def _file_digest(path: Path) -> str:
    if path.is_symlink():
        return f"symlink:{os.readlink(path)}"
    if not path.exists():
        return "missing"
    if path.is_dir():
        return "directory"

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"file:{digest.hexdigest()}"


def _tree_fingerprint(relative_path: str) -> tuple[tuple[str, str], ...]:
    root = ROOT / relative_path
    if not root.exists() and not root.is_symlink():
        return ((relative_path, "missing"),)
    if not root.is_dir() or root.is_symlink():
        return ((relative_path, _file_digest(root)),)

    entries: list[tuple[str, str]] = [(relative_path, "directory")]
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        rel = path.relative_to(ROOT).as_posix()
        entries.append((rel, _file_digest(path)))
    return tuple(entries)


def snapshot_repository() -> RepositorySnapshot:
    """Hash Git-visible content and known ignored runtime destinations."""

    tracked = _git_paths("ls-files")
    untracked = _git_paths("ls-files", "--others", "--exclude-standard")
    visible_paths = sorted(set(tracked) | set(untracked))
    files = tuple((rel, _file_digest(ROOT / rel)) for rel in visible_paths)

    guarded_entries: list[tuple[str, str]] = []
    for relative_path in GUARDED_RUNTIME_PATHS:
        guarded_entries.extend(_tree_fingerprint(relative_path))

    # Root-level log files are ignored by .gitignore but are still pollution.
    for path in sorted(ROOT.glob("*.log"), key=lambda item: item.as_posix()):
        guarded_entries.append((path.name, _file_digest(path)))

    return RepositorySnapshot(files=files, guarded=tuple(guarded_entries))


def _changed_paths(
    before: Iterable[tuple[str, str]],
    after: Iterable[tuple[str, str]],
) -> list[str]:
    before_map = dict(before)
    after_map = dict(after)
    return sorted(
        path
        for path in set(before_map) | set(after_map)
        if before_map.get(path) != after_map.get(path)
    )


def repository_test_target(target: str) -> str:
    """Resolve a repo-relative pytest node ID while preserving its selector."""

    path, separator, node = target.partition("::")
    resolved = str((ROOT / path).resolve())
    return f"{resolved}::{node}" if separator else resolved


def run_pytest_gate(pytest_args: Sequence[str]) -> int:
    """Run pytest away from the repo and fail on any observed content change."""

    before = snapshot_repository()
    with tempfile.TemporaryDirectory(prefix="stablenew-pytest-") as temp_dir:
        temp_root = Path(temp_dir)
        environment = os.environ.copy()
        environment.update(
            {
                "MPLBACKEND": "Agg",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONHASHSEED": "0",
                "STABLENEW_NO_WEBUI": "1",
                "STABLENEW_TEST_MODE": "1",
            }
        )
        current_python_path = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            str(ROOT)
            if not current_python_path
            else os.pathsep.join((str(ROOT), current_python_path))
        )
        command = [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            str(PYTEST_CONFIG),
            "--rootdir",
            str(ROOT),
            "-p",
            "no:cacheprovider",
            "--basetemp",
            str(temp_root / "pytest-temp"),
            *pytest_args,
        ]
        completed = subprocess.run(
            command,
            cwd=temp_root,
            env=environment,
            check=False,
        )

    after = snapshot_repository()
    changed = _changed_paths(before.files, after.files)
    guarded_changed = _changed_paths(before.guarded, after.guarded)
    if changed or guarded_changed:
        print("pytest changed repository contents:", file=sys.stderr)
        for path in sorted(set(changed) | set(guarded_changed)):
            print(f"  {path}", file=sys.stderr)
        return 1
    return completed.returncode


def main() -> int:
    return run_pytest_gate(
        (
            "--collect-only",
            "-q",
            *(
                f"--ignore={repository_test_target(path)}"
                for path in DEFAULT_COLLECTION_EXCLUDES
            ),
            repository_test_target("tests"),
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
