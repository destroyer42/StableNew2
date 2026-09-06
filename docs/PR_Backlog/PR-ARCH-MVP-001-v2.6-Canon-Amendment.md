# PR-ARCH-MVP-001 - v2.6 Canon Amendment for MVP Recovery

Status: Specification
Priority: CRITICAL
Effort: MEDIUM
Phase: MVP Phase 0 — Canon and recovery control
Date: 2026-09-05

## 2. Context & Motivation

The active v2.6 documentation mixed three incompatible stories: an older
PromptPack-centric identity model, a broader NJR model added during migration,
and later video/runtime workarounds. Code history shows that the large runtime
host cutover destabilized working behavior, while current code and tests still
contain compensating `pack_required`, pack-shaped request, mutable NJR, and
multiple persistence assumptions.

The owner authorized the architecture canon to be amended and requested one
synchronized, active MVP roadmap. This PR records the selected design: preserve
the proven queue/NJR/runner spine, reduce NJR to immutable authorized work,
separate mutable execution records, use source-specific typed compilers, make
PromptPack identity conditional, converge persistence on SQLite, remain
same-process for MVP, and support native SVD XT as the sole MVP video backend.

Evidence and decision basis:

- repository and commit-history audit dated 2026-09-05;
- `f919cb4` as the best demonstrated stable behavioral reference;
- failed runtime-host sequence `5634849` -> `75ffb27` -> `303cbdb` ->
  `fab810b`;
- current `pack_required` validation in `src/controller/job_service.py`;
- broad current NJR in `src/pipeline/job_models_v2.py` and pack-shaped
  `PipelineRunRequest` in `src/pipeline/job_requests_v2.py`;
- ignored but imported `src/state/` production modules;
- owner instruction approving this synchronized amendment and both PR specs.

Canonical references:

- `docs/ARCHITECTURE_v2.6.md`
- `docs/GOVERNANCE_v2.6.md`
- `docs/PR_TEMPLATE_v2.6.md`

## 3. Goals & Non-Goals

### Goals

1. Establish one evidence-based v2.6 target architecture for MVP.
2. Label current implementation gaps instead of presenting targets as complete.
3. Make the Finalized MVP Roadmap the only active roadmap.
4. Synchronize all repository-wide execution and documentation guidance.
5. Record exact MVP scope, sequencing, release gates, risks, and deferred work.
6. Generate owner-approved `PR-MVP-000` as the next runtime handoff.

### Non-goals

1. Do not change Python, schemas, tests, workflows, dependencies, or runtime
   data.
2. Do not execute the recovery branch operation.
3. Do not implement the NJR, compiler, repository, PromptPack, image, or video
   target contracts.
4. Do not delete or relocate historical backlog/completed/archive files in this
   amendment.
5. Do not claim that planned MVP contracts already work.

## 4. Guardrails

- This is a documentation-only architecture amendment explicitly authorized by
  the human owner.
- The preserved queue-only and single-`run_njr` invariants may not be weakened.
- Every unimplemented target must remain visible in the architecture gap
  register and roadmap.
- No Tier 3 document may expand MVP scope.
- Existing user changes, especially `data/webui_cache.json`, must remain
  untouched.
- NJR, queue, runner, GUI, and persistence code contracts are documented but not
  modified by this PR.

## 5. Allowed Files

### Files to Create

- `docs/PR_Backlog/PR-ARCH-MVP-001-v2.6-Canon-Amendment.md`
- `docs/PR_Backlog/PR-MVP-000-Recovery-Baseline-and-Repository-Completeness.md`

### Files to Modify

- `AGENTS.md`
- `.github/copilot-instructions.md`
- `.github/INSTRUCTION_SURFACE.md`
- `README.md`
- `docs/ARCHITECTURE_v2.6.md`
- `docs/GOVERNANCE_v2.6.md`
- `docs/PROMPT_PACK_LIFECYCLE_v2.6.md`
- `docs/Builder Pipeline Deep-Dive (v2.6).md`
- `docs/StableNew Roadmap v2.6.md`
- `docs/StableNew_Coding_and_Testing_v2.6.md`
- `docs/DEBUG HUB v2.6.md`
- `docs/ARCHITECTURE_ENFORCEMENT_CHECKLIST_v2.6.md`
- `docs/Subsystems/Testing/E2E_Golden_Path_Test_Matrix_v2.6.md`
- `docs/Subsystems/Learning/Learning_System_Spec_v2.6.md`
- `docs/Subsystems/Training/Character_Embedding_Workflow_v2.6.md`
- `docs/Subsystems/Video/Movie_Clips_Workflow_v2.6.md`
- `docs/DOCS_INDEX_v2.6.md`
- `docs/Canonical_Document_Ownership_v2.6.md`
- `docs/PR_TEMPLATE_v2.6.md`

### Forbidden Files

- `src/**`
- `tests/**`
- `data/**`
- `state/**`
- `packs/**`
- `config/**`
- `.github/workflows/**`
- dependency/lock files
- all files not explicitly listed above

## 6. Implementation Plan

1. **Reconcile Tier 1 architecture.** In architecture and governance, record the
   preserved runtime spine, target NJR/source/repository contracts, MVP process
   and video scope, current evidence, and closing PRs.
2. **Reconcile intent documentation.** In the PromptPack lifecycle and builder
   deep-dive, establish one-file versioned JSON, import/export-only TXT/TSV,
   typed source compilers, conditional identity, and NJR-only submission.
3. **Replace the roadmap.** Make `docs/StableNew Roadmap v2.6.md` the Finalized
   MVP Roadmap, include the recovery evidence, active order, definition of done,
   critical weaknesses, controls, and release gates.
4. **Reset test/enforcement canon.** Replace the stale broad golden matrix and
   enforcement checklist, and replace contradictory testing addenda with MVP
   journeys and standards that distinguish hermetic, GUI, migration, and
   real-backend acceptance.
5. **Fence adjacent subsystem claims.** Clarify Debug Hub state ownership,
   learning source identity, the training compiler target/current gap, and the
   post-MVP scope of Movie Clips outside native SVD handoff.
6. **Synchronize machine guidance.** Update `AGENTS.md`, the Copilot brief, and
   instruction manifest without creating new agent profiles or path-scoped
   instruction files.
7. **Synchronize navigation and process.** Update README, docs index, ownership
   map, and PR template; remove CompletedPlans from active PR authority and admit
   `ARCH`/`MVP` categories.
8. **Create approved handoffs.** Add this spec and `PR-MVP-000`, recording the
   owner's 2026-09-05 approval while clearly distinguishing prepared docs from
   committed/merged work.
9. **Validate consistency.** Run whitespace/link/reference/phrase checks and
   inspect the final diff. Do not run runtime tests because runtime is outside
   scope.

## 7. Testing Plan

### Unit tests

Not applicable; no runtime code changes.

### Integration tests

Not applicable.

### Journey or smoke coverage

- Verify every active canonical file in `DOCS_INDEX_v2.6.md` exists.
- Verify the active roadmap points to both created PR specs.
- Search active Tier 1/Tier 2 docs and executor briefs for conflicting claims:
  universal PromptPack identity, live `DIRECT`, paired PromptPack authority,
  child-runtime-host MVP, or Comfy/LTX MVP.
- Verify current/target wording and the architecture gap register remain present.

### Manual verification

Run:

```text
git diff --check
git status --short
git diff --stat
```

Confirm only allowed documentation files changed and the pre-existing
`data/webui_cache.json` modification remains untouched.

## 8. Verification Criteria

### Success criteria

1. The active architecture, governance, lifecycle, builder, testing, README, and
   agent briefs describe the same outer runtime and ownership boundaries.
2. The architecture names every known MVP implementation gap and closing PR.
3. The roadmap title/status explicitly identify it as current and active.
4. Only this spec and `PR-MVP-000` are listed as approved active specs.
5. MVP video is native SVD XT only; deferred systems are explicit.
6. No runtime or user-data file is modified.
7. Owner approval is recorded in both PR specs.

### Failure criteria

- Any active doc still makes PromptPack a universal job identity.
- Any active doc presents TXT+JSON pairing, `DIRECT`, a child runtime host, or
  Comfy/LTX as the MVP architecture.
- Target contracts are stated as completed without a gap entry.
- A forbidden file changes.
- Historical plans remain listed as active roadmap authority.

## 9. Risk Assessment

### Low-risk areas

- Navigation, ownership, and wording changes are reversible Git changes.

### Medium-risk areas with mitigation

- **Loss of useful older detail:** the change leaves historical files in place
  and replaces only active canon; `PR-MVP-005` will triage unlisted backlog.
- **Tier 3 contradictions:** Tier 3 cannot override the new MVP scope; any
  runtime-relevant contradiction must be handled by the PR that touches that
  subsystem.

### High-risk areas with mitigation

- **Canon outruns implementation:** explicit target labels, the gap register,
  closing PRs, and clean-checkout closeout gates prevent false completion.
- **Repeat big-bang migration:** the roadmap sequences repository recovery,
  test trust, NJR, compilers, persistence, and vertical slices separately.

### Rollback plan

Revert only this docs amendment commit. No runtime/data rollback is needed.
Restore the previous docs as historical material, not as silently mixed canon,
if the owner chooses a different architecture through a new approved amendment.

## 10. Tech Debt Analysis

### Debt removed

- Competing active roadmap/status claims.
- Universal PromptPack identity in active canon.
- Paired TXT/JSON PromptPack authority in active canon.
- Conflation of immutable NJR and mutable execution state.
- CompletedPlans incorrectly treated as active PR authority.
- Ambiguous MVP video and runtime-host scope.

### Debt intentionally deferred

- Repository completeness — owner: `PR-MVP-000`.
- Later branch delta disposition — owner: `PR-MVP-005`.
- Test harness/collection truth — owner: `PR-MVP-010`.
- NJR implementation — owner: `PR-MVP-020`.
- Typed compilers/submission — owner: `PR-MVP-030`.
- SQLite persistence/migration — owner: `PR-MVP-040`.
- PromptPack code/data migration — owner: `PR-MVP-050`.
- Image/video product slices — owners: `PR-MVP-060` and `PR-MVP-070`.
- Setup/release closure — owners: `PR-MVP-080` and `PR-MVP-090`.

## 11. Documentation Updates

All files in the allowed list are updated in this PR. They remain active at
their tiers. The two created specs remain in `docs/PR_Backlog/` until executed
and closed. On implementation closeout, move this PR's final record to
`docs/CompletedPR/`, update roadmap/index, and remove the backlog copy.

Tier 1/Tier 2 wording is validated against the 2026-09-05 code/history/test audit
and deliberately records contrary current implementation in the gap register.

## 12. Dependencies

### Internal module dependencies

None; documentation-only.

### External tools or runtimes

- Git for diff/status validation.
- No network, model, WebUI, GPU, database, or GUI dependency.

## 13. Approval & Execution

Planner: Codex
Executor: Codex (documentation only)
Reviewer: Rob
Approval Status: **Approved**
Approval Basis: Rob's 2026-09-05 instruction to create the synchronized
amendments and generate and approve `PR-MVP-000` and `PR-ARCH-MVP-001`.
Execution State: Amendments prepared in the working tree; commit/merge review
remains outstanding.

## 14. Next Steps

1. Review and commit this documentation amendment as one atomic change.
2. Execute approved `PR-MVP-000` on the specified non-destructive recovery
   branch/worktree.
3. Draft `PR-MVP-005` only after `PR-MVP-000` proves repository completeness.
