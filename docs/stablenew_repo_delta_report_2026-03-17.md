# StableNew repo delta + recommendation review (17 Mar 2026)

## Executive summary

The new snapshot is materially ahead of the old one. It adds a real tranche of work around:

- canonical artifact contracts
n- config normalization
- queue/checkpoint semantics
- WebUI recovery/diagnostics hardening
- reprocess and image-edit foundations
- SVD/AnimateDiff contract work
- prompt-optimizer infrastructure
- architecture guard tests
- docs and architecture diagram refresh

At the planning/backlog level, the repo clearly moved in the direction of the prior recommendation set. In other words: the *right* areas were worked.

However, the repo still has one major structural problem that keeps it from being "cleanly advanced": the controller layer still imports `src.controller.archive.*` modules that are not present in the snapshot. That single issue fans out into a large portion of the test suite and prevents the codebase from honestly claiming that the migration is finished.

So the delta is real and useful, but the migration is still incomplete.

## What changed between the snapshots

### File-level delta

- Added files: **71**
- Removed files: **2**
- Modified files: **142**

### Major additions

1. **Prompt optimization subsystem**
   - new `src/prompting/*` package
   - new prompt optimizer tests and fixtures
   - GUI/integration tests for prompt optimization

2. **Canonical runtime contract work**
   - `src/pipeline/artifact_contract.py`
   - `src/pipeline/config_normalizer.py`
   - `src/pipeline/cli_njr_builder.py`
   - follow-on changes in builder, payload, stage, runner, replay, history, queue

3. **Backlog + architecture planning package**
   - `docs/PR_MAR26/*`
   - revised top-20 doc
   - architecture diagrams and current-state brief

4. **Video/reprocess/history maturation**
   - SVD registry/service/postprocess updates
   - artifact-aware history polish
   - image-edit/reprocess foundations

5. **Diagnostics and recovery**
   - watchdog/diagnostics bundle updates
   - recovery/checkpoint/output routing work

## Spot-check validation performed here

### Pytest collection

Old snapshot:
- `1832` tests collected
- `102` collection errors

New snapshot:
- `1935` tests collected
- `100` collection errors

This means the repo did improve slightly at collection time, but it is **not** at a zero-error collection state.

### Targeted passing tests in the new snapshot

The following targeted suites passed in this environment:

- `tests/unit/test_prompt_classifier.py`
- `tests/unit/test_prompt_deduper.py`
- `tests/unit/test_prompt_normalizer.py`
- `tests/unit/test_prompt_optimizer_service.py`
- `tests/unit/test_prompt_splitter.py`
- `tests/unit/test_sdxl_prompt_optimizer.py`
- `tests/pipeline/test_config_normalizer.py`
- `tests/pipeline/test_artifact_contract.py`
- `tests/system/test_architecture_enforcement_v2.py`

That is a useful signal that several of the newly added subsystems are internally coherent.

## Biggest remaining obvious issue

### Legacy archive imports are still a repo-wide structural blocker

The new snapshot still imports:

- `src.controller.archive.pipeline_config_assembler`
- `src.controller.archive.pipeline_config_types`

from key runtime/controller modules such as:

- `src/controller/pipeline_controller.py`
- `src/controller/app_controller.py`
- `src/pipeline/legacy_njr_adapter.py`

But the `src/controller/archive/` package is not present in the snapshot. That produces import-time failures across a wide swath of controller, GUI, integration, journey, and regression tests.

This is the single most important reason the migration cannot yet be considered complete.

## Secondary obvious issue

### Architecture enforcement currently protects the *shape* of the migration, but not the *completion* of the migration

The new architecture enforcement test suite is directionally good, but it explicitly allowlists the remaining archive imports instead of forcing their elimination. That means the repo has a guardrail against broad architectural backsliding, but not yet a guardrail that proves the legacy bridge has actually been retired.

## Tertiary obvious issue

### The repo's self-description is ahead of its executable reality

The added planning/docs package suggests several recommendation areas are "done" or materially closed. The codebase does show real progress in those areas, but the continued controller/archive dependency means the repo is still in a partial-migration state. In practical terms, the documentation maturity is slightly ahead of the runtime maturity.

## Review against the prior top-20 recommendation set

Below is the best-effort status review by mapping the new work to the prior recommendation themes from the previous analysis.

### 1. Close recommendation #1 formally and keep it closed
**Assessment:** mostly addressed.

Evidence in the new snapshot:
- `docs/PR_MAR26/PR-CLOSE-057-Recommendation-1-Closeout-and-Duplicate-Txt2Img-Audit.md`
- `tests/pipeline/test_txt2img_path_closeout_invariants.py`

Verdict: the repo appears to have added both planning and invariant coverage to keep duplicate txt2img path drift from returning. This looks implemented in the intended direction.

### 2. Finish the NJR-only migration across queue, history, and controllers
**Assessment:** partially addressed, not finished.

Evidence:
- `PR-CORE1-060`
- `PR-CTRL-061`
- queue/history/controller file churn

Verdict: queue/history cleanup progressed, but the controller layer still depends on missing `src.controller.archive.*` modules. This recommendation is **not** complete.

### 3. Make the canonical stage contract match the real preferred flow
**Assessment:** materially addressed.

Evidence:
- `PR-PIPE-063`
- payload/stage/resolution layer changes
- `tests/api/test_sdxl_payloads.py` changes

Verdict: the repo clearly moved toward the preferred flow normalization. This appears implemented largely in the intended way.

### 4. Harden WebUI recovery so hangs and partial failures are first-class
**Assessment:** addressed in a meaningful way, but still needs runtime proving.

Evidence:
- `PR-RECOV-066`
- `PR-HB-067`
- changes to `webui_process_manager`, `client`, `watchdog_system_v2`, diagnostics

Verdict: strong progress. Remaining gap is broader runtime confidence, not absence of work.

### 5. Keep the test suite authoritative
**Assessment:** only partially addressed.

Evidence:
- collection improved from 102 to 100 errors
- new architecture and subsystem tests added
- but collection still fails broadly

Verdict: the repo invested in tests, but the suite is **not yet authoritative** because major collection blockers remain.

### 6. Unify history, manifests, and replay around one durable artifact contract
**Assessment:** materially addressed.

Evidence:
- `PR-ART-071`
- `artifact_contract.py`
- history/replay/video/history panel changes

Verdict: good progress and likely the right implementation direction.

### 7. Turn reprocess into a real productized subsystem
**Assessment:** meaningfully addressed.

Evidence:
- `PR-REPROC-072`
- `PR-EDIT-077`
- reprocess builder/runtime changes
- masked edit runtime test addition

Verdict: the repo is now treating reprocess as a subsystem rather than a side trick. Good progress.

### 8. Finish controller event API cleanup and remove reflective dispatch
**Assessment:** partially addressed.

Evidence:
- `PR-CTRL-061`
- ongoing heavy `app_controller` / `pipeline_controller` churn

Verdict: cleanup is underway, but the controller surface is still too compatibility-heavy to call this finished.

### 9. Add architecture enforcement checks so the repo can defend itself
**Assessment:** addressed.

Evidence:
- `PR-ARCH-064`
- `tests/system/test_architecture_enforcement_v2.py`

Verdict: implemented in the intended direction, but next step should tighten the enforcement to eliminate the remaining allowlisted legacy bridge.

### 10. Make queue cancellation, pause/resume, and checkpoint semantics trustworthy
**Assessment:** meaningfully addressed, likely not fully proven.

Evidence:
- `PR-QUEUE-067`
- `PR-QUEUE-067A`
- queue, runner, controller, history changes

Verdict: good implementation progress. Remaining question is runtime confidence under interruption and resume scenarios.

### 11. Complete the learning loop modestly, not ambitiously
**Assessment:** addressed in the intended direction.

Evidence:
- `PR-LEARN-073`
- learning controller/execution/output scanner changes

Verdict: the repo appears to be keeping learning bounded and metadata-driven, which matches the intended advice.

### 12. Centralize config validation and normalization
**Assessment:** clearly addressed.

Evidence:
- `PR-PIPE-062`
- `config_normalizer.py`
- targeted tests pass

Verdict: one of the stronger implemented items.

### 13. Refresh docs/readme/source-of-truth package so it matches reality
**Assessment:** addressed, but not fully reconciled with runtime truth.

Evidence:
- `PR-DOCS-065`
- README and docs index changes
- architecture diagrams/current-state brief

Verdict: docs improved a lot. The remaining problem is that docs are slightly ahead of the actual completed migration.

### 14. Build a cleaner observability story across runner, WebUI, queue, and persistence
**Assessment:** meaningfully addressed.

Evidence:
- `PR-OBS-068`
- diagnostics bundle/watchdog/service changes

Verdict: solid progress.

### 15. Finish SVD as the first serious video path
**Assessment:** meaningfully addressed.

Evidence:
- `PR-VIDEO-074`
- SVD service/runner/postprocess/registry changes
- added/updated SVD tests

Verdict: good progress and consistent with the intended strategy.

### 16. Treat AnimateDiff as a contract-gated follow-on
**Assessment:** addressed at backlog/contract level.

Evidence:
- `PR-VIDEO-075`
- animatediff-related tests/runtime changes

Verdict: directionally correct. Still secondary to SVD and substrate cleanup.

### 17. Make output naming and routing deterministic everywhere
**Assessment:** addressed.

Evidence:
- `PR-IO-069`
- output folder structure / file naming / history-related changes

Verdict: good and important progress.

### 18. Tighten model/resource discovery and refresh semantics
**Assessment:** addressed.

Evidence:
- `PR-RES-070`
- `api/webui_resource_service.py` changes
- controller/UI refresh tests updated

Verdict: good progress.

### 19. Continue GUI modernization only after the substrate is stable
**Assessment:** mostly respected.

Evidence:
- GUI work in this delta is mostly connected to substrate features (history/artifacts/prompt optimizer/running job panel), not giant standalone surface churn.

Verdict: the implementation direction is disciplined here.

### 20. Treat canvas/object editing as an architecture extension, not a one-off feature
**Assessment:** addressed in foundation form.

Evidence:
- `PR-EDIT-077`
- masked edit/runtime work via reprocess/img2img path

Verdict: this is aligned with the intended architecture-first approach.

## Net conclusion on the old recommendation set

The new snapshot **did address most of the prior recommendation areas in the intended direction**.

But the most important migration recommendation (#2) is still incomplete, and that incompleteness weakens confidence in several of the others because controller import failures prevent the repo from behaving as a fully consolidated v2.6 codebase.

---

# Fresh revised top 20 (current repo state)

## 1) Remove the `src.controller.archive.*` dependency completely
**BLUF:** This is now the highest-leverage task because it blocks honest completion of the migration and poisons a large fraction of test collection.

Why now:
- many current collection failures trace back here
- docs and architecture tests imply retirement, but runtime still depends on it
- it sits at the controller seam, so the blast radius is large

Research / reasoning:
- migration projects fail when compatibility layers linger at orchestration seams
- import-time failures are especially expensive because they hide downstream signal
- removing this dependency would immediately improve truthfulness of the test suite

2nd/3rd/4th order effects:
- good: shrinks controller complexity and improves testability
- good: makes architecture enforcement more meaningful
- risk: naive removal could break legacy test fixtures or preview paths if replacement contracts are not explicit

Caveat:
- do not do this as a "delete and pray" change; replace it with a stable canonical config DTO or strict adapter boundary first.

## 2) Drive the suite to zero collection errors before major new feature expansion
**BLUF:** The repo needs a clean import/collection floor more than it needs another capability spike.

Why now:
- collection errors mask real regressions
- the repo currently cannot use its own test surface as a trustworthy gate

Research / reasoning:
- a broken collection phase is one of the worst failure modes in large Python repos because signal disappears before tests even start
- fixing collection typically unlocks better prioritization than broad refactoring guesses

2nd/3rd/4th order effects:
- good: makes future PRs cheaper to validate
- good: reveals real failing tests hidden behind import crashes
- risk: some failures are environment/dependency related, so split structural failures from optional extras

Caveat:
- separate repo bugs from environment-only issues like optional packages (`requests_mock`).

## 3) Replace the current legacy-allowlist architecture test with a completion-oriented migration guard
**BLUF:** The repo now needs tests that prove the migration is complete, not just tests that limit the spread of incompleteness.

Why now:
- current enforcement accepts remaining archive imports in exactly the places causing the biggest failures

Research / reasoning:
- architecture tests are most useful when they force a target state, not when they immortalize transitional exceptions

2nd/3rd/4th order effects:
- good: prevents this exact class of regression from returning
- good: aligns docs/backlog with executable truth
- risk: turning it on too early will fail the branch until the controller work lands

Caveat:
- stage it in two steps: first reduce allowlist to one shim, then eliminate it.

## 4) Split `PipelineController` into a thin orchestration facade plus canonical build/run services
**BLUF:** `PipelineController` is still carrying too much compatibility and orchestration burden.

Why now:
- it is the center of import-time failures and migration drag
- it couples GUI, legacy config, job build, learning, and run orchestration

Research / reasoning:
- controllers are cheaper to evolve when they delegate to small explicit services rather than import everything directly

2nd/3rd/4th order effects:
- good: reduces fan-out and import risk
- good: makes queue/direct/preview modes easier to reason about
- risk: could create service-sprawl if not kept tight

Caveat:
- keep the facade stable for GUI callers while extracting only canonical responsibilities.

## 5) Split `AppController` responsibilities further and remove leftover pipeline compatibility code
**BLUF:** `AppController` still looks like a gravitational center for too many unrelated concerns.

Why now:
- it remains one of the highest-churn modules
- it likely amplifies migration and test brittleness

Research / reasoning:
- large GUI/application controllers tend to become the slowest-moving source of regressions

2nd/3rd/4th order effects:
- good: easier thread-dispatch reasoning
- good: better ownership boundaries for queue/history/resources/learning
- risk: over-extraction can harm readability if done without a responsibility map

Caveat:
- do this by capability slices, not generic "utils" extraction.

## 6) Finish a canonical config DTO story for preview, queue, direct run, replay, and reprocess
**BLUF:** The repo still needs one indisputable object model at the boundary between GUI intent and executable job plan.

Why now:
- the config normalizer is a strong start, but the controller seam remains inconsistent

Research / reasoning:
- stable job/config contracts are the key to reliable replay, history, and automation

2nd/3rd/4th order effects:
- good: simplifies learning metadata capture
- good: reduces one-off normalization logic
- risk: contract churn can break tests and docs if not rolled carefully

Caveat:
- version the contract and make backward-compat explicit where needed.

## 7) Convert the current docs from "planning + confidence" to "verified current state + planned next state"
**BLUF:** The docs are now useful, but they need a stronger distinction between what exists and what is proposed.

Why now:
- some docs read as more complete than the codebase currently is

Research / reasoning:
- repos with strong architecture docs gain most value when current state and target state are clearly separated

2nd/3rd/4th order effects:
- good: helps Codex/Copilot agents stop implementing against aspirational docs as if they were runtime truth
- risk: documentation churn can become excessive if tied too tightly to every PR

Caveat:
- use a small verified-current-state section instead of trying to narrate every nuance.

## 8) Turn artifact contract adoption into a hard invariant across image, reprocess, SVD, and AnimateDiff
**BLUF:** The artifact contract work is promising and should become mandatory everywhere before more media surfaces expand.

Why now:
- history, replay, diagnostics, and video all depend on stable artifact semantics

Research / reasoning:
- media systems become fragile when each pipeline writes slightly different outputs/manifests

2nd/3rd/4th order effects:
- good: cleaner history UI and replay
- good: easier bundle/export/debug tooling
- risk: may force migration logic for old history records

Caveat:
- provide explicit legacy-read compatibility if old histories matter.

## 9) Build a single "runtime incident" model across retry, recovery, diagnostics, and history
**BLUF:** Recovery work exists, but it still needs one shared incident vocabulary.

Why now:
- watchdog, recovery, diagnostics, and history are all moving in the right direction but can still drift

Research / reasoning:
- operational tooling matures faster when failures are modeled as typed events, not just log strings

2nd/3rd/4th order effects:
- good: better UX for failed/stalled jobs
- good: cleaner auto-recovery policies
- risk: too much schema too early can slow iteration

Caveat:
- keep the first incident taxonomy small: readiness failure, runtime stall, partial output, API error, recovery attempted, recovery exhausted.

## 10) Finish queue lifecycle semantics with destructive testing, not just unit coverage
**BLUF:** Queue/resume/checkpoint work is important enough that it now deserves adversarial testing.

Why now:
- semantics are being added, but interruption handling is where queue systems usually fail in production

Research / reasoning:
- resume/cancel systems often pass unit tests but fail under kill/restart timing and partial-write conditions

2nd/3rd/4th order effects:
- good: higher trust for long runs and large batches
- good: better recovery from WebUI instability
- risk: destructive tests are slower and can be flaky if not isolated well

Caveat:
- use deterministic fake runtimes first, then a thin layer of real-process journey tests.

## 11) Make prompt optimization an optional, explainable preprocessing layer rather than a hidden mutation layer
**BLUF:** The new prompt optimizer is promising; keep it transparent and reversible.

Why now:
- a new subsystem has landed and could quietly become a source of trust issues if it mutates prompts opaquely

Research / reasoning:
- creators trust assistive prompt tooling more when they can see classification, normalization, dedupe, and final emitted prompt separately

2nd/3rd/4th order effects:
- good: better user trust and debugging
- good: cleaner learning telemetry
- risk: too much UI verbosity can overwhelm authors

Caveat:
- expose a compact before/after + rules-used trace, not a wall of internals.

## 12) Add golden-path execution tests specifically for the new prompt optimizer + canonical builder + executor chain
**BLUF:** The new prompt subsystem now needs end-to-end proof, not just unit proof.

Why now:
- units pass, but the real risk is payload and runtime interaction

Research / reasoning:
- text preprocessing layers often fail at integration boundaries: token weighting, negative prompt merging, LoRA tokens, SDXL prompt splits

2nd/3rd/4th order effects:
- good: prevents subtle prompt regressions
- good: improves confidence in future optimization rules
- risk: can create brittle assertions if outputs are over-specified

Caveat:
- assert on contract properties and payload structure, not exact image results.

## 13) Make reprocess and masked editing a first-class, history-linked UX with deterministic provenance
**BLUF:** The foundation is there; now make the user-facing loop complete and trustworthy.

Why now:
- reprocess/edit is one of the highest-value product surfaces after still-image generation

Research / reasoning:
- editing workflows gain compounding value when users can see source artifact, edit intent, applied stages, and derived outputs together

2nd/3rd/4th order effects:
- good: stronger product coherence
- good: easier future canvas/object tools
- risk: provenance metadata can become noisy if every tiny tweak is recorded inconsistently

Caveat:
- define a concise provenance schema before deep UI work.

## 14) Keep SVD as the canonical video path and force all other video paths to prove their contract fit
**BLUF:** Video should stay narrow and disciplined.

Why now:
- SVD work is maturing, while broader video sprawl would multiply substrate complexity

Research / reasoning:
- early media-platform success usually comes from one reliable path, not many partially working ones

2nd/3rd/4th order effects:
- good: clearer user expectations
- good: focused debugging and artifact support
- risk: slows experimentation with other backends if gating is too rigid

Caveat:
- keep experimental backends behind explicit feature gates and non-canonical status.

## 15) Finish resource discovery as a refreshable service contract shared by GUI and runtime
**BLUF:** Resource discovery work improved, but it should become a true service contract, not UI-adjacent convenience logic.

Why now:
- models/extensions/upscalers remain central to runtime correctness

Research / reasoning:
- disagreement between UI-visible resources and runtime-usable resources is a common source of generation failures

2nd/3rd/4th order effects:
- good: cleaner startup/readiness gating
- good: easier support for optional features like ADetailer, SVD, AnimateDiff
- risk: caching strategies can hide staleness if refresh semantics are fuzzy

Caveat:
- make freshness, invalidation, and manual refresh explicit.

## 16) Unify CLI, GUI, and replay around the same NJR build and execution spine
**BLUF:** The new CLI builder is a good move; now remove any remaining separate spines.

Why now:
- divergence between CLI and GUI paths is how duplicate runtime logic returns

Research / reasoning:
- multi-entrypoint systems stay maintainable when they share one canonical build + run path

2nd/3rd/4th order effects:
- good: replay/export/automation become easier
- good: reduces hidden drift
- risk: some CLI use cases may need stricter non-GUI defaults

Caveat:
- allow entrypoint-specific defaults, but not entrypoint-specific job semantics.

## 17) Add a "repo health dashboard" command that reports collection status, key invariants, and contract coverage
**BLUF:** The repo is big enough now to justify a fast explicit health summary.

Why now:
- there is a lot of test surface and architecture intent, but no single fast truth summary

Research / reasoning:
- large repos benefit from a small number of authoritative health signals that humans and agents can read quickly

2nd/3rd/4th order effects:
- good: easier triage after PRs
- good: better agent guidance
- risk: dashboards become misleading if they are not kept minimal and objective

Caveat:
- keep it to a handful of signals: collection, invariant tests, golden-path tests, docs version alignment.

## 18) Audit and trim legacy/deprecated tests after migration completion
**BLUF:** Once collection is fixed, the next cleanup is removing tests that enforce obsolete transitional behavior.

Why now:
- the repo has accumulated migration-era tests and shims

Research / reasoning:
- old transition tests can quietly block simplification long after their purpose is gone

2nd/3rd/4th order effects:
- good: faster feedback loops
- good: less confusion for contributors and agents
- risk: deleting too early can erase useful regression coverage

Caveat:
- tag tests by canonical / legacy / migration before pruning.

## 19) Introduce explicit compatibility tiers for old packs/history instead of implicit scattered fallbacks
**BLUF:** Compatibility should be declared, not rediscovered module by module.

Why now:
- compatibility work still shows up as ad hoc guards and bridge code

Research / reasoning:
- explicit tiers reduce surprise and help decide what deserves migration tooling versus retirement

2nd/3rd/4th order effects:
- good: better user communication
- good: easier sunset decisions
- risk: adding tiers without enforcement just creates more labels

Caveat:
- keep the first pass simple: canonical, supported-legacy-read, unsupported.

## 20) Defer major new platform/backend expansion until items 1-6 are complete
**BLUF:** The substrate is close enough that restraint now will pay off more than parallel expansion.

Why now:
- the repo has meaningful momentum, but the last migration and test-floor issues are still active

Research / reasoning:
- systems in late migration are especially vulnerable to regressions when major capability branches land simultaneously

2nd/3rd/4th order effects:
- good: preserves architectural coherence
- good: makes future feature work cheaper
- risk: may feel slower in the short term

Caveat:
- continue narrow high-value polish, but avoid wide new surface area until the controller/test floor is clean.

## Final prioritization summary

Immediate next tranche:
1. remove archive dependency
2. get to zero collection errors
3. tighten architecture guard from allowlist to completion guard
4. split and simplify PipelineController/AppController seams
5. finish canonical config DTO story
6. then continue artifact/reprocess/video/prompt-optimizer work on top of the stabilized base
