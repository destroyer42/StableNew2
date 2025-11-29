# CODEX PR Usage SOP – StableNew

## Purpose

This SOP defines **exactly how to use the PR templates in `docs/pr_templates/` with GitHub Copilot / Codex** to safely modify the StableNew repo.

It is the **operational** guide for:
- Selecting PRs
- Setting up Codex/Copilot context
- Running tests
- Closing out work

A separate **PR Template Guide** (see §8) defines the standard structure and expectations for each PR.

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

If a PR depends on others:
- Either complete its dependencies first, or
- Explicitly confirm that the dependency semantics are already in place.

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
4. If relevant, mention the architecture docs explicitly, e.g.:

   > “Follow `ARCHITECTURE_v2.md` (layering and dependency rules) and `PIPELINE_RULES.md`.”

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

You can throttle scope with prompts like:

> “Implement only Step 1 (data structures) from this PR.  
> Show me the diffs, then stop.”

Then:

> “Now implement Step 2 and run the tests listed in the PR. Paste the full output.”

---

## 4. Required Behavior for Codex

When you ask Codex to implement a PR:

It **must**:

- Only modify allowed files.
- Follow the Implementation Plan sections in order.
- Announce each step briefly (e.g., “Step 2: created `randomizer_core.py`”).
- Run the specified tests and paste results.
- Respect architectural constraints:
  - No new GUI → pipeline or GUI → HTTP coupling.
  - No breaking changes to public APIs without updating tests and docs.

It **must not**:

- Edit forbidden files.
- “Improve” unrelated code outside the PR scope.
- Combine multiple PR templates into one monolithic change.
- Introduce new dependencies that break the layering in `ARCHITECTURE_v2.md`.

### Recommended prompt pattern

In Codex:

> “Implement only steps 1 and 2 of this PR.  
> Stop before you begin step 3 and show me the diffs.”

Then, after review:

> “Now implement step 3, then run the tests described and paste the output.”

This throttles scope creep and keeps diffs reviewable.

---

## 5. Using ChatGPT as Controller

Before you hand a PR to Codex, you can ask ChatGPT:

- “Sanity-check PR_B1 before I assign it to Codex.”  
- “Generate a summarized checklist from PR_F1 for quick reference.”  
- “Turn PR_G1 into a bullet-point diff plan for Codex.”  
- “Confirm this PR respects the v2 architecture rules and layering.”

ChatGPT can also:

- Suggest test additions.
- Spot architectural violations in proposed diffs.
- Help split a large PR into smaller, safer ones.

---

## 6. When Something Goes Wrong

If:

- Tests fail unexpectedly,
- Codex touched forbidden files,
- The diff is too big or unfocused,

then:

1. **Stop Codex.**
2. Ask ChatGPT:
   - “Compare these diffs with PR_X goals and highlight problems.”
3. Decide whether to:
   - Back out the entire PR (e.g., `git reset --hard`).
   - Adjust the PR template and try again.
   - Split it into two smaller PRs.

If Codex broke architecture rules (GUI ↔ pipeline, etc.):

- Roll back the offending changes.
- Make the rule explicit in the relevant docs:
  - `ARCHITECTURE_v2.md`
  - `PIPELINE_RULES.md`
- Update the PR template to mention those constraints.

---

## 7. Closeout Checklist per PR

Before marking a PR “done” in `index.yaml`:

- [ ] All Implementation Plan steps completed.
- [ ] All required tests passing.
- [ ] No forbidden files changed.
- [ ] Code matches `ARCHITECTURE_v2` principles and layering.
- [ ] Any new pipeline/learning rules reflected in:
  - `PIPELINE_RULES.md`
  - `LEARNING_SYSTEM_SPEC.md`
- [ ] Notes added in PR / commit message.
- [ ] `ROLLING_SUMMARY.md` updated with 3–6 bullets summarizing the change.

Once complete, update `status` in `index.yaml` to `merged` (or your chosen label).

---

## 8. PR Template Guide (for Codex & ChatGPT)

This section standardizes **what a PR should look like**, complementing the operational SOP above.

### 8.1 PR Template Structure

Each PR must contain:

1. **Title**  
   - Short, descriptive, e.g.  
     `PR-PIPE-27: Robust upscale tiling limits`.

2. **What’s new** (bullets)
   - High-level description of code changes (no more than 5–7 bullets).

3. **Files touched**
   - Group by area:
     - `src/pipeline/...`
     - `src/controller/...`
     - `src/gui/...`
     - `src/learning/...`
     - `tests/...`
     - `docs/...`

4. **Behavioral changes**
   - Exactly what users or calling code will see differently.
   - Note any changes to:
     - GUI behavior
     - Pipeline parameters or defaults
     - Logging/learning behavior

5. **Risks / Invariants**
   - Anything that must NOT change, e.g.:
     - “Existing CLI flags must behave identically.”
     - “No new GUI → pipeline coupling.”
     - “Learning remains opt-in.”

6. **Tests**
   - List of commands run (`pytest ...`) and coverage notes.
   - Any manual validation performed (e.g., a specific pipeline run scenario).

7. **Migration / Notes for Future PRs**
   - How this PR fits into ongoing refactors (e.g., pipeline v2 adoption).
   - Any follow-on work recommended or required.

### 8.2 Commit & Branch Style

- Branch names:
  - `feature/PIPE-27-robust-upscale`
  - `bugfix/API-12-timeouts`
  - `chore/DOC-02-update-architecture`
- Commits should be small and focused when possible.
- Commit messages should:
  - Reference the PR id (e.g., `PR-PIPE-27`) when relevant.
  - Briefly summarize the change, e.g.  
    `PIPE-27: add compute_safe_tile_size helper`.

### 8.3 Expectations For AI-Generated PRs

When an AI assistant generates a PR:

- It **must**:
  - Use the structure in §8.1.
  - Explicitly link behavior changes to tests used to verify them.
  - Call out any risk areas or open questions.
  - Respect:
    - `ARCHITECTURE_v2_COMBINED.md`
    - `PIPELINE_RULES.md`
    - `LEARNING_SYSTEM_SPEC.md`
    - `CODING_STANDARDS.md`

- It **must not**:
  - Introduce architectural violations (e.g., GUI → HTTP).
  - Quietly change public APIs or config semantics.
  - Modify unrelated modules “for cleanup” unless explicitly requested.

### 8.4 Example PR Skeleton

```markdown
# PR-PIPE-27: Robust upscale tiling limits

## What’s new
- Added `compute_safe_tile_size` helper to `src/pipeline/upscale_limits.py`.
- Enforced max MP and max tile dimensions for ESRGAN and DAT.
- Updated `PipelineRunner` to use safe tile computation before calling WebUI.
- Extended tests for upscaling tile logic and stress cases.

## Files touched
- `src/pipeline/upscale_limits.py` (new)
- `src/pipeline/pipeline_runner.py`
- `tests/pipeline/test_upscale_limits.py`

## Behavioral changes
- Prevents runaway memory usage for large images when upscaling.
- No change to default upscale factor or sampler choices.
- Logs tile size decisions at `DEBUG` level for troubleshooting.

## Risks / invariants
- Must not degrade performance dramatically for small images.
- Existing CLI/GUI options must keep their semantics.
- Must respect global `img_max_size_mp` constraints from pipeline config.

## Tests
- `pytest tests/pipeline/test_upscale_limits.py -v`
- `pytest tests/pipeline -v`
- `pytest -v` (full suite)
- Manual verification: ran a 1024x1024 → 2x upscale with ESRGAN and DAT.

## Migration / future work
- Next PR: surface tile limit hints in the GUI advanced settings.
- Consider exposing a “safe tile” diagnostics panel for troubleshooting.
