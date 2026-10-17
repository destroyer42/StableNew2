"""STATUS.md is current state only (audit P2-1): capped, free of PR narrative and stale labels, with no dead references."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _truth():
    spec = importlib.util.spec_from_file_location(
        "ci_truth_status_contract", ROOT / "tools" / "ci" / "ci_truth.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _status_root(tmp_path: Path, text: str) -> Path:
    (tmp_path / "STATUS.md").write_text(text, encoding="utf-8")
    return tmp_path


def test_the_real_status_file_satisfies_its_own_contract() -> None:
    assert _truth().status_problems(ROOT) == []


def test_a_status_file_over_the_cap_is_rejected(tmp_path: Path) -> None:
    root = _status_root(tmp_path, "\n".join(f"line {i}" for i in range(151)))
    assert any("cap is 150" in p for p in _truth().status_problems(root))


def test_pr_narrative_style_labels_are_rejected(tmp_path: Path) -> None:
    truth = _truth()
    for phrase in (
        "PR #104 open, not merged",
        "(local implementation)",
        "locally validated",
        "local deterministic validation and required gate green",
        "awaiting integration",
        "supported Windows Python 3.11/3.12 bootstrap",
    ):
        problems = truth.status_problems(_status_root(tmp_path, f"- {phrase}\n"))
        assert any("marker" in p for p in problems), phrase


def test_a_reference_to_a_missing_repository_path_is_rejected(tmp_path: Path) -> None:
    problems = _truth().status_problems(
        _status_root(tmp_path, "See `docs/Subsystems/Image/does_not_exist.md`.\n")
    )
    assert any("does not exist: docs/Subsystems/Image/does_not_exist.md" in p for p in problems)


def test_references_that_exist_and_non_path_code_spans_are_accepted(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "real.md").write_text("x", encoding="utf-8")
    text = "See `docs/real.md`, run `python tools/ci/run_pr_gate.py`, branch `main`, flag `--update`, glob `docs/*.md`.\n"
    assert _truth().status_problems(_status_root(tmp_path, text)) == []


def test_a_missing_status_file_is_reported(tmp_path: Path) -> None:
    assert _truth().status_problems(tmp_path) == ["STATUS.md is missing"]


def test_the_old_log_style_status_would_have_failed_every_rule() -> None:
    """The pre-P2-1 file (kept in Git) violated the cap, the markers and referenced stale labels; prove the guard bites."""

    import subprocess

    old = subprocess.run(
        ["git", "show", "aebfdd2a:STATUS.md"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if old.returncode != 0:  # shallow clone without that commit: nothing to compare against
        return
    problems = _truth().status_problems(_root_with(old.stdout))
    assert any("cap is 150" in p for p in problems) and any("marker" in p for p in problems)


def _root_with(text: str) -> Path:
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="status-contract-"))
    (root / "STATUS.md").write_text(text, encoding="utf-8")
    return root
