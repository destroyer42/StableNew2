# StableNew – Agent Instructions (V2/V2.5 Enforcement)

AGENTS.md (Codex + Copilot Edition — Streamlined & Safe)

Version: V2-P1
Purpose: Provide Codex/Copilot a clear, lightweight, reliable contract so they can implement PRs quickly without hallucination or repo damage.

1. Mission of Each Agent
Codex (Primary Implementer)

Applies PR instructions exactly as given.

Produces surgical diffs only within the files explicitly allowed.

Ensures tests remain green.

Never adds new behavior unless the PR explicitly calls for it.

Never “fills in gaps” creatively—only the PR spec is law.

GitHub Copilot (Inline Support)

Assists with local function bodies, small refactors, formatting, and pattern completion.

Must not introduce cross-file changes or new modules.

Adheres strictly to file boundaries and patterns set by Codex PR specs.

2. Always Start from the PR Spec

Every PR you implement will be produced by ChatGPT using the new workflow. That means:

All architecture decisions, filenames, subsystem scopes, allowed/forbidden files, and tests to satisfy are pre-defined.

You DO NOT need to infer missing information.

You DO NOT need to explore the repo outside the allowed files.

Your input = Only the PR that the user attaches.
Your output = A minimal diff implementing that PR, nothing more.

3. Golden Rules for Implementation
Rule 1 — Stay inside Allowed Files

Modify only the files listed under Files to Modify in the PR.

If the PR says:

Files to Modify:
- src/gui/views/pipeline_tab_frame.py
- src/gui/stage_cards_v2/base_stage_card_v2.py


Then do not edit any other file—even if it looks “helpful.”

Rule 2 — Never Touch Forbidden Files

Forbidden files (partial list; PRs may extend):

src/gui/main_window_v2.py
src/gui/theme_v2.py
src/main.py
src/pipeline/executor.py
src/pipeline/pipeline_runner.py


These files define core wiring, theming, lifecycle, or execution behavior and are too fragile for unscoped edits.

Rule 3 — Minimal, Surgical Diffs

Do exactly the following:

Implement the specific functionality described

Update specific methods (not entire classes)

Preserve existing structure and style

Do NOT rename, reorder, delete, or reorganize code unless the PR explicitly says so

Do NOT introduce new modules, new classes, or new patterns unless explicitly requested

Rule 4 — Follow the Snapshot

All work is evaluated relative to the snapshot ZIP + repo_inventory.json the PR specifies.

If a PR says:

Baseline Snapshot:
StableNew-snapshot-2025-11-28-2345.zip


Assume that is the source of truth.
Do not reinterpret old behavior or guess what code should exist.

Rule 5 — Never Re-Architect

Architecture is established and locked:

GUI → Controller → Pipeline → API → WebUI
(; )

Codex/Copilot must not change this ordering or connect layers directly.

4. How to Interpret the Repo (No Guesswork Required)

You do NOT need to understand the entire repo.
You only need the following truths:

4.1 Active Modules List is Authoritative

If a file is listed in ACTIVE_MODULES.md, it is valid.
If not, ignore it.
()

4.2 GUI V2 Layout is Fixed

Prompt Tab = authoring
Pipeline Tab = execution
Learning Tab = experiments
()

Codex must not restructure tab layouts or relocate responsibilities.

4.3 Roadmap is Already Decided

Codex does NOT interpret or modify overall direction.
Everything is planned already:

GUI → Pipeline wiring

Learning system

Queue + Cluster vision
(, , )

5. Execution Sequence for Every PR

When implementing a PR:

Step A — Load the PR

Read every section, especially:

Allowed Files

Forbidden Files

Step-by-step Implementation

Required Tests

Step B — Apply the Steps Exactly

Only implement what the PR says.
Do not add features or “improve” anything not in scope.

Step C — Keep Diffs Minimal

For each file:

Add the methods or lines requested

Do not modify surrounding context

Do not clean up formatting elsewhere

Step D — Run Only the Listed Tests

The PR will list tests Codex must ensure pass.
These are the only tests you need to consider for correctness.

Step E — Stop if Anything Seems Undefined

If something needed for implementation is not in the PR:

Stop

Request clarification
(You NEVER guess.)

6. Special Behavior Rules for Codex/Copilot
6.1 Codex Must Not Invent APIs

If a function or method is not explicitly described in the PR, do not create it.

6.2 Copilot Must Not Modify Cross-File References

Inline suggestions must not:

Create new imports

Change class names

Introduce new modules

6.3 Always Preserve the V2 Contracts

Examples:

Stage cards follow existing BaseStageCard patterns

Controller remains single source of truth

PipelineConfig structure remains stable

LearningRecord JSONL format must not change
(, )

7. Failure Handling

If Codex encounters:

Missing symbols

Unknown imports

Functions that don’t exist

It must NOT create new systems.
Instead:

STOP — request the file or clarification.


This prevents hallucinated classes (a major source of repo corruption historically).

8. Summary to Codex/Copilot

You are not designing StableNew.
You are implementing very small, surgical changes inside a fully defined architecture using PR specs that are provided to you.

Your responsibilities:

Follow PR specs exactly

Modify only allowed files

Keep diffs tiny

Ensure tests stay green

Stop and ask if anything is unclear

Your job is not invention.
Your job is precision.

END OF AGENTS.md