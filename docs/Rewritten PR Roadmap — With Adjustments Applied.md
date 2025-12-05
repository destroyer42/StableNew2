Rewritten PR Roadmap — With Adjustments Applied.md

Below is the revised document consolidation roadmap addressing the three critiques above.
(Only the docs portion is rewritten, as requested.)

🔥 Revised PR Roadmap for Docs Consolidation (V2.5)
Fully Addressing Structural Weaknesses & AI/Contributor Usability
PR-DOC-301 — Canonical Index + LLM Access Layer

Goals

Create a new authoritative DOCS_INDEX_v2.5.md.

Introduce “LLM Access Layer” rules that guarantee future agents reference only canonical docs:

Each canonical doc begins with:

#CANONICAL

A 5–10 line executive summary

A “PR-Relevant Facts” quick reference section

Archived docs begin with #ARCHIVED and are excluded from agent search.

Provide explicit tagging rules for files:

Canonical: *-v2.5.md

Archived: moved under docs/archive/

Key Files

docs/DOCS_INDEX_v2.5.md

Update README.md to reference the new index and LLM access rules.

PR-DOC-302 — Architecture v2.5 (Reconciliation + Redrawing)

Goals

Build one authoritative architecture document:

Incorporates:

V2.5 run path

Job normalization (ConfigMergerV2 → JobBuilderV2 → NormalizedJobRecord → Queue)

Stage sequencing rules (txt2img → img2img → refiner → hires → upscale → adetailer)

Adds a new section:

“Deprecated Concepts and Why They Changed”

V1 job model

Legacy runner

MainWindow V1 architecture

Include updated diagrams aligned with PR-204A–E.

Resolve contradictions between architecture docs before merging.

Changes

Archive old architecture docs, but preserve diagrams in docs/archive/architecture/.

PR-DOC-303 — Roadmap v2.5 (Clear Phases, No Conflicts)

Goals

Merge all roadmap variants into a single structured doc:

Phase 1 — GUI/Queue/Pipeline normalization

Phase 2 — Learning System & Randomizer UI

Phase 3 — Cluster & Distributed Compute

Include:

Dependencies between phases

Expected PR rollout order

Cross-links to architecture updates

New Requirement

Include a “What changed since V2.0/V2.1” reconciliation appendix to prevent drift from earlier roadmaps.

PR-DOC-304 — Governance v2.5 (Separated from Agent SOPs)

Fixes the earlier weakness of over-merging.

Governance File = People-Facing

Merge:

AI Self-Discipline Protocol

Development Doctrine

Request Format (High-Stability)

PR Guardrails

Development checklists

But exclude agent instructions (moved to a separate doc below).

Produces: docs/StableNew_Governance_v2.5.md

PR-DOC-305 — Agent Instructions v2.5 (Machine-Facing)

New Separation

Agents need predictable, minimal, structured files.

This doc includes:

How to read the DOCS_INDEX

How to select canonical docs

How to generate PRs

How to obey governance rules

How to avoid archived docs

How to use anchor references and summaries

Produces: docs/StableNew_Agent_Instructions_v2.5.md

PR-DOC-306 — Coding, Testing, Smoke Tests v2.5 (Separated Concerns)

Corrects the earlier issue of merging too much:

Coding Standards

Testing Strategy

Smoke Test Protocols

WebUI interaction guidelines

Each is its own clearly labeled section, not a flattened single blob.

Adds:

Examples of pipeline tests (JobBuilderV2, NormalizedJobRecord, Queue)

Examples of GUI tests (Preview, Queue)

Best practices for writing new PR tests

File: docs/StableNew_Coding_and_Testing_v2.5.md

PR-DOC-307 — Randomizer Spec v2.5

Goals

Merge randomizer docs cleanly but preserve semantic structure:

Engine-level behavior

Plan schema

GUI panel behavior

Preview/Queue injection

Updated to reflect:

RandomizerEngineV2

RandomizationPlanV2

Refined seed modes

Interaction with JobBuilderV2

File: docs/Randomizer_Spec_v2.5.md

PR-DOC-308 — Learning System Spec v2.5

Separate Learning from Cluster compute.

Reason: They are different subsystems with different lifecycles.

File: docs/Learning_System_Spec_v2.5.md

PR-DOC-309 — Cluster Compute Spec v2.5

Split from Learning.

Cluster scheduler

Multi-node GPU execution

Payload routing

Distributed model caches

File: docs/Cluster_Compute_Spec_v2.5.md

PR-DOC-310 — Inventory, Migration, Archival

Same intent as before, but with improved tagging rules.

Move all legacy docs to docs/archive/

Add README_ARCHIVE.md explaining how archived docs differ from canonical ones

Slim CHANGELOG.md and link to archive

Summary of Improvements vs Previous Plan
Issue Identified	Fix Applied
Over-merging created giant monolithic docs	Split governance vs agent instructions, split learning vs cluster, split coding vs testing
No reconciliation of conflicting architecture docs	Added formal reconciliation step + deprecated concepts appendix
No LLM/agent consumption strategy	Added LLM Access Layer, canonical tagging, summaries, PR-relevant facts requirement