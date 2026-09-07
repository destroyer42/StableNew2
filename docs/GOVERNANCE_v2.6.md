# StableNew Governance v2.6

Status: Authoritative
Updated: 2026-09-05

## 0. Purpose

This document governs architecture, planning, implementation, testing, and
documentation during the MVP recovery. It prevents a repeat of the earlier
migration failure by requiring the repository, canon, tests, and PR closeout to
tell the same story.

## 1. Authority and precedence

The active hierarchy is:

1. Human owner decisions recorded in an approved architecture or PR document.
2. Tier 1: `ARCHITECTURE_v2.6.md`, this document, and the active roadmap.
3. Tier 2 execution/workflow canon listed in `DOCS_INDEX_v2.6.md`.
4. Tier 3 subsystem references.
5. Approved PR specifications.
6. implementation code and tests as evidence of current state, not automatic
   authority to redefine the architecture.
7. completed and archived documents as history only.

When active documents conflict, stop affected implementation and resolve the
contradiction in one synchronized docs change. A historical document, passing
legacy test, or currently working workaround cannot silently override canon.

## 2. Governing architecture invariants

- Typed intent compilers converge on one immutable NJR envelope.
- Fresh work enters `JobService` and the queue; `Run Now` is immediate-start
  queue policy.
- `PipelineRunner.run_njr(...)` is the sole public production runner entry.
- NJR owns immutable authorized work; queue/history own mutable execution state.
- Since PR-MVP-020, the eight-field NJR and recursive immutability are enforced
  in code; source compilers and the reduced submission policy remain governed
  by PR-MVP-030.
- PromptPack identity is conditional on a PromptPack source.
- `JobRepository` is the sole persistence boundary; SQLite is the MVP target.
- Migration is backup-first and offline, with no live legacy fallback.
- StableNew owns orchestration; backends own typed execution only.
- MVP is same-process, single-node, and native-SVD-only for video.

## 3. Current truth versus target truth

Canonical target contracts may precede implementation only when all of the
following are true:

1. the architecture labels them as targets;
2. the active gap register identifies current contrary evidence;
3. the active roadmap assigns a closing PR;
4. tests are not rewritten to claim completion before code is changed;
5. closeout removes the gap only after clean-checkout verification.

Unknown or contradictory implementation is a discovery issue, not permission
to add a shim.

## 4. Roles

### 4.1 Planner/architect

The planner reconciles requested behavior, code evidence, test evidence, and
canonical constraints; creates atomic PR specs; updates synchronized docs; and
names risks, migration boundaries, and deletion work.

### 4.2 Executor

The executor changes only approved files, implements the approved contract,
runs proportionate verification, preserves unrelated work, and stops when the
spec cannot be completed without expanding architecture or file scope.

### 4.3 Reviewer

The reviewer checks behavior, architecture, migration safety, tests, repository
cleanliness, and documentation truth. A green subset is not sufficient when
collection, clean checkout, or persistence migration is part of acceptance.

### 4.4 Human owner

The owner sets product scope and approves architecture and PR execution. An
owner instruction becomes an architectural override only when incorporated into
the synchronized canonical amendments and approval record.

## 5. Required PR lifecycle

1. **Discovery**: record current code, tests, data, branch, and failure evidence.
2. **Specification**: use `PR_TEMPLATE_v2.6.md`; list exact allowed and forbidden
   files, ordered work, tests, migration, rollback, and debt disposition.
3. **Approval**: record owner/reviewer approval in the spec.
4. **Execution**: make only approved changes; do not extrapolate.
5. **Verification**: run targeted tests plus required architecture, persistence,
   and clean-checkout gates.
6. **Review**: compare delivered behavior to both spec and architecture.
7. **Closeout**: create one CompletedPR record, update roadmap/index, and remove
   or relocate the backlog copy.

Large migrations must be split at contract boundaries. A temporary bridge is
allowed only when the same approved sequence makes it single-directional,
observable, and schedules its deletion. Dual production execution paths remain
forbidden.

## 6. Documentation synchronization

The following changes require same-PR documentation updates:

| Runtime change | Required canonical surfaces |
|---|---|
| NJR or source identity | Architecture, governance, builder/lifecycle docs, coding/testing, roadmap |
| Queue, history, or repository | Architecture, coding/testing, golden-path matrix, roadmap |
| PromptPack format | PromptPack lifecycle, builder deep-dive, architecture, migration tests |
| Runner/backend scope | Architecture, subsystem docs, golden paths, roadmap |
| Active plan/status | Roadmap and docs index |
| Agent rules | `AGENTS.md`, Copilot brief, and instruction manifest when its enumerated surface changes |

Completed plans and archived docs never become active by reference. If old
material is useful, extract the still-valid rule into an active document.

## 7. Repository and migration safety

- Production source files must be tracked and present in a clean checkout.
- Generated runtime state must be ignored with anchored, narrow patterns.
- Tests must use temporary workspaces and must not alter tracked repository data.
- Data migrations create backups first, validate counts and identities, report
  conflicts, and are rerunnable.
- No destructive cleanup occurs until the new store is verified and rollback is
  demonstrated.
- Branch recovery preserves current branches and user changes; no hard reset is
  an approved recovery method.

## 8. MVP scope control

An item is in the MVP only when it appears in the MVP definition of done in the
active roadmap. Comfy/LTX video, distributed execution, automated closed-loop
learning, full training productization, and broad UI redesign are deferred.
Existing experimental code does not expand release scope.

## 9. Enforcement

A PR fails governance if it:

- creates a second executable job or persistence authority;
- requires PromptPack identity from unrelated intent;
- stores runtime results in NJR;
- uses tests to preserve a superseded workaround;
- leaves an undocumented compatibility path;
- claims completion without clean-checkout evidence;
- changes files outside its approved boundary;
- overwrites user state or migration source data;
- leaves active docs contradictory.

The correct response is to narrow or revise the PR, not to weaken the invariant.
