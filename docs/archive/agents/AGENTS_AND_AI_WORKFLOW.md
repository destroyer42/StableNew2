# StableNew – Agents, Copilot, and AI Workflow (v1.0)

_Last updated: 2025-11-15_

This document is the **single source of truth** for how AI tools (ChatGPT, Codex/Copilot) are used on the StableNew repo.

It replaces older scattered instructions and unifies:

- Agent roles (Controller / Implementer / Tester / GUI / Refactor / Docs)
- The GPT ↔ Codex workflow
- TDD expectations
- File risk categories and PR discipline

---

## 1. Roles & Responsibilities

### 1.1 Human (Rob)

- Decides **what** to build or fix.
- Brings logs, stack traces, and code snippets into ChatGPT.
- Approves or rejects plans from the Controller agent.
- Runs local tests and validates behavior.
- Owns branches, PRs, and merging.

### 1.2 ChatGPT (Architect / Design)

- Diagnoses issues given logs and code.
- Produces minimal, well-scoped patches and diffs.
- Writes or updates tests (starting from failing tests).
- Designs refactors and architecture changes.
- Writes and updates documentation.

### 1.3 Codex / Copilot Chat (Executor)

- Applies patches **exactly** as given.
- Runs commands (`pytest`, etc.) and reports output.
- Performs mechanical edits (rename, move, small refactors).
- Never initiates large redesigns without a spec from ChatGPT.

---

## 2. Agent Types

StableNew uses a conceptual **Controller + Specialist** model. These map to GitHub custom agents (e.g., `controller_lead_engineer.md`, `refactor_python_best_practices.md`) but also work as mental roles when prompting ChatGPT.

### 2.1 Controller Agent (Lead Engineer)

**Responsibilities:**

- Understand the problem and relevant files.
- Produce a **multi-step PR plan** with:
  - Small, sequenced tasks.
  - File boundaries.
  - Acceptance criteria & tests.
- Decide which specialist agent to delegate to:
  - Implementer, Tester, GUI, Refactor, Docs.

**Restrictions:**

- Does **not** write code or diffs.
- Stops after presenting a plan for approval.

### 2.2 Implementer Agent

**Responsibilities:**

- Write code changes that implement an approved plan.
- Use TDD:
  - Start from failing test.
  - Make it pass.
  - Run relevant test subset, then broader suite.
- Keep PRs small and focused (1–3 files where possible).

### 2.3 Tester Agent

**Responsibilities:**

- Write and refine tests:
  - Unit tests for pipeline and utils.
  - GUI tests for key workflows.
  - Journey tests for full pipeline.
- Harden existing tests (e.g., `test_config_passthrough.py`, `test_pipeline_journey.py`).
- Ensure changes are regression-protected.

### 2.4 GUI Agent

**Responsibilities:**

- Work exclusively on Tkinter GUI code:
  - Layout.
  - Widgets.
  - Theming.
- Respect the architecture and state machine.
- Introduce no pipeline logic without an explicit plan from Controller.

### 2.5 Refactor Agent

**Responsibilities:**

- Non-behavior-changing refactors:
  - Extracting helper functions.
  - Splitting large functions (>30 lines).
  - Improving naming, types, and structure.
- Keep behavior identical.
- Run tests after each significant change.

### 2.6 Docs Agent

**Responsibilities:**

- Update `README.md`, `docs/` content, and changelogs.
- Keep `StableNew_History_Summary.md`, `Known_Bugs_And_Issues_Summary.md`, and `StableNew_Roadmap_v1.0.md` in sync with code reality.
- Maintain AI workflow docs (this file, CODEX SOP, etc.).

---

## 3. File Risk Categories

### 3.1 High-Risk Files

Changes here should go through Controller → ChatGPT → Codex workflow with extra care:

- `src/gui/main_window.py`
- `src/gui/pipeline_controls_panel.py`
- `src/gui/config_panel.py`
- `src/gui/prompt_pack_panel.py`
- `src/gui/stage_chooser.py`
- `src/gui/adetailer_config_panel.py`
- `src/pipeline/executor.py`
- `src/api/client.py`
- `src/utils/randomizer.py`
- `src/utils/config.py`
- `src/gui/state.py`

Rules:

- No large refactors without a written plan and a GPT-generated diff.
- Always start from tests (add or update tests first).
- Small PRs, one main behavior change per branch.

### 3.2 Medium-Risk Files

- Other `src/gui/*.py` files.
- Logging and manifest helpers.
- Video integration code.

Rules:

- Still prefer GPT designs for significant changes.
- Implementer agent can safely do minor edits.

### 3.3 Low-Risk Files

- New pure utility modules.
- Most tests under `tests/` (once the fixtures are stable).
- Documentation under `/docs/` and `/docs/archive/`.

Rules:

- Codex can help more freely here, but keep changes small and intentional.

---

## 4. Standard Workflow (GPT + Codex)

### 4.1 Problem → Design

1. You describe the problem in ChatGPT:
   - Symptoms.
   - Logs.
   - Relevant code snippets.
2. Ask the **Controller agent** (conceptually) for a plan:
   - “Give me a 3–6 step PR plan with file paths and tests.”
3. Once the plan looks good, ask the Implementer/Testers to:
   - Write failing tests (if not present).
   - Produce a minimal diff that makes them pass.

### 4.2 Design → Execution (Codex)

In Copilot Chat:

1. Paste the **Codex Operating Rules** (from `.github/CODEX_SOP.md`).
2. Paste the diff from ChatGPT with instructions:

   > “Apply this unified diff exactly to the StableNew repo. Do not modify anything else.”

3. Ask Codex to:
   - Show updated functions/classes for verification.
   - Run targeted tests:
     - e.g. `pytest tests/test_config_passthrough.py -v`
   - Paste full test output back.

### 4.3 Execution → Feedback

Back in ChatGPT:

- If tests fail, paste the full output.
- Ask GPT to refine the patch or tests, then repeat.

---

## 5. TDD Expectations

All non-trivial work (especially in high-risk files) must follow:

1. **Write or update a failing test first.**
2. Implement the minimal change to make it pass.
3. Run focused tests.
4. Run broader test suites (GUI, journey, etc.) before merging.
5. Keep the PR as small as is reasonable.

For config or pipeline changes:

- Always run `test_config_passthrough.py`.
- Prefer also running at least one journey test from `test_pipeline_journey.py`.

---

## 6. Branch & PR Discipline

Examples:

- `fix/gui-second-run-hang`
- `stability/upscale-tiling-defaults`
- `gui/layout-main-window-v1`
- `pipeline/job-queue-prototype`

Principles:

- One main concern per branch.
- One clear behavior change per PR.
- No “while we’re here” refactors in the same PR as a bug fix.

---

## 7. Where Instructions Live

Canonical docs:

- `docs/AGENTS_AND_AI_WORKFLOW.md`  ← this file
- `.github/copilot-instructions.md`  ← short, per-session reminder
- `.github/CODEX_SOP.md`             ← detailed execution rules
- `docs/StableNew_History_Summary.md`
- `docs/StableNew_Roadmap_v1.0.md`
- `docs/Known_Bugs_And_Issues_Summary.md`

Older instruction files should be moved to `docs/archive/` and marked as superseded.

---

Update this file any time:

- A new agent role is introduced.
- The risk list changes.
- The GPT ↔ Codex workflow changes meaningfully.
