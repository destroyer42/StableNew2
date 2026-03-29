DOCS_INDEX_v2.6.md
Canonical Documentation Map and Navigation Guide

Status: Authoritative
Updated: 2026-03-29

## 0. Purpose

This index defines the active document set for StableNew v2.6 and identifies
which files are canonical, operational, backlog-driving, completed, under
review, or archived.

It also defines the target folder taxonomy for the active doc set so root-level
canonical truth stays separate from subsystem references, research material,
completed implementation records, and historical planning notes.

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

- `docs/Architecture/ARTIFACT_METADATA_CONTRACTS_v2.6.md`
- `docs/Subsystems/Learning/Learning_System_Spec_v2.6.md`
- `docs/Subsystems/Training/Character_Embedding_Workflow_v2.6.md`
- `docs/Subsystems/GUI/GUI_Ownership_Map_v2.6.md`
- `docs/Subsystems/GUI/GUI_AUDIT_AND_CONSISTENCY_INVENTORY_v2.6.md`
- `docs/Subsystems/GUI/GUI_CONSISTENCY_MAINTENANCE_CHECKLIST_v2.6.md`
- `docs/Subsystems/Video/Movie_Clips_Workflow_v2.6.md`
- `docs/Architecture/Image_Metadata_Contract_v2.6.md`
- `docs/schemas/stablenew.image-metadata.v2.6.json`
- `docs/schemas/stablenew.review.v2.6.json`
- `docs/schemas/portable_review_summary.v2.6.json`
- `docs/schemas/artifact_metadata_inspection.v2.6.json`
- `docs/Architecture/StableNew Secondary Motion Layer Design.md`
- `docs/Architecture/Prompt_Optimizer_WorldClass_v3_Design.md`
- `docs/Architecture/REFINEMENT_POLICY_SCHEMA_v1.md`
- `docs/Architecture/SECONDARY_MOTION_POLICY_SCHEMA_V1.md`
- `docs/Subsystems/Testing/KNOWN_PITFALLS_QUEUE_TESTING.md`
- `docs/Research Reports/WebUI Restart and Lost Connection Investigation 2026-03-20.md`
- `docs/Research Reports/WebUI GPU Pressure and Stall Investigation 2026-03-21.md`
- `docs/Research Reports/deep-research-report-DEEP GPU memory and stall investigation - verdict.md`
- `docs/Research Reports/staged-curation-learning-verdict-2026-03-21.md`
- `docs/Subsystems/Testing/E2E_Golden_Path_Test_Matrix_v2.6.md`
- `docs/Subsystems/Randomizer/Randomizer_Spec_v2.6.md`

### 1.4 Tier 4 - Active backlog and planning queue

- `docs/PR_Backlog/CORE_TOP_20_EXECUTABLE_MINI_ROADMAP_v2.6.md`
- `docs/PR_Backlog/PR-CORE-014 - Multi-Character Support.md`
- `docs/PR_Backlog/TOP_20_VERDICTS_AND_POST_VIDEO241_QUEUE_v2.6.md`

### 1.5 Reference and history

- `docs/CompletedPR/` contains completed PR records
- `docs/CompletedPlans/` contains completed executable roadmaps, sweeps, and
  multi-PR sequence records
- `docs/NeedsReview/` contains ambiguous or recently superseded material that
  still needs an explicit disposition
- completed rollout docs that no longer belong in the active backlog now live
  in `docs/CompletedPlans/`, including
  `MIGRATION_CLOSURE_EXECUTABLE_BACKLOG_v2.6-1.md`,
  `STAGED_CURATION_EXECUTABLE_ROADMAP_v2.6.md`, and
  `UX_HELP_AND_IN-PRODUCT_GUIDANCE_EXECUTABLE_SEQUENCE_v2.6.md`, and
  `StableNew_ComfyAware_Backlog_v2.6.md`
- superseded queue snapshots and retired backlog specs now live in
  `docs/archive/reference/`, including
  `MASTER_PR_SEQUENCE_FROM_CURRENT_REPO_STATE_v2.6.md`,
  `REVISED_MINI_ROADMAP_PR_ORDER_v2.6.md`,
  `HYBRID_STAGED_CURATION_REVIEW_HANDOFF_PR_SEQUENCE_v2.6.md`,
  `VIDEO_AND_SECONDARY_MOTION_REMAINING_WORK_SEQUENCE_v2.6.md`,
  `PR-TEST-280-Full-Suite-Collection-Recovery-and-Test-Hygiene.md`, and
  `PR-POLISH-282-Canonical-Roadmap-Video-Status-Harmonization.md`
- retired discovery docs moved out of the backlog now live in
  `docs/archive/discovery/`, including
  `D-NSFW-SFW-001-Content-Visibility-Mode-Discovery.md`
- `docs/CompletedPlans/ADAPTIVE_REFINEMENT_EXECUTABLE_ROADMAP_v2.6.md`
- `docs/CompletedPlans/SECONDARY_MOTION_EXECUTABLE_ROADMAP_v2.6.md`
- `docs/CompletedPlans/PROMPT_OPTIMIZER_EXECUTABLE_ROADMAP_v2.6.md`
- `docs/CompletedPR/PR-LEARN-259A-Curation-Contracts-Lineage-and-Selection-Events.md`
- `docs/CompletedPR/PR-LEARN-259B-Learning-Workspace-Staged-Curation-Mode.md`
- `docs/CompletedPR/PR-LEARN-259C-Review-History-Import-and-Large-Compare-Surface.md`
- `docs/CompletedPR/PR-LEARN-259D-Derived-Stage-Advancement-and-Face-Triage-Routing.md`
- `docs/CompletedPR/PR-LEARN-259E-Learning-Evidence-Bridge-and-Reason-Tag-Analytics.md`
- `docs/CompletedPR/PR-LEARN-259F-Replay-Diagnostics-and-Workflow-Summaries.md`
- `docs/CompletedPR/PR-CONFIG-271-Content-Visibility-Mode-Contract-and-Persistence.md`
- `docs/CompletedPR/PR-CTRL-272-Content-Visibility-Resolver-and-Selector-Wiring.md`
- `docs/CompletedPR/PR-GUI-273-Mode-Toggle-UX-and-Cross-Tab-Filtering.md`
- `docs/CompletedPR/PR-TEST-274-Content-Visibility-Regression-and-Journey-Hardening.md`
- `docs/CompletedPR/PR-ARCH-243-Archive-Import-Fencing-and-Reference-Relocation.md`
- `docs/CompletedPR/PR-HYGIENE-244-Tracked-Runtime-State-Purge-and-Hygiene-Enforcement.md`
- `docs/CompletedPR/PR-CI-245-CI-Truth-Sync-and-Smoke-Suite-Contract.md`
- `docs/CompletedPR/PR-ARCH-246-Architecture-Enforcement-Expansion-and-Import-Guards.md`
- `docs/CompletedPR/PR-CTRL-247-PipelineController-Service-Extraction-and-Facade-Reduction.md`
- `docs/CompletedPR/PR-PORTS-248-Backend-Port-Boundaries-for-Image-and-Video-Runtimes.md`
- `docs/CompletedPR/PR-REPLAY-250-Replay-Fidelity-Contract-and-Versioned-Validation.md`
- `docs/CompletedPR/PR-APP-251-Shared-Application-Bootstrap-and-Kernel-Composition.md`
- `docs/CompletedPR/PR-HARDEN-252-Optional-Dependency-Capabilities-and-Startup-Probes.md`
- `docs/CompletedPR/PR-HARDEN-256-WebUI-Pressure-Guardrails-and-Failure-Damping.md`
- `docs/CompletedPR/PR-HARDEN-257-WebUI-State-Recovery-and-Admission-Control.md`
- `docs/CompletedPR/PR-HARDEN-281-ADetailer-Stability-Closure-and-Request-Local-Pinning-Rollback.md`
- `docs/CompletedPR/PR-CORE-001-Finalize-Native-SVD-Integration.md`
- `docs/CompletedPR/PR-CORE-002-Character-Embedding-Pipeline.md`
- `docs/CompletedPR/PR-CORE-004-Cinematic-Prompt-Template-Library.md`
- `docs/CompletedPR/PR-CORE-011-End-to-End-Pipeline-Tests.md`
- `docs/CompletedPR/PR-CI-253-Mypy-Smoke-Gate-and-Whitelist-Expansion.md`
- `docs/CompletedPR/PR-CONTRACT-254-Intent-Artifact-Versioning-and-Hash-Closure.md`
- `docs/CompletedPR/PR-VIDEO-255-Workflow-Registry-Governance-and-Pinning-Closure.md`
- `docs/CompletedPR/PR-GUI-283-AppController-UI-Boundary-Closure-and-Operator-Log-Projection.md`
- `docs/CompletedPR/PR-GUI-284-AppState-Batched-Invalidation-and-Flush-Contract.md`
- `docs/CompletedPR/PR-GUI-285-Hot-Surface-Refresh-Scheduler-and-Subscription-Ownership.md`
- `docs/CompletedPR/PR-GUI-286-Incremental-Projection-Reconciliation-and-Visibility-Gating.md`
- `docs/CompletedPR/PR-HARDEN-287-Runtime-Status-Backpressure-GUI-Perf-Journey-and-Architecture-Guards.md`
- `docs/CompletedPR/PR-VIDEO-236-Secondary-Motion-Intent-Contract-and-Observation-Only-Policy-Carrier.md`
- `docs/CompletedPR/PR-VIDEO-237-Shared-Secondary-Motion-Engine-and-Provenance-Contract.md`
- `docs/CompletedPR/PR-VIDEO-238-SVD-Native-Secondary-Motion-Postprocess-Integration.md`
- `docs/CompletedPR/PR-VIDEO-239-AnimateDiff-Secondary-Motion-Frame-Pipeline-Integration.md`
- `docs/CompletedPR/PR-VIDEO-240-Workflow-Video-Secondary-Motion-Parity-and-Replay-Closure.md`
- `docs/CompletedPR/PR-VIDEO-241-Learning-and-Risk-Aware-Secondary-Motion-Feedback.md`
- `docs/archive/` contains historical, superseded, and reference-only material
- `docs/runbooks/TRACKED_RUNTIME_STATE_HYGIENE_v2.6.md`

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

## 3. Folder Taxonomy

- `docs/` root is reserved for Tier 1 and Tier 2 canonical docs only
- `docs/Architecture/` is for active architecture contracts, policy schemas,
  and design references
- `docs/Subsystems/` is for active Tier 3 subsystem and operational references
  that are not canonical root docs
- `docs/Research Reports/` is for discovery reports, investigations, deep
  dives, verdicts, and implementation-guidance notes
- `docs/PR_Backlog/` is for open PR specs and still-active unfinished planning
  docs only
- `docs/CompletedPR/` is for one final closeout file per completed PR
- `docs/CompletedPlans/` is for completed multi-PR sequences, executable
  roadmaps, and finished sweep plans
- `docs/NeedsReview/` is for ambiguous or recently superseded material awaiting
  explicit disposition
- `docs/runbooks/` is for active operator runbooks
- `docs/schemas/` is for active machine-readable contract companions
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
- If a PR changes runtime, product, or process truth, update the affected
  canonical docs in the same PR or explicitly retire the stale docs.
- If a PR completes, create or update one final `docs/CompletedPR/PR-...md`
  record, update roadmap and index references as needed, and remove the
  duplicate execution spec from `docs/PR_Backlog/`.
- If a whole executable roadmap or sweep becomes complete, move it to
  `docs/CompletedPlans/` instead of leaving it in `docs/PR_Backlog/`.
- If a document's status or applicability is uncertain, move it to
  `docs/NeedsReview/` instead of leaving it active by default.
- If a doc stops being active, move it to `CompletedPR`, `CompletedPlans`,
  `NeedsReview`, or `archive` as appropriate; do not leave it in the root
  folder.
- If a retained v2.5 doc is superseded, remove it from the active hierarchy in
  the same PR that introduces the replacement.
