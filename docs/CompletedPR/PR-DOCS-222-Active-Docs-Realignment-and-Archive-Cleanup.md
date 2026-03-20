# PR-DOCS-222 - Active Docs Realignment and Archive Cleanup

Status: Completed 2026-03-19

## Purpose

Realign the active docs set with the current post-unification v2.6 repo truth:

- queue-only fresh execution
- NJR as the sole outer execution contract
- PromptPack as the primary image authoring surface, not the only intent surface
- active docs root reserved for active docs only

## Delivered

### Root docs cleanup

Moved non-active root docs out of `docs/`:

- `docs/PR-CI-JOURNEY-001.md` ->
  `docs/CompletedPR/PR-CI-JOURNEY-001-CI-Journey-Tests-with-WebUI-Mocks.md`
- `docs/TEST-SUITE-ANALYSIS-2026-01-01.md` ->
  `docs/archive/reference/testing/TEST-SUITE-ANALYSIS-2026-01-01.md`
- `docs/StableNew_v2.6_Canonical_Execution_Contract.md` ->
  `docs/archive/superseded/StableNew_v2.6_Canonical_Execution_Contract.md`
- `docs/Cluster_Compute_Spec_v2.5.md` ->
  `docs/archive/reference/Cluster_Compute_Spec_v2.5.md`

### Canonical doc rewrites

Rewrote these active docs to current repo truth:

- `docs/GOVERNANCE_v2.6.md`
- `docs/PROMPT_PACK_LIFECYCLE_v2.6.md`
- `docs/Builder Pipeline Deep-Dive (v2.6).md`
- `docs/KNOWN_PITFALLS_QUEUE_TESTING.md`
- `docs/Movie_Clips_Workflow_v2.6.md`
- `docs/Canonical_Document_Ownership_v2.6.md`
- `docs/DOCS_INDEX_v2.6.md`
- `docs/DEBUG HUB v2.6.md`

### Targeted doc updates

Updated active supporting docs:

- `README.md`
- `.github/copilot-instructions.md`
- `.github/PULL_REQUEST_TEMPLATE.md`
- `docs/agentic/USAGE_GUIDE.md`
- `docs/Learning_System_Spec_v2.6.md`
- `docs/Image_Metadata_Contract_v2.6.md`

## Result

The active `docs/` root now contains only active docs, and the live guidance
surface no longer points executors at the archived execution-contract document
or at stale root-level PR and test-analysis records.

## Deferred Follow-On

- replace `docs/Randomizer_Spec_v2.5.md` with a v2.6 rewrite in a later docs or
  subsystem PR
- revisit whether `docs/GUI_Ownership_Map_v2.6.md` needs a broader refresh after
  `PR-GUI-220` and `PR-CTRL-221`
