#!/usr/bin/env python

"""
Bootstrap script for StableNew AI agents configuration.

This script does NOT talk to GitHub APIs or VS Code directly.
Instead, it:

- Verifies that agent instruction files exist under .github/agents/.
- Verifies that docs exist under docs/.
- Prints guidance on how to register these agents with GitHub Copilot
  or other multi-agent tooling (e.g., by referencing the markdown files as prompts).

Usage:

  python scripts/bootstrap_agents.py

Run from the repository root.
"""

from __future__ import annotations

from pathlib import Path


AGENT_FILES = [
    ".github/agents/controller_lead_engineer.md",
    ".github/agents/implementer.md",
    ".github/agents/tester.md",
    ".github/agents/gui.md",
    ".github/agents/refactor.md",
    ".github/agents/docs.md",
]

DOC_FILES = [
    "docs/engineering_standards.md",
    "docs/testing_strategy.md",
    "docs/gui_overview.md",
    "docs/repo_cleanup_plan.md",
]


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    print(f"[bootstrap] Repo root: {repo_root}")

    missing_agents = []
    missing_docs = []

    print("\n[bootstrap] Checking agent instruction files:")
    for rel in AGENT_FILES:
        p = repo_root / rel
        if p.exists():
            print(f"  ✓ {rel}")
        else:
            print(f"  ✗ MISSING: {rel}")
            missing_agents.append(rel)

    print("\n[bootstrap] Checking doc files:")
    for rel in DOC_FILES:
        p = repo_root / rel
        if p.exists():
            print(f"  ✓ {rel}")
        else:
            print(f"  ✗ MISSING: {rel}")
            missing_docs.append(rel)

    print("\n[bootstrap] Summary:")
    if not missing_agents and not missing_docs:
        print("  All core agent and doc files are present.")
    else:
        if missing_agents:
            print("  Missing agent files:")
            for rel in missing_agents:
                print(f"    - {rel}")
        if missing_docs:
            print("  Missing doc files:")
            for rel in missing_docs:
                print(f"    - {rel}")

    print("\n[bootstrap] Next steps (manual wiring):")
    print("""
  1. In GitHub or VS Code, create custom agents for each file in .github/agents/:
     - Controller
     - Implementer
     - Tester
     - GUI
     - Refactor
     - Docs

  2. For each agent, paste the corresponding markdown file as its system instructions.

  3. For the Controller agent:
     - Prefer a higher-tier model (e.g., GPT-5-CODEX).
     - Give it access to repo-browsing tools.

  4. For the specialist agents:
     - Use more cost-effective models (e.g., GPT-4.1 or default Copilot models).
     - Restrict their scope to relevant files as described in their instructions.

  5. Ensure that your README.md includes the AI Agents & Coding Assistants section
     from README_agent_block.md so that any scanning assistant sees the contract.

  6. Optionally, add or update your CI workflow (in .github/workflows/ci.yml)
     to run pytest and linting for all PRs.
""")

if __name__ == "__main__":
    main()
