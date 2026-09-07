# PR-REPO-CONVERGENCE-002 — Establish Authoritative Main and Integrate Repository Simplification

**Type:** Repository integration / Git convergence / regression validation  
**Priority:** Critical — complete before any further product PRs  
**Risk:** High if performed mechanically; moderate if performed using the controlled process below

## Objective

Converge StableNew's currently fragmented development state into **one verified, authoritative `main` branch** containing:

1. all intended recovered/MVP work;
2. all intended QOL work, including the latest known-working image-generation state;
3. `PR-REPO-HYGIENE-001` commit `9906997`;
4. no accidental loss of unique work;
5. no newly introduced image-generation, runner, queue, or pipeline regressions.

After successful convergence:

- `main` must represent the current product;
- `main` must contain the simplified repository/instruction structure from `PR-REPO-HYGIENE-001`;
- obsolete fully-integrated branches should be deleted;
- branches with genuinely unique unresolved work must remain explicitly identified;
- subsequent Codex work should start from `main` and normally use one short-lived outcome branch.

Do **not** begin PR-MVP-040, PR-MVP-050, or any other feature/refactor work in this PR.

---

# 1. Preserve the Known-Working QOL Baseline

The current/local `QOL-Work` state has been able to generate images successfully, although runner stalls and queue errors have sometimes occurred.

Treat this as an important functional regression baseline.

Before integration:

1. `git fetch --all --prune`
2. inspect local and remote `QOL-Work`;
3. verify whether Rob's latest intended local changes have been committed;
4. verify the current QOL commit is pushed to `origin/QOL-Work`.

If meaningful intended QOL source/configuration changes remain uncommitted, preserve them before proceeding.

Do not commit transient/generated files simply to make the worktree clean.

Report the exact:

- local QOL SHA;
- remote QOL SHA;
- whether they match;
- working-tree status;
- commits unique to QOL;
- purpose of those commits.

Create an annotated safety tag at the verified known-working QOL commit:

`baseline/qol-imagegen-pre-convergence-2026-09-07`

Push that tag to `origin`.

Also preserve the existing remote `main` position with an annotated tag:

`baseline/main-pre-convergence-2026-09-07`

Push that tag as well.

These tags are safety/recovery markers and should remain after old branches are eventually removed.

---

# 2. Verify the Current Git Graph Before Changing Anything

Inspect:

- `origin/main`
- local `main`
- `QOL-Work`
- `origin/QOL-Work`
- `recovery/mvp-baseline`
- `repo/simplification-and-hygiene`
- commit `9f1be49792688b056fd608750bbaeebcaf87f509`
- commit `9906997a6a19c1d38f0129851bc5f440f3825d0e`
- all other local and remote branches containing unique commits
- all worktrees
- all stashes

Use merge-base, commit ancestry, patch equivalence, file/tree comparison, and actual diffs rather than relying only on branch names.

Produce a commit-disposition table for every commit that is unique among:

- `origin/main`
- latest QOL baseline
- `recovery/mvp-baseline`
- hygiene branch

Use:

| Commit | Source | Purpose | Already represented elsewhere? | Integrate? | Method |
|---|---|---|---|---|---|

Do not assume two differently named commits contain different work.

Do not assume a merge commit must be retained merely because it exists.

---

# 3. Establish a Pre-Integration Functional Baseline

Before changing the repository, establish what "working" means at the known-good QOL baseline.

At minimum run the normal automated verification applicable to that commit.

Record:

- collection count;
- required smoke result;
- focused pipeline/queue/runner tests;
- existing failures;
- optional dependency skips.

## Real image-generation baseline

If the local WebUI/model/GPU environment used by Rob is available to Codex, perform one controlled representative image-generation run on the QOL baseline.

Prefer:

- a known existing PromptPack;
- fixed seed;
- fixed model;
- fixed sampler/scheduler;
- fixed resolution;
- ordinary single-image execution;
- no experimental video or unrelated feature.

Record:

- exact QOL SHA;
- relevant generation settings;
- whether the job entered the queue;
- whether execution started;
- whether the runner completed;
- whether an output artifact was produced;
- any queue warnings;
- any runner stalls;
- any exceptions;
- relevant diagnostic/log location.

Do not commit the generated image or runtime diagnostic artifacts.

The purpose is behavioral comparison, not pixel-perfect image validation.

If a real generation cannot be performed because the necessary local runtime is unavailable, explicitly state that and rely on the strongest automated pipeline/runner tests available.

---

# 4. Prove the Hygiene PR Did Not Introduce Existing Test Failures

The previous hygiene run reported:

- 3,086 tests collected;
- required smoke: 74 passed on Python 3.11 and 74 passed on Python 3.12;
- broad diagnostic: 10 failed, 215 passed, 2 skipped.

Codex previously characterized the 10 broad failures as pre-existing.

Verify that claim directly.

Run the same relevant broad diagnostic against:

1. `recovery/mvp-baseline` at `9f1be49`;
2. hygiene state at `9906997`.

Compare the failures by test name and failure mode.

Classify them as:

- identical pre-existing failure;
- altered by hygiene;
- newly introduced by hygiene;
- resolved by hygiene;
- environment-dependent.

Do not attribute a failure to "pre-existing debt" without evidence.

Also review the hygiene changes involving:

- `JobService` fixture teardown;
- autorun disabling in the queue-envelope test.

Verify these changes improve test isolation rather than mask production behavior.

If they suppress a real runtime failure, surface that before integration.

---

# 5. Build a Dedicated Convergence Branch

Create a new clean worktree/branch for this integration.

Preferred branch name:

`repo/converge-authoritative-main`

Do not use the dirty original QOL worktree for integration.

Determine the safest starting point from the actual Git graph.

The resulting branch must contain the desired state of:

- main;
- recovery;
- QOL;
- hygiene.

## Integration philosophy

Do **not** simply perform wholesale merges of every historical branch.

Instead:

1. determine which commits/changes are actually required;
2. identify superseded or duplicate work;
3. apply the intended changes in dependency order;
4. resolve conflicts based on current architecture and desired product behavior;
5. retain the known-working QOL behavior unless a newer recovery implementation intentionally supersedes it.

Use cherry-pick, replay, selective merge, manual resolution, or another normal Git method based on repository evidence.

The goal is a clean product state, not preservation of a complicated historical graph.

Do not rewrite or force-push existing safety branches.

---

# 6. Conflict-Resolution Priority

When QOL, recovery, hygiene, and main disagree, resolve conflicts using this priority:

### Functional behavior

Prefer the implementation that represents the current intended working application.

The known-working QOL image-generation behavior is an important reference.

### Current architecture

Use the current recovered/MVP architecture rather than resurrecting superseded legacy paths.

### Hygiene operating model

Preserve the repository simplification from `9906997` unless a specific deleted artifact is proven necessary.

Do not restore hundreds of deleted historical documents merely because an older branch references them.

### Current tests

Tests that represent current architecture should be preserved.

Legacy tests that assert superseded contracts should not dictate resurrection of obsolete runtime behavior.

### Historical documentation

Historical PR specs, completed plans, generated inventories, snapshots, old instruction surfaces, and archives are lowest priority and should normally remain deleted.

---

# 7. Protect Image Generation and the Core Pipeline

The most important functional acceptance behavior is:

> A normal StableNew image job can be created, queued, executed by the runner, and produce an image artifact.

Pay particular attention to conflicts affecting:

- `JobService`
- queue persistence
- pipeline runner
- pipeline controller
- GUI submission
- NJR creation
- PromptPack compilation
- model/backend invocation
- history/artifact recording
- worker lifecycle
- autorun behavior

Rob has already observed occasional:

- runner stalls;
- queue errors.

Do not automatically classify every occurrence of these as a new regression.

Compare post-integration behavior against the QOL baseline.

Distinguish:

- known pre-existing instability;
- materially worse behavior;
- genuinely new failure.

---

# 8. Validate the Integrated Branch

After convergence, run the same validation used for the baseline.

At minimum:

- `git diff --check`
- repository completeness check
- Ruff baseline
- mypy smoke
- test collection gate
- required smoke
- focused architecture/entrypoint tests
- focused queue/runner/pipeline tests
- broad diagnostic test run

Then repeat the representative image-generation run using the **same configuration and fixed seed** used for the QOL baseline, if the runtime is available.

Compare:

| Behavior | QOL baseline | Integrated branch |
|---|---|---|
| Job accepted | | |
| Queue entry created | | |
| Runner starts | | |
| Runner completes | | |
| Image artifact produced | | |
| History/artifact recorded | | |
| Queue error | | |
| Runner stall | | |
| Exception | | |

Exact image identity is not required unless the pipeline is expected to be deterministic.

Functional pipeline completion is the principal test.

---

# 9. Regression Handling

If integration causes a failure not present at the baseline:

Do not move `main`.

Instead:

1. identify the smallest conflicting change set;
2. determine whether the regression comes from:
   - recovery;
   - QOL reconciliation;
   - hygiene;
   - conflict resolution itself;
3. repair it if the correct behavior is clear and the repair is within the integration scope;
4. rerun the relevant baseline comparison.

Do not introduce a large new architecture refactor to repair an integration regression.

If the correct resolution is ambiguous, preserve the integration branch and report the issue to Rob/ChatGPT.

---

# 10. Update Repository Truth

Once the integrated result is validated, update:

`STATUS.md`

It should reflect the resulting actual state, including:

- `main` as authoritative;
- current product state;
- current test baseline;
- known runner/queue instability;
- highest-priority remaining product debt;
- next intended outcome.

Remove stale references to:

- hygiene integration still pending;
- recovery integration still pending;
- QOL being the active source of truth.

README and other active docs should only be updated if integration makes an existing statement inaccurate.

Do not create another integration-status document.

---

# 11. Publish and Establish Authoritative `main`

If all required acceptance criteria pass and no material regression remains:

1. commit the convergence work;
2. push `repo/converge-authoritative-main`;
3. integrate it into `main` using normal non-destructive Git operations;
4. push `main`;
5. verify `origin/main` resolves to the intended integrated state.

**Never force-push `main`.**

If normal integration to `main` is not possible without a force push, stop and report why.

After pushing, fetch again and verify local/remote SHAs.

The important final condition is:

> A fresh clone of `origin/main` contains the intended recovery/QOL functionality and the repository simplification from `9906997`.

---

# 12. Branch Cleanup After Successful Integration

Only after `origin/main` is verified:

Re-evaluate all local and remote branches.

Delete branches that are proven:

- fully merged;
- patch-equivalent;
- superseded;
- devoid of unique work.

This should normally include QOL/recovery/hygiene branches once their intended contents are proven represented in `main`.

Do not delete branches containing unresolved unique work.

Keep the two baseline tags created in Section 1.

For remaining unique backup/archive branches, report exactly what unique commits remain and why they are being retained.

The desired normal state is:

```text
main
└── authoritative long-lived branch

one short-lived feature/outcome branch
└── only while active work is underway
```

Historical safety should primarily come from Git commits/tags rather than a forest of permanent branches.

---

# 13. Required Final State

Do not start another product PR.

Stop after repository convergence and return the following report.

## A. Pre-integration state

- main SHA
- QOL SHA
- recovery SHA
- hygiene SHA
- dirty state
- worktrees
- stashes
- baseline tags created

## B. Commit disposition

Provide the complete commit-disposition table.

## C. Integration

- integration branch
- starting point
- commits/replays performed
- conflicts encountered
- how each meaningful conflict was resolved
- final integration SHA

## D. Hygiene preservation

Confirm whether the following remain true:

- concise `AGENTS.md`
- concise Copilot pointer
- `STATUS.md`
- approximately minimal active docs
- historical docs removed
- generated inventories/reports/snapshots ignored
- specialized redundant agent instructions removed

Report anything from `9906997` that had to be restored and why.

## E. Baseline vs integrated validation

Provide side-by-side results for:

- collection
- smoke
- focused tests
- broad diagnostic
- real image-generation smoke, if available

## F. Image pipeline comparison

Explicitly answer:

**Can the integrated version still generate a normal image through the queue/runner pipeline?**

Answer:

- Yes
- No
- Not testable in this environment

Then explain the evidence.

## G. Known pre-existing failures

List failures/instability that existed before integration and remain afterward.

Do not mix these with newly introduced regressions.

## H. New regressions

List any newly introduced regression.

If none:

`No new regressions identified relative to the verified QOL/recovery baselines.`

## I. Main publication

- local main SHA
- origin/main SHA
- whether they match
- whether a force push was used — expected answer: **No**
- whether a fresh remote checkout would contain the integrated state

## J. Branch disposition

| Branch | Unique work remaining? | Action |
|---|---:|---|

Include local and remote branches.

## K. Remaining repository complexity

List only the five largest remaining sources.

## L. Final Repo Compass

Return:

```text
Repo:
Authoritative branch:
HEAD:
Origin HEAD:
Working tree:
Active work branch:
Active docs:
Test state:
Known runtime issues:
Top 3 remaining debts:
Recommended next PR:
```

## M. Problems encountered

Surface every material issue, unexpected conflict, uncertainty, skipped validation, environment limitation, or judgment call that Rob/ChatGPT should know about.

Do not omit resolved problems merely because they were resolved.

---

# Acceptance Criteria

This PR is complete only when:

- [ ] Latest intended QOL state is committed and safely backed up.
- [ ] Known-working QOL SHA is tagged.
- [ ] Pre-convergence main SHA is tagged.
- [ ] All unique recovery/QOL/hygiene/main work is dispositioned.
- [ ] No intended QOL functionality is lost.
- [ ] Hygiene changes from `9906997` are retained unless specifically justified.
- [ ] Historical repository clutter is not accidentally restored.
- [ ] Pre/post test results are compared.
- [ ] The claim that pre-existing broad-suite failures are pre-existing is verified.
- [ ] Queue/runner/image-generation behavior is compared against baseline where possible.
- [ ] No material new image-generation regression exists.
- [ ] `STATUS.md` reflects the resulting truth.
- [ ] Integrated result is committed.
- [ ] Integrated result is pushed.
- [ ] `origin/main` becomes the authoritative integrated state.
- [ ] `main` is not force-pushed.
- [ ] Fully obsolete branches are removed only after equivalence is proven.
- [ ] Branches containing unresolved unique work are retained and documented.
- [ ] Repository/worktree is clean at completion.
- [ ] No subsequent feature PR is started.
- [ ] Full completion report is returned for independent ChatGPT review.

# Scope Guard

Do not use this PR to:

- redesign queue persistence;
- implement SQLite migration;
- converge PromptPack formats;
- conduct broad V1/V2 deletion;
- redesign the GUI;
- fix all Ruff findings;
- fix all mypy findings;
- solve all pre-existing queue stalls;
- solve every pre-existing test failure;
- begin video architecture work.

Those are subsequent product/technical PRs.

The purpose of this PR is narrower and more important:

**establish one safe, simplified, tested, authoritative repository state from which all subsequent work will proceed.**