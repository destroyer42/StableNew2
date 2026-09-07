# PR-REPO-HYGIENE-001 — StableNew Repository Simplification and AI Operating Model Reset

**Type:** Repository hygiene / documentation governance / developer experience / AI operating model  
**Priority:** High  
**Risk:** Moderate  
**Primary objective:** Make StableNew substantially easier for Rob and Codex to understand, navigate, maintain, and evolve without altering intended product behavior.

---

# 1. Intent

StableNew has accumulated substantial repository-management complexity around the product:

- overlapping AI instruction files
- extensive historical documentation
- multiple PR-record systems
- stale or contradictory documentation
- generated inventories and snapshots committed to the repository
- temporary/test artifacts
- several long-lived branches
- obsolete or possibly unreachable code
- multiple places that attempt to describe the current state or development direction

The desired end state is a repository where:

1. `main` is the clear long-lived source of truth.
2. Active work happens on one short-lived branch at a time.
3. Rob can understand repository direction without reconstructing it from historical PRs.
4. Codex can understand the repository using a small, authoritative instruction surface.
5. Historical material does not consume normal agent context.
6. Generated diagnostics and inventories are created on demand rather than permanently committed unless they serve an active product purpose.
7. Current product state and immediate direction are visible from one concise file.
8. Dead/stale code can subsequently be removed based on evidence rather than historical speculation.

This PR MUST prioritize **simplification, deletion, consolidation, and clear ownership** over adding additional governance layers.

---

# 2. Critical Safety Requirement — Secure Existing Work First

Before implementing any cleanup, determine the exact current repository state.

Do **not** assume the repository is clean or that the current branch is safe to abandon.

## 2.1 Preflight inspection

Report:

- repository path
- current branch
- current HEAD SHA
- upstream/tracking branch
- `git status`
- staged changes
- unstaged changes
- untracked files
- current branch ahead/behind upstream
- current branch ahead/behind `main`
- local branches
- remote branches
- worktrees
- stashes
- latest relevant commits
- whether the current work appears complete, incomplete, or ambiguous
- whether any currently running/unfinished Codex task is evident from the working tree or branch state

Run an appropriate fetch first so remote comparisons are current.

## 2.2 If existing work is in progress

If the current branch contains meaningful unfinished work:

**Finish the current coherent unit of work before beginning this PR whenever reasonably possible.**

That means:

1. understand the purpose of the current work;
2. finish any obviously incomplete implementation associated with that purpose;
3. run the appropriate validation/tests;
4. commit the completed coherent unit;
5. push it to its existing remote branch if the branch is intended to be retained remotely;
6. clearly report what was finished.

Do not mix repository-hygiene changes into an unfinished functional change.

## 2.3 If existing work cannot safely be completed

If current work is incomplete, broken, ambiguous, or outside the information available to Codex:

- do **not** discard it;
- do **not** silently reset it;
- do **not** stash it and forget about it;
- preserve it in a safe and recoverable state;
- commit a clearly labeled checkpoint only if doing so is safer than leaving uncommitted work;
- push the checkpoint branch when appropriate;
- report exactly what remains incomplete and why.

If a commit would falsely imply completed functionality, use an explicit checkpoint/WIP commit message.

## 2.4 Establish a safe cleanup baseline

Repository hygiene work should begin only when Codex can state:

> Existing work has been completed or safely checkpointed, the current state is recoverable, and repository cleanup can proceed without destroying or obscuring functional work.

Prefer creating a dedicated branch from the correct clean baseline, for example:

`repo/simplification-and-hygiene`

Do not perform this cleanup directly on an unrelated feature branch.

---

# 3. Phase 1 — Establish Current Repository Truth

Before editing, inspect the repository deeply enough to verify or correct the assumptions in this PR.

Produce an internal working inventory of:

- root-level files/directories
- `.github/`
- `docs/`
- `src/`
- `tests/`
- `tools/`
- `archive/`
- `inventory/`
- `snapshots/`
- generated reports
- temporary/probe directories
- PR specification/history directories
- agent instruction files
- path-specific instruction files
- current roadmap/backlog/status documents

Also identify:

- active code paths
- obvious duplicate top-level structures
- stale documentation references
- contradictions among active documentation
- historical documents living outside designated archive areas
- generated artifacts that do not need permanent tracking
- OS/editor junk
- duplicate repo inventories
- stale temporary files
- committed diagnostic artifacts
- stale branch references embedded in documentation

Do not delete source code merely because an old generated report marks it as unreachable.

---

# 4. Phase 2 — Simplify the AI Instruction Surface

The current AI operating model is too procedural and too distributed.

The target is a small instruction surface centered on one authoritative `AGENTS.md`.

## 4.1 Rewrite `AGENTS.md`

Replace the existing heavyweight multi-agent workflow with a concise repository operating contract.

Target length: approximately 100–200 lines unless repository reality requires slightly more.

It should contain:

### Product/repository identity

- what StableNew is
- authoritative repository identity
- primary runtime model

### Architectural invariants

Keep only the important rules Codex genuinely needs to avoid architectural drift.

Examples include:

- canonical outer job contract
- queue-first execution
- runner ownership
- canonical artifact/history/replay path
- GUI/controller/pipeline ownership boundaries
- prohibition on unnecessary parallel execution paths
- preference for removing obsolete compatibility layers rather than preserving them indefinitely

### Codex operating behavior

Codex should:

1. inspect before editing;
2. understand the requested product outcome;
3. determine the implementation implications from repository state;
4. explain material architectural tradeoffs;
5. prefer coherent changes rather than mechanical file-by-file instructions;
6. remove obsolete code where evidence supports removal;
7. validate changes with appropriate tests;
8. surface ambiguity or contradictions;
9. report repository/branch state at completion.

Codex should **not** be forced to reject normal product-owner language merely because Rob did not specify files or an exact PR implementation sequence.

### Human/Codex relationship

Rob defines:

- desired product behavior
- priorities
- constraints
- approval of material architecture changes

Codex determines:

- relevant implementation areas
- specific files required
- normal refactors needed to achieve the requested outcome
- tests needed
- low-level technical implementation decisions consistent with architecture

### Historical-context rule

Explicitly state that archived/historical material is not part of the normal instruction context and should only be consulted when relevant to a specific historical question.

## 4.2 Simplify `.github/copilot-instructions.md`

Prefer one of:

- deleting it if unnecessary, or
- reducing it to a small pointer to `AGENTS.md`.

It must not duplicate major sections of `AGENTS.md`.

Example intent:

> Follow `/AGENTS.md`. Read active subsystem documentation only when relevant to the requested task. Do not treat archive/history material as active architectural guidance.

## 4.3 Evaluate `.github/agents/`

Review each specialized agent profile.

For every file, determine:

- still necessary;
- redundant with `AGENTS.md`;
- useful only historically;
- unnecessary for current Codex workflow.

Remove or archive profiles that do not provide unique, high-value instructions.

Do not preserve files solely because they existed in the previous governance model.

## 4.4 Evaluate `.github/instructions/`

Review path-scoped instruction files.

Keep only instructions that:

- prevent a real architectural or operational failure;
- are specific to that path;
- cannot be expressed more simply in code/tests/static checks.

Remove redundant prose constraints.

## 4.5 Remove instruction-precedence contradictions

There must be one clear precedence model.

No active instruction file should claim contradictory authority.

---

# 5. Phase 3 — Create a Human-Readable Repository Compass

Create:

`STATUS.md`

This becomes the concise current-state entrypoint for both Rob and Codex.

It should NOT become another historical log.

Target length: normally under 150 lines.

Include:

## Repository

- authoritative repository
- default branch
- current release/version

## Product state

A concise statement of where StableNew currently stands.

## Runtime invariants

A short canonical runtime representation.

## Current work

- active outcome
- active work branch when applicable
- relationship to `main`

Do not hard-code stale branch information without an update mechanism or clear manual-maintenance rule.

## Known problems / current debt

Limit to the highest-value items.

## Now / Next / Later

Prefer a very small priority sequence.

Example:

**Now**
- active work currently being finished

**Next**
- highest-priority follow-up

**Later**
- material but non-immediate work

## Verification state

Include the latest verified test baseline only if it can be reliably maintained.

Avoid duplicating test counts across many documents.

## Update rule

Any PR that materially changes repository direction should update `STATUS.md`.

Do not use `STATUS.md` as a changelog.

---

# 6. Phase 4 — Simplify Documentation

Review the complete `docs/` tree.

The objective is not merely moving clutter from one folder to another.

The objective is to reduce the amount of documentation an agent or human must reason about during normal development.

## 6.1 Define the minimum active documentation set

Aim toward something conceptually similar to:

```text
docs/
├── ARCHITECTURE.md
├── ROADMAP.md
├── TESTING.md
├── runbooks/
├── schemas/
└── subsystem/
```

Exact naming does not need to match this if renaming would create disproportionate churn.

The important requirement is that the active set be obvious and small.

## 6.2 Canonical architecture

Evaluate whether all of these are genuinely necessary as separate active canonical documents:

- architecture
- governance
- architecture enforcement checklist
- builder pipeline deep dive
- prompt-pack lifecycle
- canonical document ownership
- debug hub
- coding/testing standards
- roadmap
- docs index

Consolidate documents where the separation does not materially help implementation.

Avoid having a documentation-management system more complicated than the application-management problem.

## 6.3 Fix stale references

At minimum validate:

- README references to current backlog locations
- test-count claims
- completed vs planned functionality
- moved files
- canonical document paths
- branch names
- repository names
- active vs historical PR sequences

No active document should knowingly point to a completed plan as if it is the active queue.

## 6.4 Clean historical directories

Review:

- `docs/older/`
- `docs/PRs/`
- `docs/NeedsReview/`
- `docs/CompletedPR/`
- `docs/CompletedPlans/`
- `docs/archive/`
- old planning directories
- prior instruction/governance files

Determine what can be:

- deleted because Git history already preserves it;
- retained only under a clearly fenced archive;
- consolidated into a concise historical summary;
- retained because it still provides unique operational value.

Strong preference:

**Do not keep hundreds of completed implementation records in the normal active context merely to preserve history that Git already contains.**

## 6.5 `NeedsReview`

Anything clearly implemented, completed, superseded, or invalid should not remain indefinitely in `NeedsReview`.

Disposition every item possible.

If something truly cannot be resolved, explicitly document why it remains.

---

# 7. Phase 5 — Remove Generated and Temporary Repository Clutter

Review committed artifacts such as:

- `inventory/repo_inventory.json`
- legacy candidate inventories
- `snapshots/repo_inventory.json`
- pipeline state snapshots
- committed ZIP snapshots
- temporary probe directories
- root-level review artifacts
- `desktop.ini`
- generated diagnostic reports
- redundant machine-generated state

Determine whether each file is:

1. necessary runtime/source data;
2. a reproducible generated artifact;
3. historical evidence;
4. accidental clutter.

Prefer deleting reproducible generated artifacts from Git and regenerating them when needed.

If a tool exists to regenerate the artifact, document that command instead of retaining large snapshots.

Update `.gitignore` to prevent recurrence where appropriate.

---

# 8. Phase 6 — Branch Hygiene

Inspect all local and remote branches.

Known remote branches may include items such as:

- `main`
- `QOL-Work`
- old feature branches
- Codex-generated branches
- archive branches
- repair/hardening branches

For each branch, determine:

- merged into `main`;
- superseded;
- contains unique unmerged work;
- intentionally retained;
- safe to delete.

Do not delete any branch with unique unmerged work.

Produce a recommended branch disposition table.

Where safe and authorized by normal repository operation, delete stale merged branches.

Target operating model:

- `main` = long-lived source of truth
- normally one short-lived active outcome branch
- merged branches deleted after completion
- archive branches used only when there is a compelling reason

Evaluate whether `main` should receive basic branch protection or equivalent safeguards.

Do not introduce a heavyweight enterprise Git workflow for a primarily single-owner repository.

---

# 9. Phase 7 — Dead/Stale Code Assessment

This PR should perform the **analysis and safe obvious cleanup**, but must not conduct reckless mass deletion based solely on old reachability reports.

Review:

- duplicate GUI implementations
- V1/V2 leftovers
- compatibility modules
- archived code still under active source directories
- unused adapters
- dead controllers
- obsolete tests
- duplicate test files
- migration-only paths
- archive/reference source files

For a source file to be deleted as dead code, establish reasonable evidence such as:

- no production imports
- no supported dynamic use
- no active entrypoint dependency
- no meaningful test dependency
- superseding implementation exists where required

Run appropriate tests after each coherent deletion group.

If substantial dead-code removal is too risky for this PR, produce a prioritized follow-on cleanup queue instead of forcing it into this PR.

The repository simplification must not become an uncontrolled architecture rewrite.

---

# 10. Phase 8 — README Reset

Update `README.md` so a new Codex session or human contributor can quickly understand:

1. what StableNew is;
2. how to run it;
3. the canonical runtime;
4. where current project state lives;
5. where architecture guidance lives;
6. where testing guidance lives.

Remove historical project-management detail that belongs elsewhere.

Explicitly state which GitHub repository is authoritative if naming ambiguity remains between `StableNew` and `StableNew2`.

---

# 11. Token-Efficient Codex Workflow

Document a concise recommended working pattern, preferably in `AGENTS.md` or a very small contributor section.

Codex should support two standard interaction modes.

## 11.1 Repo Compass

When asked for a repo orientation, report:

```text
Repo:
Current branch:
HEAD:
Tracking branch:
Ahead/behind main:
Working tree:
Current branch objective:
Relevant recent changes:
Test state:
Top risks:
Recommended next action:
```

Keep routine compass responses concise.

## 11.2 Outcome-first implementation

Rob should be able to say:

> I want [product/user outcome].

Codex should then:

1. inspect the relevant repository state;
2. explain current behavior;
3. identify the smallest coherent implementation;
4. identify what can be removed/consolidated;
5. identify files/subsystems affected;
6. identify risks;
7. propose validation;
8. implement once directed or when the task explicitly authorizes implementation.

Do not require Rob to know internal file boundaries in advance.

---

# 12. Testing and Validation

Repository simplification must not silently change StableNew runtime behavior.

At minimum:

- run formatting/lint/static checks applicable to touched files;
- run targeted tests for any source-code cleanup;
- run documentation/link/reference validation if tooling exists;
- run test collection;
- run the broadest practical regression suite appropriate to the repository state.

Compare test collection/count with the actual current result.

Update documentation to reflect the verified baseline.

If full tests cannot run successfully because of environment dependencies:

- run every viable subset;
- report the exact blocker;
- do not claim the repository is fully green.

---

# 13. Required Completion Report

At the end, Codex MUST provide a structured report suitable for handing directly back to ChatGPT.

Use this exact general structure.

## A. Repository state before cleanup

- original branch
- original HEAD
- dirty/clean
- existing work found
- how existing work was finished or preserved
- commits/pushes performed before cleanup

## B. Cleanup branch

- branch name
- base SHA
- final SHA
- remote push status

## C. Files/directories removed

Group by:

- historical docs
- generated artifacts
- temporary files
- redundant instructions
- dead code
- other

## D. Files consolidated or rewritten

Include:

- `AGENTS.md`
- Copilot instructions
- `STATUS.md`
- README
- active architecture/roadmap/testing docs
- `.gitignore`
- any other important governance files

## E. Branch dispositions

For every local/remote branch reviewed:

| Branch | Status | Unique work? | Action taken/recommended |
|---|---|---|---|

## F. Documentation issues found

List every meaningful contradiction or stale reference discovered and its disposition.

## G. Code-cleanup findings

Separate:

- deleted with confidence
- likely stale but retained
- requires deeper follow-up

## H. Validation

Report exact commands and results.

Include:

- collection count
- passed
- failed
- skipped
- environment blockers

## I. Problems encountered

**Surface every material issue.**

For each issue provide:

- what happened
- affected files/subsystem
- whether it was resolved
- how it was resolved
- remaining risk
- whether Rob/ChatGPT needs to make a decision

Do not hide or silently workaround contradictions.

## J. Remaining complexity

Identify the five largest remaining sources of repository complexity after this PR.

## K. Comparison to target repository model

Assess the resulting repository against:

```text
StableNew/
├── AGENTS.md
├── STATUS.md
├── README.md
├── CHANGELOG.md
├── docs/
│   ├── architecture
│   ├── roadmap
│   ├── testing
│   └── genuinely useful subsystem/runbook/schema docs
├── src/
├── tests/
├── tools/
├── packs/
└── required configuration/runtime assets
```

For each category report:

- achieved
- partially achieved
- not achieved
- reason

## L. Recommended next three actions

Return only the three highest-value follow-up actions.

---

# 14. Acceptance Criteria

This PR is complete when:

- [ ] Any pre-existing work was completed or safely preserved before cleanup.
- [ ] Cleanup occurred on a safe dedicated branch or otherwise did not contaminate unrelated functional work.
- [ ] Current branch/upstream/main relationships are documented.
- [ ] The active AI instruction surface is materially smaller.
- [ ] `AGENTS.md` supports outcome-first Codex work.
- [ ] Instruction precedence is unambiguous.
- [ ] `STATUS.md` exists and accurately describes current state.
- [ ] README reflects current repository/product truth.
- [ ] Stale documentation references were corrected.
- [ ] Historical documentation was substantially reduced or clearly fenced.
- [ ] Generated repo inventories/snapshots were removed from active tracking where unnecessary.
- [ ] Temporary/OS/test-probe artifacts were removed and ignored where appropriate.
- [ ] Branches were audited and stale branches dispositioned.
- [ ] No branch containing unique work was deleted.
- [ ] Obvious dead-code candidates were assessed using actual dependency evidence.
- [ ] Runtime behavior was not intentionally changed except for safe removal of proven-unused material.
- [ ] Tests/validation were run.
- [ ] Any failures or ambiguities were explicitly surfaced.
- [ ] The final report contains enough evidence for ChatGPT to independently reassess the repository afterward.

---

# 15. Important Constraints

Do not:

- destroy or overwrite current work;
- reset a dirty branch merely to obtain a clean state;
- mix unrelated feature implementation into repository hygiene;
- mass-delete code based only on `LEGACY_CANDIDATES.md`;
- preserve obsolete files solely because previous governance documents mentioned them;
- create new layers of repository-management documentation to explain the old layers;
- add elaborate Git process unnecessary for a single-owner project;
- claim tests pass if they were not run;
- hide encountered problems;
- leave the repository in an ambiguous unpushed state without reporting it.

Prefer:

- deletion over duplication;
- consolidation over additional abstractions;
- Git history over permanent historical files;
- one source of current truth;
- one concise instruction surface;
- product-owner language over PR bureaucracy;
- short-lived branches over permanent feature branches;
- evidence-backed cleanup over speculative deletion.

---

# 16. Final Handoff Requirement

After implementation, stop and provide the completion report from Section 13.

Do not immediately begin another large refactor.

The resulting state will be independently reviewed by ChatGPT against the target simplified repository model before further cleanup work is authorized.