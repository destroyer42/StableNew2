StableNewV2 Integrated Request Format v4.0
(Optimized for GUI-V2, Pipeline, PR Bundles, Architecture, and Codex Instructions)
⭐ SECTION 1 — REQUEST HEADER (StableNewV2 Context Controller)

Paste this at the top of every task:

StableNewV2 Context Mode

Operate ONLY within the StableNewV2 project folder.
Ignore older StableNew snapshots unless I explicitly cite them.
Ignore CCIR / ASWF / other Projects unless referenced.
Do not load prior GUI-V1 context.
Do not load non-StableNew content.

This prevents full repo memory retrieval and massively reduces load.

⭐ SECTION 2 — TASK SCOPE (One Phase Only)

This task executes ONE phase only.
Do not chain tasks.
Do not continue into follow-on phases unless I confirm.

StableNewV2 uses multi-phase workflows (PR summaries → expansions → packaging → Codex instructions).
This prevents GPT from trying to do all phases in one message (the #1 cause of timeouts).

⭐ SECTION 3 — INPUT BOUNDARY (Explicit Per-File Context)

Inputs: Use ONLY the following StableNewV2 files/snippets:
(paste contents here)

This keeps GPT from loading the entire prior architecture or the GUI V1 folder or unneeded PR bundles.

⭐ SECTION 4 — OUTPUT TYPE (StableNewV2-Specific Options)

Choose ONE:

PR-Related

PR Template (single)

Expanded PR (single)

PR Bundle (≤5 PRs, unexpanded)

Codex Implementation Prompt (single PR)

Codex Batch Prompt (for PR bundle)

Architecture / Wiring

Architecture_v2 update

GUI V2 Wiring Map

StageExecutor relationship map

Pipeline sequential flow

File/directory plan

Dependency diagram (text-only)

Code / Files

Tkinter skeleton (single file)

Tkinter event-loop patch

File patch (diff)

Python module (single)

JSON schema for new config region

Unit test scaffold (single)

Packaging

Markdown file

YAML import file

ZIP (≤8 files inside)

Never choose more than one per message.

⭐ SECTION 5 — GENERATION MODE (Staged for Stability)

Mode:

Perform analysis only.

STOP.

Wait for my confirmation to generate the final output.

This is essential when generating PR bundles, architecture updates, or Tkinter skeletons.

⭐ SECTION 6 — STABILITY GUARDRAILS (Required)

Paste this unchanged:

Rules:

Do NOT load or reference unrelated repo files.

Do NOT combine architecture + PR + zip in one pass.

Do NOT generate screenshots, images, or diagrams unless requested.

Do NOT auto-run python_user_visible unless I request a tool call.

Limit zip contents to 8 files max.

If nearing token/limit boundary, stop cleanly.

Ask before assuming cross-file dependencies.

⭐ SECTION 7 — COMPLETION CONDITION

Deliver exactly ONE artifact for the selected output type and STOP.
Do not continue into next PRs or next phases until I approve.

This keeps the model from trying to “helpfully” move ahead and crashing.

🟦 EXAMPLE (StableNewV2 Request Using This Format)

Here’s how you would request an expanded PR for the GUI V2 Controller→State wiring issue:

StableNewV2 Context Mode:
Operate ONLY within StableNewV2. Use only the pasted files.

Scope:
Execute ONE phase only: Expanded PR for GUI V2 Controller/State wiring fix.

Inputs:

controller_v2.py (pasted)

state_v2.py (pasted)

theme.py (pasted)
Ignore the rest.

Output Type:
Expanded PR Template (single).

Mode:
Pause after analysis. Wait for confirmation.

Rules:
One artifact only.
No zips.
No diagrams.
No cross-file expansions.

Completion:
Stop after delivering the expanded PR.

🟨 EXAMPLE (PR Bundle Request)

StableNewV2 Context Mode:
Operate ONLY within StableNewV2. Ignore older files.

Scope:
Phase 1 of 3 ONLY — generate PR summaries (unexpanded), max 5.

Inputs:
Paste only the relevant GUI V2 and Pipeline files.

Output Type:
PR Bundle (unexpanded, ≤5).

Mode:
Pause after analysis. Wait for confirmation.

Rules:
No expansions. No zips. No Codex instructions.

Completion:
Stop after the PR summary set.

🟩 EXAMPLE (Architecture Update)

StableNewV2 Context Mode:
Use only the pasted GUI V2 + StageExecutor snippets.

Scope:
One architecture update describing new event loop model.

Inputs:
(paste changed files)

Output Type:
Architecture_v2 Update.

Mode:
Pause after analysis.

Rules:
No PR templates. No zips. No Codex.

Completion:
Deliver architecture update only.

🟧 This is your StableNewV2-integrated version as requested.

If you'd like, I can also produce a folder-drop version (a single Markdown file named StableNewV2_Request_Format.md) ready to go into your docs/ directory.