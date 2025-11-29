# StableNew – Codex Integration SOP

> **Purpose:** Define how GitHub Copilot / Codex should work on the StableNew repo so changes are safe, traceable, and small enough to review.

---

## How to Use This Document

- **For you (Rob):** Use this as your playbook for when and how to involve Codex, and what to ask it to do.
- **For Codex:** At the start of each Copilot Chat session, paste the “Operating Rules” section and refer back to the recipes in this doc.
- **For contributors (future):** Treat this as the standard for AI-assisted changes to StableNew.

You don’t need to memorize the whole thing. Focus on:

1. The **Operating Rules** section when starting a Codex session.
2. The **Standard Task Recipes** section when you want Codex to apply patches, run tests, or adjust files.

---

## Table of Contents

1. [Overview](#overview)  
2. [Roles and Responsibilities](#roles-and-responsibilities)  
3. [Branch and PR Discipline](#branch-and-pr-discipline)  
4. [File Risk Categories](#file-risk-categories)  
5. [Codex Operating Rules](#codex-operating-rules)  
6. [Standard Task Recipes](#standard-task-recipes)  
   - [Apply a Patch from ChatGPT](#apply-a-patch-from-chatgpt)  
   - [Insert a New Helper Function](#insert-a-new-helper-function)  
   - [Run Tests](#run-tests)  
7. [When Things Go Wrong](#when-things-go-wrong)  
8. [Versioning This SOP](#versioning-this-sop)

---

## Overview

StableNew uses ChatGPT (“GPT”) for design and patch generation, and GitHub Copilot / Codex (“Codex”) for local implementation.

**High-level flow:**

1. GPT produces **designs, diffs, and instructions**.  
2. Codex **applies those diffs exactly** and runs tests.  
3. You review, test, and commit in small, focused PRs.

This SOP exists so that:

- Codex doesn’t “freestyle” large refactors.
- Changes remain small, reviewable, and reversible.
- The GUI and pipeline don’t regress every time we touch them.

---

## Roles and Responsibilities

### You (Rob)

- Decide **what** to build/fix.
- Bring logs, stack traces, prompts, and snippets to GPT.
- Feed GPT’s diffs/specs into Codex.
- Review Codex’s changes and run tests.
- Own branch/PR structure.

### ChatGPT (GPT)

- Analyze code snippets, logs, and prompts you provide.
- Propose **minimal, well-scoped patches** (often as unified diffs).
- Generate:
  - Codex-ready prompts
  - Test adjustments
  - PR descriptions and commit messages
- Help debug test failures and regressions.

### Codex / GitHub Copilot Chat

- Apply diffs **exactly** when requested.
- Perform mechanical edits (rename, move, small refactors).
- Run tests and paste back full output.
- **Do not** redesign core parts of the app without a GPT-approved spec.

---
## Prompt Packs & Randomization Presets

- All medieval / fantasy work must stay compatible with:
  - `presets/medieval_heroes_master_realistic_v1.json`
  - `presets/medieval_heroes_master_fantasy_v1.json`
  - `presets/Juggernaut_MedievalHeroes_RandomizerAligned_v1b.json`
- New packs should follow the token patterns used in:
  - `packs/SDXL_female_heroes_*_v1*.txt`
  - `packs/SDXL_male_heroes_*_v1*.txt`
  - `packs/SDXL_myth_beasts_*_v1*.txt`
  - `packs/SDXL_epic_structures_*_v1*.txt`
  - `packs/SDXL_angelic_warriors_*_v1*.txt`
  - `packs/SDXL_beautiful_women_*_v1*.txt`

## Branch and PR Discipline

Always work on a **feature/fix branch**, not directly on `main` or `postGemini`.

**Examples:**

- `feature/randomizer-rng-v2`
- `fix/gui-stop-hang`
- `techdebt/tests-gui-root-fixture`

**Recommended workflow:**

1. From base branch (`postGemini`, `gui_sprint`, etc.):

   ```bash
   git checkout -b fix/randomizer-matrix-rng-v2
Apply patches via Codex / manual edits.

Run tests locally.

Commit with a focused message, e.g.:

bash
Copy code
git commit -am "Randomizer: treat rotate/random as per-prompt RNG"
Open a PR into the appropriate integration branch.

Keep each PR small and single-purpose (1–3 files, one clear behavior change).

File Risk Categories
High-Risk (Ask GPT for Design First)
These files are central and prone to regressions:

src/gui/main_window.py

src/gui/pipeline_controls_panel.py

src/gui/config_panel.py

src/pipeline/executor.py

src/api/client.py

src/utils/randomizer.py

Rule: Codex should not perform large refactors here without a GPT-generated spec/diff.

Medium / Safe for Smaller Edits
New utility modules under src/utils/ that you add.

Test files under tests/ (once fixtures are stable).

Logging helpers, small pure functions.

Rule: Codex may tidy these, but changes should still be driven by a clear request.

Codex Operating Rules
Paste this block into Codex at the start of each session working on StableNew.

When I paste a patch or unified diff, you must apply it exactly.

Do not “improve,” optimize, or partially apply it.

When I say “insert this block above/below X,” you must:

Locate X exactly, and

Insert the block there without altering its contents.

If you cannot find the target lines or symbols:

Stop and tell me exactly what you couldn’t match.

Do not guess or refactor around it.

Do not modify unrelated files unless I explicitly ask.

Before and after a change set, run the commands I specify (e.g. pytest tests/gui/test_main_window_pipeline.py -v) and paste the full output.

If tests fail, paste the full traceback and wait for instructions instead of trying to fix them on your own.

Treat src/gui/main_window.py, src/pipeline/executor.py, src/api/client.py, and src/utils/randomizer.py as protected: no large refactors without a clear spec I provide.

Standard Task Recipes
Apply a Patch from ChatGPT
You say to Codex:

“You are working on the StableNew repo. Apply the following unified diff exactly and do not modify anything else.”

Then paste the diff from GPT.

Afterwards:

“Now show me the updated functions/classes touched by this diff so I can verify the changes.”

Insert a New Helper Function
Example: adding _refresh_samplers_async next to _refresh_upscalers_async.

You say:

“Open src/gui/main_window.py. Find the function def _refresh_upscalers(self):. Immediately above that function, insert this exact code block and do not modify its contents:”

Then paste the code block from GPT.

Run Tests
You say:

“From the project root, run:
pytest tests/gui/test_main_window_pipeline.py -v
and paste the full output here.”

Use targeted tests for quick feedback, then run the full suite as needed.

When Things Go Wrong
If Codex:

Partially applies a diff, or

“Helpfully” rewrites large chunks of code, or

Cannot run tests properly,

Then:

Ask Codex to show the full updated function/file.

Copy that output into GPT.

GPT will:

Diagnose the mistake.

Generate a corrective diff.

Return to Codex and say:

“Apply this new diff exactly and do not modify anything else.”

This keeps the system stable even when Codex misbehaves.

Versioning This SOP
Treat this file as source-of-truth for AI integration.

When behavior changes (new tools, new branches, different risks), update:

The file list under File Risk Categories.

The Operating Rules as needed.

Use commit messages like:

docs: update Codex SOP for new randomizer modes

docs: add GUI stop-hang safeguards to SOP

Make sure any new contributors read this before letting Codex touch the repo.

yaml
Copy code

---

## 2. `docs/dev/Codex_Autopilot_Workflow_v1.md`

**Path:** `/docs/dev/Codex_Autopilot_Workflow_v1.md`  
(Create `docs/dev/` if it doesn’t exist.)

```markdown
# Codex Autopilot Workflow v1 – StableNew

> **Purpose:** Define the end-to-end loop between you, ChatGPT, Codex, and GitHub so features and fixes ship in small, safe increments.

---

## How to Use This Document

- If you’re about to make a non-trivial change (randomizer behavior, STOP button, pipeline tweaks), **start here**.
- Follow the steps in order: they’re designed to keep regressions contained.
- Use this workflow together with `.github/CODEX_SOP.md`:
  - SOP = *rules of engagement* for Codex.
  - Autopilot Workflow = *step-by-step playbook* for a change.

You don’t have to read it top to bottom every time; treat it as a **checklist** you dip into.

---

## Table of Contents

1. [Overview](#overview)  
2. [Prerequisites](#prerequisites)  
3. [Step 0 – Problem Statement](#step-0--problem-statement)  
4. [Step 1 – ChatGPT Design and Diff](#step-1--chatgpt-design-and-diff)  
5. [Step 2 – Codex Patch Application](#step-2--codex-patch-application)  
6. [Step 3 – Codex Test Execution](#step-3--codex-test-execution)  
7. [Step 4 – ChatGPT Debug / Adjust](#step-4--chatgpt-debug--adjust)  
8. [Step 5 – Manual GUI / Pipeline Sanity Check](#step-5--manual-gui--pipeline-sanity-check)  
9. [Step 6 – Commit and PR](#step-6--commit-and-pr)  
10. [Step 7 – Plan the Next Micro-Change](#step-7--plan-the-next-micro-change)  
11. [Appendix A – Example Patch Lifecycle](#appendix-a--example-patch-lifecycle)  
12. [Appendix B – Standard Prompts](#appendix-b--standard-prompts)

---

## Overview

The Autopilot Workflow is designed to:

- Let GPT handle **design and patch creation**.
- Let Codex handle **mechanical patch application and test runs**.
- Keep each change **small, testable, and reversible**.

You run this loop for each focused change:

> **Problem → GPT spec/diff → Codex applies + tests → you verify → commit + PR**

---

## Prerequisites

Before using this workflow:

- You have a **feature branch** checked out (see SOP).
- You have a reproducible issue or enhancement in mind:
  - e.g., “Matrix randomization always picks the same combo.”
  - e.g., “STOP button leaves Python processes and causes GUI hang on next launch.”
- You can run:
  - `pytest ...` commands locally.
  - `python -m src.main` for GUI tests.

---

## Step 0 – Problem Statement

Clearly define what’s wrong or what you want:

- *“Matrix randomizer uses the same [hair]=blonde, [clothes]=bikini combo for every prompt.”*
- *“STOP button leaves orphaned processes; GUI hangs on next start if those processes are still running.”*
- *“Sampler dropdown shows only 6 options, but WebUI has ~15 available samplers.”*

Collect:

- Logs or stack traces.
- A sample prompt pack or manifest JSON if relevant.
- Any GUI observations (hang, crash, display issues).

Bring that to ChatGPT.

---

## Step 1 – ChatGPT Design and Diff

In ChatGPT, ask for:

- A **short diagnosis** (“what’s likely going wrong?”).
- A **minimal patch** in the form of a unified diff or specific code block changes.
- Any **test updates** needed.

Example ask:

> “Here are logs + relevant code for `PromptRandomizer`. Randomization is not changing per prompt. Diagnose and give me a minimal patch (unified diff) that makes matrix slots random per prompt without breaking fanout or round-robin.”

GPT responds with:

- Explanation of current behavior.
- Target behavior.
- A `diff` for 1–2 files.
- Optional notes for tests.

You **do not edit the diff**; you pass it directly to Codex.

---

## Step 2 – Codex Patch Application

In Codex Chat:

1. Paste the SOP “Operating Rules” (once per session).
2. Then say something like:

   > “You are working on the StableNew repo. Apply the following unified diff exactly and do not modify anything else.”

3. Paste the diff from GPT.

After Codex claims success, say:

> “Show me the updated functions/classes touched by this diff so I can verify them.”

You eyeball to ensure it matches what GPT provided.

---

## Step 3 – Codex Test Execution

In the same Codex session:

> “From the project root, run:
> `pytest tests/gui/test_main_window_pipeline.py -v`
> and paste the full output here.”

Use targeted tests for quicker iteration (e.g., GUI tests or specific modules), then the full suite as needed.

If:

- **Tests pass:** move to Step 4.  
- **Tests fail:** capture the full output for ChatGPT.

---

## Step 4 – ChatGPT Debug / Adjust

If tests fail or behavior isn’t right:

1. Copy the failing test output or new logs into ChatGPT.
2. Ask:

   > “Here’s the failing output after the last patch you gave me. Refine the patch or tests so this passes while keeping the new behavior.”

3. GPT returns:
   - A refined diff.
   - Test adjustments, if necessary.

4. Return to **Step 2** with the new diff.

Repeat until tests and behavior match expectations.

---

## Step 5 – Manual GUI / Pipeline Sanity Check

Once tests pass:

1. Run:

   ```bash
   python -m src.main
Perform a minimal manual sanity test:

For randomizer changes:

Run a small pack (1–3 prompts, 1 image per prompt).

Confirm log entries show varied [hair]/[clothes]/[environment], etc.

For STOP behavior:

Start a pipeline, hit STOP.

Confirm GUI survives, and you can re-launch without clearing Task Manager.

If something still feels off:

Grab relevant logs / manifests.

Return to GPT for a small follow-up patch.

## Step 6 – Commit and PR
When you’re satisfied:

Check changes:

bash
Copy code
git status
git diff
Ensure Codex didn’t touch unrelated files.

Commit with a clear, focused message:

bash
Copy code
git commit -am "Randomizer: treat rotate/random as per-prompt RNG"
# or
git commit -am "GUI: add _refresh_samplers_async and hook into Check API flow"
Push and open a PR into your integration branch (postGemini, gui_sprint, etc.).

In the PR description, include:

Summary of behavior change.

Any new tests or updated tests.

A brief note of how you manually sanity-tested.

## Step 7 – Plan the Next Micro-Change

Avoid bundling too many concerns into one PR. Instead, queue them:

Examples of micro-changes:

Randomization Sprint:

v1: Matrix true random per prompt.

v2: Better log messages + global matrix limit safe defaults.

v3: “Preview N variants” dry-run UI button.

GUI Resilience Sprint:

v1: STOP uses cooperative cancellation; no orphan processes.

v2: Check API path robust against missing WebUI.

v3: Sampler/upscaler dropdowns always sync with WebUI.

Run the Autopilot Workflow once per micro-change.

## Appendix A – Example Patch Lifecycle
Scenario: Matrix randomization always picks [hair]=blonde etc.

Step 0: You describe the behavior and paste logs → GPT diagnoses: mode "rotate" is treated as “not fanout” and always uses combo 0, index resets each time.

Step 1: GPT produces:

Diff to normalize matrix modes.

_matrix_combos_for_prompt using random.choice for "random" mode.

Step 2: You tell Codex to apply the diff.

Step 3: Codex runs GUI tests; maybe one fails if it assumed old behavior.

Step 4: GPT adjusts tests or adds a new assertion about randomization.

Step 5: You run a tiny pipeline; logs show varied [hair] and [environment].

Step 6: You commit + PR.

Step 7: Next micro-change: expose matrix mode in UI as “Random per prompt” vs “Fanout.”

## Appendix B – Standard Prompts
You can reuse these as templates.

B.1 – Diagnose and Patch
“Here is the behavior I’m seeing, plus logs and the relevant code. Diagnose the likely cause and produce a minimal unified diff that fixes it without changing unrelated behavior.”

B.2 – Refine a Failing Patch
“This is the test output after applying the last diff you gave me. Update the patch and/or tests so the new behavior is preserved and these tests pass.”

B.3 – Generate Codex-Friendly Instructions
“Convert this patch and explanation into a short set of instructions for GitHub Copilot Chat so it can apply the changes safely in my StableNew repo.”

By following this workflow, you keep Codex as a disciplined executor, GPT as the architect and spec-writer, and yourself as the final decision-maker.

yaml
Copy code

---

## 3. Where to Put These Files

- **SOP:**  
  `/.github/CODEX_SOP.md`
- **Workflow:**  
  `/docs/dev/Codex_Autopilot_Workflow_v1.md`

Optional but recommended:

- In `README.md` or `CONTRIBUTING.md`, add a short section:

  ```markdown
  ### AI-Assisted Development

  StableNew uses GitHub Copilot / Codex + ChatGPT under a documented process:

  - [Codex Integration SOP](.github/CODEX_SOP.md)
  - [Codex Autopilot Workflow v1](docs/dev/Codex_Autopilot_Workflow_v1.md)

  Please read these before using AI tools to modify this repo.
4. How to Make Codex Actually Follow This Every Time
A. Pin the Rules in Codex Chat
Each time you start a new Codex Chat session for StableNew:

Paste the “Codex Operating Rules” block from CODEX_SOP.md.

Optionally add:

“For context, this repo has a full SOP at .github/CODEX_SOP.md. Follow that when applying changes.”

Codex doesn’t have persistent long-term memory per repo (yet), so this is your “boot script” per session.

B. Keep the SOP Open in VS Code / Browser
In VS Code:

Open .github/CODEX_SOP.md and pin the tab.

In browser (GitHub):

Keep the SOP open in a separate tab when you’re working with Copilot Web Chat.

This makes it easy to copy/paste the Operating Rules at the start of every session.

C. Use a Saved Snippet / Macro
Create a note/snippet (OneNote, Obsidian, VS Code snippet, etc.) that contains just the Operating Rules block.

Your flow becomes:

Open Codex Chat.

Type: SOP → expand snippet to the Operating Rules.

Hit enter.

That gets Codex into the right mode in a couple of seconds.

D. Reinforce in Key Files (Optional)
At the top of particularly sensitive modules, you can add a short comment:

python
Copy code
# NOTE: Changes to this file should follow .github/CODEX_SOP.md
#       Use ChatGPT for design and diffs; Codex only applies patches.
It doesn’t make Codex “read” the SOP, but it reminds you to route changes through the process.