# StableNew repository operating contract

This is the authoritative instruction file for work in this repository.

## Product and repository

StableNew is a local desktop application for reproducible image and video
generation. It owns intent compilation, queueing, execution orchestration,
artifacts, history, replay, diagnostics, and learning-ready provenance.

- Authoritative remote: `https://github.com/destroyer42/StableNew2.git`
- Product/repository name: StableNew
- Default long-lived branch: `main`
- Current release line: v2.6 MVP recovery
- Current state and immediate priorities: `STATUS.md`
- Task-oriented code map: `docs/CODEX_MAP.md`
- Architecture: `docs/ARCHITECTURE_v2.6.md`
- Roadmap: `docs/StableNew Roadmap v2.6.md`
- Testing: `docs/StableNew_Coding_and_Testing_v2.6.md`

Git history preserves old plans and completed work. Archived, deleted, or
historical material is not active guidance and should be consulted only for a
specific historical question.

## Runtime invariants

The canonical outer path is:

`Intent -> Compiler -> NJR -> JobService -> Queue/Repository -> PipelineRunner.run_njr -> Handler -> Artifacts/History`

- Fresh work is always queued. Run Now means enqueue with immediate-start
  policy; it is not a direct execution path.
- `NormalizedJobRecord` is the immutable, versioned executable envelope.
- `JobService.submit_njrs` is the application submission boundary.
- `PipelineRunner.run_njr` is the only public production runner entry.
- Queue/history own mutable status, progress, retry, error, and result state.
- Replay creates a new NJR identity with parent lineage and uses the same path.
- PromptPack identity exists only for PromptPack-sourced work.
- GUI code captures intent and renders projections. It does not build backend
  payloads, mutate queue persistence, or call the runner.
- Controllers coordinate application services; pipeline modules compile and
  execute typed work; backend details stay behind adapters.
- MVP execution is same-process and single-node. Native SVD XT is the only MVP
  video backend.
- Do not create parallel job models, runner entrypoints, live legacy fallbacks,
  or compatibility layers without a named removal condition.
- Prefer deleting proven-obsolete compatibility code over preserving it
  indefinitely.

Material changes to these invariants require Rob's approval and an architecture
update in the same coherent change.

## Working relationship

Rob defines desired product behavior, priorities, constraints, and approval of
material architecture changes.

Codex determines the implementation implications from repository evidence,
including the relevant files, normal refactors, low-level technical choices,
and tests required to deliver the requested outcome.

Normal outcome-first requests are sufficient authorization to inspect and
implement within their stated scope. Rob does not need to provide an internal
file list or prescribe a mechanical PR sequence. Stop and ask when a missing
choice would materially change product behavior, data safety, or architecture.

## How Codex works here

1. Read `STATUS.md`, `docs/CODEX_MAP.md`, and only the relevant authoritative
   architecture section; then inspect the current branch and worktree.
2. Start with targeted symbol/path searches. Search history, archives, or
   recovery material only when current evidence is insufficient or the request
   is historical.
3. Understand the requested product outcome and explain material architectural
   tradeoffs or contradictions.
4. Choose the smallest coherent change that fully delivers the outcome. Do not
   ask Rob for implementation file lists that repository evidence can provide.
5. Preserve unrelated user changes and avoid mixing independent work.
6. Remove obsolete code when dependency evidence supports removal.
7. Add or update deterministic tests for changed behavior.
8. Run validation proportional to risk, starting targeted and expanding to the
   repository gates where practical.
9. Update `STATUS.md` when repository direction, active work, or verified state
   materially changes.
10. Close out concisely with outcome, branch/SHA, targeted validation, required
    CI, architecture/controller effect, known blocker/debt, and next outcome.

Do not reject ordinary product-owner language merely because it lacks an exact
file allowlist. Do not invent a broader product change under the cover of a
refactor or cleanup.

Classify execution as **Narrow**, **Standard**, or **Architectural**. The
current advisory model mapping below is an execution-cost policy, not an
architecture invariant, and may change as available models change.

## Context and execution efficiency

Repository/branch/HEAD and repo-local canonical docs outrank Codex memories,
old recovery plans, historical chats, and stale planning files. Do not inspect
`~/.codex/memories` by default; use Codex memory only when the task explicitly
depends on historical context unavailable from the current repository or prompt.

For a bounded prompt with an exact parent SHA, explicit outcome, acceptance
contract, and named surfaces:

1. verify branch, SHA, and worktree;
2. read `STATUS.md`;
3. read only the relevant `CODEX_MAP.md` task row;
4. read only relevant architecture and testing sections;
5. inspect implementation.

Do not reread the full roadmap or architecture unless sequencing or
architecture is actually in question. Prefer symbol/path searches over
repo-wide exploratory scans. Do not search the web unless external/current
dependency semantics are necessary to the acceptance contract. Do not repeat
already-green expensive validation when relevant source is unchanged; docs-only
changes do not invalidate source/runtime acceptance evidence.

If Ruff, mypy, or another prescribed tool is unavailable locally, run the
prescribed gate once, report **TOOLING BLOCKER**, and do not rebuild the
environment inside an unrelated PR. `PR-MVP-090` owns normalizing/bootstrapping
the local development environment.

Advisory execution/model matrix:

- Narrow: **GPT-5.6 Luna — High**
- Standard: **GPT-5.6 Terra — High**
- Architectural: **GPT-5.6 Sol — Medium**

If discovery shows that a task belongs to a higher execution class than the
current invocation, stop and recommend escalation rather than silently
broadening scope. This model mapping is an execution-cost policy, not a
product architecture invariant, and may be updated as available models change.

Use **LOCAL Codex** when dirty or unpushed local work, local SQLite/user state,
Tk/native GUI, A1111, GPU/CUDA/SVD, local filesystem/runtime acceptance, or
environment/bootstrap work matters. **Cloud Codex** is suitable only when the
exact parent is pushed, the relevant tree is clean, the task is source/test/docs
only, no local hardware/runtime/user state is needed, and deterministic tests
plus GitHub CI can establish acceptance.

Every authored StableNew PR or bounded work package records an **Execution
Profile + Model/Reasoning Recommendation**, a **Controller Surface Assessment**
when controller or coordinator code may be touched, and a **Token-Efficient
Validation Plan**. Reuse one acquired context set and exact-SHA evidence while
the relevant source is unchanged; do not turn a documentation or closeout task
into a new runtime/test pass without a current acceptance need. The reusable
shape is `docs/CODEX_WORK_PACKAGE_TEMPLATE.md`.

## Documentation impact gate

After every accepted Codex implementation and before beginning the next
functional phase:

1. verify exact SHA/diff and applicable validation/required CI;
2. accept or reject based on behavior and architecture, not tests alone;
3. determine whether canonical truth changed;
4. update only affected repo authorities before continuing.

Check the following authorities when their scope is affected:

- `STATUS.md`: verified state, accepted evidence, active objective, next action;
- `docs/ARCHITECTURE_v2.6.md`: ownership, lifecycle, architecture, or invariant changes;
- `docs/StableNew Roadmap v2.6.md`: phase completion, scope, sequencing, or priority changes;
- `docs/CODEX_MAP.md`: newly discovered task-to-code authority;
- `docs/StableNew_Coding_and_Testing_v2.6.md`: validation or evidence-reuse policy;
- `AGENTS.md`: Codex execution/process policy.

Do not update docs merely to narrate a commit; Git history owns implementation
history. If implementation discovers a new product or architecture decision
rather than implementing an already-approved one, stop for product-owner review
before making that decision canonical. The next functional phase begins only
after required canonical-document updates are coherent.

## Work budget and checkpoint discipline

- Work only on the authorized phase and outcome. Fixing a blocker does not
  authorize starting the next major phase.
- A default Narrow/Standard budget is one focused discovery pass, one coherent
  implementation pass, one focused repair pass, and one final verification.
  A second materially different repair class requires a checkpoint/report.
- Stop and checkpoint after two materially different failure classes; more than
  two is a mandatory stop/report. Context compaction ends broad exploration on
  the first Narrow/Standard compaction and requires a checkpoint/report on the
  second. Architecture work requires owner continuation.
- Around 12–15 minutes of ongoing Narrow/Standard work, prefer a coherent
  checkpoint before more exploration; this is guidance, not a hard kill.
- When the phase acceptance contract is true, stop. Do not begin another
  roadmap item or PR without explicit authorization.
- Do not rerun expensive passing validation unless relevant code changed.
  Passing focused tests remain valid while their relevant files are unchanged;
  docs-only changes do not require real-backend acceptance. A source change
  affecting a validated path invalidates that result.
- Use one practical local interpreter. Python 3.11/3.12 GitHub required CI is
  the canonical compatibility verdict. Do not spend substantial time rebuilding
  duplicate environments; one small tool install is acceptable when cheaper,
  and should be reported.

### Phased PRs and completion reports

For a large approved PR, treat the specification as the acceptance contract:
Phase A implements and proves the core slice, Phase B covers edge/lifecycle
behavior, and Phase C performs real acceptance and closeout. Checkpoint, commit,
and report between phases unless the owner explicitly authorizes continuous
execution. A checkpoint or completion report should fit roughly 250 words and
state: branch/SHA (or preserved uncommitted work), phase complete, tests passed,
exact blocker, next smallest coherent phase, and whether continuation exceeds
the normal budget.

## Code ownership boundaries

- `src/gui/` owns Tk presentation and event wiring.
- `src/gui_v2/` contains toolkit-neutral GUI adapters and view models.
- `src/controller/` owns application coordination and lifecycle adapters.
- `src/pipeline/` owns intent compilation, NJR contracts, runner, and stage
  orchestration.
- `src/queue/` and `src/history/` own execution-state projections while they
  converge on the repository boundary.
- `src/video/` owns typed video execution adapters.
- `src/learning/` consumes post-execution records; it does not create a second
  runtime path.
- `src/state/` is source code and must remain tracked.
- `tools/` and `scripts/` are maintenance/operational utilities, not homes for
  application logic.

Top-level oversized controllers are protected by
`tools/ci/check_controller_surface.py`. When feature work materially touches a
ratcheted controller, assess whether the changed responsibility belongs behind
an existing or new cohesive service boundary. Do not increase a ceiling without
an explicitly approved architecture exception. When a controller shrinks,
lower its checked-in ceiling in the same PR.

Keep GUI work non-blocking and marshal widget updates onto the GUI thread.
Avoid import-time network, process, GPU/model, GUI-loop, or filesystem side
effects. Keep randomization and compilers deterministic for fixed inputs.

## Validation defaults

`pyproject.toml` is the only pytest configuration authority. The standard local
gate is:

```text
python tools/ci/run_pr_gate.py
```

Run focused changed-behavior tests first, then the local gate when practical.
GitHub required CI is the canonical Python 3.11/3.12 integration verdict. Do not
rebuild local interpreters merely to duplicate that matrix; unsupported local
runs are diagnostic only. Informational full-suite debt does not broaden an
unrelated PR. Run real-backend acceptance only when the outcome requires it.

Tests must use temporary state/artifact roots and must not require real networks,
WebUI, models, GPUs, or GUI displays unless explicitly marked as opt-in
acceptance tests.

Ruff is pinned. New or increased lint debt fails. Leave touched source files
clean even while the bounded legacy baseline exists.

## Git and repository hygiene

- Inspect status before changing files.
- Use a short-lived branch for a coherent outcome; do not work directly on an
  unrelated dirty branch.
- Never discard, reset, or overwrite uncommitted user work.
- Keep generated reports, inventories, diagnostics, caches, and runtime outputs
  out of Git.
- Prefer Git history to checked-in copies of obsolete plans or code.
- Do not delete branches with unique work. Delete merged short-lived branches
  after the owner accepts the result.
- Do not push, merge, rewrite history, or delete remote state unless the task
  authorizes that external change.

## Repo compass

When asked for orientation, report only what is useful:

```text
Repo / branch / HEAD / tracking branch
Ahead or behind main
Working-tree state
Current branch objective
Relevant recent changes
Verified test state
Top risks
Recommended next action
```

Keep this answer concise and derive it from current Git/repository evidence.
