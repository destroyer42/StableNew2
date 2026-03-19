DOCS_INDEX_v2.6.md
Canonical Documentation Map and Navigation Guide

Status: Authoritative
Updated: 2026-03-18

0. Purpose

This index defines the active document set for StableNew v2.6 and identifies
which files are canonical, operational, backlog-driving, or archived.

1. Canonical Document Hierarchy

1.1 Tier 1 - System Constitution

- `docs/ARCHITECTURE_v2.6.md`
- `docs/GOVERNANCE_v2.6.md`
- `docs/StableNew Roadmap v2.6.md`

1.2 Tier 2 - Canonical Execution, Testing, And Workflow Specs

- `docs/PROMPT_PACK_LIFECYCLE_v2.6.md`
- `docs/Builder Pipeline Deep-Dive (v2.6).md`
- `docs/DEBUG HUB v2.6.md`
- `docs/ARCHITECTURE_ENFORCEMENT_CHECKLIST_v2.6.md`
- `docs/StableNew_Coding_and_Testing_v2.6.md`
- `docs/PR_TEMPLATE_v2.6.md`
- `docs/StableNew_v2.6_Canonical_Execution_Contract.md`
- `docs/Canonical_Document_Ownership_v2.6.md`
- `AGENTS.md`
- `.github/copilot-instructions.md`

1.3 Tier 3 - Active Migration And Expansion Backlogs

- `docs/PR_Backlog/MIGRATION_CLOSURE_EXECUTABLE_BACKLOG_v2.6-1.md`
- `docs/PR_Backlog/StableNew_ComfyAware_Backlog_v2.6.md`

These documents sequence active work but do not outrank Tier 1 or Tier 2.

1.4 Tier 4 - Subsystem Specifications

- `docs/Learning_System_Spec_v2.6.md`
- `docs/Image_Metadata_Contract_v2.6.md`
- `docs/Movie_Clips_Workflow_v2.6.md`
- `docs/GUI_Ownership_Map_v2.6.md`
- `docs/Randomizer_Spec_v2.5.md`
- `docs/Cluster_Compute_Spec_v2.5.md`

The retained v2.5 docs above remain reference specs only until replaced.

1.5 Tier 5 - Testing Infrastructure

- `docs/E2E_Golden_Path_Test_Matrix_v2.6.md`
- `docs/KNOWN_PITFALLS_QUEUE_TESTING.md`
- `docs/PR-CI-JOURNEY-001.md`
- `docs/TEST-SUITE-ANALYSIS-2026-01-01.md`

1.6 Tier 6 - Operator And Reference Guides

- `README.md`
- `docs/agentic/USAGE_GUIDE.md`
- `.github/PULL_REQUEST_TEMPLATE.md`

These support development and operations but do not override the canonical
documents above.

2. Canonical Reading Order

Read in this order:

1. `README.md`
2. `docs/ARCHITECTURE_v2.6.md`
3. `docs/GOVERNANCE_v2.6.md`
4. `docs/StableNew Roadmap v2.6.md`
5. `docs/StableNew_v2.6_Canonical_Execution_Contract.md`
6. `docs/StableNew_Coding_and_Testing_v2.6.md`
7. `docs/PR_Backlog/MIGRATION_CLOSURE_EXECUTABLE_BACKLOG_v2.6-1.md`
8. `docs/PR_Backlog/StableNew_ComfyAware_Backlog_v2.6.md`

3. Duplicate And Redirect Rules

- `docs/archive/superseded/StableNew_Architecture_v2.6.md` is not an active
  architecture source.
- The only canonical architecture document is `docs/ARCHITECTURE_v2.6.md`.
- Any duplicate architecture summary must be archived or reduced to a redirect note.

4. Root Folder Rule

- `docs/` root is reserved for canonical active docs only.
- Backlogs and draft PR materials belong under `docs/PR_Backlog/`.
- Completed PR records belong under `docs/CompletedPR/`.
- Historical, superseded, discovery, and reference-only materials belong under
  `docs/archive/`.

5. Active Agent Instruction Surface

Active machine-facing guidance is catalogued in `.github/INSTRUCTION_SURFACE.md`.
That manifest is the single source of truth for what is active, what is
archived, and what precedence order applies.

6. Maintenance Rules

- If the runtime story changes, update `README.md` in the same PR.
- If canonical architecture or roadmap truth changes, update Tier 1 docs in the
  same PR.
- If migration order changes, update
  `docs/PR_Backlog/MIGRATION_CLOSURE_EXECUTABLE_BACKLOG_v2.6-1.md` in the same
  PR.
- If Comfy/video sequencing changes, update
  `docs/PR_Backlog/StableNew_ComfyAware_Backlog_v2.6.md` in the same PR.
- Historical documents should be archived, not left active.
