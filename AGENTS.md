# StableNew Multi-Agent Development Rules v2.6

Status: Canonical repository instruction
Updated: 2026-09-05

## 1. Purpose

StableNew is developed by Rob (product owner), planner/architect agents,
executor agents such as Codex, and inline assistants such as Copilot. These
rules keep code, tests, documentation, and PR status aligned while the MVP is
recovered.

The active machine-facing guidance inventory is
`.github/INSTRUCTION_SURFACE.md`.

## 2. Authority

Read and follow, in order:

1. this repository instruction and explicit owner-approved records;
2. `docs/ARCHITECTURE_v2.6.md`;
3. `docs/GOVERNANCE_v2.6.md`;
4. `docs/StableNew Roadmap v2.6.md`;
5. Tier 2 and relevant Tier 3 docs from `docs/DOCS_INDEX_v2.6.md`;
6. the approved PR specification;
7. matching `.github/instructions/*.instructions.md` files.

Archived, completed, needs-review, and unlisted backlog documents are not active
authority. Code and tests are evidence of current implementation; they do not
silently redefine architecture.

## 3. Canonical MVP architecture

The only production flow is:

`Typed Intent -> Compiler -> NJR -> JobService -> Queue/JobRepository -> PipelineRunner.run_njr -> Typed Handler -> Artifacts -> History/Learning/Diagnostics`

Required invariants:

- NJR is the sole public executable envelope and is immutable after submission.
- NJR holds authorized work; queue/history records hold mutable runtime state.
- Fresh execution is queue-only. `Run Now` is immediate-start queue policy.
- PromptPack is the primary authored image source, not a universal job identity.
- PromptPack identity is required only for PromptPack-source NJRs.
- Source-specific typed DTOs/compilers converge on one NJR contract.
- `PipelineRunner.run_njr` is the sole public production runner entry.
- StableNew owns orchestration and persistence; backends execute typed requests.
- `JobRepository` is the persistence boundary; SQLite is the MVP target.
- The MVP is same-process and single-node; native SVD XT is its only video path.

Some target contracts are not implemented yet. The architecture gap register
and active roadmap name those gaps. Do not claim they are complete, add shims to
hide them, or use stale tests to reverse the approved direction.

## 4. Roles

### 4.1 Human owner — Rob

Rob sets product scope, approves PRs, and is final authority. Architecture
changes become binding through synchronized canonical document amendments and a
recorded approval.

### 4.2 Planner/architect

The planner:

- performs evidence-based discovery;
- reconciles code, tests, history, and intended product behavior;
- maintains canon and the active roadmap;
- writes atomic PR specs using `docs/PR_TEMPLATE_v2.6.md`;
- provides exact allowed/forbidden boundaries, tests, migration, and rollback;
- identifies debt deletion and documentation closeout.

The planner must distinguish current implementation from target architecture.

### 4.3 Executor/implementer

The executor:

- reviews the approved spec and relevant active docs before changes;
- modifies only allowed files;
- preserves unrelated user work and data;
- implements the complete approved slice without alternate paths;
- runs and records proportionate verification;
- stops if architecture or allowed-file scope must expand;
- reports actual files, tests, residual risk, and closeout work.

The executor may perform discovery and planning when requested. It may amend
architecture only when the owner explicitly authorizes an architecture/docs
change, as in `PR-ARCH-MVP-001`.

### 4.4 Inline assistant

An inline assistant may complete boilerplate and small changes within an
approved implementation. It must not invent architecture, expand scope, or
create alternate builder/queue/runner behavior.

## 5. Required workflow

1. **Discovery** — establish branch/commit, working-tree state, relevant code,
   tests, persistence/data risks, and contradictions.
2. **PR specification** — use the canonical template with exact files, ordered
   steps, tests, success/failure criteria, debt, migration, and rollback.
3. **Owner approval** — record approval in the spec before runtime execution.
4. **Implementation** — edit only approved files; no architectural inference.
5. **Verification** — targeted tests, required broad gates, clean-checkout proof,
   and migration/recovery checks appropriate to risk.
6. **Review** — compare implementation against spec and canon.
7. **Closeout** — create one CompletedPR record, update roadmap/index/gap
   register, and remove or relocate the backlog copy.

A multi-PR migration may use a temporary bridge only when the approved sequence
names its owner and deletion PR. It may not create two production execution or
persistence authorities.

## 6. File and worktree boundaries

- Existing changes belong to the user unless proven otherwise.
- Never reset, delete, overwrite, or bulk-move user work to “clean” a branch.
- Recovery uses new branches/worktrees and explicit commits, not destructive
  history rewrites.
- Production modules must be tracked and available in a clean checkout.
- Runtime data ignore rules must be anchored and must not hide source packages.
- Only files listed in an approved PR are editable during its execution.
- If a needed file is not allowed, stop and revise the spec.

## 7. Forbidden behavior

- `DIRECT` fresh execution or GUI-to-runner calls;
- a second job model, runner entry, or persistence authority;
- requiring PromptPack identity for non-PromptPack intent;
- mutable status/results/progress/output paths in NJR;
- source resolution, randomization, or source-file reads in the runner;
- pack-shaped generic requests extended to every intent kind;
- live legacy fallback, dual-read, or dual-write migration;
- backend workflow JSON outside its backend boundary;
- child runtime host, daemon, or distributed scheduling during MVP recovery;
- partial migrations with no explicit completion/deletion step;
- tests that call real services during collection or mutate tracked repo data;
- changing tests only to conceal an implementation gap;
- claiming a target architecture is implemented without verification evidence;
- treating historical backlog or completed plans as active work.

## 8. MVP sequencing

`docs/StableNew Roadmap v2.6.md` is the single current roadmap. At this amendment,
only `PR-ARCH-MVP-001` and `PR-MVP-000` are approved. Later roadmap entries must
receive exact specs and owner approval before execution.

Feature work outside the MVP definition of done is deferred unless Rob amends
the roadmap.

## 9. Documentation synchronization

No PR may knowingly leave active docs contradictory. Runtime contract changes
must update all affected Tier 1/Tier 2 surfaces and tests in the same PR. A gap
is removed from the architecture only after implementation and clean-checkout
verification, not when code is merely planned.

New agent profiles or path-scoped instruction files must be registered in
`.github/INSTRUCTION_SURFACE.md` in the same PR.
