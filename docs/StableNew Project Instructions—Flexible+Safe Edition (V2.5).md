#CANONICAL
StableNew Project Instructions — Flexible + Safe Edition (V2.5)
(Rewritten with Canonical Docs Layer, Priority Ordering, Snapshot Rules, Discovery Protocols, and Architecture-Change Triggers)
0. Canonical Documentation Access Layer (LLM Governance Rule)

StableNew reasoning MUST use canonical documentation only, located in:

/docs/


Canonical docs always end with _v2.5.md.

Canonical Priority Order (NEW)

When canonical docs overlap, apply this precedence:

ARCHITECTURE_v2.5.md — authoritative for system boundaries & invariants

GOVERNANCE_v2.5.md — authoritative for process, safety, guardrails, risk tiers

ROADMAP_v2.5.md — authoritative for release sequencing & phase goals

AGENTS_v2.5.md — authoritative for LLM-specific reasoning behavior

Module Specs — Randomizer / Learning System / Cluster Compute

PR Templates in /docs/pr_templates/

docs/older/ — historical context if canonical version does not override

docs/archive/ — NEVER referenced for reasoning (all begin with #ARCHIVED)

When in doubt

Check DOCS_INDEX_v2.5.md.

1. Scope & Context Rules

Keep reasoning strictly within the StableNew repository and current snapshot.

Ignore external projects unless explicitly referenced.

Do not re-derive architecture unless the user indicates it has changed (see below).

Use the canonical docs as the stable truth for system design, not the snapshot.

Architecture-Change Triggers (NEW)

The LLM must treat the architecture as changed when:

User uploads a new or revised architecture/pipeline doc

Snapshot structure changes in src/pipeline/, src/controller/, or runtime systems

The user says “This changes how the pipeline works,” “We redesigned X,” or similar

A PR modifies cross-subsystem control flow

A new canonical version is added

If triggered → LLM may re-evaluate architecture boundaries using the canonical docs.

2. Snapshot Usage (Optimized)

Snapshots are required only when:

Generating or modifying code

Writing diffs

Verifying file contents

Navigating file structure

Analyzing runtime logic in detail

Snapshots are NOT required for:

Writing documentation

Designing UI/UX behaviors

Architecture planning

Workflow modeling

High-level analysis or conceptual PR plans

If the user says “Same snapshot as last time,” accept it immediately.

3. File Access & Modification Rules
Allowed

Identify files likely involved in a fix or feature (Discovery Step).

Propose allowed-file scopes even if user is unsure.

Required

Modify only the files explicitly listed in the PR spec.

Maintain strict separation of subsystem responsibilities as per ARCHITECTURE_v2.5.md.

Forbidden (Unless Explicitly Unlocked)
src/gui/main_window_v2.py
src/gui/theme_v2.py
src/main.py
src/pipeline/executor.py
Pipeline runner core
Healthcheck core

4. Risk Tier Model (Version 2.5)
Tier 1 – Light Mode (Default)

For:

GUI wiring

Layout fixes

Theming

Test updates

Documentation

Very lightweight guardrails. No deep validation.

Tier 2 – Standard Mode

For:

Controller logic

JobBuilder integrations

Queue behavior

Randomizer integration

Config → payload translation

Requires architecture boundary validation but not heavy executor reasoning.

Tier 3 – Heavy Mode

For:

Executor

Thread model

Pipeline runner

Learning core

Cluster & distributed systems

Queue core internals

Requires deep cross-subsystem analysis, invariants, and strict guardrails.

5. Subsystem Map

As defined in ARCHITECTURE_v2.5.md:

GUI V2

Controller Layer

Pipeline Runtime

API / WebUI Client

Randomizer Engine V2

Queue & JobService

Learning System L3

Tests / CI

Every PR should modify 1–2 subsystems maximum unless explicitly authorized otherwise.

6. Architecture Boundary Rules

Based on canonical architecture:

GUI V2 → Controller → Pipeline Runtime → API/WebUI → Worker/Executor
                       ↘ Queue System
                       ↘ Learning System
                       ↘ Randomizer Engine


Invariants (must not be violated):

GUI never calls pipeline or WebUI directly.

Controller is authoritative for:

dropdown population

pipeline config assembly

randomizer integration

last-run restore behavior

Pipeline produces NormalizedJobRecord → then becomes UI summaries.

If a PR appears to violate these boundaries, LLM must warn the user before proceeding.

7. Two-Step Workflow (NEWLY REFINED)
Step 1 — Discovery Pass

Provide:

Subsystems involved

3–7 concise root causes

Minimal file list

Risk tier

A Discovery ID (D-XX)

No PR generation, no test writing, no heavy reasoning.

Multi-Subsystem Discovery Rule (NEW)

If multiple subsystems are implicated:

Identify Primary subsystem

Identify Secondary subsystem(s)

Choose risk tier based on highest-impact subsystem

Recommend multi-part PRs (e.g., PR-210A/B/C)

This ensures atomicity and avoids messy PRs that span boundaries.

Step 2 — PR Generation

When user says:
“Generate PR-### using D-##”:

Reuse discovery scope exactly

Do NOT re-analyze repo structure

Do NOT re-derive architecture

Fill official PR template from /docs/pr_templates/

Provide:

step-by-step implementation

allowed/forbidden files

tests

acceptance criteria

rollback plan

risk tier

8. Snapshot vs Canonical Conflict Rule (NEW)

If snapshot code conflicts with canonical docs:

For PR Design:

➡️ Follow Canonical docs (they represent intended architecture/behavior).

For Implementation/Diffs:

➡️ Follow Snapshot contents (must modify real code correctly).

If conflict is fundamental:

Ask user whether to:

Update snapshot to match canonical documents

Update canonical documents to match new system reality

This prevents hidden architectural drift.

9. Validation Checklist (Short Mode)

Before finalizing any PR:

App boots

GUI V2 loads without Tk errors

Dropdowns populate correctly

JobBuilderV2 produces valid NormalizedJobRecord(s)

Queue operations behave normally

WebUI healthcheck is unaffected (unless related)

Learning hooks unchanged unless PR explicitly modifies them

No full-system review required for GUI-level PRs.

10. “When in Doubt → Ask” Rule

If:

File unclear

Behavior ambiguous

Code structure uncertain

User desire unclear

→ Ask for the file or run a Discovery Pass.
Never silently assume complex behavior.

11. PR Queue Memory Rules

To maintain continuity:

After generating a series of PR specs, produce a PR Queue Summary.

When user asks for a follow-up (“Generate PR-145”), do NOT restart reasoning.

Continue from the queue.

If context scrolls away, reconstruct queue based on the last summary.

12. Output Format Rules

Prefer downloadable files/zips for code.

Avoid huge inline code blocks unless necessary.

Use Python only for snapshot inspection.

Always reference canonical documents where appropriate.

13. What These Rules Solve (Mission Alignment)

Eliminates redundant re-analysis

Guarantees consistent architectural reasoning

Dramatically reduces drift and hallucination

Accelerates PR production

Supports GUI, UX, and feature-rich expansion

Maintains safety in pipeline/executor modifications

Enables predictable, high-completeness automation for the StableNew program