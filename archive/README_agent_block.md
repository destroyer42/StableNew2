### AI Agents & Coding Assistants

If you are an AI coding assistant (e.g., GitHub Copilot, GPT-5-CODEX, or similar),
you **must** read and follow these documents before editing this repository:

- `docs/engineering_standards.md` – coding style, directory rules, performance & safety
- `docs/testing_strategy.md` – how to design, name, and structure tests (TDD expected)
- `docs/gui_overview.md` – StableNew GUI layout, theming, and behavior constraints
- `docs/repo_cleanup_plan.md` – the canonical plan for consolidating docs and cleaning up the repo

Controller / Lead Engineer agents should also use:

- `.github/agents/controller_lead_engineer.md`
- `.github/agents/implementer.md`
- `.github/agents/refactor.md`
- `.github/agents/tester.md`
- `.github/agents/gui.md`
- `.github/agents/docs.md`

All AI agents are expected to:

- Keep PRs small and focused.
- Write or update tests for every behavior change.
- Update documentation for user-visible changes.
- Avoid modifying files outside the scope defined by the Controller agent.
