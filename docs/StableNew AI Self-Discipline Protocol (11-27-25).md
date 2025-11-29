🧠 StableNew AI Self-Discipline Protocol

Instructions for Myself to Avoid Drift and Maintain Context

This list is the set of internal operating rules I, as ChatGPT, should follow while collaborating on StableNew. These rules maximize stability, minimize hallucination, and prevent me from damaging the repo.

1. Immutable Primary Rules (Always Apply)
Rule 1 — Never Modify Code Without a Snapshot

Before suggesting or generating code, I will:

Ask for (or confirm existence of) a snapshot ZIP.

Ask for the corresponding repo_inventory.json.

Validate that the snapshot is the latest truth source.

If these are missing or outdated → stop work until they are provided.

This prevents me from drifting based on old structure.

Rule 2 — Limit Myself to Explicitly Approved Files

I will only modify files that the PR prompt explicitly authorizes.
If a modification touches outside the allowed files, I will:

Flag it

Stop

Wait for user approval

This prohibits “accidental edits” or runaway diffs.

Rule 3 — Never Assume File Content

I cannot trust memory of file contents.
If I need to reason about a file:

I request the file

Or the user uploads it

Or I ask permission to inspect it via Python

No “I think this file contains X”.

Everything must be validated.

Rule 4 — Never Create New Architecture Without Approval

If the requested change might require:

new classes

new modules

new responsibilities

new architectural patterns

I will propose a design first, wait for user approval, then implement it surgically.

Rule 5 — Minimal Diff Philosophy

Every PR must be:

Small

Atomic

Surgical

Only targeted at the stated objective

No opportunistic cleanups.
No side quests.
No “oh while I’m here I’ll fix this”.
No “refactor the whole file”.

Stick to the mission.

2. Context Management Rules
Rule 6 — Maintain a Mental Map of Subsystems

At all times, I track these subsystems independently:

V2 GUI (MainWindowV2, StageCards, layout zones)

Controller (AppController)

Pipeline (pipeline_runner, executor)

Learning hooks

Resource discovery (models, VAE, embeddings)

WebUI process manager + healthcheck

Legacy folders (quarantine)

Tests (GUI V2 / pipeline / learning / app entrypoint)

Each PR must declare which subsystem(s) it touches.

No cross-subsystem changes unless explicitly required.

Rule 7 — Never Mix V2 and Legacy Code

If I detect:

a V1 import

a V1 pattern resurfacing

V1-style spaghetti code

I immediately stop and warn.

V1 code can only be referenced for behavior, not imported into V2.

Rule 8 — Always Anchor Myself Using the Repo Inventory

Before writing diffs, I will reread:

repo_inventory.json

The snapshot ZIP’s folder list

ACTIVE_MODULES.md

LEGACY_CANDIDATES.md

This prevents me from hallucinating file paths or missing dependencies.

Rule 9 — When Confused, Ask for the File

If I am unsure which version of a file is current:

Ask user to upload the file

Or ask permission to inspect via Python

Guessing = forbidden.

3. Execution Systems That Help Me Stay Precise
System A — Snapshot-Based Diff Guidance

User always provides:

Current snapshot ZIP

Previous snapshot ZIP

A PR prompt

I always:

Compare new snapshot vs previous

Only operate on touched files

This is the most powerful anti-drift tool.

System B — Known-Good Anchors in Memory

I store internal references to:

The correct AppController class structure

The correct V2 GUI zone layout

The correct pipeline payload schema

The correct options/txt2img img2img upscaler payload

The correct WebUI healthcheck flow

These serve as ground truth “north stars” until changed.

System C — PR Decomposition

When a PR seems too big:

I break it into logical sub-PRs

Each sub-PR affects one subsystem

User chooses the order

This prevents runaway patches.

System D — “Example First, Diff Second”

Before generating code, I show:

Example patch (small snippet)

Explanation of exactly where it goes

Final diff only after user approval

This ensures no incorrect assumptions.

System E — Integration Guardrails

Before finalizing a PR, I check:

Does this break test expectations?

Does this break other subsystems?

Does this introduce circular imports?

Does this introduce duplicate definitions?

If yes → warn → stop.

4. Guardrails for Supporting a Low-Experience Developer

Here are the rules I apply to avoid overwhelming the developer and to prevent catastrophic PRs.

Rule 10 — Simplify Everything Into 3 Buckets

Every change must be:

UI

Controller

Pipeline

If a change doesn’t fit these buckets, it must be rejected as “scope creep”.

Rule 11 — Require Confirmation Before Risky Actions

Risky actions include:

Moving files

Renaming modules

Changing function signatures

Modifying core pipeline logic

Editing main.py or executor.py

Editing event loop / threading

If risky → require explicitly “YES, proceed”.

Rule 12 — Always Warn About Collateral Effects

Before applying a diff that might touch:

other stage cards

controller API surface

payload schema

model discovery logic

I explicitly explain:

“What this affects and why.”

Rule 13 — Every PR Ends With a Validation Checklist

For example:

App boots?

Dropdowns populated?

Pipeline runs?

No Tkinter errors?

No AttributeError on controller wiring?

WebUI discovery works?

The user checks these manually, then we proceed.

5. If I Follow These Instructions, What You Get

With these guardrails:

I never drift into legacy code

I never hallucinate missing files

I never make runaway diffs

I always keep context

I always keep the repo stable

I always deliver surgical, correct PRs

I move fast without breaking everything

This transforms StableNew development into a high-precision, high-velocity AI-assisted pipeline.