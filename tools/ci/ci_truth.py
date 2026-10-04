"""Canonical CI/testing documentation truth, checkable without the application environment (PR-DEVEX-CI-110).

Standard library only: the docs-only cheap path of the required job runs this under the runner's system Python, and the
pytest truth tests (``tests/system/test_ci_truth_sync_v2.py``) call the same function, so the rules live in exactly one place.

    python tools/ci/ci_truth.py        # exit 1 and print each problem when a canonical document violates current CI truth
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

CODING = "docs/StableNew_Coding_and_Testing_v2.6.md"
#: Stale generic statements that described the pre-CI-110 workflow as an always-present full-suite job.
STALE_PHRASES = {
    "STATUS.md": ("one required gate, one informational full-suite job",),
    "docs/CODEX_MAP.md": ("(required gate + informational full-suite)",),
}


def _read(root: Path, rel: str) -> str | None:
    path = root / rel
    return path.read_text(encoding="utf-8") if path.is_file() else None


def docs_truth_problems(root: Path = ROOT) -> list[str]:
    problems: list[str] = []
    coding = _read(root, CODING)
    agents = _read(root, "AGENTS.md")
    if coding is None:
        problems.append(f"{CODING} is missing")
    else:
        for heading in ("Level 1", "Level 2", "Level 3"):
            if heading not in coding:
                problems.append(f"{CODING} no longer defines {heading}")
        if "Python 3.14" not in coding:
            problems.append(f"{CODING} must name Python 3.14 as the supported interpreter")
        for stale in ("Python 3.11", "Python 3.12"):
            if stale in coding:
                problems.append(f"{CODING} still names {stale}")
        if "python tools/ci/run_pr_gate.py" not in coding:
            problems.append(f"{CODING} must point to `python tools/ci/run_pr_gate.py`")
        if "GitHub required CI" not in coding:
            problems.append(f"{CODING} must describe GitHub required CI")
        if "tools/ci/validation_plan.py" not in coding:
            problems.append(f"{CODING} must describe the repository-owned validation plan (tools/ci/validation_plan.py)")
    if agents is None:
        problems.append("AGENTS.md is missing")
    elif "python tools/ci/run_pr_gate.py" not in agents:
        problems.append("AGENTS.md must point to `python tools/ci/run_pr_gate.py`")
    for rel, phrases in STALE_PHRASES.items():
        text = _read(root, rel)
        if text is None:
            problems.append(f"{rel} is missing")
            continue
        for phrase in phrases:
            if phrase in text:
                problems.append(f"{rel} still states the pre-CI-110 workflow: {phrase!r}")
    return problems


def main() -> int:
    problems = docs_truth_problems()
    for problem in problems:
        print(f"CI truth: {problem}", file=sys.stderr)
    if not problems:
        print("CI/testing documentation truth OK")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
