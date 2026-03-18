# StableNew - Revised Top 20 Recommendations After Repo Review

## Method and confidence

This list is based on:

- direct inspection of the repository
- review of the canonical v2.6 architecture and governance docs
- inspection of key implementation modules under `src/`
- a lightweight `pytest --collect-only -q` sanity check in this environment, which now collects **2,223 tests** with **1 skipped** and **0 collection errors**

I did not run the full runtime suite end to end here. Priorities are grounded in
architecture, code shape, test-surface health, and the repo's current migration
state.

## Overall BLUF

The best path is still:

1. finish the v2.6 canonical migration
2. remove legacy and compatibility drag
3. harden execution and recovery
4. keep the tests authoritative
5. then complete the highest-leverage product surfaces: reprocess, learning, and video

The biggest meta-risk is building new capability on top of partially migrated
internals.

## Phase 0/1 status update

As of 2026-03-16:

- `#1` closeout is complete in runtime terms and has an invariant guard.
- `#2` has been substantially reduced by the queue/history cleanup and controller bridge retirement, but legacy compatibility tail work still remains.
- `#3` core runtime contract work is complete; remaining work is mostly docs/default-surface consistency.
- `#9` is now implemented in a low-noise form via architecture enforcement tests.
- `#13` is being executed by the current documentation refresh tranche.

---

## 1) Close recommendation #1 formally and keep it closed

Status: complete in runtime terms.

Treat this as a hygiene item only. The live txt2img path is already the stage-based
NJR path, and the remaining work is keeping docs and invariant tests aligned so the
retired executor path does not return.

## 2) Finish the NJR-only migration across queue, history, and controllers

Status: partially complete.

Queue/history runtime cleanup and the main controller bridge retirement are done, but
there are still archive-facing controller imports and deprecated compatibility methods
that need to be retired or isolated further.

## 3) Make the canonical stage contract match the real preferred flow

Status: core runtime contract complete.

The repo should consistently describe the preferred still-image path as:

`txt2img -> optional img2img -> optional adetailer -> optional final upscale`

Refiner and hires should remain supported, but only as advanced `txt2img` metadata,
not as preferred-flow stages.

## 4) Harden WebUI recovery so hangs and partial failures are first-class

Expand recovery to handle timeouts, HTTP 500s, pre-stage readiness failures, and
partial per-image degradation rather than treating only narrow connection failures as
restart-worthy.

## 5) Keep the test suite authoritative

The test surface is healthier than earlier snapshots suggested. With `2,223`
collected tests and no collection errors, this is now a credibility and pruning task,
not an emergency collection-failure item.

## 6) Unify history, manifests, and replay around one durable artifact contract

Define and enforce one canonical output/manifest contract for image, reprocess, and
video jobs, then make history and replay consume only that contract.

## 7) Turn reprocess into a real productized subsystem

Promote reprocess from a partial runner trick into a documented, validated,
history-linked workflow with deterministic output routing and clear stage semantics.

## 8) Finish the controller event API cleanup and remove reflective dispatch

Status: partially complete.

The major controller bridge cleanup is done, but the remaining event and legacy
controller surfaces should still be tightened until GUI-to-controller interaction uses
explicit entrypoints consistently.

## 9) Add architecture enforcement checks so the repo can defend itself

Status: implemented in initial form.

The repo now has architecture guard tests. Keep expanding them carefully, with a bias
toward low-noise checks such as:

- no forbidden GUI imports of runner/executor
- no direct runner invocation from GUI modules
- no stray legacy adapter usage outside isolated legacy surfaces
- no reintroduction of retired executor entrypoints

## 10) Make queue cancellation, pause/resume, and checkpoint semantics trustworthy

Finish queue lifecycle semantics so pause, cancel, resume, and checkpoint behavior are
explicit, recoverable, and reflected correctly in UI and history.

## 11) Complete the learning loop modestly, not ambitiously

Keep learning useful and bounded: strong metadata, reproducible comparisons, and
small-step feedback integration before any ambitious closed-loop automation.

## 12) Centralize config validation and normalization

Status: materially advanced.

The pipeline-boundary normalization layer now exists. The remaining work is to keep
validation close to the canonical build path and avoid duplicating normalization logic
across GUI, controller, builder, and runner.

## 13) Refresh the docs/readme/source-of-truth package so it matches reality

Status: in progress with the current documentation tranche.

README, the docs index, and onboarding docs should reflect v2.6, NJR-first runtime,
the preferred still-image flow, and the current subsystem maturity.

## 14) Build a cleaner observability story across runner, WebUI, queue, and persistence

Consolidate runtime logging, structured events, retry envelopes, and diagnostics
bundles into one coherent observability model.

## 15) Finish SVD as the first serious video path

Native SVD is the right near-term video investment because it already has a clearer
boundary than most other video options in the repo.

## 16) Treat AnimateDiff as a contract-gated follow-on, not a parallel sprawl path

Keep AnimateDiff behind a stricter contract gate until the artifact, recovery, and
runtime boundaries are cleaner.

## 17) Make output naming and routing deterministic everywhere

Standardize output path and filename behavior across generation, reprocess, and video
so history, replay, and diagnostics can rely on stable file semantics.

## 18) Tighten model/resource discovery and refresh semantics

Resource discovery should be explicit, refreshable, and deterministic so the UI and
runtime stop disagreeing about available models, upscalers, and extensions.

## 19) Continue GUI modernization only after the substrate is stable

Polish remains important, but it should sit on top of a trustworthy canonical runtime,
not compensate for architectural drift underneath.

## 20) Treat canvas/object editing as an architecture extension, not a one-off feature

Manual editing, masking, and canvas-driven workflows should be built as structured
extensions of reprocess and artifact contracts rather than as isolated side paths.

## Recommended execution order

Near-term queue:

1. finish remaining Phase 1 migration and documentation work
2. harden WebUI recovery and queue lifecycle semantics
3. unify artifact contracts
4. productize reprocess
5. continue learning and video work on top of the stabilized substrate
