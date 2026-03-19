StableNew — Formal Strategy Document (v2.6).md
Canonical Vision • Architectural Direction • Governance & Enforcement • 2026 Roadmap

Version: 2.6 (Ratified December 2025)
Authors: Rob (Product Owner), ChatGPT (Planner), Agents (Codex, Copilot)
Status: Canonical & Binding

1. Strategic Intent

StableNew’s core purpose is to provide a deterministic, scalable, multi-stage SDXL image generation platform that:

Eliminates all architectural ambiguity

Guarantees reproducibility

Enables distributed compute and automated optimization

Supports multi-agent development without drift

Maintains continuous architectural integrity through strict governance

This strategy formalizes how the system must evolve, how changes must be implemented, and how the overall architecture remains cohesive, minimal, and forward-compatible.

StableNew v2.6 is the turning point where the project transitions from “rapid expansion” to structured, enforceable architectural discipline.

2. Guiding Principles

These principles govern all future development and form the constraints for all agents and contributors.

2.1 Single Source of Truth

There must be one — and only one — authoritative version of each canonical concept:

Prompt source → PromptPack

Job format → NormalizedJobRecord (NJR)

Job execution path → Builder Pipeline → Queue → Runner

Job summary → UnifiedJobSummary

Pipeline state → AppStateV2 (no redundancy)

Prompt resolution → UnifiedPromptResolver

No GUI logic, legacy objects, or shims may reconstruct or simulate these.

2.2 Deterministic Execution

Every job executed by StableNew must be:

reproducible

explainable

identical across runs (given identical inputs)

traceable from PromptPack → NJR → output image

Randomness (e.g., seeds, Randomizer) must be intentional, controlled, and part of NJR.

2.3 Minimalism & Architectural Purity

The architecture removes:

multiple run paths

legacy job models

GUI-side job construction

prompt-based mutations

any backward-compatibility logic

The rule is simple:

If it contradicts the v2.6 architecture, it is removed—not adapted.

2.4 Multi-Agent Development Discipline

All contributors (ChatGPT, Codex, Copilot, humans) must follow:

PR Template v2.6

Tech Debt obligations

Enforcement Checklists

Agents.md rules

Agents must never infer or guess architectural behavior not explicitly described in the canonical documents.

2.5 No Deferred Technical Debt

Tech debt is not tolerated or postponed.
Every PR must:

resolve, delete, or refactor conflicting legacy structures

not introduce new drift

align the entire system even if it requires substantial change

If a PR introduces a simplification opportunity, that simplification happens immediately.

3. Architectural Strategy

StableNew v2.6 is defined by complete consolidation around the following pipeline:

Canonical Runtime Flow
PromptPack → Builder Pipeline → NJR → JobService/Queue → Runner → Output → History → Learning → DebugHub


There are no alternative execution paths.

3.1 Prompt Strategy — PromptPack-Only
Prompt Packs are:

the sole prompt source

immutable during pipeline execution

curated, versionable, and diffable

GUI text inputs are forbidden.

Negative prompt logic is layered via:

pack negatives

row negatives

global negative

per-stage global-negative flags

This ensures completely deterministic final prompts.

3.2 Builder Strategy — Deterministic Expansion

Builder Pipeline v2.6 is the heart of the architecture:

Rows × ConfigVariants × MatrixVariants × Batch Size
 → list[NormalizedJobRecord]


Respects:

UnifiedConfigResolver

UnifiedPromptResolver

RandomizationPlanV2

ConfigVariantPlanV2

Produces NJRs that are:

immutable

fully self-contained

reproducible

ready for execution

suitable for History & Learning

3.3 Execution Strategy — Queue-First

All jobs are executed through:

JobService (enqueue)

Queue lifecycle

Runner

Terminal state → COMPLETED or FAILED

Direct execution paths (Run Now) must still route through this same lifecycle.

3.4 GUI Strategy — Read-Only Consumer

GUI never constructs:

prompts

configs

job objects

pipeline state

GUI only:

displays summaries

selects packs, configs, variants

triggers controller events

Controllers produce and push NJRs.
GUI merely renders them.

3.5 Debug & Observability Strategy

DebugHub v2.6 provides:

lifecycle logs

API payload inspection

stage chain breakdown

NJR introspection

run provenance (PromptPack, seeds, variants)

All debugging is routed through canonical DTOs.

3.6 Tech Debt Strategy — Aggressive Reduction

All backward-compatibility layers, transitional stubs, orphaned classes, legacy execution paths, and GUI-side prompt/config fields are removed systematically.

A formal list of removal targets includes:

legacy pipeline controllers

legacy job models

direct runner paths

builder stubs from v2.1–v2.4

GUI prompt text and shadow config fields

pipeline_config snapshots not aligned to NJR

StateManager (obsolete)

The strategy is deletion—not adaptation.

3.7 Documentation Strategy

Canonical documents form a closed, mutually consistent system:

Architecture_v2.6

PromptPack Lifecycle v2.6

Builder Pipeline Deep-Dive

Governance v2.6

Coding & Testing Standards

DebugHub v2.6

Roadmap v2.6

Agents.md

Copilot-Instructions.md

All must align; any contradiction triggers immediate revision.

4. Organizational Strategy

StableNew is designed for multi-agent development, requiring strict role separation:

ChatGPT (Planner/Architect)

produces specs

enforces architecture

protects invariants

defines PR boundaries

performs doc rewrites and refactors

Codex (Executor)

implements PRs exactly

does not redesign architecture

refuses unscoped work

follows file rules: allowed vs forbidden

Copilot (Local Assistant)

assists with auto-completion and local refactors

may not introduce new architecture

Human Owner (Rob)

approves specs

validates direction

reviews architectural changes

acts as final governance authority

5. Roadmap Strategy (v2.6 → v3.0)
Phase 1 — Stabilization & Purification (now–Q1 2026)

Remove all legacy code and stubs

Enforce single execution path

Lock in PromptPack-only prompting

Solidify NJR lifecycle

Finalize DebugHub v2.6

Phase 2 — Distributed Compute (Q2–Q3 2026)

Cluster node registry

Model hot-cache across nodes

Distributed queue

Multi-node job scheduling

Phase 3 — Closed-Loop Optimization (Q3–Q4 2026)

Learning v3.0

Automated parameter sweeps

Preference modeling

Image quality scoring integration

Phase 4 — Full Creative Automation (2027+)

Automated prompt refinement

Intelligent config selection

Self-optimizing pipelines

User preference models

6. Enforcement & Success Criteria

StableNew v2.6 is successful when:

There is exactly one canonical execution path.

Every job is an NJR.

Every prompt comes from a PromptPack.

Pipeline state lives only in AppStateV2.

GUI never constructs pipeline data.

Agents cannot confuse or misinterpret architecture.

New development does not create drift.

All PRs include:

tech debt removal

architectural alignment

enforcement checklist

7. Risks & Mitigations
Risk	Mitigation
Legacy code re-emerging	immediate deletion mandate
Agent divergence	strict agent instructions + enforcement checklist
Partial migrations	PRs must be atomic and complete
Architectural drift	weekly architecture audit
Increased PR cost	long-term benefit > short-term PR size
8. Conclusion

StableNew v2.6 represents the pivot from an organically-grown, capability-driven tool into a deliberately engineered, architecture-driven platform. The system now has:

a single execution model

deterministic prompting

clean architectural boundaries

multi-agent governance

a standardized and enforceable development process

This strategy gives StableNew the operational stability and clarity it needs to scale into 2026 and beyond—into distributed compute, automated optimization, and closed-loop creative intelligence.