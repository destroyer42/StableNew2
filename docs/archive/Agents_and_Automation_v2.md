# Agents and Automation v2  
_ChatGPT Architect · Codex Implementer · Tester_

This document replaces the older **AGENTS_AND_AI_WORKFLOW.md** and aligns agent roles with the v2 roadmap and architecture.

---

## 1. Roles

### 1.1 Architect (ChatGPT)

Responsibilities:

- Design PRs:
  - Define title, scope, allowed/forbidden files.
  - Specify behavior changes and non‑goals.
  - Provide high‑level implementation steps.
  - Define required tests and acceptance criteria.

- Maintain architectural integrity:
  - Uphold the layering (GUI → Controller → Pipeline → Utils/Learning → Cluster → API).
  - Enforce TDD and small diffs.
  - Keep V2 as source of truth; avoid regressing into V1 patterns.

Must NOT:

- Write large, multi‑concern diffs.
- Bypass tests or treat them as optional.
- Encourage Codex to modify out‑of‑scope modules.

### 1.2 Implementer (Codex)

Responsibilities:

- Apply diffs exactly as described by the Architect.
- Ask for clarification when requirements are ambiguous.
- Run the specified tests and return full output.
- Keep changes confined to the allowed file list.

Must NOT:

- “Improve” unrelated code opportunistically.
- Modify tests to make failures disappear without fixing root causes.
- Introduce new dependencies or patterns outside the scope of the PR.

### 1.3 Tester (ChatGPT)

Responsibilities:

- Design failing tests first, where appropriate.
- Review Codex output and test logs.
- Decide whether a PR is acceptable or needs revision.
- Maintain regression protection for bugs and architectural guarantees.

---

## 2. PR Workflow

1. User requests a change or feature.
2. Architect writes a detailed PR template:
   - Problem statement, goals, non‑goals.
   - Allowed/forbidden files.
   - Implementation steps.
   - Required tests and acceptance criteria.
3. Codex receives:
   - PR template (.md file).
   - A **run sheet / command block** specifying how to run tests.
4. Codex implements:
   - Applies diffs.
   - Runs tests.
   - Returns logs and a short summary.
5. Tester reviews logs and code at a high level:
   - If acceptable: PR considered “green” and can be committed.
   - If not: new PR or revision instructions are generated.

---

## 3. Codex Safety Wrapper

To reduce the risk of Codex making unintended changes, we use:

- **Codex safety wrapper instructions** embedded in PR templates:
  - Explicit list of disallowed modules (e.g., core architecture files not in scope).
  - Warnings against changing system‑level configurations.
  - Requirements to avoid GUI imports in utils and similar.

- **Safety tests**:
  - These are run regularly and will fail if Codex violates import or IO boundaries.

- **Scope Checker Scripts**:
  - Tools that can be run to ensure diffs stay within expected paths.

---

## 4. Automation Hooks

In the future, we can introduce:

- **Automated PR scaffolding**:
  - A script or assistant flow that takes a high‑level request and generates a PR template automatically using this document and the roadmap.

- **CI integration**:
  - Automatic execution of `pytest` and specific test suites per PR label.
  - Enforcement of safety tests and core invariants.

- **Learning/Randomizer/Cluster PR Bundles**:
  - Pre‑defined PR series (e.g., LEARNING‑HOOKS, RANDOMIZER‑UX, CLUSTER‑SCHEDULER) that follow a known sequence of steps.

---

## 5. Principles for Future Automation

- All automation should **increase clarity**, not hide complexity.
- The human remains the final arbiter of whether a change is acceptable.
- AI tools are powerful assistants, not autonomous committers.

---

## 6. Summary

- The v2 agent workflow is designed to balance velocity and safety.
- Architect (ChatGPT) designs; Codex implements; Tester (ChatGPT) enforces quality.
- PR templates, safety wrappers, and tests form a “rails system” that keep all work aligned with the StableNew V2 vision.
