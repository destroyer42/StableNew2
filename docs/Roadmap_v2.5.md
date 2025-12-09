#CANONICAL
Roadmap_v2.5.md
(The authoritative planning and sequencing document for all StableNew development work.
Agents must not rely on any roadmap not marked #CANONICAL.)

Executive Summary (8–10 lines)

StableNew v2.5 is a multi-phase modernization effort designed to replace legacy systems (MainWindow V1, V1 job models, inconsistent queue logic) with a unified, testable pipeline architecture.
Phase 1 establishes architectural stabilization: fixed pipeline sequencing, ConfigMergerV2, JobBuilderV2, NormalizedJobRecord, Queue-first execution, GUI normalization (including PR-GUI-H and PR-GUI-I for layout and validation colors), and run-control clarity.
Phase 2 expands StableNew into a learning-driven platform by adding a deterministic Learning System, Randomizer UI, and structured telemetry outputs.
Phase 3 extends StableNew into multi-node cluster computing, enabling distributed rendering, remote job scheduling, and scalable batching.
Each phase builds directly on canonical architecture, governance, and subsystem boundaries.
All work must follow the canonical job lifecycle defined in ARCHITECTURE_v2.5, PR guardrails in Governance_v2.5, and documentation rules in DOCS_INDEX_v2.5.
This roadmap defines all milestones, PR bundles, dependencies, risks, and expected outputs for v2.5 through v3.0 development.

PR-Relevant Facts (Quick Reference)

Only this file defines project sequencing and priorities.

All PRs must specify which phase (1, 2, or 3) they belong to.

All architectural changes must reference ARCHITECTURE_v2.5.md.

All governance interactions must reference Governance_v2.5.md.

Roadmap items must not invent new architectural patterns without updating canonical docs.

Deprecated or legacy roadmap notes are archived and ignored.

The PR numbering scheme is continuous: 204-series for pipeline stabilization, 300-series for docs, 400-series for GUI, 500-series for learning, 600-series for cluster.

============================================================

0. BLUF / TLDR — Concise Roadmap Summary (Option C Layer)

============================================================

A condensed version for rapid reasoning and LLM initialization.

0.1 Three-Phase Roadmap Overview
Phase 1 — Stabilization (v2.5 Core)

Focus: architectural correctness, queue predictability, GUI clarity.

Key items:

Finalize ConfigMergerV2 + JobBuilderV2 + NormalizedJobRecord

Full Preview + Queue UI rewrite

Run controls simplification

Randomizer GUI foundations

Prompt Pack + Config override correctness

Fix all pipeline correctness issues (e.g., missing prompts, inconsistent configs)
Queue/Runner lifecycle repair (PR-CORE-C) with PromptPack-only normalized records, job_submitted events, and consistent GUI/history delivery of canonical summaries.

Begin documentation consolidation PRs (DOC-300 series)

Phase 1 Finish Criteria:
Stable, test-covered, architecturally consistent local pipeline with deterministic runs.

Phase 2 — Learning-Centric Iteration (v2.6)

Focus: introspection, feedback loops, learning signal generation.

Key items:

Learning System v2 (JSONL output, metadata, runtimes, scoring)

Integrations with Randomizer for experiment generation

Enhanced UI analytics panels

Job history persistence and load-from-history support

Telemetry schema versioning

Expansion of batch/variant inspection tools

Phase 2 Finish Criteria:
Stable experiment generation / evaluation loop with persistent job history + learning signals.

Phase 3 — Distributed Compute (v2.7–v3.0)

Focus: scaling StableNew across nodes.

Key items:

Cluster scheduler V2

Multi-node queue

Distributed WebUI execution

Centralized storage for model caches

Failover + recovery semantics

Unified remote-runner protocol

Phase 3 Finish Criteria:
StableNew runs multi-node batches at scale with job persistence, cluster queue, and worker orchestration.

0.2 Canonical Development Priorities

Highest priority: correctness, determinism, reproducibility.
Never allowed: UI logic influencing pipeline behavior; pipeline modifying queue; runner bypassing normalization.
Cross-phase rule: No subsystem breaks architecture invariants defined in ARCHITECTURE_v2.5.

0.3 TLDR Dependencies

Phase 2 requires complete Phase 1 stabilization.

Phase 3 requires Learning System instrumentation to support distributed metrics.

All phases require canonical docs to be consolidated (PR-DOC-301→310).

============================================================

1. Roadmap Purpose & Structure

============================================================

StableNew’s roadmap provides:

A consistent long-term plan

PR grouping rules

Sequencing constraints

Risk categorization

Architectural dependency mapping

Milestone definitions

Completion criteria

The roadmap must always remain aligned with:

ARCHITECTURE_v2.5

Governance_v2.5

DOCS_INDEX_v2.5

It is updated when core architectural assumptions change or when new phases are formally approved.

============================================================

2. Phase Structure (v2.5 → v3.0)

============================================================

Three-phase model:

Phase 1 — Stabilization

Phase 2 — Learning System

Phase 3 — Cluster / Distributed Compute

Each phase contains:

Goals

PR bundles

Dependencies

Completion criteria

============================================================

3. Phase 1 — Stabilization (v2.5 Core)

============================================================

Phase 1 consolidates architecture, fixes foundation-level correctness issues, and unifies pipeline behavior.

3.1 Objectives

Enforce canonical job lifecycle

Eliminate all V1 artifacts

Ensure predictable run behavior

Normalize all pipeline paths

Fix GUI/UX confusion in pipeline tab

Rewrite run controls

Clarify queue semantics

Remove architectural drift

Complete PR-204A–E buildout and follow-on PRs

3.2 Major Deliverables
A. Pipeline & Job Normalization

ConfigMergerV2 → complete & validated

JobBuilderV2 → complete & validated

NormalizedJobRecord → becomes sole job format

Controller rewiring (PR-204C)

Preview & Queue integration (PR-204D)

End-to-end tests (PR-204E)

B. Run Control Simplification

Remove unused/duplicated run modes

Consolidate Run / Run Now / Queue actions

Add Auto-Run toggle

Ensure queue behavior matches GUI labels

Running Job card redesign

C. GUI Wishlist Phase 1 items

Including but not limited to:

Dark mode fixes

Prompt Pack preview persistence

Show/hide refiner + hires options

Denoise and percentage sliders with numeric indicators

Batch size vs batch runs clarity

Filename template documentation

Output directory editing

Randomizer foundational controls

Removing obsolete buttons

D. Documentation Consolidation

PR-DOC-301 → Canonical Index

PR-DOC-302 → Architecture v2.5

PR-DOC-303 → This roadmap

PR-DOC-304 → Governance v2.5

PR-DOC-305 → Agent Instructions

PR-DOC-306 → Coding & Testing Standards

E. Queue Normalization

Queue view rewritten to use JobSpec/NormalizedJobRecord

Reordering, removal, clearing, running behavior clarified

Preparation for persistence in later phases

3.3 Completion Criteria (Phase 1)

Phase 1 is complete when:

All core pipeline behavior is deterministic

All major GUI confusion points resolved

Run controls align with architecture

Queue is test-covered and predictable

Docs consolidation is complete

The system can reliably run multi-stage SDXL pipelines with randomization

No PRs are blocked by missing architectural clarity

============================================================

4. Phase 2 — Learning System (v2.6)

============================================================

Phase 2 adds introspection, evaluation, and experiment-generation capability.

4.1 Objectives

Add a Learning System for recording per-stage metadata, quality metrics, runtime behavior, and structured outputs

Support post-run callbacks that record learning signals

Add structured job history and load-from-history capabilities

Provide Randomizer + Learning integration for experiment sweeps

Add UI analytics for job performance

4.2 Major Deliverables
A. Learning System v2

JSONL-based LearningRecord writer

Standardized metadata schema (seed, prompts, runtime metrics, config snapshot hash)

LearningController for capturing and processing signals

Metrics computation plugin architecture

B. Enhanced Job History

Persistent record of completed jobs

“Restore job” → load configs into GUI for editing

Browsable history with metadata search

C. Experimentation Tools

Randomizer-driven experiment sweeps

Automatic grouping of variants

Post-run comparison modal or panel

D. Analytics & Visualization

Render stage-by-stage timing

Show prompt-token breakdown

Quality annotations (manual or automated)

4.3 Dependencies

Phase 1 complete (canonical pipeline must be stable)

NormalizedJobRecord must already capture metadata needed for learning

Agent Instructions must be finalized (PR-DOC-305)

4.4 Completion Criteria (Phase 2)

Phase 2 ends when:

Learning System can fully capture and store metadata

Jobs can be restored from history

Experiment sweeps are possible and meaningful

The GUI exposes learning insights in a useful and intuitive way

============================================================

5. Phase 3 — Cluster Compute (v2.7–v3.0)

============================================================

Phase 3 scales StableNew horizontally across nodes.

5.1 Objectives

Enable distributed workers to execute jobs

Provide a cluster scheduler that distributes NormalizedJobRecords

Allow remote execution via WebUI or other backends

Enable large-batch, multi-node SDXL rendering

Provide cluster-level job monitoring

5.2 Major Deliverables
A. Cluster Scheduler

Master queue capable of dispatching jobs to remote workers

Worker registration protocol

Health monitoring + failover

B. Remote Runner Protocol

NormalizedJobRecord → remote runner

Secure communication

Runner heartbeat + progress channels

C. Distributed Model Caching

Shared or replicated models

Local cache invalidation rules

Sharded cache architecture

D. Cluster Control UI

Worker list

Queue load distribution

Failover visualization

Throttling / resource control

5.3 Dependencies

Complete Learning System (phase 2)

File storage + caching strategy

Networking layer tests

5.4 Completion Criteria (Phase 3)

Multi-node jobs can run end-to-end

Workers auto-discover and register

Recovery after connection loss

Cluster maintains consistent, correct queue semantics

Metrics aggregated across nodes

============================================================

6. Cross-Cutting Concerns

============================================================

6.1 UX Consistency

All phases require the GUI to follow the same design language and hierarchy.

6.2 Documentation

All major PRs must update relevant canonical docs.

6.3 Test Coverage

No subsystem may regress below its minimum test baseline.

6.4 State Persistence

Phase 1: queue preview
Phase 2: job history
Phase 3: cluster queue

6.5 Security & Privacy

Cluster phase introduces authentication and secure messaging.

============================================================

7. Risk Management & Fallback Plans

============================================================

Phase 1 Risks

Architectural contradictions

GUI layout inconsistencies

Queue instability
Mitigation: 204-series architecture + consolidated docs.

Phase 2 Risks

Learning System complexity

Large metadata files
Mitigation: versioned schema + incremental rollout.

Phase 3 Risks

Distributed cache consistency

Network failures
Mitigation: heartbeats + worker failover protocol.

============================================================

8. PR Grouping and Numbering Rules

============================================================

200-series → Pipeline stabilization

300-series → Documentation canonicalization

400-series → GUI Wishlist implementation

500-series → Learning

600-series → Cluster compute

Every PR must list its phase and dependency.

============================================================

9. Completion Criteria for v2.5 → v3.0

============================================================

The project reaches v3.0 when:

Canonical architecture is stable

Learning System can perform job-level and variant-level evaluation

Cluster scheduler is operational

Queue persistence is robust

GUI fully supports all phases

Documentation remains fully canonical and up-to-date

============================================================

10. Deprecated Roadmaps (Archived)

============================================================
#ARCHIVED
(Agents must ignore this section.)

Deprecated:

Early V1 Roadmap (pre-GUI rewrite)

Early V2 Roadmap drafts prior to PR-204 series

Ad-hoc notes prior to Revised PR Roadmap ()

Architecture fragments inconsistent with ConfigMerger/JobBuilder path

End of Roadmap_v2.5.md
