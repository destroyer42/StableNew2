"""AGENTS.md is the only place operating rules live; bridges stay short and point to it (audit P2-4)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _truth():
    spec = importlib.util.spec_from_file_location(
        "ci_truth_rules", ROOT / "tools" / "ci" / "ci_truth.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tree(tmp_path: Path) -> Path:
    for rel in (
        "AGENTS.md",
        "CLAUDE.md",
        ".github/copilot-instructions.md",
        "docs/AGENT_OPERATING_MODEL.md",
        "docs/AI_MODEL_SELECTION.md",
    ):
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("Follow AGENTS.md.\n", encoding="utf-8")
    return tmp_path


def test_the_real_repository_keeps_one_source_for_the_rules() -> None:
    assert _truth().rules_problems(ROOT) == []


def test_a_bridge_file_over_its_cap_is_rejected(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    (root / "CLAUDE.md").write_text("Follow AGENTS.md.\n" + "line\n" * 40, encoding="utf-8")
    assert any("CLAUDE.md" in p and "cap is 40" in p for p in _truth().rules_problems(root))


def test_a_bridge_that_does_not_name_the_authority_is_rejected(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    (root / "docs/AI_MODEL_SELECTION.md").write_text("Choose a model.\n", encoding="utf-8")
    assert any("must name AGENTS.md" in p for p in _truth().rules_problems(root))


def test_restating_a_rule_outside_agents_md_is_rejected(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    agents = root / ".github" / "agents"
    agents.mkdir(parents=True)
    (agents / "builder.agent.md").write_text(
        "Immediately before an authorized integration, verify refs.\n", encoding="utf-8"
    )
    (root / "docs/AI_MODEL_SELECTION.md").write_text(
        "Follow AGENTS.md.\n| Cost/task |\n", encoding="utf-8"
    )
    problems = _truth().rules_problems(root)
    assert any("builder.agent.md" in p and "belongs only in AGENTS.md" in p for p in problems)
    assert any("AI_MODEL_SELECTION.md" in p for p in problems)
