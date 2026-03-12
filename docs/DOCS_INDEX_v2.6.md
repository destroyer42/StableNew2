DOCS_INDEX_v2.6.md
Canonical Documentation Map and Navigation Guide

Status: Authoritative
Updated: 2026-03-11

0. Purpose

This index defines the active document set for StableNew v2.6 and identifies which files are canonical, operational, or archived.

1. Canonical Document Hierarchy

1.1 Tier 1 - System Constitution

- `docs/ARCHITECTURE_v2.6.md`
- `docs/GOVERNANCE_v2.6.md`
- `docs/StableNew Roadmap v2.6.md`

1.2 Tier 2 - Canonical Specification Layer

- `docs/PROMPT_PACK_LIFECYCLE_v2.6.md`
- `docs/Builder Pipeline Deep-Dive (v2.6).md`
- `docs/DEBUG HUB v2.6.md`
- `docs/StableNew_Coding_and_Testing_v2.6.md`
- `docs/PR_TEMPLATE_v2.6.md`
- `AGENTS.md`
- `.github/copilot-instructions.md`
- `docs/StableNew_v2.6_Canonical_Execution_Contract.md`

1.3 Tier 3 - Subsystem Specifications

- `docs/Randomizer_Spec_v2.5.md` until a v2.6 replacement exists
- `docs/Learning_System_Spec_v2.5.md` until a v2.6 replacement exists
- `docs/Cluster_Compute_Spec_v2.5.md` until a v2.6 replacement exists
- `docs/Image_Metadata_Contract_v2.6.md`
- `docs/Movie_Clips_Workflow_v2.6.md` — Movie Clips MVP tab and service boundary

1.4 Tier 4 - Implementation And PR Specs

- `docs/OpenSpec/`
- `docs/pr_templates/`
- `docs/PR_MAR26/`

These documents implement or sequence canonical work but do not outrank Tiers 1-2.

1.5 Tier 5 - Testing Infrastructure

- `docs/E2E_Golden_Path_Test_Matrix_v2.6.md`
- `docs/KNOWN_PITFALLS_QUEUE_TESTING.md`
- `docs/PR-CI-JOURNEY-001.md`
- `docs/TEST-SUITE-ANALYSIS-2026-01-01.md`

1.6 Tier 6 - Operator And Reference Guides

- `docs/agentic/USAGE_GUIDE.md`
- `.github/PULL_REQUEST_TEMPLATE.md`
- `.github/workflows/copilot-setup-steps.yml`

These support development but do not override canonical docs.

2. Active Agent Instruction Surface

Active machine-facing guidance lives in:

- `AGENTS.md`
- `.github/copilot-instructions.md`
- `.github/agents/`
- `.github/instructions/`

Archived agent or SOP files under `docs/archive/` are reference-only.

3. Required Reading Order

3.1 Foundations

- `docs/ARCHITECTURE_v2.6.md`
- `docs/GOVERNANCE_v2.6.md`
- `docs/StableNew Roadmap v2.6.md`

3.2 Execution Path

- `docs/PROMPT_PACK_LIFECYCLE_v2.6.md`
- `docs/Builder Pipeline Deep-Dive (v2.6).md`
- `docs/DEBUG HUB v2.6.md`
- `docs/StableNew_v2.6_Canonical_Execution_Contract.md`

3.3 Coding And PR Workflow

- `docs/StableNew_Coding_and_Testing_v2.6.md` — includes §8 Runtime Artifact Policy (PR-CLEANUP-LEARN-045): `data/learning/experiments/`, `data/photo_optimize/assets/`, `state/` are gitignored runtime artifacts; `tests/fixtures/` is for committed static fixtures only
- `docs/PR_TEMPLATE_v2.6.md`
- `AGENTS.md`
- `.github/copilot-instructions.md`

3.4 Operational Usage

- `docs/agentic/USAGE_GUIDE.md`
- `.github/PULL_REQUEST_TEMPLATE.md`

4. Archival Rules

The following must be archived rather than left active:

- duplicate `AGENTS.md` copies outside the chosen active source of truth
- stale Copilot/Codex SOP files
- duplicate or one-off custom agent profiles
- docs that reference retired architecture, retired file paths, or missing canonical docs

Archive location for the 2026 agentic refresh:

- `docs/archive/agents/2026-agentic-refresh/`

5. Maintenance Rules

- If active agent file locations change, update this index in the same PR.
- If canonical governance changes, update `AGENTS.md` and the executor brief together.
- If a document is only historical, move it to `docs/archive/` rather than leaving it active.
