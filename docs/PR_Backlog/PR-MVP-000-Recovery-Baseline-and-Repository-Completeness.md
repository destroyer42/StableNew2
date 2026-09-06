# PR-MVP-000 - Recovery Baseline and Repository Completeness

Status: Specification
Priority: CRITICAL
Effort: MEDIUM
Phase: MVP Phase 0 — Canon and recovery control
Date: 2026-09-05

## 2. Context & Motivation

The current repository cannot yet prove that its apparently stable behavior is
reproducible from version-controlled source. Audit found that more than twenty
production imports reach `src.state`, while these required files exist locally
but are hidden by the unanchored `.gitignore` rule `state/`:

- `src/state/__init__.py`
- `src/state/workspace_paths.py`
- `src/state/output_routing.py`

A disposable tracked-files-only worktree at the candidate stable commit could
not import the application because that package was absent. The current working
tree also contains a user-owned modification to `data/webui_cache.json` that
must not be disturbed.

Commit evidence identifies `f919cb4` as the best demonstrated stable behavioral
baseline. Later `main` (`d452a2a`), `QOL-Work` (`1a9eb49`), and fix commit
`24063b7` contain changes that must remain available for later individual audit.
The failed child-runtime-host sequence is not a recovery base.

This PR establishes a recoverable, complete source baseline before any NJR or
feature migration begins. It implements no product or architecture feature.

References:

- `docs/ARCHITECTURE_v2.6.md`, sections 12–13
- `docs/GOVERNANCE_v2.6.md`, section 7
- `docs/StableNew Roadmap v2.6.md`, Phase 0
- `docs/StableNew_Coding_and_Testing_v2.6.md`, section 2
- `PR-ARCH-MVP-001`

## 3. Goals & Non-Goals

### Goals

1. Create a non-destructive recovery branch/worktree rooted at `f919cb4` plus
   the single reviewed `PR-ARCH-MVP-001` docs commit.
2. Preserve `main`, `QOL-Work`, all comparison commits, and the original dirty
   working tree unchanged.
3. Anchor the root runtime-state ignore rule so it does not hide `src/state/`.
4. Audit, minimally correct if necessary, and track the three required state
   modules.
5. Add an automated repository-completeness check and focused tests.
6. Prove the result from a second tracked-files-only disposable worktree.
7. Record exact provenance, hashes, commands, and results at closeout.

### Non-goals

1. Do not merge/cherry-pick later runtime commits wholesale.
2. Do not redesign NJR, JobService, queue, runner, persistence, PromptPack,
   video, GUI, or controller behavior.
3. Do not fix unrelated tests, lint, type, or runtime defects.
4. Do not edit, delete, migrate, or reset runtime/user data.
5. Do not claim full application or MVP health.
6. Do not import changes from `24063b7`, `d452a2a`, or `1a9eb49`; that decision
   belongs to `PR-MVP-005`.

## 4. Guardrails

- Use a new Git worktree; do not switch, clean, stash, reset, or mutate the
  owner's current `QOL-Work` working tree.
- Root the recovery branch at exactly `f919cb4`.
- Before runtime edits, carry exactly the committed `PR-ARCH-MVP-001`
  documentation commit. If it is not available as one reviewed commit, stop and
  obtain its exact commit hash; do not recreate or partially cherry-pick it.
- Preserve the queue-only, NJR-only public execution path and same-process MVP.
- No NJR, queue, runner, GUI, controller, backend, or persistence contracts may
  change.
- State modules may receive only corrections required for tracked-files-only
  import/operation and their existing focused tests. Any broader behavior change
  requires a revised spec.
- No destructive Git or filesystem command is authorized.

## 5. Allowed Files

### Files to Create

- `tools/ci/check_repository_completeness.py`
- `tests/system/test_repository_completeness_v2.py`
- `docs/CompletedPR/PR-MVP-000-Recovery-Baseline-and-Repository-Completeness.md`
  (closeout only)

### Files to Modify

- `.gitignore`
- `src/state/__init__.py`
- `src/state/workspace_paths.py`
- `src/state/output_routing.py`
- `tests/state/test_workspace_paths.py`
- `tests/state/test_output_routing.py`
- `docs/ARCHITECTURE_v2.6.md` (gap status only at verified closeout)
- `docs/StableNew Roadmap v2.6.md` (status/next action only at closeout)
- `docs/DOCS_INDEX_v2.6.md` (spec disposition only at closeout)
- `docs/PR_Backlog/PR-MVP-000-Recovery-Baseline-and-Repository-Completeness.md`
  (closeout disposition/removal)

### Forbidden Files

- `data/**`
- `state/**`
- `packs/**`
- `config/**`
- all `src/**` except the three explicitly allowed `src/state/` files
- all `tests/**` except the three explicitly allowed test files
- `.github/workflows/**`
- dependency/lock files
- branch pointers `main` and `QOL-Work`
- all files not explicitly listed above

## 6. Implementation Plan

1. **Preflight and preserve evidence.** In the original worktree, record current
   branch/HEAD, `main`, `QOL-Work`, `24063b7`, `f919cb4`, `git status --short`,
   and hashes of the three local `src/state/` files. Do not modify that worktree.
2. **Create isolated recovery worktree.** Verify
   `C:\Users\rob\projects\StableNew-mvp-recovery` does not exist. Create branch
   `recovery/mvp-baseline` at exactly `f919cb4` in that new worktree. If either
   branch or path already exists, stop and report rather than overwrite it.
3. **Carry the canon amendment.** Cherry-pick exactly the reviewed, single
   `PR-ARCH-MVP-001` docs commit and record its hash. Resolve no runtime conflict;
   if one appears, stop.
4. **Correct ignore scope.** Change the root runtime-state rule from `state/` to
   `/state/`. Verify root `state/` remains ignored and all three `src/state/`
   files are not ignored.
5. **Audit source provenance.** Compare the local state modules against all
   known commit objects/branches and their consumers. Record whether each file
   is recovered verbatim or requires an allowed minimal correction. Do not
   borrow unrelated later-branch changes.
6. **Track and test state modules.** Add the three modules. Update only the two
   existing state tests as needed to prove path rooting, output routing, no
   import-time writes, and temporary-workspace behavior.
7. **Add repository-completeness guard.** Create a deterministic, offline check
   that fails when a Python file under `src/` is ignored/untracked or when
   tracked source statically imports a missing internal module. Exclude generated
   caches and make exclusions explicit. Add focused tests with temporary Git
   repositories/fixtures; do not inspect or modify user data.
8. **Verify from tracked files only.** Create a second disposable worktree from
   the candidate commit/tree, run the commands in section 7, and confirm no
   ignored local source is copied in. Compare `git status --short` before and
   after tests.
9. **Close out.** Record actual files/hashes/commands/results in one CompletedPR
   file. Mark only the repository-completeness architecture gap closed, update
   roadmap/index, and remove the backlog copy in the same commit. Do not mark
   broader startup, test-suite, or MVP gaps complete.

## 7. Testing Plan

Use the managed Python 3.11 environment in the isolated recovery worktree.

### Unit tests

```text
pytest tests/state/test_workspace_paths.py -q
pytest tests/state/test_output_routing.py -q
pytest tests/system/test_repository_completeness_v2.py -q
```

Tests must use temporary paths and leave both worktrees unchanged.

### Integration tests

```text
python tools/ci/check_repository_completeness.py
python -m compileall src
python -c "import src.state; import src.state.workspace_paths; import src.state.output_routing"
```

### Journey or smoke coverage

In the second tracked-files-only disposable worktree:

```text
git ls-files --error-unmatch src/state/__init__.py
git ls-files --error-unmatch src/state/workspace_paths.py
git ls-files --error-unmatch src/state/output_routing.py
git check-ignore -q src/state/workspace_paths.py
git check-ignore -q state/queue_state_v2.json
python tools/ci/check_repository_completeness.py
python -m compileall src
pytest tests/state/test_workspace_paths.py tests/state/test_output_routing.py tests/system/test_repository_completeness_v2.py -q
```

Expected Git semantics: the `git check-ignore` command for `src/state/...`
returns nonzero; the command for root `state/...` returns zero.

### Manual verification

- Confirm original `QOL-Work` status and `data/webui_cache.json` are unchanged.
- Confirm `main` and `QOL-Work` refs are unchanged.
- Confirm no file outside the allowed list differs after subtracting the carried
  docs commit.
- Inspect the three source files for network, worker, GUI, or persistence side
  effects at import time.
- Record `git diff --check` and before/after `git status --short`.

## 8. Verification Criteria

### Success criteria

1. `recovery/mvp-baseline` has ancestry at `f919cb4` and includes exactly the
   reviewed canon amendment plus this scoped recovery change.
2. The original working tree, user data, and protected branch refs are unchanged.
3. All three `src/state/` modules are tracked and no longer ignored.
4. Root runtime `state/` remains ignored.
5. The completeness checker and focused tests pass in a tracked-files-only
   worktree.
6. Production source compilation and the three state imports succeed there.
7. Tests create no tracked-file changes.
8. Closeout updates only the repository-completeness gap and points next to
   `PR-MVP-005`/`PR-MVP-010`.

### Failure criteria

- Any protected branch, original worktree change, or runtime data is altered.
- Recovery requires an unapproved file or later runtime commit.
- A required source module remains ignored/untracked.
- The check passes only when local ignored files are present.
- Import/compile/test writes into the repository or starts external activity.
- The PR includes architecture/feature refactoring.
- Broad application or MVP health is claimed from this narrow proof.

## 9. Risk Assessment

### Low-risk areas

- Anchoring `.gitignore` is narrow and directly testable.
- Adding isolated guard tests does not touch runtime behavior.

### Medium-risk areas with mitigation

- **State-file provenance is uncertain:** hash and compare every candidate;
  restrict corrections to allowed modules and focused behavior.
- **Static import analysis can false-positive:** test explicit package/relative
  import cases and document narrow exclusions; it is a completeness guard, not
  a general dependency resolver.

### High-risk areas with mitigation

- **Loss of user work/history:** operate in a new worktree, record refs/status,
  forbid reset/clean/stash and all user-data edits.
- **Wrong baseline selection:** preserve all branches and schedule evidence-based
  delta triage in `PR-MVP-005`; no later work is destroyed.
- **Docs commit not isolated:** stop unless the exact reviewed docs commit can be
  identified and carried without runtime changes.

### Rollback plan

Because work occurs on a new branch/worktree, rollback is to stop using that
branch and remove the worktree only after the owner confirms no unique data is
inside it. Do not delete the branch or worktree automatically. The original
repository remains untouched. The recovery commit itself can be reverted on its
branch without changing `main` or `QOL-Work`.

## 10. Tech Debt Analysis

### Debt removed

- Production imports depending on ignored/untracked `src/state/` code.
- Ambiguous root-versus-source `state/` ignore behavior.
- No automated tracked-source completeness check.
- No reproducible recovery provenance.

### Debt intentionally deferred

- Later-commit selection — owner: `PR-MVP-005`.
- Global collection/test isolation — owner: `PR-MVP-010`.
- NJR/source identity — owner: `PR-MVP-020`.
- Compiler/JobService migration — owner: `PR-MVP-030`.
- Persistence convergence — owner: `PR-MVP-040`.
- PromptPack/image/video product behavior — owners: `PR-MVP-050` through
  `PR-MVP-070`.

## 11. Documentation Updates

At verified closeout only:

- update the repository-completeness row in `docs/ARCHITECTURE_v2.6.md`;
- mark `PR-MVP-000` completed and set the next action in the active roadmap;
- replace this backlog copy with one final record in `docs/CompletedPR/` and
  update `docs/DOCS_INDEX_v2.6.md`.

All other canonical target/gap statements remain active. The closeout record is
the only new completed document.

## 12. Dependencies

### Internal module dependencies

- `src.state` consumers already present on the recovery baseline.
- Existing focused state tests.
- The committed `PR-ARCH-MVP-001` docs amendment.

### External tools or runtimes

- Git worktree support.
- Project-managed Python 3.11 and pytest.
- No WebUI, network, GPU, SVD model, ffmpeg, or GUI display is required.

## 13. Approval & Execution

Planner: Codex
Executor: Codex
Reviewer: Rob
Approval Status: **Approved**
Approval Basis: Rob's 2026-09-05 instruction to generate and approve
`PR-MVP-000` and begin the finalized MVP roadmap.
Execution Prerequisite: `PR-ARCH-MVP-001` must first exist as one reviewed docs
commit whose exact hash can be recorded.
Execution State: Not started.

## 14. Next Steps

1. Commit/review `PR-ARCH-MVP-001` as one documentation commit.
2. Execute this PR in the isolated recovery worktree.
3. After closeout, write the exact `PR-MVP-005` delta-disposition spec; do not
   adopt later commits before that review.
