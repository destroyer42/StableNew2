# StableNew Architecture Enforcement Checklist v2.6

Status: Canonical, Binding
Updated: 2026-09-07

Use this checklist for every runtime or contract PR. A checked target item does
not mean the current branch already implements it; consult the architecture gap
register and active roadmap first.

PR-MVP-020 evidence (2026-09-07): all section 3 NJR-core items are enforced by
contract tests and an AST mutation guard. Section 2 source-compiler items and
the first two section 4 submission-policy items remain assigned to PR-MVP-030.

## 1. PR authority and truth

- [ ] Is the PR listed in the active roadmap or explicitly approved by Rob?
- [ ] Is there an exact PR spec using `PR_TEMPLATE_v2.6.md`?
- [ ] Are allowed and forbidden files explicit?
- [ ] Does the spec identify current code/test evidence separately from target
      behavior?
- [ ] Are unrelated user changes and runtime data preserved?
- [ ] Does the closeout update roadmap, index, architecture gaps, and one
      CompletedPR record?

## 2. Intent and compiler boundary

- [ ] Does each source enter through a typed intent DTO/compiler?
- [ ] Does every compiler emit NJR before submission?
- [ ] Is PromptPack identity required only for `source.kind == "prompt_pack"`?
- [ ] Are source choices, defaults, randomization, matrices, and sweeps resolved
      before queue submission?
- [ ] Are compilers free of queue, runner, GUI, and persistence side effects?
- [ ] Is the pack-shaped `PipelineRunRequest` being reduced rather than extended
      as a universal request?

## 3. NJR contract

- [ ] Is NJR the only public executable envelope?
- [ ] Does it contain the versioned core: job ID, workload kind, source,
      workload, stages, output plan, and provenance?
- [ ] Is it immutable after submission?
- [ ] Does serialization round-trip every accepted field?
- [ ] Are status, timestamps, progress, errors, retry state, result summaries,
      thumbnails, and produced paths absent from NJR?
- [ ] Do replay/modification create a new identity with parent lineage?
- [ ] Are schema migrations explicit, versioned, and tested?

## 4. Submission, queue, and repository

- [ ] Does `JobService` accept NJR plus a small submission policy?
- [ ] Does `Run Now` enqueue before execution and differ only by immediate-start
      policy?
- [ ] Is queue lifecycle state owned by a mutable job execution record?
- [ ] Does application code use one `JobRepository` boundary?
- [ ] Are lifecycle transitions transactional and validated?
- [ ] Are queue and history projections of the same authority?
- [ ] Is legacy import offline, backup-first, dry-run-capable, idempotent, and
      conflict-reporting?
- [ ] Is there no live dual-read, dual-write, or fallback?

## 5. Runner and backends

- [ ] Is `PipelineRunner.run_njr(...)` the only public production entry?
- [ ] Does the runner derive a typed run plan without mutating NJR?
- [ ] Do internal handlers receive typed requests and return typed results?
- [ ] Are progress/results persisted through runner/application contracts rather
      than placed in NJR?
- [ ] Is there no fallback to a legacy config/dict execution branch?
- [ ] Does backend workflow JSON stay inside its adapter?
- [ ] Does MVP remain same-process and single-node?
- [ ] If video is advertised for MVP, is it native SVD XT only?

## 6. GUI and application ownership

- [ ] Does GUI code capture intent and render projections only?
- [ ] Do controllers call application services rather than builder/repository/
      runner internals?
- [ ] Are queue submissions non-blocking?
- [ ] Are all widget changes marshalled onto the GUI thread?
- [ ] Is display cache/projection state prevented from becoming execution truth?
- [ ] Are unsupported/post-MVP surfaces hidden or clearly labeled?

## 7. PromptPack

- [ ] Is one versioned JSON document the native authority?
- [ ] Are TXT/TSV explicit import/export formats only?
- [ ] Does migration preserve originals and surface conflicts?
- [ ] Does the runner avoid loading or changing PromptPack files?
- [ ] Does PromptPack JSON avoid backend-private workflow payloads?
- [ ] Is JSON-only author/save/load/compile covered?

## 8. Repository and test hygiene

- [ ] Are all imported production modules tracked in a clean checkout?
- [ ] Are ignore patterns rooted narrowly so they cannot hide source packages?
- [ ] Do imports avoid workers, GUI loops, network, GPU/model loads, and writes?
- [ ] Do tests use temporary repository/artifact/state roots?
- [ ] Does collection complete without unexpected errors or side effects?
- [ ] Are unit/contract/integration/GUI/real-backend tests classified?
- [ ] Are real WebUI/SVD tests opt-in, bounded, and recorded?
- [ ] Is every quarantine explicit, owned, and time-bounded?
- [ ] Is `git status --short` unchanged after tests, apart from approved edits?

## 9. Data and rollback

- [ ] Are backups created before migration writes?
- [ ] Are counts, identities, hashes, statuses, artifacts, and conflicts checked?
- [ ] Is a second migration run idempotent?
- [ ] Is rollback rehearsed in a disposable copy?
- [ ] Is automatic startup forbidden from destructively deleting legacy data?

## 10. Documentation synchronization

- [ ] NJR/source changes update architecture, governance, builder/lifecycle,
      testing standards, golden paths, and roadmap.
- [ ] Repository changes update architecture, testing, golden paths, and a
      migration/recovery runbook.
- [ ] PromptPack changes update lifecycle, builder, migration tests, and roadmap.
- [ ] Backend/MVP-scope changes update architecture, subsystem references,
      golden paths, README, and roadmap.
- [ ] Agent-rule changes update `AGENTS.md`, Copilot brief, and instruction
      manifest as applicable.
- [ ] No archived/completed/unlisted backlog file is cited as active authority.

## 11. Automatic rejection conditions

Reject or revise the PR if it introduces:

- `DIRECT` fresh execution;
- a second executable job, runner entry, or persistence authority;
- universal PromptPack identity;
- mutable execution state in NJR;
- GUI-built normalized/backend payloads;
- runner source resolution or legacy fallback;
- live legacy data fallback or dual-write;
- an untracked production dependency;
- import-time external activity;
- child runtime host/distributed execution during MVP;
- Comfy/LTX/AnimateDiff as an MVP requirement;
- a target-complete claim without clean-checkout evidence.
