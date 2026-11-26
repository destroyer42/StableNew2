"""STATUS.md is current state only (audit P2-1): capped, free of PR narrative and stale labels, with no dead references."""

from __future__ import annotations

import importlib.util
import json
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
    problems = _truth().status_problems(_status_root(tmp_path, text))
    assert [p for p in problems if "ratchet" not in p] == []


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


def _ratchet_root(tmp_path: Path, *, mypy_errors: int = 1403, line: str | None = None) -> Path:
    """A throwaway repo whose per-file fixture baselines produce the figures on its STATUS ratchet line."""
    ci = tmp_path / "tools" / "ci"
    ci.mkdir(parents=True)
    (ci / "mypy_baseline.json").write_text(
        json.dumps({"counts": {"src/a.py": 1, "src/b.py": mypy_errors - 1}}), encoding="utf-8"
    )
    (ci / "ruff_ratchet_baseline.json").write_text(
        json.dumps(
            {
                "format": {"files": [f"src/f{i}.py" for i in range(378)]},
                "rules": {"counts": {"src/a.py": {"BLE001": 1213, "S110": 479, "S112": 35}}},
            }
        ),
        encoding="utf-8",
    )
    (ci / "architecture_baseline.json").write_text(
        json.dumps(
            {
                "counts": {
                    "src/a.py": {
                        "daemon_threads": 13,
                        "raw_threads": 9,
                        "utils_upward_imports": 18,
                        "controller_gui_imports": 6,
                        "non_atomic_writes": 17,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    text = line or (
        "- Ratchets only allow recorded debt to shrink: whole-`src` strict mypy (1,403 errors in\n"
        "  2 files), unformatted files (378), excepts (BLE001 1,213, S110 479, S112 35), threads\n"
        "  (daemon threads 13, raw threads 9, utils importing upward 18, controller importing the GUI 6, non-atomic file writes 17).\n"
        "- Next bullet.\n"
    )
    return _status_root(tmp_path, text)


def test_ratchet_numbers_matching_the_baselines_pass(tmp_path: Path) -> None:
    assert _truth().status_problems(_ratchet_root(tmp_path)) == []


def test_a_ratchet_line_without_figures_passes(tmp_path: Path) -> None:
    line = "- Ratchets only allow recorded debt to shrink: mypy, unformatted files and excepts.\n- Next bullet.\n"
    assert _truth().status_problems(_ratchet_root(tmp_path, line=line)) == []


def test_a_wrong_ratchet_number_is_rejected(tmp_path: Path) -> None:
    root = _ratchet_root(tmp_path, mypy_errors=1500)
    problems = _truth().status_problems(root)
    assert any("mypy errors 1,403" in p and "1,500" in p for p in problems), problems


def test_the_ratchet_figures_are_derived_from_the_per_file_baselines(tmp_path: Path) -> None:
    figures = _truth().ratchet_figures(_ratchet_root(tmp_path, mypy_errors=10))
    assert figures is not None
    assert (
        figures["mypy errors"] == 10
        and figures["mypy files"] == 2
        and figures["unformatted files"] == 378
    )
    assert figures["S110"] == 479 and figures["non-atomic writes"] == 17


def test_a_missing_ratchet_line_is_rejected(tmp_path: Path) -> None:
    root = _ratchet_root(tmp_path, line="- Nothing about ratchets here.\n")
    assert any("no ratchet line" in p for p in _truth().status_problems(root))


def test_an_overlong_status_line_is_rejected(tmp_path: Path) -> None:
    truth = _truth()
    root = _ratchet_root(tmp_path)
    status = root / "STATUS.md"
    status.write_text(
        status.read_text(encoding="utf-8") + "x" * (truth.STATUS_MAX_LINE_BYTES + 1) + "\n",
        encoding="utf-8",
    )
    problems = truth.status_problems(root)
    assert any("bytes; the cap is" in p for p in problems), problems
