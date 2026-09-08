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

Classify execution as **Narrow** (isolated/mechanical), **Standard** (cross-file
but bounded), or **Architectural** (ambiguous or cross-boundary). PR planning
maps that class to the currently appropriate model; repository policy does not
hardcode model names.

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
