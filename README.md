# StableNew

StableNew is a local desktop orchestrator for reproducible image and video jobs,
with queueing, artifacts, history, replay, diagnostics, and learning-ready
provenance.

Version: v2.6
Status: MVP recovery in progress
Active roadmap: `docs/StableNew Roadmap v2.6.md`

## Architecture

The canonical target runtime is:

`Typed Intent -> Compiler -> NJR -> JobService -> Queue/JobRepository -> PipelineRunner.run_njr -> Typed Handler -> Artifacts -> History/Learning/Diagnostics`

Key rules:

- all fresh execution is queue-only;
- NJR is the immutable executable envelope;
- queue/history records own mutable status and results;
- PromptPack is the primary image authoring source, not a universal identity;
- StableNew owns orchestration; image/video backends execute typed requests;
- MVP is a same-process desktop app with WebUI image generation and native SVD
  XT image-to-video.

This is a target with named implementation gaps. See section 13 of
`docs/ARCHITECTURE_v2.6.md`; do not assume every contract above is complete in
the current branch.

## Current repository state

The September 2026 audit found a usable queue/NJR/runner spine but also an
unfinished architecture migration:

- current NJR is broader and more mutable than the target;
- non-PromptPack work can be rejected by pack-oriented validation;
- queue/history persistence has not converged on one SQLite repository;
- production `src/state/` modules are hidden by an overly broad ignore rule;
- the test suite does not yet provide a trustworthy clean-checkout MVP gate;
- several video paths exist, while only native SVD XT is selected for MVP.

The active recovery sequence starts with approved `PR-ARCH-MVP-001` and
`PR-MVP-000`. Older completion ledgers and backlogs do not supersede it.

## Start here

1. `docs/DOCS_INDEX_v2.6.md`
2. `docs/ARCHITECTURE_v2.6.md`
3. `docs/GOVERNANCE_v2.6.md`
4. `docs/StableNew Roadmap v2.6.md`
5. `docs/PR_TEMPLATE_v2.6.md`

Workflow references:

- `docs/PROMPT_PACK_LIFECYCLE_v2.6.md`
- `docs/Builder Pipeline Deep-Dive (v2.6).md`
- `docs/StableNew_Coding_and_Testing_v2.6.md`
- `docs/Subsystems/Testing/E2E_Golden_Path_Test_Matrix_v2.6.md`

## Running

The intended entrypoint remains:

```text
python -m src.main
```

The MVP setup and clean-machine procedure are not yet certified. Use the
repository-managed Python 3.11 environment and expect configured external
dependencies for the flow under test. `PR-MVP-080` and `PR-MVP-090` close setup
and release documentation.

## Testing

Do not rely on old collection counts. `PR-MVP-010` will establish the canonical
test environment and baseline. During recovery, run targeted tests in a
disposable workspace and verify that tracked files remain unchanged.

Expected final gate shape:

```text
python -m compileall src
pytest --collect-only -q
pytest -m "not real_backend and not quarantine" -q
```

Real WebUI and native SVD tests are opt-in acceptance gates, never collection
side effects.

## Documentation status

- `docs/` root contains Tier 1/Tier 2 canon.
- `docs/PR_Backlog/` contains open specs; only roadmap-listed, approved specs are
  executable.
- `docs/CompletedPR/` and `docs/CompletedPlans/` are history.
- `docs/archive/` and `docs/NeedsReview/` are non-active.
- If this README conflicts with active canon, active canon wins.
