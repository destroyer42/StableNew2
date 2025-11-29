# CODEX PR Usage SOP – StableNew

## Purpose

This SOP defines **exactly how to use the PR templates in `docs/pr_templates/` with GitHub Copilot / Codex** to safely modify the StableNew repo.

---

## Roles

- **Human Owner (You)** – picks which PR to work, sets context, approves changes.
- **ChatGPT (Controller/Architect)** – explains and clarifies the PR, sometimes generates diffs.
- **Codex / Copilot (Implementer)** – applies diffs and runs tests.

---

## 1. Selecting a PR

1. Open `docs/pr_templates/index.yaml`.
2. Choose a PR with `status: ready` and no unmet dependencies.
3. Open the corresponding `.md` in:
   - VS Code, or
   - GitHub web editor.

---

## 2. Setting Up Codex Context (VS Code style)

In a new Codex chat (or Copilot panel):

1. Paste the **entire PR template markdown** for the one you’re working on.
2. Add this instruction at the end (adapt as needed):

   > “You are Codex implementing this PR in the StableNew repo.  
   > Only modify the files listed under ‘Allowed files’.  
   > Do NOT touch any files under ‘Forbidden files’.  
   > Follow the Implementation Plan and Codex Execution Checklist step by step.  
   > After edits, run the specified `pytest` commands and paste the full output.”

3. Pin the PR text in the chat if your tool allows it (so context isn’t lost).

---

## 3. Execution Workflow

For each PR:

1. **Read the template carefully.**
2. **Implement in small steps:**
   - Start with new files or dataclasses.
   - Then refactor existing code.
3. **Run tests as specified** in the PR (typically some subset of `pytest`).
4. **Paste full test output into the PR / notes.**
5. **Stop** if:
   - Codex is about to modify a forbidden file.
   - You see unexpected behavior.
   - The changeset feels too large.

---

## 4. Required Behavior for Codex

When you ask Codex to implement a PR:

- It **must**:
  - Only modify allowed files.
  - Follow the Implementation Plan sections in order.
  - Announce each step briefly (e.g., “Step 2: created randomizer_core.py”).
  - Run the specified tests and paste results.

- It **must not**:
  - Edit forbidden files.
  - “Improve” unrelated code.
  - Combine multiple PR templates into one monolithic change.

### Recommended prompt pattern

In Codex:

> “Implement only steps 1 and 2 of this PR.  
> Stop before you begin step 3 and show me the diffs.”

Then you review, then:

> “Now implement step 3, then run the tests described and paste the output.”

This throttles scope creep.

---

## 5. Using ChatGPT as Controller

Before you hand a PR to Codex, you can ask ChatGPT:

- “Sanity-check PR_B1 before I assign it to Codex.”  
- “Generate a summarized checklist from PR_F1 for quick reference.”  
- “Turn PR_G1 into a bullet-point diff plan for Codex.”

This keeps Codex focused and uses ChatGPT’s reasoning to catch issues early.

---

## 6. When Something Goes Wrong

If:

- Tests fail unexpectedly,
- Codex touched forbidden files,
- The diff is too big,

then:

1. **Stop Codex.**
2. Ask ChatGPT:
   - “Compare these diffs with PR_X goals and highlight problems.”
3. Decide whether to:
   - Back out the entire PR.
   - Adjust the PR template and try again.
   - Split it into two smaller PRs.

---

## 7. Closeout Checklist per PR

Before marking a PR “done” in `index.yaml`:

- [ ] All Implementation Plan steps completed.
- [ ] All required tests passing.
- [ ] No forbidden files changed.
- [ ] Code matches Architecture_v2 principles.
- [ ] Notes added in PR / commit message.

Once complete, update `status` in `index.yaml` to `merged` (or your chosen label).
