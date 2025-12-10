ARCHITECTURE_ENFORCEMENT_CHECKLIST_v2.6
Canonical — Mandatory for ALL PRs

Updated: 2025-12-09

0. Purpose of This Checklist

The purpose of this document is to guarantee that no PR — whether written by ChatGPT, Codex, or a human — can violate the canonical StableNew architecture.

All PRs must include this checklist at the end, with explicit YES/NO answers and explanations for each item.
A PR cannot be merged unless all applicable items are marked YES, or a governance-approved waiver is attached.

This checklist protects:

determinism

architectural purity

subsystem boundaries

long-term maintainability

the PromptPack-only rule

the NJR-only runtime rule

the builder resolver pipeline

the GUI→Controller→Builder→Runner pipeline

test coverage

removal of tech debt

SECTION 1 — Prompt & Config Source of Truth
1.1 PromptPack-only prompt sourcing

 Does all prompt text come exclusively from a PromptPack (.txt + .json)?

 Is there no GUI prompt textbox, legacy prompt field, or controller-created prompt?

 Are no prompts constructed inside GUI, controller, runner, preview panel, or config loader?

1.2 UnifiedPromptResolver-only resolution

 Is prompt resolution performed only inside UnifiedPromptResolver?

 Are global negative and pack-level negatives layered in the correct order?

 Are stage-level apply_global_negative flags respected?

1.3 No Prompt Mutation

 Does the PR avoid mutating PromptPack files?

 Are PromptPack rows treated as immutable input objects?

SECTION 2 — Job Model Integrity
2.1 NJR-only (NormalizedJobRecord-only) execution

 Does execution exclusively use NJR objects?

 Are legacy job structures (RunPayload, DraftBundle, CallStagePayload, etc.) avoided and/or removed?

2.2 UnifiedJobSummary-only for UI

 Does the GUI display only what the controller passes via UnifiedJobSummary?

 Does the GUI avoid reading PromptPack files directly?

 Does the GUI avoid reading configs or building them internally?

2.3 No Partial/Hybrid Job Objects

 Does the PR remove or avoid mixtures of V1/V1.5/V2 job formats?

 Are there no leftover stubs or adapters bridging old paths?

SECTION 3 — Pipeline Purity & Determinism
3.1 Builder-only job construction

 Is the Builder (JobBuilderV2) the only module creating NJRs?

 Is there no job creation in:

controllers

GUI

runner

webui adapters

debug tools

3.2 Deterministic enumeration

 Does job enumeration follow strictly:

Rows × ConfigVariants × MatrixVariants × Batches


with no variability?

3.3 Deterministic config layering

 Is config layering performed in exactly this order:

Base SDXL Defaults
→ Config Snapshot (Pipeline Tab)
→ Pack JSON Stage Overrides
→ ConfigVariant Overrides (Sweeps)
→ Global Toggles

3.4 No non-deterministic behavior introduced

 Seeds?

 Ordering?

 Randomization slots?

 Sweep variant ordering?

Everything must be deterministic.

SECTION 4 — Controller Responsibilities
4.1 Controller does NOT build jobs

 Does the controller strictly orchestrate (GUI → Builder → Runner → History)?

 Are no prompts or configs constructed or mutated in controllers?

4.2 Correct pack-to-job flow

 Does the PR use only on_pipeline_add_packs_to_job + start_pipeline_with_pack_based_draft?

 Are all legacy draft paths deleted or updated (DraftBundle, legacy add-to-job methods, etc.)?

4.3 Correct lifecycle emission

 Does the controller correctly send job_lifecycle_event messages?

SECTION 5 — Runner Responsibilities
5.1 Runner does NOT build or mutate jobs

 Runner only executes the NJR exactly as given.

 Runner does not:

resolve prompts

merge configs

reorder stages

inject random values

5.2 No legacy executor code paths remain

 Old pipelines must be deleted:

StageExecutorV1/V1.5

Legacy run_payload

Legacy call_stage

AI21/InvokeAI adapters

SECTION 6 — GUI Responsibilities
6.1 GUI does NOT generate logic or objects

 GUI never builds prompts

 GUI never builds configs

 GUI never builds job objects

 GUI calls controllers only

6.2 GUI reflects the NJR/UnifiedJobSummary

 Preview Panel reads from controller-provided summary

 Queue Panel shows lifecycle updates

 Running Job Panel shows controller→runner events

 History Panel reads NJR-only data

6.3 Sweep Designer UI compliance

 Sweep variants produce only config overrides

 No prompt modifications

 No pipeline-building logic in GUI

SECTION 7 — DebugHub Responsibilities
7.1 DebugHub is read-only

 DebugHub does NOT mutate prompts or jobs

 DebugHub displays the NJR + internal state only

 DebugHub does not modify execution

SECTION 8 — Subsystem Isolation
8.1 Each layer must depend downward only

GUI depends on controller

Controller depends on builder

Builder depends on resolvers

Runner depends on NJR output

No upward dependencies allowed.

SECTION 9 — Tech Debt Removal

Every PR must answer:

 Did you identify any dead code in the modified subsystem?

 Did you delete it?
(If not: attach a PR-DEBT follow-up at the bottom of the PR)

 Did you remove partial migrations?

 Did you remove any shim layers or compatibility bridges?

 Did you remove unused DTOs or legacy objects?

 Did you consolidate multiple code paths into the v2.6 canonical path?

SECTION 10 — Testing Requirements
10.1 Unit Tests

 Updated or created new unit tests?

 Do they assert architecture invariants?

10.2 Integration Tests

 Do builder, controller, runner, and GUI integration tests still pass?

10.3 Golden Path Tests

 Does the PR maintain GP1–GP15?

 Did you add new Golden Path tests if the PR introduces new user flows?

10.4 Regression Tests

 Were regressions identified?

 Were tests added to prevent recurrence?

SECTION 11 — Documentation Requirements
11.1 Documentation updated?

 Architecture_v2.6

 PromptPack Lifecycle v2.6

 Builder Deep Dive v2.6

 DebugHub_v2.6

 Coding & Testing Standards

 Docs Index

11.2 PR Template section completed

 “Architectural Impact” section

 “Tech Debt Impact” section

 “Canonical Document Updates Needed”

SECTION 12 — Final Merge Conditions

A PR may merge only if:

 ALL applicable items above are YES

 No architectural violations remain

 Tests pass

 Codex implementation matches ChatGPT spec

 Documentation is current

If any violation remains → PR must be rejected.

SUMMARY

This checklist is the gatekeeper for the entire project.

It ensures:

One execution path

One job format

One builder

One prompt source

One architectural truth

No ambiguity, no drift, no legacy confusion

Every PR must pass this checklist.
Every agent must respect it.
Every contributor must adopt it.

StableNew becomes easier, faster, safer, and more joyful to develop — once the architecture is protected by discipline.