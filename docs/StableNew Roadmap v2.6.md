StableNew Roadmap v2.6.md
 (Canonical Edition)

Status: Authoritative
Updated: 2025-12-09
Applies To: Codex, Copilot, ChatGPT Planner, Human Contributors

0. Strategic Objective

Return StableNew to a lean, deterministic, fully testable image-generation pipeline built on:

North Star Loop

PromptPack ➜ Pipeline Tab (config/sweep/randomization) ➜ JobBuilderV2 ➜ NJR ➜ Queue/Runner ➜ History ➜ Learning ➜ DebugHub

Every design choice reinforces this loop.
Every PR must eliminate legacy ambiguity, prevent prompt drift, and reduce architectural debt.

1. Core Goals for v2.6
1.1 Restore Reliable, Deterministic Execution

Pipeline produces correct NJRs every time

Config + sweep + matrix + batch expansion deterministic

GUI never constructs prompts or configs

Queue and Runner operate on complete NJRs only

1.2 Collapse and Remove All Legacy Paths

No DraftBundle

No PromptConfigDict

No RunJobPayload

No free-text prompting outside Advanced Prompt Builder

Controllers own all config resolution

Builder owns all NJR construction

Runner is pure consumer

1.3 Strict Canonical Documentation Governance

Architecture_v2.6 is authoritative

PromptPack Lifecycle v2.6 defines all ownership rules

DebugHub v2.6 defines the introspection surface

PR Template v2.6 includes mandatory tech-debt section

1.4 Zero-Tech-Debt Policy

PRs must fix all architectural drift they introduce

If a PR touches a subsystem, it must align that subsystem

No partial migrations or compatibility shims

Every subsystem is modernized or removed entirely

1.5 Complete E2E Golden-Path Coverage

All 12 Golden Path tests must be runnable, using:

Real PromptPack → PackJobEntry → Preview → Queue → Runner → History → Learning → DebugHub

Fully deterministic and reproducible job flows

2. High-Level Roadmap

The roadmap is structured into 5 Phases.

PHASE 1 — Architectural Cleanup & Unification (v2.6 Immediate)

Duration: 2–4 weeks
Focus: Remove ambiguity, unify the execution path.

1.1 Remove all legacy execution paths

Delete:

DraftBundle, _draft_bundle

RunJobPayload, PipelineConfigPayload

old prompt builder storage (outside Advanced Prompt Builder)

legacy prompt_resolver

legacy pipeline runner wrappers

shadow state in GUI widgets

1.2 Canonicalize “Single Path to Execution”

Execution can only come from:

PromptPack → ConfigPreset/Sweep → JobBuilderV2 → NormalizedJobRecord → JobService → Runner → History


All other agents (GUI, controllers, Learning, DebugHub) must be consumers of NJRs only.

1.3 Update All Controllers

PipelineController must use app_state.job_draft exclusively

AppController must never call builder or runner directly

Controllers publish NJR summaries, never jobs or configs

1.4 Update All GUI Panels

Pipeline panel only displays UnifiedJobSummary

No prompt textboxes

No config editing outside presets + sweeps

Preview panel derives entirely from NJR summary

Queue panel uses NJR + lifecycle events

History panel displays NJR + DebugHub DTO

1.5 Documentation Rewrite

Architecture_v2.6

Builder Pipeline Deep Dive v2.6

PromptPack Lifecycle v2.6

DebugHub v2.6

Agents.md / Copilot-Instructions.md (new governance)

PR Template v2.6 (new tech-debt handling)

Phase 1 Success Criteria

No legacy code reachable

UI consistently displays NJR summaries

Job execution starts successfully from PromptPack

DebugHub displays correct layering

Queue processes jobs deterministically

PHASE 2 — Deterministic Builder Enhancements (PR-CORE-A → E Completion)

Duration: 2–3 weeks

Focus: Strengthen the builder pipeline and eliminate all non-deterministic drift.

2.1 Prompt Determinism

UnifiedPromptResolver fully layered

Global negative integration

Per-stage global negative toggles

No GUI influence allowed

2.2 Config Determinism

ConfigVariantPlanV2

Deterministic sweep expansion

Strict width/height validation

Per-stage config override rules

2.3 Randomizer Determinism

Matrix variant enumeration

Slot/value substitution lifecycle

JSON-stable variant ordering

2.4 UnifiedJobSummary Stability

Summary must be pure function of NJR

Summaries never constructed by GUI

Phase 2 Success Criteria

Same inputs → identical NJRs

Matrix × Sweep × Batch expansion correct

DebugHub reconstructed payload equals actual runner payload

All builder + resolver tests green

PHASE 3 — Full Queue/Runner Lifecycle Stabilization

Duration: 1 week

Focus: Make queuing & execution bulletproof.

3.1 Queue correctness

FIFO guarantee

Runner only pops QUEUED jobs

Lifecycle events: SUBMITTED → QUEUED → RUNNING → COMPLETED/FAILED

No RUNNING leaks

No stuck jobs

3.2 Runner execution determinism

No intermediate config re-resolution

NJR must already contain everything needed

3.3 Learning Integration

Each completed job emits LearningRecord

LearningRecord derives from NJR

No prompt drift allowed

Phase 3 Success Criteria

All Golden Path queue tests pass

Runner error handling produces stable DebugHub output

History + Learning receive complete metadata

PHASE 4 — GUI V2 Alignment & UX Completion

Duration: 2–3 weeks

Focus: Complete migration to the canonical V2 GUI model.

4.1 Pipeline Tab Completion

Config Sweep Designer

Randomizer Designer

Stage cards reflect NJR summary

Preview panel always accurate

4.2 History Panel Completion

NJR replay (“Restore to GUI”)

Variant metadata

Sweep assignment

Matrix assignment

4.3 DebugHub Integration

Layered prompt view

Config-layer diffs

Stage chain visualization

Lifecycle timeline

4.4 Side Panels

PromptPack selector

Preset selector

Config snapshot browser

Phase 4 Success Criteria

Add to Job → Preview → Add to Queue works

All GUI-driven golden paths pass

No GUI reconstructs prompts or configs

All GUI panels consistent with NJR

PHASE 5 — v2.7 Stabilization & Feature Enrichment

Duration: 4–6 weeks

Focus: polish, enhance, expand.

5.1 NJR Comparison Tools

Compare two jobs

Highlight differences

Show config diff

Show prompt diff

Show time-to-run diff

5.2 Learning Enhancements

Prioritize high-performing config variants

Auto-generate variant suggestions

Exportable Learning dataset

5.3 Batch Visualization

Show sweep × matrix × batch grid visually

5.4 Model & Asset Management

Caching improvements

Model selection heuristics

Phase 5 Success Criteria

Stable feature set

Fully expressive pipeline

Config exploration tools mature

DebugHub supports comparison workflows

3. Dependencies & Ordering Rules
3.1 Hard Dependencies
Task	Requires
PR-CORE-A (NJR unification)	Architecture v2.6
PR-CORE-B (deterministic builder)	PR-CORE-A
PR-CORE-C (queue lifecycle)	PR-CORE-A/B
PR-CORE-D (GUI V2 alignment)	PR-CORE-A/B/C
PR-CORE-E (global negative + sweeps)	PR-CORE-A/B
History / Learning integration	PR-CORE-C
3.2 No feature may skip layers.

Example:

A GUI feature cannot be implemented until:

builder supports the required deterministic metadata

controllers are aligned

NJR includes the field

This prevents architectural drift.

4. The Zero-Tech-Debt Rule

Every PR must answer:

1. Did you introduce new tech debt?

If yes → fix it within the PR.

2. Did you uncover old debt while working?

If yes →

Fix it immediately or

Create a self-contained PR-DEBT-X and implement directly next

3. Did you discover legacy code?

Delete it unless explicitly authorized to remain for compatibility.

4. Are there any forks in the execution path?

Collapse them. There must be exactly:

One builder path
One NJR schema
One queue/runner contract
One prompt source
One config source

5. Testing Requirements
5.1 Unit Coverage

Prompt resolver

Config resolver

Stage resolver

Randomizer

Sweep expansion

NJR construction

DebugHub DTOs

5.2 Integration Coverage

GUI → Controller → NJR

Queue lifecycle

DebugHub reconstruction

History/Replay

5.3 Golden Path E2E Coverage

All 12 GP tests must pass.

5.4 Regression Requirements

Any bug uncovered → write a test before fixing it.

6. Completion Criteria for v2.6

StableNew v2.6 is “complete” when:

All 12 Golden Path tests run and pass

No legacy paths exist

Pipeline runs cleanly from PromptPack → Learning

DebugHub introspection is accurate and readable

NJR determinism is guaranteed

GUI V2 alignment complete

Tech-debt backlog reduced to near-zero

Codex and ChatGPT operate on a unified architecture

Documentation fully consistent across system

7. Post-v2.6 Roadmap (v2.7 → v3.0)
v2.7 — Enhancement Mode

Model-based adaptive sweeps

Cross-run analytics

Job grouping & tagging

Multi-agent optimization loops

PromptPack evolution tools

v3.0 — Distributed Execution

Multi-node GPU orchestration

Learning optimizers

Cluster scheduling

Distributed queue drivers

END — Roadmap_v2.6 (Canonical Edition)