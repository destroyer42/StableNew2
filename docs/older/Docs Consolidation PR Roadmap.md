Docs Consolidation PR Roadmap.md
2.1 Current Docs Landscape

From repo_inventory.json and earlier mapping, the docs/ space includes:

Architecture & Roadmap

docs/ARCHITECTURE_v2.md

docs/Stage_Sequencing_V2_5_V2-P1.md

docs/Run Pipeline Path (V2) – Architecture Notes.md

docs/ROADMAP_v2.md

docs/StableNew_Roadmap_v2.0.md

docs/StableNewV2_5P2-ROADMAP-2025-11-27.md

StableNewV2_Summary_V2-P1.md (executive summary).

Governance / Process / Agents

docs/StableNew AI Self-Discipline Protocol (11-27-25).md

docs/StableNew Interactive AI Development Checklist-11-27-25-v2.md

docs/StableNewV2 — High-Stability Request Format v4.0.md

docs/StableNewV2_Coding_Best_Practices_AI_Optimized.md

docs/StableNew_Development_Doctrine.md

docs/StableNew_PR_Template_Guardrails.md

docs/Agents_and_Automation_v2.md

docs/agents/AGENTS_AND_AI_WORKFLOW.md

docs/agents/CODEX_5_1_MAX_Instructions.md

docs/agents/CODEX_PR_Usage_SOP.md

docs/StabeNewV2-SUPER-CurrentProjectInstructions.md.

Feature / System Specs

docs/Randomizer_System_Spec_v2.md

docs/RANDOMIZATION_AND_MATRIX_UI_SUMMARY.md

docs/Testing_Strategy_v2.md

docs/Cluster_Compute_Vision_v2.md

docs/Learning_System_Spec_v2.md

docs/STABLE-DIFFUSION-README.md

docs/Post_Merge_Smoke_Test_SAFE_RAND_THEME.md.

Meta & Inventory

docs/StableNew_V2_Inventory.md

docs/StableNew_V2_Inventory_V2-P1.md

docs/repo_inventory_classified_v2_phase1.json

docs/ROLLING_SUMMARY_FINAL.md

docs/StableNew_V2_Rescue_Summary_and_Plan(24NOV-2154).md

docs/ContextDocs.zip

docs/CHANGELOG.md

docs/README_CHANGELOG_V2_PACKAGE/PR-README-CHANGELOG-V2-001.md.

Migration

docs/Migration_Notes_V1_to_V2.md.

2.2 Target End-State

Goal: shrink to a small, authoritative doc set that matches V2.5 reality:

Core Entry Points

README.md (top-level) – short project intro; points into docs/ index.

docs/DOCS_INDEX_v2.5.md – one map for humans and agents.

Canonical Architecture & Roadmap

docs/ARCHITECTURE_v2.5.md – unify architecture, stage sequencing, run path.

docs/StableNew_Roadmap_v2.5.md – unify all roadmap variants into one.

Governance & Dev Workflow

docs/StableNew_Governance_v2.5.md – merge AI Self-Discipline, Development Doctrine, High-Stability Request Format, PR Template Guardrails, and Interactive Checklist.

docs/StableNew_Coding_and_Testing_v2.5.md – merge Coding Best Practices, Testing Strategy, smoke tests, and any relevant parts of STABLE-DIFFUSION-README that are dev-facing.

Subsystem Specs

docs/Randomizer_Spec_v2.5.md – merge Randomizer spec + RANDOMIZATION_AND_MATRIX_UI_SUMMARY.

docs/Learning_and_Cluster_Spec_v2.5.md – merge Learning_System_Spec_v2 + Cluster_Compute_Vision_v2 (plus relevant notes from Roadmap/Architecture).

Optional small docs/Queue_and_RunModes_Spec_v2.5.md bridging Run Pipeline Path + Stage Sequencing for queue semantics, if not fully folded into architecture.

Meta / Historical

Archive, not delete:

docs/StableNew_V2_Inventory_V2-P1.md, ROLLING_SUMMARY_FINAL.md, Rescue_Summary, ContextDocs.zip, Migration_Notes_V1_to_V2.md, etc., into docs/archive/.

Keep minimal CHANGELOG.md (current + link to archived full changelog).

2.3 Docs PR Roadmap
PR-DOC-301 – Docs Index & Canonical Map

Scope

Introduce docs/DOCS_INDEX_v2.5.md that:

Lists each canonical doc and its purpose.

Marks legacy docs with “Archived” and links to archive folder.

Includes a small section “For Agents” pointing to governance & project instructions.

Update top-level README.md to:

Point to DOCS_INDEX_v2.5.md.

Briefly summarize V2.5 architecture and Phase-1/Phase-2 scope.

Key Files

README.md

docs/DOCS_INDEX_v2.5.md (new)

PR-DOC-302 – Architecture Unification (ARCHITECTURE_v2.5)

Scope

Create docs/ARCHITECTURE_v2.5.md as the architecture doc by:

Folding in:

ARCHITECTURE_v2.md (base).

Stage_Sequencing_V2_5_V2-P1.md (stage order, ADetailer/Refiner/Hires rules).

Run Pipeline Path (V2) – Architecture Notes.md (run path, queue, JobService, PipelineRunner).

Adding explicit section on:

Job normalization (ConfigMergerV2 + JobBuilderV2 + NormalizedJobRecord).

Queue semantics (direct vs queue, eventual queue-first model from PR-GUI-206).

Mark the old files as legacy and move them to docs/archive/.

Key Files

docs/ARCHITECTURE_v2.5.md (new)

docs/ARCHITECTURE_v2.md → docs/archive/

docs/Stage_Sequencing_V2_5_V2-P1.md → docs/archive/

docs/Run Pipeline Path (V2) – Architecture Notes.md → docs/archive/

PR-DOC-303 – Roadmap Consolidation

Scope

Create docs/StableNew_Roadmap_v2.5.md by merging:

docs/ROADMAP_v2.md

docs/StableNew_Roadmap_v2.0.md

docs/StableNewV2_5P2-ROADMAP-2025-11-27.md

Align with StableNewV2_Summary_V2-P1.md next-steps section.

Clearly mark:

Phase-1 (single-node GUI/queue),

Phase-2 (learning, randomizer UI, etc.),

Phase-3 (cluster, scheduler).

Move superseded roadmaps into docs/archive/.

Key Files

docs/StableNew_Roadmap_v2.5.md (new)

Existing roadmap docs → docs/archive/.

PR-DOC-304 – Governance & Agent Docs Merge

Scope

Create docs/StableNew_Governance_v2.5.md that unifies:

StableNew AI Self-Discipline Protocol (11-27-25).md

StableNew_Development_Doctrine.md

StableNewV2 — High-Stability Request Format v4.0.md

StableNew_PR_Template_Guardrails.md

StableNew Interactive AI Development Checklist-11-27-25-v2.md

Agents_and_Automation_v2.md

StabeNewV2-SUPER-CurrentProjectInstructions.md

docs/agents/* high-value content (AGENTS_AND_AI_WORKFLOW, CODEX instructions, PR usage SOP).

Organize sections as:

Immutable principles (Self-Discipline, Doctrine).

Request & PR templates.

AI agent behavior & instructions.

Developer checklists.

Move old granular docs into docs/archive/ but keep them accessible.

Key Files

docs/StableNew_Governance_v2.5.md (new)

All governance/agent docs → docs/archive/ after content merged.

PR-DOC-305 – Coding, Testing, and Smoke Tests

Scope

Create docs/StableNew_Coding_and_Testing_v2.5.md to unify:

StableNewV2_Coding_Best_Practices_AI_Optimized.md

Testing_Strategy_v2.md

Post_Merge_Smoke_Test_SAFE_RAND_THEME.md

Relevant technical bits from STABLE-DIFFUSION-README.md that matter for devs (e.g., how we call WebUI, API expectations).

Add:

Section on our current pytest suite, including job builder/queue tests,

Guidance on new tests expected per PR (esp. GUI vs pipeline vs queue).

Key Files

docs/StableNew_Coding_and_Testing_v2.5.md (new)

Older coding/testing/smoke docs → docs/archive/.

PR-DOC-306 – Randomizer, Learning, and Cluster Specs

Scope

Randomizer:

docs/Randomizer_Spec_v2.5.md:

Merge Randomizer_System_Spec_v2.md + RANDOMIZATION_AND_MATRIX_UI_SUMMARY.md.

Update to reflect:

RandomizationPlanV2,

RandomizerEngineV2,

GUI integration PRs (Randomizer panel, seed modes, randomizer injection in preview).

Learning & Cluster:

docs/Learning_and_Cluster_Spec_v2.5.md:

Merge Learning_System_Spec_v2.md + Cluster_Compute_Vision_v2.md.

Align with current Phase-2+ cluster vision and AIP learning roadmap (from earlier docs).

Key Files

docs/Randomizer_Spec_v2.5.md (new)

docs/Learning_and_Cluster_Spec_v2.5.md (new)

Old feature docs → docs/archive/.

PR-DOC-307 – Inventory, Migration, and Historical Archive

Scope

Create docs/archive/ folder (if not present).

Move into archive:

StableNew_V2_Inventory_V2-P1.md, StableNew_V2_Inventory.md, repo_inventory_classified_v2_phase1.json (or keep one “current inventory” in root if needed).

ROLLING_SUMMARY_FINAL.md

StableNew_V2_Rescue_Summary_and_Plan(24NOV-2154).md

ContextDocs.zip

Migration_Notes_V1_to_V2.md (keep; mark as historical).

Old READMEs/CHANGELOG fragments (e.g., README_CHANGELOG_V2_PACKAGE).

Slim down docs/CHANGELOG.md to:

Current milestone notes.

Pointer to archive for historical detail.

Key Files

docs/archive/*

docs/CHANGELOG.md