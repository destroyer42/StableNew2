"""docs/CODE_MAP.md is generated from module docstrings and the task map stays short with live paths (audit P2-3)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _generator():
    return _load("tools/generate_code_map.py", "generate_code_map_under_test")


def test_the_committed_code_map_is_current() -> None:
    committed = (ROOT / "docs" / "CODE_MAP.md").read_text(encoding="utf-8")
    assert committed == _generator().render(ROOT), (
        "docs/CODE_MAP.md is stale; run: python tools/generate_code_map.py"
    )


def test_summaries_are_the_first_sentence_of_the_module_docstring() -> None:
    summarize = _generator().summarize
    assert (
        summarize('"""Does a thing. Then more detail\nacross lines."""\nx = 1\n') == "Does a thing"
    )
    assert summarize('"""Wraps\nacross lines\n\nSecond paragraph."""\n') == "Wraps across lines"
    assert summarize("x = 1\n") == "(no docstring)"
    assert summarize("def broken(:\n") == "(could not be parsed)"
    assert len(summarize('"""' + "word " * 80 + '"""\n')) <= 110


def test_the_map_lists_modules_in_a_stable_order_without_line_counts(tmp_path: Path) -> None:
    generator = _generator()
    package = tmp_path / "src" / "pkg"
    package.mkdir(parents=True)
    (package / "b.py").write_text('"""Second."""\n', encoding="utf-8")
    (package / "a.py").write_text('"""First."""\n', encoding="utf-8")
    (package / "__pycache__").mkdir()
    (package / "__pycache__" / "skip.py").write_text('"""Skipped."""\n', encoding="utf-8")
    rendered = generator.render(tmp_path)
    assert rendered.index("`a.py`") < rendered.index("`b.py`")
    assert "Skipped" not in rendered
    assert "2 of 2 modules have a docstring" in rendered


def test_the_task_map_satisfies_its_contract() -> None:
    assert _load("tools/ci/ci_truth.py", "ci_truth_task_map").task_map_problems(ROOT) == []


def test_a_task_map_that_grows_or_points_nowhere_is_rejected(tmp_path: Path) -> None:
    truth = _load("tools/ci/ci_truth.py", "ci_truth_task_map_negative")
    task_map = tmp_path / "docs" / "CODEX_MAP.md"
    task_map.parent.mkdir(parents=True)
    task_map.write_text("\n".join(["row"] * 61) + "\n", encoding="utf-8")
    assert any("cap is 60" in p for p in truth.task_map_problems(tmp_path))
    task_map.write_text("| Task | `src/does_not_exist.py` |\n", encoding="utf-8")
    assert any("does not exist" in p for p in truth.task_map_problems(tmp_path))
