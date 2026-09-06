from __future__ import annotations

import subprocess
from pathlib import Path

from tools.ci.check_repository_completeness import inspect_repository


def _run_git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        check=True,
    )


def _write(root: Path, relative_path: str, content: str = "") -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _repository(tmp_path: Path, *, ignore_rule: str = "/state/\n") -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _run_git(root, "init", "--quiet")
    _write(root, ".gitignore", ignore_rule)
    _write(root, "src/__init__.py")
    _write(root, "src/app.py", "from src.state.helper import VALUE\n")
    _write(root, "src/state/__init__.py")
    _write(root, "src/state/helper.py", "VALUE = 1\n")
    _run_git(root, "add", ".gitignore", "src")
    return root


def _codes(root: Path) -> set[str]:
    return {issue.code for issue in inspect_repository(root)}


def test_complete_tracked_source_passes(tmp_path: Path) -> None:
    root = _repository(tmp_path)

    assert inspect_repository(root) == []


def test_untracked_source_fails(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    _write(root, "src/untracked.py")

    assert "UNTRACKED_SOURCE" in _codes(root)


def test_broad_state_ignore_rule_fails_for_source(tmp_path: Path) -> None:
    root = _repository(tmp_path, ignore_rule="state/\n")

    issues = inspect_repository(root)

    assert "IGNORED_SOURCE" in {issue.code for issue in issues}
    assert any(issue.path == "src/state/helper.py" for issue in issues)


def test_missing_internal_import_fails(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    (root / "src/state/helper.py").unlink()

    assert {issue.code for issue in inspect_repository(root)} == {
        "MISSING_INTERNAL_IMPORT",
        "MISSING_TRACKED_SOURCE",
    }


def test_external_import_does_not_require_local_module(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    _write(root, "src/external.py", "import requests\n")
    _run_git(root, "add", "src/external.py")

    assert inspect_repository(root) == []


def test_namespace_subpackage_is_a_valid_internal_module(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    _write(root, "src/app.py", "from src.config import app_config\n")
    _write(root, "src/config/app_config.py", "VALUE = 1\n")
    _run_git(root, "add", "src")

    assert inspect_repository(root) == []


def test_utf8_bom_source_is_read_using_python_encoding_rules(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    path = root / "src/bom_module.py"
    path.write_bytes(b"\xef\xbb\xbfVALUE = 1\n")
    _run_git(root, "add", "src/bom_module.py")

    assert inspect_repository(root) == []


def test_relative_internal_import_is_checked(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    _write(root, "src/state/consumer.py", "from .missing import VALUE\n")
    _run_git(root, "add", "src/state/consumer.py")

    issues = inspect_repository(root)

    assert any(
        issue.code == "MISSING_INTERNAL_IMPORT"
        and issue.detail == "cannot resolve src.state.missing"
        for issue in issues
    )
