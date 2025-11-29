Files to reference:
When planning: Reference the "High-Level-Reasoning-and-plan" in the Project Folder
When generating PRs or CODEX/Co-Pilot Prompts: Reference "StableNew AI Self-Discipline Protocol", and the "StableNew_PR_Template_Guardrails" and "AI checklist" in the Project Folder
Use the most recent repo Snapshot for all coding snippets, queries, file paths, etc.: StableNew-snapshot-(timestamp).zip and project-repo.json
For architecture reference: ARCHITECTURE_V2.MD


General Rules for
1. When giving code or docs, or text, avoid giving it in any type of coding language directly in chat. On long conversations it bogs down the web-browser who doesn't have the right interpreter for bash or cmd or py. Always default to a downloadable file, or if multiple files, bundle as a zip. 
2. Reference these source documents (saved in the project folder) frequently. If you notice them getting stale with outdated references, suggest that they be replaced/updated.
3. Follow the instructions below with fervor.
4. Remember that you can use Python to examine contents in .zip files. Reference the .zip file repo snapshots for any file context. Always ask for the updated snapshot/file to reference to close out the PR.

1. Core Rule: V2-ONLY

All work uses V2 architecture exclusively.
Legacy/V1 code is never referenced or reused. Archive only.

2. Mandatory Snapshot Discipline

Before any reasoning or code:

Confirm latest snapshot ZIP + repo_inventory.json.

If missing/outdated → STOP and request them.

All diffs anchor to snapshot structure and the inventory (including active/legacy modules).

Never assume file contents — request them if needed.

3. File Modification Rules

Modify only files explicitly listed in the PR prompt.

If a requested change touches any other file → STOP and ask for approval.

Keep diffs minimal, atomic, surgical.

Do not refactor, rename, move files, or introduce architecture changes without explicit permission.

Forbidden unless unlocked:
src/gui/main_window_v2.py, src/gui/theme_v2.py,
src/main.py, src/pipeline/executor.py,
pipeline runner, healthcheck, last-run store, API discovery.

4. Architectural Boundaries (Strict)

Follow the canonical layer chain:
GUI V2 → Controller → Pipeline → API → WebUI.

GUI never touches pipeline or WebUI directly.

Controller is the single source of truth for dropdowns, pipeline configs, last-run, learning mode, and randomizer adapters.

Pipeline execution must remain deterministic and contract-compatible.

GUI work must follow the validated V2 layout defined in the Unified GUI V2 Redesign Summary :

Prompt Tab = text/structure source of truth

Pipeline Tab = runtime/execution source of truth

Learning Tab = experiment/rating source of truth

5. Subsystem Mental Map

Every PR must declare which subsystem(s) it touches:

GUI V2

Controller

Pipeline Runtime

API/WebUI

Learning

Randomizer

Queue/Cluster

Tests

No cross-subsystem modifications unless explicitly required.

Use ACTIVE_MODULES.md to identify real V2 entrypoints and LEGACY_CANDIDATES.md to ensure no V1/V1-style imports leak through.

6. Safety Systems
System A — Snapshot-Based Diffing

Always compare current vs prior snapshot.
Touch only files listed in PR Template’s “Files to Modify”.

System B — Known-Good Anchors

Always adhere to validated structures:
AppController, V2 GUI zone map, pipeline payload schema, healthcheck flow.

System C — PR Decomposition

If PR seems large → split into sub-PRs by subsystem.

System D — Example-First, Diff-Second

Provide:

Micro example patch

Explanation of placement

Wait for approval
Only then provide the full diff.

System E — Integration Guardrails

Before finishing:

No new circular imports

No duplicated methods

No broken tests

No API/schema changes unless approved

7. High-Level Execution Rules

Always follow the High-Level Reasoning & Plan before coding:

Phase 1 = stabilize GUI V2, pipeline payloads, dropdowns, WebUI healthcheck.

Phase 2 = unify stage contracts & controller flows.

Phase 3 = learning system integration (passive + active).

Phase 4 = creative expansion (randomizer, advanced editor).

Phase 5 = distributed cluster controller.

When unsure → choose smallest, safest, V2-aligned action.

8. Forbidden Behaviors

No new classes/modules without explicit design approval.

No rewriting controller, pipeline, or GUI scaffolding.

No broad refactors or “cleanup”.

No assumptions about content of any file.

No multi-file edits in a single PR unless explicitly approved.

9. Required PR Style

Every PR must conform to the StableNew PR Template :

Explicit snapshot baseline

Exact file list

Forbidden files list

Done criteria

Required tests to stay green

Minimal diffs

Human-verifiable validation checklist (boot, dropdowns, pipeline run, learning emit, etc.)

10. Validation Checklist (Always Run)

Before concluding any PR, ensure:

App boots cleanly

V2 layout loads

Dropdowns populate

Pipeline config roundtrip works

Pipeline executes full run

WebUI healthcheck passes

Learning record writes (if enabled)

No new warnings or Tk errors

11. When in Doubt

Default to:
“Do not modify; request clarification.”