DOCS_INDEX_v2.6.md
Canonical Documentation Map and Navigation Guide

Status: Authoritative
Updated: 2026-03-20

## 0. Purpose

This index defines the active document set for StableNew v2.6 and identifies
which files are canonical, operational, backlog-driving, or archived.

## 1. Canonical Document Hierarchy

### 1.1 Tier 1 - System constitution

- `docs/ARCHITECTURE_v2.6.md`
- `docs/GOVERNANCE_v2.6.md`
- `docs/StableNew Roadmap v2.6.md`

### 1.2 Tier 2 - Execution and workflow canon

- `docs/PROMPT_PACK_LIFECYCLE_v2.6.md`
- `docs/Builder Pipeline Deep-Dive (v2.6).md`
- `docs/DEBUG HUB v2.6.md`
- `docs/ARCHITECTURE_ENFORCEMENT_CHECKLIST_v2.6.md`
- `docs/StableNew_Coding_and_Testing_v2.6.md`
- `docs/PR_TEMPLATE_v2.6.md`
- `docs/Canonical_Document_Ownership_v2.6.md`
- `AGENTS.md`
- `.github/copilot-instructions.md`

### 1.3 Tier 3 - Active subsystem references

- `docs/Learning_System_Spec_v2.6.md`
- `docs/GUI_Ownership_Map_v2.6.md`
- `docs/Movie_Clips_Workflow_v2.6.md`
- `docs/Image_Metadata_Contract_v2.6.md`
- `docs/REFINEMENT_POLICY_SCHEMA_v1.md`
- `docs/KNOWN_PITFALLS_QUEUE_TESTING.md`
- `docs/E2E_Golden_Path_Test_Matrix_v2.6.md`
- `docs/Randomizer_Spec_v2.6.md`

### 1.4 Tier 4 - Active backlog and planning queue

- `docs/PR_Backlog/MIGRATION_CLOSURE_EXECUTABLE_BACKLOG_v2.6-1.md`
- `docs/PR_Backlog/StableNew_ComfyAware_Backlog_v2.6.md`
- `docs/PR_Backlog/ADAPTIVE_REFINEMENT_EXECUTABLE_ROADMAP_v2.6.md`
- `docs/PR_Backlog/PR-VIDEO-215-Workflow-Video-Output-Routing-and-History-Convergence.md`
- `docs/PR_Backlog/PR-VIDEO-216-Sequence-Orchestration-and-Segment-Planning.md`
- `docs/PR_Backlog/PR-VIDEO-217-Stitching-Interpolation-and-Clip-Assembly-Unification.md`
- `docs/PR_Backlog/PR-VIDEO-218-Continuity-Pack-Foundation.md`
- `docs/PR_Backlog/PR-VIDEO-219-Story-and-Shot-Planning-Foundation.md`
- `docs/PR_Backlog/PR-GUI-220-UX-First-Workspace-Polish-on-Tkinter.md`
- `docs/PR_Backlog/PR-CTRL-221-GUI-Config-Adapter-and-Final-Controller-Shrink.md`
- `docs/PR_Backlog/PR-HARDEN-224-Adaptive-Refinement-Contracts-and-Dark-Launch-Foundation.md`
- `docs/PR_Backlog/PR-HARDEN-225-Prompt-Intent-Analysis-and-Observation-Only-Decision-Capture.md`
- `docs/PR_Backlog/PR-HARDEN-226-Detector-Boundary-and-Optional-OpenCV-Subject-Assessment.md`
- `docs/PR_Backlog/PR-HARDEN-227-Safe-ADetailer-Adaptive-Policy-Application.md`
- `docs/PR_Backlog/PR-HARDEN-228-Prompt-Patch-and-Upscale-Policy-Integration.md`
- `docs/PR_Backlog/PR-HARDEN-229-Learning-Loop-and-Recommendation-Aware-Refinement-Feedback.md`

### 1.5 Reference and history

- `docs/CompletedPR/` contains completed PR records
- `docs/archive/` contains historical, superseded, and reference-only material

## 2. Canonical Reading Order

Read in this order:

1. `README.md`
2. `docs/DOCS_INDEX_v2.6.md`
3. `docs/ARCHITECTURE_v2.6.md`
4. `docs/GOVERNANCE_v2.6.md`
5. `docs/StableNew Roadmap v2.6.md`
6. `docs/PR_TEMPLATE_v2.6.md`
7. subsystem docs relevant to the work
8. active PR backlog specs if planning or executing roadmap work

## 3. Root Folder Rule

- `docs/` root is reserved for active docs only
- `docs/PR_Backlog/` is for active and historical planning docs
- `docs/CompletedPR/` is for completed PR records
- `docs/archive/` is reference-only and not active canon

## 4. Explicit Non-Active Documents

These are no longer part of the active root doc set:

- `docs/archive/superseded/StableNew_v2.6_Canonical_Execution_Contract.md`
- `docs/archive/reference/Cluster_Compute_Spec_v2.5.md`
- `docs/archive/reference/Randomizer_Spec_v2.5.md`
- `docs/archive/reference/testing/TEST-SUITE-ANALYSIS-2026-01-01.md`
- `docs/CompletedPR/PR-CI-JOURNEY-001-CI-Journey-Tests-with-WebUI-Mocks.md`

## 5. Retained v2.5 Document

No v2.5 docs remain in the active root set.

## 6. Maintenance Rules

- If active file locations change, update this index in the same PR.
- If a doc stops being active, move it to `CompletedPR` or `archive`, do not
  leave it in the root folder.
- If a retained v2.5 doc is superseded, remove it from the active hierarchy in
  the same PR that introduces the replacement.
